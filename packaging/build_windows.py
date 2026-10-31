#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the Windows application, portable ZIP and setup EXE with source/licenses."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from padbridge_app import __version__
from build_installer import compile_installer, compiler_path
from windows_resources import resources
from windows_dependencies import driver_payload


def source_archive(bundle):
    """Ship corresponding source without copying ignored or untracked local files."""
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    with zipfile.ZipFile(bundle / 'source.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(set(names) - {''}):
            path = ROOT / name
            if path.is_file():
                archive.write(path, 'PadBridge/' + name)


def build():
    if sys.platform != 'win32':
        raise SystemExit('Run this build on Windows x64 with Python 3.12-3.14.')
    output = ROOT / 'dist'
    work = ROOT / 'build' / 'windows'
    work.mkdir(parents=True, exist_ok=True)
    compiler = compiler_path()
    icon, version_info = resources(ROOT, work, __version__)
    driver = driver_payload()
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--name', 'PadBridge', '--onedir', '--console', '--hide-console', 'hide-early',
                    '--icon', str(icon), '--version-file', str(version_info),
                    '--paths', str(ROOT / 'vendor/opendisplay-x11'),
                    '--collect-all', 'av', '--collect-all', 'zeroconf',
                    '--collect-all', 'dxcam', '--collect-all', 'winrt',
                    '--add-data', str(ROOT / 'padbridge.svg') + ';.',
                    '--add-data', str(ROOT / 'padbridge_app/windows/styles.qss') + ';padbridge_app/windows',
                    '--add-data', str(ROOT / 'padbridge_app/windows/display_control.ps1') + ';padbridge_app/windows',
                    '--add-data', str(driver) + ';padbridge_app/windows',
                    '--copy-metadata', 'av', '--copy-metadata', 'zeroconf',
                    '--copy-metadata', 'psutil', '--copy-metadata', 'PySide6-Essentials',
                    '--exclude-module', 'gi', '--exclude-module', 'Xlib',
                    '--exclude-module', 'tkinter', '--exclude-module', 'pystray',
                    '--distpath', str(output), '--workpath', str(work),
                    '--specpath', str(work), str(ROOT / 'app.py')], check=True, cwd=ROOT)
    bundle = output / 'PadBridge'
    shutil.copy2(icon, bundle / 'PadBridge.ico')
    shutil.copy2(ROOT / 'LICENSE', bundle / 'LICENSE')
    (bundle / 'docs/releases').mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'docs/windows.md', bundle / 'docs/windows.md')
    shutil.copy2(ROOT / f'docs/releases/v{__version__}.md', bundle / f'docs/releases/v{__version__}.md')
    (bundle / 'Windows使用说明.md').write_text(
        '# PadBridge for Windows\n\n完整解压本压缩包后，运行 `PadBridge.exe`。\n\n'
        '配置、依赖和故障排查见 [Windows 使用说明](docs/windows.md)。\n\n'
        '本版本更新见 [发布说明](docs/releases/v' + __version__ + '.md)。\n\n'
        '完整源码和开发资料见 [source.zip](source.zip)。\n', encoding='utf-8')
    source_archive(bundle)
    third_party = bundle / 'third-party-licenses'
    third_party.mkdir(exist_ok=True)
    (third_party / 'inno-setup').mkdir(exist_ok=True)
    shutil.copy2(compiler.parent / 'License.txt', third_party / 'inno-setup/LICENSE.txt')
    shutil.copytree(ROOT / 'packaging/licenses', third_party / 'setup-components', dirs_exist_ok=True)
    versions = {}
    names = ['av', 'zeroconf', 'psutil', 'PySide6-Essentials', 'shiboken6', 'ifaddr',
             'pyinstaller', 'dxcam', 'numpy', 'comtypes', 'typing_extensions']
    names += [d.metadata['Name'] for d in importlib.metadata.distributions()
              if d.metadata['Name'].lower().startswith('winrt')]
    for name in names:
        dist = importlib.metadata.distribution(name)
        versions[name] = dist.version
        for file in dist.files or []:
            if any(part.lower().startswith(('license', 'copying', 'notice')) for part in file.parts):
                path = Path(dist.locate_file(file))
                if path.is_file() and path.suffix != '.pyc':
                    target = third_party / name / str(file).replace('/', '_').replace('\\', '_')
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(path, target)
    # Python/Tcl/Tk license files reside in the runtime, not importlib metadata.
    for base in (Path(sys.base_prefix), Path(sys.base_prefix) / 'tcl'):
        for path in base.glob('**/license*' if base.name == 'tcl' else 'LICENSE*'):
            if path.is_file():
                shutil.copy2(path, third_party / ('python-' + str(path.relative_to(base)).replace('\\', '_')))
    (bundle / 'BUILD-INFO.json').write_text(json.dumps({'version': __version__,
        'python': sys.version, 'dependencies': versions}, indent=2), encoding='utf-8')
    archive = Path(shutil.make_archive(str(output / f'padbridge-{__version__}-windows-x64'),
                                      'zip', root_dir=output, base_dir='PadBridge'))
    installer = compile_installer(bundle, output)
    checksums = ''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
                        for path in (archive, installer))
    (output / 'SHA256SUMS-windows').write_text(checksums, encoding='ascii')
    print(archive)
    print(installer)


if __name__ == '__main__':
    build()
