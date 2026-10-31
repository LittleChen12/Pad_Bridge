#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Wrap the complete portable application in a per-user Windows installer."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from padbridge_app import __version__

APP_ID = 'LittleChen12.PadBridge'
UNINSTALL_KEY = rf'Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1'


def compiler_path():
    path = ROOT / '.cache/tools/inno-7.1.1/ISCC.exe'
    if not path.is_file():
        raise RuntimeError('Run powershell -File packaging/bootstrap_inno.ps1 first.')
    return path


def compile_installer(bundle, output, version=__version__):
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    if not (bundle / 'PadBridge.exe').is_file() or not (bundle / '_internal').is_dir():
        raise RuntimeError('Build the complete portable application first.')
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(compiler_path()), '/Qp', f'/DAppVersion={version}',
                    f'/DProgramSource={bundle}', f'/DOutputPath={output}',
                    str(ROOT / 'packaging/windows.iss')], check=True)
    installer = output / f'padbridge-{version}-windows-x64-setup.exe'
    if not installer.is_file():
        raise RuntimeError('Installer compiler produced no executable.')
    return installer


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT / 'dist/PadBridge')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    info = json.loads((args.bundle / 'BUILD-INFO.json').read_text(encoding='utf-8'))
    if info['version'] != __version__:
        raise SystemExit('Portable application version does not match source version.')
    print(compile_installer(args.bundle, args.output))
