# SPDX-License-Identifier: GPL-3.0-or-later
"""Offscreen controller regressions. No real input, service or preferences changes."""
import os
import threading
import time
from unittest.mock import Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication
from padbridge_app.video import VideoOptions
from padbridge_app.windows import desktop, ui


@pytest.fixture(scope='module')
def qt():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    return app


@pytest.fixture
def window(qt, monkeypatch):
    saved = {'transport': 'usb', 'address': '', 'name': '', 'display_mode': 'mirror',
             'monitor': '', 'video_options': VideoOptions().to_dict()}
    monkeypatch.setattr(ui.service, 'active', lambda: False)
    monkeypatch.setattr(ui.service, 'current_status', lambda: {'state': 'off'})
    monkeypatch.setattr(ui.service, 'stop', Mock())
    monkeypatch.setattr(ui.virtual_display, 'available', lambda: False)
    monkeypatch.setattr(ui, 'save_preferences', Mock())
    monkeypatch.setattr(ui, 'preferences', lambda: dict(saved))
    monkeypatch.setattr(desktop, 'monitors', lambda: [desktop.Monitor('primary', 0, 0, 1920, 1080, True)])
    item = ui.Window(saved, tray=False)
    item.show()
    qt.processEvents()
    yield item
    item.status_timer.stop()
    item.event_timer.stop()
    item.save_timer.stop()
    item.pool.shutdown(wait=True)
    item.hide()
    item.deleteLater()
    qt.processEvents()


def test_connection_error_remains_visible_across_status_refresh(window):
    window.show_error('TCP connection timed out')
    window.refresh()
    assert window.connection.heading.text() == '连接未完成'
    assert 'timed out' in window.connection.detail.text()
    assert window.stack.currentWidget() == window.pages['connection']
    assert window.connection.connect_button.isEnabled()


def test_live_worker_syncs_mode_and_locks_video_controls(window, monkeypatch):
    window.show_error('Previous Wi-Fi connection timed out')
    monkeypatch.setattr(ui.service, 'active', lambda: True)
    monkeypatch.setattr(ui.service, 'current_status', lambda: {
        'pid': 42, 'state': 'streaming', 'transport': 'wifi', 'display_mode': 'mirror',
        'display_position': 'left',
        'stream_size': [1280, 800], 'target_fps': 30,
        'video_options': VideoOptions('1280x800', 30, 8).to_dict()})
    window.refresh()
    assert window.error_message == ''
    assert 'timed out' not in window.connection.detail.text()
    assert window.connection.transport.get() == 'wifi'
    assert window.connection.position.get() == 'left'
    assert not window.connection.position.isEnabled()
    assert window.video.values() == VideoOptions('1280x800', 30, 8)
    assert not window.video.controls.isEnabled()
    assert not window.connection.connect_button.isVisible()
    assert window.connection.stop_button.isVisible()


def test_quit_waits_for_pending_start_before_stopping_worker(window, qt, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []
    def start(*args, **kwargs):
        calls.append('start')
        started.set()
        assert release.wait(3)
    monkeypatch.setattr(ui.service, 'start', start)
    monkeypatch.setattr(ui.service, 'stop', lambda: calls.append('stop'))
    window.connect_display()
    assert started.wait(1)
    window.request_quit()
    assert calls == ['start']
    release.set()
    deadline = time.monotonic()+3
    while window.event_timer.isActive() and time.monotonic() < deadline:
        qt.processEvents()
        time.sleep(0.005)
    assert calls == ['start', 'stop']
    assert not window.isVisible()
    assert not window.event_timer.isActive()


def test_empty_extension_reports_actionable_error_without_start(window, monkeypatch):
    start = Mock()
    monkeypatch.setattr(ui.service, 'start', start)
    window.connection.mode.set('extend')
    window.connect_display()
    assert '安装虚拟显示组件' in window.connection.detail.text()
    start.assert_not_called()


def test_extension_position_is_saved_and_used_for_connection(window, monkeypatch):
    start = Mock()
    monkeypatch.setattr(ui.service, 'start', start)
    monkeypatch.setattr(ui.virtual_display, 'available', lambda: True)
    monkeypatch.setattr(window, 'work', lambda function, *_: function())
    window.refresh_extension()
    window.connection.mode.set('extend')
    window.connection.position.set('left')
    assert not window.connection.position_row.isHidden()
    window.connect_display()
    assert ui.save_preferences.call_args.args[0]['display_position'] == 'left'
    assert start.call_args.kwargs == {'monitor': 'auto', 'display_position': 'left'}
    window.connection.mode.set('mirror')
    assert window.connection.position_row.isHidden()
    window.connection.mode.set('extend')
    assert window.connection.position.get() == 'left'


def test_custom_resolution_and_auto_bitrate_roundtrip(window):
    options = VideoOptions('1920x1080', 45, 16)
    window.video.load(options.to_dict())
    assert window.video.values() == options
    window.video.auto.setChecked(True)
    assert window.video.values().bitrate_mbps == 0
    assert window.video.manual.isHidden()
