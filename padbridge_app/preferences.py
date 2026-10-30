# SPDX-License-Identifier: GPL-3.0-or-later
"""Atomic per-user preferences, including migration from earlier versions."""
import json
import os
from pathlib import Path
import tempfile
from .video import VideoOptions
PREFERENCES = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'padbridge' / 'connection.json'


def preferences():
    try:
        data = json.loads(PREFERENCES.read_text())
        if not isinstance(data, dict) or data.get('transport') not in ('usb', 'wifi'):
            raise ValueError('Invalid connection preferences')
        if any(not isinstance(data.get(key, ''), str) for key in ('address', 'name')):
            raise ValueError('Invalid saved address')
        mode = data.get('display_mode', 'extend')
        if mode not in ('extend', 'mirror'):
            mode = 'extend'
        try:
            video = VideoOptions.from_dict(data.get('video_options'))
        except (ValueError, TypeError):
            video = VideoOptions()
        return {**{key: data.get(key, '') for key in ('transport', 'address', 'name')},
                'display_mode': mode, 'video_options': video.to_dict()}
    except (OSError, ValueError):
        return {'transport': 'usb', 'address': '', 'name': '', 'display_mode': 'extend',
                'video_options': VideoOptions().to_dict()}


def save_preferences(data):
    PREFERENCES.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=PREFERENCES.parent, prefix='.connection-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False)
        os.replace(temporary, PREFERENCES)
    finally:
        Path(temporary).unlink(missing_ok=True)
