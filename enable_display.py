#!/usr/bin/python3
"""Grant this boot's plugdev users access to ONE unused DRM connector.

Run via pkexec, using Python -I. No package installation, boot configuration,
sudoers changes, network operations, or execution of user-provided commands.
"""
import argparse
import grp
import os
from pathlib import Path
import pwd
import re
import sys


def validate_connector(name, root=Path('/sys/class/drm')):
    if not re.fullmatch(r'card[0-9]+-HDMI-A-[0-9]+', name):
        raise ValueError('Only an explicit HDMI connector is accepted')
    connector = root / name
    card = name.split('-', 1)[0]
    driver = (root / card / 'device/driver').resolve().name
    if driver not in ('i915', 'xe', 'amdgpu'):
        raise ValueError(f'Unsupported display driver: {driver}')
    if (connector / 'status').read_text().strip() != 'disconnected':
        raise ValueError('The connector must be unused and disconnected')
    if (connector / 'edid').read_bytes():
        raise ValueError('A real monitor was detected on this connector')
    return connector / 'status'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('connector')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise PermissionError('Run through the system authentication dialog')
    uid = int(os.environ.get('PKEXEC_UID', os.environ.get('SUDO_UID', '-1')))
    if uid < 1000:
        raise PermissionError('The invoking desktop user could not be identified')
    user = pwd.getpwuid(uid)
    group = grp.getgrnam('plugdev')
    if group.gr_gid not in os.getgrouplist(user.pw_name, user.pw_gid):
        raise PermissionError('The desktop user must belong to plugdev')
    path = validate_connector(args.connector)
    os.chown(path, 0, group.gr_gid)
    os.chmod(path, 0o664)
    print(f'Enabled temporary connector access: {args.connector}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
