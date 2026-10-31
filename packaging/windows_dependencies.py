# SPDX-License-Identifier: GPL-3.0-or-later
"""Pinned display-driver payload and installer notices, without redistributing Apple binaries."""
import hashlib
from pathlib import Path
import urllib.request

from padbridge_app.windows import components, driver_setup

ROOT = Path(__file__).resolve().parent.parent


def driver_payload():
    path = ROOT / '.cache/components/VirtualDisplayDriver.zip'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != driver_setup.SHA256:
        with urllib.request.urlopen(driver_setup.URL, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != driver_setup.SHA256:
            raise RuntimeError('Virtual display driver checksum mismatch.')
        path.write_bytes(data)
    return path


def installer_inputs():
    work = ROOT / 'build/windows'
    work.mkdir(parents=True, exist_ok=True)
    # Keep Apple's original MSI license verbatim. Insert the PadBridge license
    # before its body using the existing RTF font table, rather than stripping RTF.
    apple = (ROOT / 'packaging/licenses/apple-mobile-device-support.rtf').read_text(encoding='utf-8')
    notice = ('PadBridge setup\n\nThis installer sets up PadBridge and its USB / extended-display '
              'components. Missing Apple Mobile Device Support is downloaded directly from Apple. '
              'An Internet connection and Windows administrator confirmation may be required.\n\n'
              'PadBridge is licensed under GPL-3.0-or-later:\n\n' +
              (ROOT / 'LICENSE').read_text(encoding='utf-8') +
              '\n\nApple Mobile Device Support\nThe following license is supplied with the official '
              'Apple Mobile Device Support 19.4.0.10 installer. By accepting and continuing, '
              'you also accept these terms for this component.\n\n')
    rtf = ''.join('\\' + c if c in '\\{}' else '\\par\n' if c == '\n' else
                  c if ord(c) < 128 else f'\\u{ord(c)}?' for c in notice)
    position = apple.index('\\pard')
    license_path = work / 'installer-license.rtf'
    license_path.write_text(apple[:position] + '\\pard\\f0\\fs20 ' + rtf + '\\page\n' +
                            apple[position:], encoding='ascii')
    includes = work / 'installer-components.iss'
    includes.write_text(f'#define AppleURL "{components.APPLE_URL}"\n'
                        f'#define AppleSHA256 "{components.APPLE_SHA256}"\n', encoding='ascii')
    return license_path, includes
