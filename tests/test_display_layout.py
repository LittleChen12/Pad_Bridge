# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from unittest.mock import patch
from padbridge_app.display_layout import initial_layout, restore_positions


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.outputs = {'left': [0,100,1920,1080], 'primary': [1920,200,2560,1600],
                        'right': [4480,0,1280,1024]}

    def test_right_uses_whole_desktop_edge_and_primary_top(self):
        position, moved = initial_layout(self.outputs, self.outputs['primary'], 2224, 'right')
        self.assertEqual(position, (5760,200))
        self.assertEqual(moved, self.outputs)

    def test_left_translates_origin_without_resizing_or_rearranging_physical_screens(self):
        position, moved = initial_layout(self.outputs, self.outputs['primary'], 2224, 'left')
        self.assertEqual(position, (0,200))
        for name, before in self.outputs.items():
            self.assertEqual(moved[name], [before[0]+2224, *before[1:]])

    def test_below_centers_on_primary_beneath_the_lowest_screen(self):
        self.outputs['right'] = [4480, 0, 1280, 2160]
        position, moved = initial_layout(self.outputs, self.outputs['primary'], 2224, 'below')
        self.assertEqual(position, (2088, 2160))
        self.assertEqual(moved, self.outputs)

    def test_below_translates_origin_when_ipad_is_wider_than_primary(self):
        outputs = {'primary': [0, 0, 1920, 1080]}
        position, moved = initial_layout(outputs, outputs['primary'], 2360, 'below')
        self.assertEqual(position, (0, 1080))
        self.assertEqual(moved, {'primary': [220, 0, 1920, 1080]})

    def test_cleanup_only_undoes_our_exact_translation(self):
        _, moved = initial_layout(self.outputs, self.outputs['primary'], 2224, 'left')
        record = {'layout_before':self.outputs, 'layout_applied':moved}
        with patch('padbridge_app.display_layout.read_layout', return_value=moved) as read, \
                patch('padbridge_app.display_layout.subprocess.run') as run:
            restore_positions(record, 'virtual')
            args = run.call_args.args[0]
            self.assertNotIn('--mode', args)
            self.assertNotIn('--off', args)
            run.reset_mock()
            read.return_value = {**moved, 'primary':[2200,200,2560,1600]}
            restore_positions(record, 'virtual')
            run.assert_not_called()
            read.return_value = self.outputs  # Desktop environment already restored it.
            restore_positions(record, 'virtual')
            run.assert_not_called()

    def test_left_rotation_from_hotplug_restored_coordinates_tracks_normalized_origin(self):
        # GNOME can restore the physical screen at x=2224 before attach runs.
        existing = {'primary':[2224,0,2560,1600]}
        position, moved = initial_layout(existing, existing['primary'], 1668, 'left')
        self.assertEqual(position, (0,0))
        self.assertEqual(moved['primary'], [1668,0,2560,1600])
        position, moved = initial_layout(existing, existing['primary'], 2224, 'right')
        self.assertEqual(position, (2560,0))
        self.assertEqual(moved['primary'], [0,0,2560,1600])
