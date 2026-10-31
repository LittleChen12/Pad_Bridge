# SPDX-License-Identifier: GPL-3.0-or-later
from padbridge_app.windows.receiver_layout import LayoutHistory


def test_aspect_transition_is_reset_once_after_first_frame_is_remembered(tmp_path):
    path = tmp_path/'layout.json'
    layout = LayoutHistory(path)
    assert not layout.needs_reset('ipad', (2560, 1600))
    layout.remember('ipad', (2560, 1600))
    assert LayoutHistory(path).needs_reset('ipad', (2224, 1668))
    layout.remember('ipad', (2224, 1668))
    assert not LayoutHistory(path).needs_reset('ipad', (2224, 1668))


def test_another_receiver_and_aligned_resizes_do_not_reconnect(tmp_path):
    layout = LayoutHistory(tmp_path/'layout.json')
    layout.remember('ipad', (2224, 1668))
    assert not layout.needs_reset('other-ipad', (2560, 1600))
    assert not layout.needs_reset('ipad', (266, 200))
    assert layout.needs_reset('ipad', (1668, 2224))


def test_invalid_history_or_anonymous_receiver_does_not_force_reconnect(tmp_path):
    path = tmp_path/'layout.json'
    path.write_text('{"receiver_id":"ipad", "size":[0,"wrong"]}', encoding='utf-8')
    layout = LayoutHistory(path)
    assert not layout.needs_reset('ipad', (2224, 1668))
    layout.remember('', (2560, 1600))
    assert layout.previous['receiver_id'] == 'ipad'
