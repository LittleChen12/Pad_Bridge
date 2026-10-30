#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check package metadata, source fidelity, desktop integration and CLI startup."""
import argparse
import ast
from pathlib import Path
import subprocess
import tempfile

from build_deb import ROOT, read_version


def check(package):
    for field, expected in (('Package','padbridge'), ('Version',read_version()), ('Architecture','amd64')):
        value = subprocess.check_output(['dpkg-deb','--field',str(package),field],text=True).strip()
        if value != expected:
            raise RuntimeError(f'{field}: expected {expected!r}, got {value!r}')
    with tempfile.TemporaryDirectory(prefix='padbridge-check-') as folder:
        subprocess.run(['dpkg-deb','-x',str(package),folder],check=True)
        unpacked = Path(folder)
        software = unpacked / 'usr/lib/padbridge'
        for item in software.rglob('*'):
            if item.is_dir():
                if item.name in ('__pycache__','.git','.cache','runtime','validation'):
                    raise RuntimeError(f'Development directory in package: {item}')
                continue
            original = ROOT / item.relative_to(software)
            if item.read_bytes() != original.read_bytes():
                raise RuntimeError(f'Packaged source differs: {original.relative_to(ROOT)}')
            if item.suffix == '.py':
                ast.parse(item.read_text(), filename=str(item))
        subprocess.run(['desktop-file-validate',str(unpacked / 'usr/share/applications/local.padbridge.Controller.desktop')],check=True)
        subprocess.run([str(software / 'padbridge'),'--help'],check=True,stdout=subprocess.DEVNULL)
    print(f'{package.name}: metadata, sources, desktop entry and CLI passed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    check(parser.parse_args().package.resolve())
