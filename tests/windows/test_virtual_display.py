# SPDX-License-Identifier: GPL-3.0-or-later
"""Display ownership tests. Mutating Win32 calls are mocked in every test."""
from dataclasses import replace
from unittest.mock import Mock
import ctypes
import pytest
from padbridge_app.windows import desktop, display_config as cc, virtual_display as vd, device_control as dc

VDD = vd.Adapter('virtual', 'Virtual Display Driver', r'Root\MttVDD', 'stable-key', False, False)
MAIN = desktop.Monitor('primary', 0, 0, 2560, 1600, True)
DEVICE = dc.Device(r'ROOT\DISPLAY\0001', False)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(vd, 'OWNER', tmp_path/'owner.json')
    monkeypatch.setattr(vd, 'LEASE', tmp_path/'lease.json')
    monkeypatch.setattr(cc, 'current', lambda **_: ('virtual', False, False, 'owned-monitor'))
    monkeypatch.setattr(dc, 'owned_device', lambda: DEVICE)
    monkeypatch.setattr(dc, 'set_enabled', Mock())
    monkeypatch.setattr(dc, 'ready', lambda: True)


def test_unowned_or_ambiguous_driver_is_not_managed(monkeypatch):
    monkeypatch.setattr(vd, 'adapters', lambda: [VDD])
    assert vd.owned_adapter() is None
    vd.storage.write_json(vd.OWNER, {'hardware_id': r'Root\MttVDD'})
    assert vd.owned_adapter() == VDD
    monkeypatch.setattr(vd, 'adapters', lambda: [VDD, replace(VDD, name='second')])
    assert vd.owned_adapter() is None


def test_physical_and_primary_adapters_cannot_be_modified():
    for adapter in (replace(VDD, description='Intel'), replace(VDD, primary=True)):
        with pytest.raises(RuntimeError, match='拒绝修改'):
            vd.apply_mode(adapter, vd.DevMode())


def test_crash_recovery_requires_stable_identity(monkeypatch):
    monkeypatch.setattr(cc, 'current', lambda **_: ('virtual', True, False, 'owned-monitor'))
    monkeypatch.setattr(desktop, 'monitors', lambda: [MAIN])
    detach = Mock()
    monkeypatch.setattr(vd, 'detach', detach)
    monkeypatch.setattr(vd, 'owned_adapter', lambda: replace(VDD, attached=True))
    for key in ('reused-name-different-adapter', VDD.key):
        vd.storage.write_json(vd.LEASE, {'device_id': VDD.device_id, 'key': key})
        vd.recover()
    detach.assert_called_once_with(replace(VDD, attached=True))
    dc.set_enabled.assert_called_once_with(False)
    assert not vd.LEASE.exists()


def test_user_enabled_virtual_screen_is_borrowed_without_changes(monkeypatch):
    monkeypatch.setattr(cc, 'current', lambda **_: ('virtual', True, False, 'owned-monitor'))
    monkeypatch.setattr(vd, 'owned_adapter', lambda: replace(VDD, attached=True))
    monitor = desktop.Monitor('virtual', 2560, 0, 1920, 1080)
    monkeypatch.setattr(desktop, 'monitors', lambda: [MAIN, monitor])
    change, recover = Mock(), Mock()
    monkeypatch.setattr(vd, 'apply_mode', change)
    monkeypatch.setattr(vd, 'recover', recover)
    lease = vd.VirtualDisplay(position='left')
    assert lease.attach((2224, 1668)) == monitor
    lease.close()
    change.assert_not_called()
    recover.assert_not_called()
    dc.set_enabled.assert_not_called()


@pytest.mark.parametrize('position, expected_x', [('left', -2224), ('right', 2560)])
def test_auto_extension_uses_selected_side(monkeypatch, position, expected_x):
    monkeypatch.setattr(vd, 'owned_adapter', lambda: VDD)
    monitor = desktop.Monitor('virtual', expected_x, 0, 2224, 1668)
    screens = [MAIN]
    monkeypatch.setattr(desktop, 'monitors', lambda: screens)
    mode = vd.DevMode(size=ctypes.sizeof(vd.DevMode), width=2224, height=1668, bits=32, frequency=60)
    monkeypatch.setattr(vd, 'modes', lambda _: {(2224, 1668): mode})
    def apply(adapter, selected):
        assert selected.position.x == expected_x and selected.position.y == 0
        assert vd.storage.read_json(vd.LEASE)['key'] == VDD.key
        screens.append(monitor)
    monkeypatch.setattr(vd, 'apply_mode', apply)
    lease = vd.VirtualDisplay(position=position)
    assert lease.attach((2224, 1668)) == monitor


@pytest.mark.parametrize('position, expected_x', [('left', -4144), ('right', 4480)])
def test_initial_position_avoids_other_screens_without_being_shifted_by_a_screen_above(position, expected_x):
    screens = [MAIN, desktop.Monitor('left', -1920, 200, 1920, 1080),
               desktop.Monitor('right', 2560, 0, 1920, 1080),
               desktop.Monitor('above', -10000, -1600, 1280, 720)]
    assert vd.initial_position(screens, (2224, 1668), position) == (expected_x, 0)


@pytest.mark.parametrize('manual_move', [False, True])
def test_resize_keeps_left_screen_attached_but_preserves_manual_placement(monkeypatch, manual_move):
    lease = vd.VirtualDisplay(position='left')
    lease.adapter, lease.monitor_name, lease.size = VDD, 'virtual', (2224, 1668)
    lease.placed_at = (-2224, 0)
    old_point = (-2500, 100) if manual_move else lease.placed_at
    screens = [MAIN, desktop.Monitor('virtual', *old_point, 2224, 1668)]
    monkeypatch.setattr(vd, 'owned_adapter', lambda: VDD)
    monkeypatch.setattr(desktop, 'monitors', lambda: screens)
    mode = vd.DevMode(width=1668, height=2224, bits=32, frequency=60)
    monkeypatch.setattr(vd, 'modes', lambda _: {(1668, 2224): mode})
    def apply(adapter, selected):
        screens[1] = desktop.Monitor('virtual', selected.position.x, selected.position.y, 1668, 2224)
    monkeypatch.setattr(vd, 'apply_mode', apply)
    actual = lease.attach((1668, 2224))
    assert (actual.x, actual.y) == (old_point if manual_move else (-1668, 0))
    assert screens[0] == MAIN


def test_disabled_driver_is_still_available_without_a_gdi_adapter(monkeypatch):
    monkeypatch.setattr(dc, 'owned_device', lambda: replace(DEVICE, disabled=True))
    monkeypatch.setattr(vd, 'adapters', lambda: [])
    assert vd.available()
    assert vd.owned_adapter() is None


def test_recovery_withdraws_inactive_monitor_and_does_not_need_a_gdi_adapter(monkeypatch):
    monkeypatch.setattr(vd, 'owned_adapter', lambda: None)
    monkeypatch.setattr(cc, 'current', lambda **_: None)
    vd.storage.write_json(vd.LEASE, {'instance_id': DEVICE.instance_id})
    vd.recover()
    dc.set_enabled.assert_called_once_with(False)
    assert not vd.LEASE.exists()


def test_failed_withdrawal_keeps_lease_for_later_recovery(monkeypatch):
    monkeypatch.setattr(vd, 'owned_adapter', lambda: VDD)
    dc.set_enabled.side_effect = RuntimeError('task unavailable')
    vd.storage.write_json(vd.LEASE, {'instance_id': DEVICE.instance_id})
    with pytest.raises(RuntimeError, match='task unavailable'):
        vd.recover()
    assert vd.LEASE.exists()


def test_recovery_does_not_disable_replaced_device_or_user_primary(monkeypatch):
    monkeypatch.setattr(vd, 'owned_adapter', lambda: VDD)
    vd.storage.write_json(vd.LEASE, {'instance_id': 'another-device'})
    vd.recover()
    assert vd.LEASE.exists()
    monkeypatch.setattr(cc, 'current', lambda **_: ('virtual', True, False, 'owned-monitor'))
    monkeypatch.setattr(desktop, 'monitors', lambda: [replace(MAIN, name='virtual')])
    vd.storage.write_json(vd.LEASE, {'instance_id': DEVICE.instance_id})
    vd.recover()
    dc.set_enabled.assert_not_called()
    assert not vd.LEASE.exists()


def test_idle_migration_only_withdraws_an_inactive_screen(monkeypatch):
    vd.park_idle()
    dc.set_enabled.assert_called_once_with(False)
    dc.set_enabled.reset_mock()
    monkeypatch.setattr(cc, 'current', lambda **_: ('virtual', True, False, 'owned-monitor'))
    vd.park_idle()
    dc.set_enabled.assert_not_called()


@pytest.mark.parametrize('position, expected_x, restored_x', [('left', -2224, 2560), ('right', 2560, -2224)])
def test_newly_enabled_screen_uses_selected_side_even_if_windows_restores_old_position(
        monkeypatch, position, expected_x, restored_x):
    current = [None]
    monitor = [desktop.Monitor('virtual', restored_x, 0, 2224, 1668)]
    monkeypatch.setattr(cc, 'current', lambda **_: current[0])
    monkeypatch.setattr(vd, 'owned_adapter', lambda: VDD if current[0] else None)
    monkeypatch.setattr(desktop, 'monitors', lambda: [MAIN, monitor[0]] if current[0] else [MAIN])
    mode = vd.DevMode(width=2224, height=1668, bits=32, frequency=60)
    monkeypatch.setattr(vd, 'modes', lambda _: {(2224, 1668): mode})
    def apply(adapter, selected):
        monitor[0] = replace(monitor[0], x=selected.position.x, y=selected.position.y)
    monkeypatch.setattr(vd, 'apply_mode', Mock(side_effect=apply))
    monkeypatch.setattr(vd, 'detach', Mock())
    def enable(value):
        assert vd.storage.read_json(vd.LEASE)['instance_id'] == DEVICE.instance_id
        monitor[0] = replace(monitor[0], x=restored_x)
        current[0] = ('virtual', True, False, 'owned-monitor') if value else None
    dc.set_enabled.side_effect = enable
    lease = vd.VirtualDisplay(position=position)
    for _ in range(2):
        attached = lease.attach((2224, 1668))
        assert attached.x == expected_x and attached.y == 0
        assert not lease.borrowed
        lease.close()
        assert current[0] is None and not vd.LEASE.exists()
    assert dc.set_enabled.call_args_list == [((True,),), ((False,),)] * 2
    assert vd.apply_mode.call_count == 2


def test_stable_stream_checks_geometry_without_enumerating_pnp_or_ccd(monkeypatch):
    lease = vd.VirtualDisplay()
    lease.adapter, lease.monitor_name, lease.size = VDD, 'virtual', (2224, 1668)
    moved = desktop.Monitor('virtual', -2224, 0, 2224, 1668)
    monkeypatch.setattr(desktop, 'monitors', lambda: [MAIN, moved])
    monkeypatch.setattr(dc, 'owned_device', Mock(side_effect=AssertionError('slow PnP query')))
    monkeypatch.setattr(cc, 'current', Mock(side_effect=AssertionError('slow CCD query')))
    assert lease.attach((2224, 1668)) == moved


def test_size_fallback_preserves_tablet_aspect_and_orientation():
    assert vd.choose_size([(1920, 1080), (1920, 1440)], (2224, 1668)) == (1920, 1440)
    assert vd.choose_size([(1920, 1440), (1440, 1920)], (1668, 2224)) == (1440, 1920)


def topology():
    main = cc.Path(source=cc.Source(cc.Luid(7, 0), 0, 1, 1),
                   target=cc.Target(adapter=cc.Luid(7, 0), id=10, mode=0, available=True), flags=1)
    clone = cc.Path.from_buffer_copy(main)
    clone.target.id, clone.target.mode = 20, 2
    unused = cc.Path.from_buffer_copy(main)
    unused.source.id, unused.source.mode, unused.flags = 1, cc.INVALID, 0
    return main, clone, unused


def test_clone_to_extend_preserves_physical_path_and_allocates_free_source():
    main, clone, unused = topology()
    modes = [cc.Mode(type=2), cc.Mode(type=1), cc.Mode(type=2)]
    before_main, before_clone = bytes(main), bytes(clone)
    paths, updated = cc.plan([main, clone, unused], modes, clone, 2224, 1668, 2560, 0)
    assert len(paths) == 2 and bytes(paths[0]) == before_main
    assert cc.source_key(paths[1]) == (7, 0, 1)
    assert cc.target_key(paths[1]) == cc.target_key(clone)
    assert paths[1].source.mode == 3
    assert updated[3].data.source.position.x == 2560
    assert [bytes(x) for x in updated[:3]] == [bytes(x) for x in modes]
    assert bytes(clone) == before_clone


def test_detach_removes_only_owned_clone_target_and_keeps_primary():
    main, clone, unused = topology()
    paths, _ = cc.plan([main, clone, unused], [], clone, 0, 0, 0, 0)
    assert len(paths) == 1 and bytes(paths[0]) == bytes(main)
    with pytest.raises(RuntimeError, match='最后一块'):
        cc.plan([clone], [], clone, 0, 0, 0, 0)
