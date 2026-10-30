# SPDX-License-Identifier: GPL-3.0-or-later
"""GTK lifecycle, async user actions, status events, and orderly tray exit."""
import logging
import signal
import subprocess
import threading
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Gio, GLib
from odx11 import state
from .. import service, network
from ..paths import ROOT, RUNTIME
from ..preferences import preferences, save_preferences
from ..video import VideoOptions
from .tray import Tray
from .window import Window

log = logging.getLogger('padbridge.ui')


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='local.padbridge.Controller', flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = self.tray = None
        self.busy = self.updating = self.running = self.quitting = False
        self._save_pending = self._refresh_pending = None
        self._monitors, self._signals, self._sources = [], [], []
        self._shown_pid = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()  # A hidden window stays reachable through the tray.
        for name, callback in (('show',self.show_window),('hide',self.hide_window),
                ('connect',self.connect_display),('disconnect',self.disconnect_display),('quit',self.request_quit)):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda _a, _p, fn=callback: fn())
            self.add_action(action)
        settings = Gtk.Settings.get_default()
        settings.set_property('gtk-application-prefer-dark-theme', False)
        css = Gtk.CssProvider()
        css.load_from_path(str(Path(__file__).with_name('styles.css')))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.css = css
        self._sources.append(GLib.timeout_add_seconds(15, self.refresh))
        for sig in (signal.SIGINT, signal.SIGTERM):
            self._sources.append(GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig,
                            lambda: (self.request_quit(), GLib.SOURCE_CONTINUE)[1]))
        # State changes drive refreshes; the slow timer is only a health fallback.
        for folder in (Path(state.path()).parent, RUNTIME):
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            monitor = Gio.File.new_for_path(str(folder)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
            monitor.connect('changed', lambda *_: self.schedule_refresh())
            self._monitors.append(monitor)
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._signals.append(self.bus.signal_subscribe('org.freedesktop.systemd1',
            'org.freedesktop.DBus.Properties', 'PropertiesChanged',
            '/org/freedesktop/systemd1/unit/padbridge_2eservice', None,
            Gio.DBusSignalFlags.NONE, lambda *_: self.schedule_refresh()))

    def do_activate(self):
        if self.window is None:
            self.updating = True
            self.window = Window(self, preferences())
            self.updating = False
            try:
                self.tray = Tray(self.show_window, self.disconnect_display, self.request_quit)
            except (ImportError, ValueError, GLib.Error) as exc:
                log.warning('Tray unavailable: %s', exc)
                self.window.connection.footer.set_text('托盘不可用；请使用窗口菜单退出。')
        self.show_window()
        self.refresh()

    def show_window(self):
        if self.window:
            self.window.reveal()
            self.refresh()

    def hide_window(self):
        if self.window:
            self.save_settings()
            if self.tray and self.tray.has_host():
                self.window.hide()
            else:
                self.show_error('系统托盘不可用', '请启用 Ubuntu AppIndicators 扩展；也可从窗口菜单退出。')
        return True

    def settings_changed(self):
        if self.updating or not self.window:
            return
        self.window.connection.update_visibility()
        self.window.video.update_visibility()
        if self._save_pending:
            GLib.source_remove(self._save_pending)
        self._save_pending = GLib.timeout_add(500, self.save_settings)

    def save_settings(self):
        self._save_pending = None
        if not self.window or self.running or self.busy or self.updating:
            return False
        try:
            video = self.window.video.values()
            self.window.video.notice.set_text('')
            data = preferences()
            previous = dict(data)
            panel = self.window.connection
            data.update(transport=panel.transport.get(), display_mode=panel.mode.get(),
                        address=panel.address.get_text().strip(), video_options=video.to_dict())
            if data != previous:
                save_preferences(data)
            res = '原生' if video.resolution=='native' else video.resolution.replace('x',' × ')
            rate = '自动码率' if not video.bitrate_mbps else f'{video.bitrate_mbps} Mbps'
            panel.summary.set_text(f'{res} · {video.fps} FPS · {rate}')
        except (ValueError, OSError) as exc:
            self.window.video.notice.set_text(str(exc))
        return False

    def schedule_refresh(self):
        if self._refresh_pending is None:
            self._refresh_pending = GLib.timeout_add(100, self._scheduled_refresh)

    def _scheduled_refresh(self):
        self._refresh_pending = None
        self.refresh()
        return False

    def refresh(self):
        if not self.window or self.busy:
            return True
        self.running = service.active()
        facts = service.current_status()
        if self.running and facts.get('pid') != self._shown_pid:
            self._shown_pid = facts.get('pid')
            self.updating = True
            self.window.connection.mode.set(facts.get('display_mode','extend'))
            self.window.connection.transport.set(facts.get('transport','usb'))
            self.window.video.load(facts.get('video_options',VideoOptions().to_dict()))
            self.updating = False
        self.window.render(facts, self.running)
        if self.tray:
            self.tray.update(self.running, self.window.connection.mode.get()=='mirror')
        if not self.running:
            self.save_settings()
        return True

    def work(self, action, message, done=None):
        if self.busy:
            return
        self.busy = True
        self.window.connection.heading.set_text(message)
        self.window.connection.detail.set_text('请稍候…')
        self.window.render({}, self.running, busy=True)

        def run():
            try:
                result, error = action(), None
            except Exception as exc:
                log.exception('Operation failed')
                result, error = None, str(exc)
            GLib.idle_add(self.finished, result, error, done)
        threading.Thread(target=run, daemon=True).start()

    def finished(self, result, error, done):
        self.busy = False
        if error:
            self.quitting = False
            self.show_error('操作未完成', error)
        elif done:
            done(result)
        self.refresh()
        return False

    def connect_display(self):
        if not self.window or self.busy or self.running:
            return
        try:
            video = self.window.video.values()
        except ValueError as exc:
            self.window.show_page('video')
            self.window.video.notice.set_text(str(exc))
            return
        panel = self.window.connection
        mode, transport, address = panel.mode.get(), panel.transport.get(), panel.address.get_text().strip()
        self.work(lambda: service.start(transport,address,mode,video), '正在连接 iPad')

    def disconnect_display(self):
        self.work(service.stop, '正在断开连接')

    def request_quit(self):
        if self.quitting:
            return
        if self.busy:
            # Finish the in-flight start/stop first, then stop the worker exactly once.
            GLib.timeout_add(150, self._quit_when_ready)
            self.quitting = True
            return
        self.quitting = True
        self.save_settings()
        self.work(service.stop, '正在退出', done=lambda _: self.finish_quit())

    def _quit_when_ready(self):
        if self.busy:
            return True
        self.quitting = False
        self.request_quit()
        return False

    def finish_quit(self):
        if self.tray:
            self.tray.close()
        self.quit()

    def search(self):
        def found(items):
            if len(items)==1:
                self.window.connection.address.set_text(items[0].endpoint)
                return
            dialog = Gtk.Dialog(title='选择 iPad', transient_for=self.window, modal=True)
            dialog.add_buttons('取消', Gtk.ResponseType.CANCEL, '选择', Gtk.ResponseType.OK)
            choices = Gtk.ComboBoxText(margin=18)
            for item in items:
                choices.append(item.endpoint, f'{item.name} · {item.endpoint}')
            choices.set_active(0)
            dialog.get_content_area().add(choices)
            dialog.show_all()
            if dialog.run()==Gtk.ResponseType.OK:
                self.window.connection.address.set_text(choices.get_active_id())
            dialog.destroy()
        def discover():
            items = network.discover()
            if not items:
                raise RuntimeError('未发现 iPad。请确认同一 Wi-Fi 和“本地网络”权限，或直接填写 IP 地址。')
            return items
        self.work(discover, '正在搜索 iPad', found)

    def arrange(self):
        subprocess.Popen(['gnome-control-center','display'])

    def show_error(self, title, message):
        self.window.present()
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                 message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def do_shutdown(self):
        for monitor in self._monitors:
            monitor.cancel()
        for subscription in self._signals:
            self.bus.signal_unsubscribe(subscription)
        for source in self._sources + [self._save_pending, self._refresh_pending]:
            if source and GLib.MainContext.default().find_source_by_id(source):
                GLib.source_remove(source)
        if self.tray:
            self.tray.close()
        Gtk.Application.do_shutdown(self)


def run():
    GLib.set_prgname('padbridge')
    GLib.set_application_name('PadBridge')
    return Application().run(['padbridge'])
