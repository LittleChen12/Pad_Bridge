# SPDX-License-Identifier: GPL-3.0-or-later
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from padbridge_app.windows import driver_setup as setup, virtual_display as vd, display_config as cc


@pytest.mark.parametrize('requested,expected', [(30, 60), (60, 60), (90, 90), (100, 120), (120, 120), (144, 120)])
def test_mode_selection_prefers_sufficient_refresh(requested, expected, monkeypatch):
    records = [vd.DevMode(width=2224, height=1668, bits=32, frequency=f) for f in (120, 60, 90)]
    def enumerate_mode(name, index, destination, flags):
        if index >= len(records):
            return False
        ctypes.memmove(destination, ctypes.byref(records[index]), ctypes.sizeof(vd.DevMode))
        return True
    monkeypatch.setattr(vd, 'api', lambda: SimpleNamespace(EnumDisplaySettingsExW=enumerate_mode))
    assert vd.modes('owned', requested)[(2224, 1668)].frequency == expected


def test_new_driver_config_includes_portrait_landscape_and_120hz():
    root = ET.fromstring(setup.configuration())
    assert all({'60', '90', '120'} <= rates for _, rates in setup.refresh_modes(root).values())
    sizes = {(int(r.findtext('width')), int(r.findtext('height'))) for r in root.findall('resolutions/resolution')}
    assert (2224, 1668) in sizes and (1668, 2224) in sizes


def test_upgrade_adds_refresh_without_losing_custom_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(vd, 'INSTALL_DIR', tmp_path)
    monkeypatch.setattr(setup.device_control, 'owned_device', lambda: object())
    monkeypatch.setattr(setup.device_control, 'set_enabled', Mock())
    monkeypatch.setattr(setup.ct.windll.shell32, 'IsUserAnAdmin', lambda: True)
    monkeypatch.setattr(cc, 'current', lambda **_: None)
    before = b'<vdd_settings><global><g_refresh_rate>144</g_refresh_rate></global><gpu><friendlyname>Custom GPU</friendlyname></gpu><resolutions><resolution><width>1232</width><height>800</height><refresh_rate>75</refresh_rate></resolution></resolutions></vdd_settings>'
    path = tmp_path / 'vdd_settings.xml'
    path.write_bytes(before)
    setup.upgrade_refresh_modes()
    assert setup.high_refresh_ready()
    root = ET.parse(path).getroot()
    assert root.findtext('gpu/friendlyname') == 'Custom GPU'
    assert root.findtext('resolutions/resolution/refresh_rate') == '75'
    assert '144' in {r.text for r in root.findall('global/g_refresh_rate')}
    assert path.with_suffix('.pre-120hz.xml').read_bytes() == before
    first = path.read_bytes()
    setup.upgrade_refresh_modes()
    assert path.read_bytes() == first
    setup.device_control.set_enabled.assert_called_once_with(False)


def test_high_refresh_ccd_plan_preserves_physical_screen():
    main = cc.Path(source=cc.Source(cc.Luid(7, 0), 0, 1, 1),
                   target=cc.Target(adapter=cc.Luid(7, 0), id=10, mode=0, available=True), flags=1)
    tablet = cc.Path(source=cc.Source(cc.Luid(7, 0), 1, 2, 1),
                     target=cc.Target(adapter=cc.Luid(7, 0), id=20, mode=3, available=True), flags=0)
    before = bytes(main)
    paths, _ = cc.plan([main, tablet], [], tablet, 2224, 1668, -2224, 0, refresh=120)
    assert bytes(paths[0]) == before
    assert (paths[1].target.refresh.numerator, paths[1].target.refresh.denominator) == (120, 1)
