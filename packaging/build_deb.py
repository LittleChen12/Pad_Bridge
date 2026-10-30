#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build an Ubuntu 24.04 amd64 .deb without root or machine-specific runtime files."""
import argparse
import gzip
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
DEPENDENCIES = (
    'python3 (>= 3.12)', 'python3-gi', 'python3-xlib', 'gir1.2-gtk-3.0',
    'gir1.2-gstreamer-1.0', 'gir1.2-gst-plugins-base-1.0',
    'gir1.2-ayatanaappindicator3-0.1', 'gstreamer1.0-tools',
    'gstreamer1.0-plugins-base', 'gstreamer1.0-plugins-good',
    'gstreamer1.0-plugins-bad', 'gstreamer1.0-plugins-ugly',
    'x11-xserver-utils', 'xcvt', 'usbmuxd', 'avahi-daemon', 'pkexec',
)


def read_version():
    return re.search(r'__version__ = "([\d.]+)"',
                     (ROOT/'padbridge_app/__init__.py').read_text()).group(1)


def build(destination):
    version = read_version()
    destination.mkdir(parents=True, exist_ok=True)
    output = destination/f'padbridge_{version}_amd64.deb'
    epoch = int(os.environ.get('SOURCE_DATE_EPOCH', time.time()))
    with tempfile.TemporaryDirectory(prefix='padbridge-deb-') as temp:
        staging = Path(temp)
        software = staging/'usr/lib/padbridge'
        software.mkdir(parents=True)
        for name in ('app.py','padbridge','enable_display.py','settings.toml','padbridge.svg','LICENSE'):
            shutil.copy2(ROOT/name, software/name)
        ignore = shutil.ignore_patterns('__pycache__','*.pyc','.git')
        shutil.copytree(ROOT/'padbridge_app', software/'padbridge_app', ignore=ignore)
        vendor = software/'vendor/opendisplay-x11'
        vendor.mkdir(parents=True)
        shutil.copytree(ROOT/'vendor/opendisplay-x11/odx11', vendor/'odx11', ignore=ignore)
        shutil.copy2(ROOT/'vendor/opendisplay-x11/LICENSE', vendor/'LICENSE')
        binary = staging/'usr/bin/padbridge'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\nexec /usr/lib/padbridge/padbridge "$@"\n')
        binary.chmod(0o755)
        desktop = staging/'usr/share/applications/local.padbridge.Controller.desktop'
        desktop.parent.mkdir(parents=True)
        shutil.copy2(ROOT/'packaging/local.padbridge.Controller.desktop', desktop)
        icon = staging/'usr/share/icons/hicolor/scalable/apps/padbridge.svg'
        icon.parent.mkdir(parents=True)
        shutil.copy2(ROOT/'padbridge.svg',icon)
        docs = staging/'usr/share/doc/padbridge'
        docs.mkdir(parents=True)
        shutil.copy2(ROOT/'README.md', docs/'README.md')
        shutil.copy2(ROOT/'LICENSE', docs/'copyright')
        shutil.copy2(ROOT/'vendor/opendisplay-x11/LICENSE', docs/'opendisplay-x11.LICENSE')
        changes = f'padbridge ({version}) noble; urgency=medium\n\n  * Extended and mirrored iPad display, tray lifecycle, configurable streaming.\n\n -- PadBridge local build <noreply@localhost>  {time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(epoch))}\n'
        (docs/'changelog.Debian.gz').write_bytes(gzip.compress(changes.encode(),mtime=epoch))
        control = staging/'DEBIAN'
        control.mkdir()
        size = sum(p.stat().st_size for p in (staging/'usr').rglob('*') if p.is_file())
        (control/'control').write_text(f'''Package: padbridge
Version: {version}
Architecture: amd64
Section: utils
Priority: optional
Maintainer: PadBridge local build <noreply@localhost>
Installed-Size: {(size+1023)//1024}
Depends: {', '.join(DEPENDENCIES)}
Recommends: gnome-shell-extension-appindicator, libimobiledevice-utils
Description: Extend or mirror an X11 desktop to an iPad over USB or LAN
 GTK desktop controller with tray lifecycle, H.264 encoding and configurable
 resolution, bitrate and frame rate. Requires OpenDisplay on the iPad.
 Targets Ubuntu 24.04 amd64 with an Xorg session. Extended display mode
 additionally requires a supported free Intel or AMD display connector.
''')
        # Source, launcher, assets, and licenses only. No post-install root scripts.
        for p in staging.rglob('*'):
            if p.is_dir():
                p.chmod(0o755)
            elif p not in (binary, software/'padbridge'):
                p.chmod(0o644)
            os.utime(p,(epoch,epoch))
        (software/'padbridge').chmod(0o755)
        subprocess.run(['desktop-file-validate',str(desktop)],check=True)
        subprocess.run(['dpkg-deb','--root-owner-group','--build',str(staging),str(output)],
                       check=True,env={**os.environ,'SOURCE_DATE_EPOCH':str(epoch)})
    print(output)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    build(parser.parse_args().output.resolve())
