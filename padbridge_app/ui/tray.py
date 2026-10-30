# SPDX-License-Identifier: GPL-3.0-or-later
"""Notification-area integration. Lifecycle actions are supplied by the app."""
from gi.repository import Gtk, Gio, GLib
from ..paths import ROOT


class Tray:
    def __init__(self, show, disconnect, quit_app):
        import gi
        gi.require_version('AyatanaAppIndicator3', '0.1')
        from gi.repository import AyatanaAppIndicator3 as Indicator
        self.api = Indicator
        self.indicator = Indicator.Indicator.new('padbridge', str(ROOT / 'padbridge.svg'),
                                                 Indicator.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_title('PadBridge')
        menu = Gtk.Menu()
        self.summary = Gtk.MenuItem(label='PadBridge · 未连接')
        self.summary.set_sensitive(False)
        menu.append(self.summary)
        menu.append(Gtk.SeparatorMenuItem())
        for text, action in (('显示窗口', show), ('断开连接', disconnect), ('退出 PadBridge', quit_app)):
            item = Gtk.MenuItem(label=text)
            item.connect('activate', lambda _, fn=action: fn())
            menu.append(item)
            if text == '断开连接':
                self.disconnect_item = item
        menu.show_all()
        self.indicator.set_menu(menu)
        self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)

    @staticmethod
    def has_host():
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            result = bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus',
                    'org.freedesktop.DBus', 'NameHasOwner',
                    GLib.Variant('(s)', ('org.kde.StatusNotifierWatcher',)), None,
                    Gio.DBusCallFlags.NONE, 1500, None)
            return result.unpack()[0]
        except GLib.Error:
            return False

    def update(self, running, mirror=False):
        title = ('镜像运行中' if mirror else '扩展运行中') if running else '未连接'
        self.summary.set_label(f'PadBridge · {title}')
        self.disconnect_item.set_sensitive(running)

    def close(self):
        self.indicator.set_status(self.api.IndicatorStatus.PASSIVE)
