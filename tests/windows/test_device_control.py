# SPDX-License-Identifier: GPL-3.0-or-later
"""Device identity and privilege-boundary regressions; no real PnP mutations."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess
import pytest
from padbridge_app.windows import device_control as dc, storage, virtual_display as vd

DEVICE = dc.Device(r'ROOT\DISPLAY\0001', False)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(vd, 'OWNER', tmp_path/'owner.json')
    monkeypatch.setattr(dc, 'DIRECTORY', tmp_path/'helper')
    monkeypatch.setattr(dc, 'devices', lambda: [DEVICE])
    monkeypatch.setattr(dc.subprocess, 'run', Mock(return_value=SimpleNamespace(returncode=0)))


def test_ownership_requires_install_record_and_unique_matching_device(monkeypatch):
    assert dc.owned_device() is None
    storage.write_json(vd.OWNER, {'hardware_id': dc.HARDWARE, 'instance_id': 'replaced'})
    assert dc.owned_device() is None
    storage.write_json(vd.OWNER, {'hardware_id': dc.HARDWARE, 'instance_id': DEVICE.instance_id})
    assert dc.owned_device() == DEVICE
    monkeypatch.setattr(dc, 'devices', lambda: [DEVICE, replace(DEVICE, instance_id='other')])
    assert dc.owned_device() is None


def test_control_refuses_unowned_device_before_launching_task():
    with pytest.raises(RuntimeError, match='无法唯一确认'):
        dc.set_enabled(False)
    dc.subprocess.run.assert_not_called()


def test_already_parked_device_needs_no_task(monkeypatch):
    storage.write_json(vd.OWNER, {'hardware_id': dc.HARDWARE})
    monkeypatch.setattr(dc, 'devices', lambda: [replace(DEVICE, disabled=True)])
    dc.set_enabled(False)
    dc.subprocess.run.assert_not_called()


def test_task_permission_failure_is_actionable_and_no_fallback_elevation(monkeypatch):
    storage.write_json(vd.OWNER, {'hardware_id': dc.HARDWARE})
    monkeypatch.setattr(dc, 'ready', lambda: True)
    dc.subprocess.run.side_effect = subprocess.CalledProcessError(1, 'powershell')
    with pytest.raises(RuntimeError, match='管理员'):
        dc.set_enabled(False)
    assert dc.subprocess.run.call_count == 1


def test_task_result_is_verified_against_device_state(monkeypatch):
    storage.write_json(vd.OWNER, {'hardware_id': dc.HARDWARE})
    monkeypatch.setattr(dc, 'ready', lambda: True)
    device_states = iter([DEVICE, replace(DEVICE, disabled=True)])
    monkeypatch.setattr(dc, 'owned_device', lambda: next(device_states))
    dc.set_enabled(False)
    import json
    data = json.loads(dc.subprocess.run.call_args.kwargs['input'])
    assert data == {'folder': dc.TASK_FOLDER, 'action': 'Disable'}


def test_device_replaced_during_transition_aborts(monkeypatch):
    monkeypatch.setattr(dc, 'ready', lambda: True)
    device_states = iter([DEVICE, replace(DEVICE, instance_id='other')])
    monkeypatch.setattr(dc, 'owned_device', lambda: next(device_states))
    with pytest.raises(RuntimeError, match='身份发生变化'):
        dc.set_enabled(False)
