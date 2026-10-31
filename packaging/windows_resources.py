# SPDX-License-Identifier: GPL-3.0-or-later
"""Build Windows icon/version resources from the existing SVG and package version."""
import os
import struct


def resources(root, work, version):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    from PySide6.QtGui import QGuiApplication, QIcon
    app = QGuiApplication.instance() or QGuiApplication([])
    icon = QIcon(str(root / 'padbridge.svg'))
    images = []
    for size in (16, 32, 48, 64, 128, 256):
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not icon.pixmap(size, size).save(buffer, 'PNG'):
            raise RuntimeError('Unable to render the PadBridge icon.')
        images.append((size, bytes(data)))
    offset = 6 + 16 * len(images)
    directory, payload = [], []
    for size, data in images:
        directory.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        payload.append(data)
        offset += len(data)
    icon_path = work / 'PadBridge.ico'
    icon_path.write_bytes(struct.pack('<HHH', 0, 1, len(images)) + b''.join(directory + payload))
    parts = tuple(int(n) for n in version.split('.'))
    parts += (0,) * (4-len(parts))
    info_path = work / 'version.txt'
    strings = {'CompanyName': 'LittleChen12', 'FileDescription': 'PadBridge',
               'FileVersion': version, 'InternalName': 'PadBridge',
               'OriginalFilename': 'PadBridge.exe', 'ProductName': 'PadBridge', 'ProductVersion': version}
    info_path.write_text(
        f'VSVersionInfo(ffi=FixedFileInfo(filevers={parts!r}, prodvers={parts!r}, '
        'mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)), '
        'kids=[StringFileInfo([StringTable("040904B0", [' +
        ','.join(f'StringStruct({key!r}, {value!r})' for key, value in strings.items()) +
        '])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])])', encoding='utf-8')
    return icon_path, info_path
