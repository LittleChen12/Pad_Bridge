# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression checks for PRIME mapping and the privileged connector boundary."""
from pathlib import Path
import tempfile
import unittest

from padbridge_app.displays import output_for_id, panel_mode
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


if __name__ == '__main__':
    unittest.main()
