#!/usr/bin/python3
import sys
from pathlib import Path

if sys.platform == 'win32':
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')

# Source checkouts work from any shell, without a POSIX launcher/PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor' / 'opendisplay-x11'))
from padbridge_app.cli import entrypoint

if __name__ == "__main__":
    raise SystemExit(entrypoint())
