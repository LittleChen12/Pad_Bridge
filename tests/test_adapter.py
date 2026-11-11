# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression checks for PRIME mapping and the privileged connector boundary."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from odx11.display import Geometry
from padbridge_app.displays import HybridDisplay, output_for_id, panel_mode
from enable_display import validate_connector


class ConnectorTests(unittest.TestCase):
    def test_air3_native_mode_keeps_all_1668_lines(self):
        self.assertEqual(panel_mode(2224, 1668, 1.0), (2224, 1668, 'normal'))
        self.assertEqual(panel_mode(1668, 2224, 1.0), (2224, 1668, 'left'))

    def test_hybrid_names_use_the_driver_id(self):
        sample = ('HDMI-0 disconnected (normal)\n'
                  '\tCONNECTOR_ID: 12\n'
                  'eDP-1-1 connected primary 2560x1600+0+0\n'
                  '\tCONNECTOR_ID: 95\n'
                  'HDMI-1-1 disconnected (normal)\n'
                  '\tCONNECTOR_ID: 283\n')
        self.assertEqual(output_for_id(sample, 283), 'HDMI-1-1')
        with self.assertRaises(RuntimeError):
            output_for_id(sample, 999)

    def test_colliding_ids_are_not_guessed(self):
        with self.assertRaises(RuntimeError):
            output_for_id('HDMI-1 connected\n CONNECTOR_ID: 9\nHDMI-2 connected\n CONNECTOR_ID: 9\n', 9)

    def test_root_helper_rejects_paths_and_non_hdmi_ports(self):
        for name in ('../../etc/passwd', 'card1-eDP-1', '/sys/class/drm/card1-HDMI-A-1', 'card1-HDMI-A-1/status'):
            with self.assertRaises(ValueError):
                validate_connector(name)

    def test_root_helper_refuses_real_displays_and_nvidia(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / 'card1/device'
            device.mkdir(parents=True)
            driver = device / 'driver'
            driver.symlink_to(root / 'drivers/i915')
            port = root / 'card1-HDMI-A-1'
            port.mkdir()
            (port / 'edid').write_bytes(b'')
            (port / 'status').write_text('disconnected\n')
            self.assertEqual(validate_connector(port.name, root), port / 'status')
            (port / 'status').write_text('connected\n')
            with self.assertRaises(ValueError):
                validate_connector(port.name, root)
            (port / 'status').write_text('disconnected\n')
            (port / 'edid').write_bytes(b'physical-monitor')
            with self.assertRaises(ValueError):
                validate_connector(port.name, root)
            (port / 'edid').write_bytes(b'')
            driver.unlink()
            driver.symlink_to(root / 'drivers/nvidia')
            with self.assertRaises(ValueError):
                validate_connector(port.name, root)


class HotplugTests(unittest.TestCase):
    def setUp(self):
        self.screen = HybridDisplay.__new__(HybridDisplay)
        self.screen.cfg = SimpleNamespace(divisor=1.0, connect_timeout_s=5.0, settle_timeout_s=2.0)
        self.screen.output = 'HDMI-A-1-0'
        self.screen._xrandr = Mock()
        self.screen._connected = Mock(return_value=True)
        self.target = Geometry(2560, 0, 2360, 1640)
        self.fallback = Geometry(2560, 0, 640, 480)
        self.args = ('--output', self.screen.output, '--mode', 'odx11_2360x1640')

    def test_timeout_retry_still_waits_for_connector_and_initial_layout(self):
        screen = self.screen
        screen.port = Path('card2-HDMI-A-1')
        screen.resolution, screen.position = None, 'right'
        screen.mode_name, screen.forced, screen.attached = None, False, False
        screen.layout_record, screen._automatic_geometry = {}, None
        screen._randr, screen.root = Mock(), object()
        screen._force = Mock()
        screen._ensure_mode = Mock(return_value='odx11_2360x1640')
        screen._connected.return_value = False
        screen._wait_until = Mock(side_effect=[False, True, True])
        screen.main_geometry = Mock(return_value=Geometry(0, 0, 2560, 1440))
        screen.geometry = Mock(return_value=self.fallback)
        screen._outputs = Mock(return_value=[])
        screen._apply_mode = Mock(return_value=self.target)
        device = SimpleNamespace(mode=None)

        with patch('padbridge_app.displays.record_ownership'):
            with self.assertRaisesRegex(RuntimeError, 'HDMI-A-1-0'):
                screen.attach(2360, 1640, device)
            self.assertTrue(screen.forced)
            self.assertFalse(screen.attached)
            self.assertEqual(screen.attach(2360, 1640, device), self.target)

        screen._force.assert_called_once_with('on')
        self.assertEqual(screen._randr.get_screen_resources.call_count, 2)
        self.assertEqual(screen._wait_until.call_args_list[1].args, (screen._connected, 5.0))
        self.assertEqual(screen._wait_until.call_args_list[2].args[1], 2.0)
        self.assertEqual(screen._apply_mode.call_args.args[1:], ((2360, 1640), True))

    def test_startup_reapplies_mode_once_if_hotplug_overwrites_it(self):
        screen = self.screen
        with tempfile.TemporaryDirectory() as directory:
            screen.port = Path(directory)
            (screen.port / 'edid').write_bytes(b'')
            screen._wait_until = Mock(side_effect=lambda predicate, timeout: predicate())
            screen.geometry = Mock(side_effect=[self.fallback, self.target, self.target])

            self.assertEqual(screen._apply_mode(self.args, (2360, 1640), True), self.target)
            self.assertEqual(screen._xrandr.call_count, 2)
            self.assertEqual(screen._wait_until.call_count, 2)

    def test_active_resize_does_not_reapply_mode_when_geometry_changes(self):
        screen = self.screen
        screen._wait_until = Mock()
        screen.geometry = Mock(return_value=self.fallback)

        self.assertEqual(screen._apply_mode(self.args, (2360, 1640), False), self.fallback)
        screen._xrandr.assert_called_once_with(*self.args)
        screen._wait_until.assert_not_called()


if __name__ == '__main__':
    unittest.main()
