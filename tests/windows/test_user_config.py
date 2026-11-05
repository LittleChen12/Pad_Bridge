# SPDX-License-Identifier: GPL-3.0-or-later
from unittest.mock import Mock

import pytest

from padbridge_app import preferences
from padbridge_app.windows import user_config


def test_windows_preferences_inherit_the_user_directory_acl(tmp_path, monkeypatch):
    path = tmp_path / 'PadBridge' / 'connection.json'
    monkeypatch.setattr(preferences, 'PREFERENCES', path)
    preferences.save_preferences({'transport': 'usb', 'video_options': {'fps': 120}})
    # The old 0700 mkdir produces a protected DACL with OWNER RIGHTS (OW),
    # which becomes Administrators for an elevated first launch.
    from padbridge_app.windows.device_control import powershell
    result = powershell("$p = [Console]::In.ReadToEnd() | ConvertFrom-Json; (Get-Acl -LiteralPath $p.path).AreAccessRulesProtected",
                        {'path': str(path.parent)})
    assert result.stdout.strip() == 'False'
    assert preferences.preferences()['video_options']['fps'] == 120


def test_old_elevated_directory_repair_preserves_settings(tmp_path, monkeypatch):
    path = tmp_path / 'PadBridge' / 'connection.json'
    path.parent.mkdir(mode=0o700)
    contents = b'{"transport":"wifi","address":"ipad.local:9000"}'
    path.write_bytes(contents)
    monkeypatch.setattr(preferences, 'PREFERENCES', path)
    user_config.repair(user_config.user_sid())
    user_config.probe()
    assert path.read_bytes() == contents


def test_normal_writable_startup_needs_no_elevation(monkeypatch):
    monkeypatch.setattr(user_config, 'probe', Mock())
    monkeypatch.setattr(user_config.ctypes.windll.shell32, 'IsUserAnAdmin', lambda: False)
    monkeypatch.setattr(user_config.elevation, 'run', Mock())
    user_config.prepare()
    user_config.elevation.run.assert_not_called()


def test_permission_error_repairs_once_then_rechecks(monkeypatch):
    monkeypatch.setattr(user_config, 'probe', Mock(side_effect=[PermissionError('old ACL'), None]))
    monkeypatch.setattr(user_config, 'user_sid', lambda: 'original-user')
    monkeypatch.setattr(user_config.elevation, 'run', Mock())
    user_config.prepare()
    user_config.elevation.run.assert_called_once_with(['repair-preferences', '--caller-sid', 'original-user'])
    assert user_config.probe.call_count == 2


def test_canceled_repair_does_not_retry_or_overwrite_preferences(monkeypatch):
    monkeypatch.setattr(user_config, 'probe', Mock(side_effect=PermissionError('old ACL')))
    monkeypatch.setattr(user_config, 'user_sid', lambda: 'original-user')
    monkeypatch.setattr(user_config.elevation, 'run', Mock(side_effect=RuntimeError('canceled')))
    with pytest.raises(RuntimeError, match='canceled'):
        user_config.prepare()
    assert user_config.elevation.run.call_count == 1
    assert user_config.probe.call_count == 1
