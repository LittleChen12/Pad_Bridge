#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a matching binary/source release from a clean Git revision."""
import argparse
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

from build_deb import ROOT, build, read_version


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def release(destination, tag=None):
    version = read_version()
    if tag is not None and tag != f'v{version}':
        raise SystemExit(f'Tag {tag!r} does not match source version v{version}.')
    if git('status', '--porcelain', '--untracked-files=normal').strip():
        raise SystemExit('Commit source changes before building a release; the .deb and source archive must match.')
    notes = ROOT / 'docs/releases' / f'v{version}.md'
    if not notes.is_file():
        raise SystemExit(f'Missing release notes: {notes.relative_to(ROOT)}')
    epoch = int(os.environ.setdefault('SOURCE_DATE_EPOCH', git('log', '-1', '--format=%ct').decode().strip()))
    destination.mkdir(parents=True, exist_ok=True)
    deb = build(destination)
    source = destination / f'padbridge-{version}-source.tar.gz'
    archive = git('archive', '--format=tar', f'--prefix=padbridge-{version}/', 'HEAD')
    source.write_bytes(gzip.compress(archive, mtime=epoch))
    shutil.copy2(notes, destination / 'RELEASE_NOTES.md')
    checksums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'
                        for p in (deb, source))
    (destination / 'SHA256SUMS').write_text(checksums)
    print(f'Release v{version} built from {git("rev-parse", "HEAD").decode().strip()}')
    print(checksums, end='')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--tag', help='Reject a version tag that does not match the source.')
    args = parser.parse_args()
    release(args.output.resolve(), args.tag)
