# SPDX-License-Identifier: GPL-3.0-or-later
"""Atomic UTF-8 state and Windows byte-range locks; no Unix PID signals."""
import json
import os
from pathlib import Path
import tempfile
import time
from ..paths import RUNTIME, USER_DATA

STATE = RUNTIME / 'state.json'
STOP = RUNTIME / 'stop.json'
LOG = USER_DATA / 'padbridge.log'


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.padbridge-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
        # Brief readers can hold a Windows file open across ReplaceFile.
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.01)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Lock:
    def __init__(self, name, wait=0):
        self.path, self.wait = RUNTIME / name, wait
        self.file = None

    def __enter__(self):
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b'\0')
            self.file.flush()
        deadline = time.monotonic() + self.wait
        while True:
            try:
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.file.close()
                    raise RuntimeError('PadBridge 工作进程或控制操作已经在运行。') from None
                time.sleep(0.05)

    def __exit__(self, *_):
        import msvcrt
        self.file.seek(0)
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.file.close()


def owned_process(facts):
    import psutil
    if type(facts.get('pid')) is not int or not isinstance(facts.get('token'), str):
        return None
    try:
        process = psutil.Process(facts['pid'])
        if abs(process.create_time() - float(facts['created'])) > 0.01:
            return None
        args = process.cmdline()
        if 'run' not in args:
            return None
        if facts.get('foreground'):
            if args != facts.get('command'):
                return None
        else:
            index = args.index('--worker-token')
            if args[index+1] != facts['token']:
                return None
        return process if process.is_running() else None
    except (psutil.Error, ValueError, KeyError, IndexError, TypeError):
        return None
