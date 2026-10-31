# SPDX-License-Identifier: GPL-3.0-or-later
"""First-install, repair and failure behavior without changing system components."""
import configparser
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from padbridge_app.windows import components as c
from padbridge_app.windows import transport

REAL_USB_READY = c.usb_ready
REAL_VERIFY_APPLE = c.verify_apple


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(c.ctypes.windll.shell32, 'IsUserAnAdmin', lambda: True)
    monkeypatch.setattr(c, 'usb_ready', lambda: False)
    monkeypatch.setattr(c, 'apple_service_exists', lambda: False)
    monkeypatch.setattr(c.device_control, 'owned_device', lambda: None)
    monkeypatch.setattr(c.device_control, 'devices', lambda: [])
    monkeypatch.setattr(c.device_control, 'ready', lambda: False)
    monkeypatch.setattr(c, 'verify_apple', Mock())
    monkeypatch.setattr(c, 'start_apple_service', Mock())
    monkeypatch.setattr(c, 'wait_for_usb', lambda: True)
    monkeypatch.setattr(c.subprocess, 'run', Mock(return_value=SimpleNamespace(returncode=0)))
    monkeypatch.setattr(c.driver_setup, 'install', Mock())


def display_ready(monkeypatch):
    monkeypatch.setattr(c.device_control, 'owned_device', lambda: object())
    monkeypatch.setattr(c.device_control, 'ready', lambda: True)


def test_components_already_ready_need_no_admin_or_installer(monkeypatch):
    display_ready(monkeypatch)
    monkeypatch.setattr(c, 'usb_ready', lambda: True)
    monkeypatch.setattr(c.ctypes.windll.shell32, 'IsUserAnAdmin', lambda: False)
    assert c.provision()['apple'] == 'ready'
    c.subprocess.run.assert_not_called()
    c.driver_setup.install.assert_not_called()


def test_missing_components_require_elevation_before_modification(monkeypatch):
    monkeypatch.setattr(c.ctypes.windll.shell32, 'IsUserAnAdmin', lambda: False)
    with pytest.raises(RuntimeError, match='管理员'):
        c.provision()
    c.subprocess.run.assert_not_called()


def test_other_apps_display_driver_is_preserved(monkeypatch):
    monkeypatch.setattr(c.device_control, 'devices', lambda: [object()])
    assert c.probe()['display'] == 'conflict'
    with pytest.raises(RuntimeError, match='不会覆盖'):
        c.provision()
    c.subprocess.run.assert_not_called()
    c.driver_setup.install.assert_not_called()


def test_fresh_install_verifies_both_components(monkeypatch, tmp_path):
    c.driver_setup.install.side_effect = lambda **kw: display_ready(monkeypatch)
    result = c.provision(tmp_path / 'Apple.msi', interactive=True)
    assert result == {'apple': 'ready', 'display': 'ready', 'restart': '0', 'error': ''}
    c.verify_apple.assert_called_once()
    assert '/qn' in c.subprocess.run.call_args.args[0]
    assert '/norestart' in c.subprocess.run.call_args.args[0]
    c.driver_setup.install.assert_called_once_with(interactive=True)


def test_stopped_existing_apple_service_is_started_without_replacing_package(monkeypatch):
    display_ready(monkeypatch)
    monkeypatch.setattr(c, 'apple_service_exists', lambda: True)
    assert c.probe()['apple'] == 'repair'
    assert c.provision()['apple'] == 'ready'
    c.start_apple_service.assert_called_once()
    c.verify_apple.assert_not_called()
    c.subprocess.run.assert_not_called()


@pytest.mark.parametrize('code', [1603, 1618, 1638])
def test_msi_failure_stops_setup_without_touching_display(code, tmp_path):
    c.subprocess.run.return_value.returncode = code
    with pytest.raises(RuntimeError, match=str(code)):
        c.provision(tmp_path / 'Apple.msi')
    c.driver_setup.install.assert_not_called()


def test_usb_failure_is_not_reported_as_success(monkeypatch, tmp_path):
    monkeypatch.setattr(c, 'wait_for_usb', lambda: False)
    with pytest.raises(RuntimeError, match='安装未完成'):
        c.provision(tmp_path / 'Apple.msi')
    c.driver_setup.install.assert_not_called()


def test_restart_is_returned_to_installer_without_rebooting(monkeypatch, tmp_path):
    c.subprocess.run.return_value.returncode = 3010
    monkeypatch.setattr(c, 'wait_for_usb', lambda: False)
    c.driver_setup.install.side_effect = c.driver_setup.RestartRequired()
    result = c.provision(tmp_path / 'Apple.msi')
    assert result['restart'] == '1'
    assert result['apple'] == result['display'] == 'restart'


def test_display_post_install_failure_stops_setup(tmp_path):
    with pytest.raises(RuntimeError, match='安装后检查'):
        c.provision(tmp_path / 'Apple.msi')


def test_error_reaches_unicode_installer_report(monkeypatch, tmp_path):
    monkeypatch.setattr(c, 'provision', Mock(side_effect=RuntimeError('安装取消\n请重试')))
    output = tmp_path / '报告.ini'
    assert c.run(output) == 1
    report = configparser.ConfigParser(interpolation=None)
    report.read(output, encoding='utf-16')
    assert report['components']['error'] == '安装取消 请重试'
    assert report['components']['apple'] != 'ready'


def test_readonly_probe_works_without_connected_ipad(monkeypatch):
    monkeypatch.setattr(transport, 'list_devices', lambda **kw: [])
    assert REAL_USB_READY()


def test_corrupted_download_is_rejected_before_execution(tmp_path):
    package = tmp_path / 'Apple.msi'
    package.write_bytes(b'bad download')
    with pytest.raises(RuntimeError, match='校验失败'):
        REAL_VERIFY_APPLE(package)
    c.subprocess.run.assert_not_called()


def test_valid_hash_with_wrong_publisher_is_rejected(monkeypatch, tmp_path):
    import hashlib
    package = tmp_path / 'Apple.msi'
    package.write_bytes(b'fixture')
    monkeypatch.setattr(c, 'APPLE_SHA256', hashlib.sha256(b'fixture').hexdigest())
    monkeypatch.setattr(c.device_control, 'powershell', Mock(return_value=SimpleNamespace(
        stdout='{"status":"Valid","signer":"O=Some Other Publisher"}')))
    with pytest.raises(RuntimeError, match='发布者签名无效'):
        REAL_VERIFY_APPLE(package)
    c.subprocess.run.assert_not_called()
