#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit per-user install/upgrade/uninstall test; refuses an existing installation."""
import argparse
import configparser
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time
import uuid
import winreg

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'packaging'), str(ROOT / 'vendor/opendisplay-x11')]
from padbridge_app import __version__
from padbridge_app.windows.installation import running_application
from build_installer import compile_installer, UNINSTALL_KEY


def installed():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return {name: winreg.QueryValueEx(key, name)[0] for name in
                    ('DisplayName', 'DisplayVersion', 'InstallLocation', 'UninstallString')}
    except FileNotFoundError:
        return None


def run_installer(executable, *options, success=True):
    result = subprocess.run([str(executable), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                             '/NORESTART', '/SP-', *options], timeout=600)
    if success:
        if result.returncode:
            for option in options:
                if option.startswith('/LOG='):
                    path = Path(option.removeprefix('/LOG='))
                    if path.is_file():
                        print('\n'.join(path.read_text(encoding='utf-8-sig', errors='replace').splitlines()[-40:]))
        assert result.returncode == 0, f'Installer failed: {result.returncode}'
    elif success is False:
        assert result.returncode != 0, 'Installer must refuse to modify a running application'
    return result.returncode


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def smoke(setup, bundle, headless_components=False):
    if installed():
        raise RuntimeError('PadBridge is already installed for this user; use a clean test account.')
    work = (ROOT / 'build' / ('installer-smoke-' + uuid.uuid4().hex)).resolve()
    assert work.is_relative_to((ROOT / 'build').resolve())
    work.mkdir(parents=True)
    target = work / '安装目录' / 'PadBridge'
    programs = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 2, None, 0, programs) != 0:
        raise RuntimeError('Cannot find the current user Start menu.')
    shortcut = Path(programs.value) / 'PadBridge/PadBridge.lnk'
    shortcut_before = shortcut.read_bytes() if shortcut.exists() else None
    preferences = Path(os.environ['APPDATA']) / 'PadBridge/connection.json'
    before = preferences.read_bytes() if preferences.exists() else None
    uninstall = None
    deployment = []
    confirmation_guard = False
    try:
        # An older setup fixture uses the same payload and stable application ID.
        # Only its package version differs, so this exercises a real Inno upgrade.
        older = compile_installer(bundle, work, version='0.0.0')
        code = run_installer(older, f'/DIR={target}', '/TASKS=', f'/LOG={work / "install.log"}',
                             success=None if headless_components else True)
        if code:
            # A headless runner cannot click the native publisher confirmation.
            # Only this exact rejection is expected: download/signature/MSI,
            # privilege, PnP and all other failures still fail this test.
            component_report = Path(os.environ['LOCALAPPDATA']) / 'PadBridge/setup-logs/components.ini'
            blocked = configparser.ConfigParser()
            blocked.read(component_report, encoding='utf-16')
            assert blocked.get('components', 'reason', fallback='') == 'publisher-confirmation'
            assert not installed() and not (target / 'PadBridge.exe').exists()
            from padbridge_app.windows import components, device_control
            assert components.usb_ready(), 'Fresh Apple USB installation did not succeed'
            assert not device_control.owned_device(), 'Rejected driver install was not rolled back'
            confirmation_guard = True
            deployment = ['/APPLICATIONONLY=1']
            run_installer(older, *deployment, f'/DIR={target}', '/TASKS=', f'/LOG={work / "app-install.log"}')
        record = installed()
        assert record and record['DisplayVersion'] == '0.0.0'
        assert Path(record['InstallLocation']).resolve() == target.resolve()
        uninstall = Path(record['UninstallString'].strip('"')).resolve()
        assert uninstall.is_relative_to(target.resolve()) and uninstall.is_file()
        assert shortcut.is_file(), 'Start menu shortcut was not installed'
        exe = target / 'PadBridge.exe'
        assert sha(exe) == sha(bundle / 'PadBridge.exe')
        assert (target / 'source.zip').is_file() and not (target / 'source').exists()
        # Both checks are from the installed executable, with no iPad attached.
        report = work / 'components.ini'
        subprocess.run([str(exe), 'setup-components', '--check', '--result', str(report)],
                       check=True, timeout=45)
        checks = configparser.ConfigParser()
        checks.read(report, encoding='utf-16')
        assert checks['components']['apple'] == 'ready'
        assert checks['components']['display'] == ('missing' if confirmation_guard else 'ready')
        # Do not remove files the user added to the installation directory.
        retained = target / 'user-file.txt'
        retained.write_text('keep this user file', encoding='utf-8')
        with running_application():
            run_installer(setup, success=False)
            run_installer(uninstall, success=False)
            assert installed()['DisplayVersion'] == '0.0.0' and exe.exists()
        # No /DIR: an upgrade must reuse the previous installation.
        run_installer(setup, *deployment, f'/LOG={work / "upgrade.log"}')
        record = installed()
        assert record['DisplayVersion'] == __version__ and record['DisplayName'] == 'PadBridge'
        assert Path(record['InstallLocation']).resolve() == target.resolve()
        assert shortcut.exists() and retained.read_text(encoding='utf-8') == 'keep this user file'
        assert sha(exe) == sha(bundle / 'PadBridge.exe')
        subprocess.run([str(exe), 'encoder-test'], check=True, timeout=45)
        run_installer(uninstall, f'/LOG={work / "uninstall.log"}')
        deadline = time.monotonic() + 15
        while (installed() or exe.exists()) and time.monotonic() < deadline:
            time.sleep(.1)
        assert not installed() and not exe.exists() and not shortcut.exists()
        assert retained.read_text(encoding='utf-8') == 'keep this user file'
        after = preferences.read_bytes() if preferences.exists() else None
        assert after == before, 'Installer changed the existing user preferences'
        print(json.dumps({'install': 'passed', 'upgrade': 'passed', 'uninstall': 'passed',
                          'running_app_protection': 'passed', 'start_menu': 'passed',
                          'user_files_and_preferences': 'preserved', 'apple_usb': 'ready',
                          'display_setup': ('publisher_confirmation_guard_passed' if confirmation_guard else 'ready')}))
    finally:
        logs = Path(os.environ['LOCALAPPDATA']) / 'PadBridge/setup-logs'
        if logs.is_dir():
            shutil.copytree(logs, work / 'component-logs', dirs_exist_ok=True)
            error = logs / 'components-error.log'
            if error.is_file():
                print(error.read_text(encoding='utf-8', errors='replace'))
        record = installed()
        if record and Path(record['InstallLocation']).resolve() == target.resolve() and uninstall:
            run_installer(uninstall)
        if shortcut_before is not None:
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            shortcut.write_bytes(shortcut_before)
        # Keep logs and failed-test evidence for inspection. Delete no user folders.


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', type=Path, default=ROOT / f'dist/padbridge-{__version__}-windows-x64-setup.exe')
    parser.add_argument('--bundle', type=Path, default=ROOT / 'dist/PadBridge')
    parser.add_argument('--headless-components', action='store_true',
                        help='Verify native publisher-consent rejection, then separately test application-only deployment.')
    args = parser.parse_args()
    smoke(args.setup.resolve(), args.bundle.resolve(), args.headless_components)
