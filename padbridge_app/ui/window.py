# SPDX-License-Identifier: GPL-3.0-or-later
"""Window composition and presentation; side effects stay in the application."""
from gi.repository import Gtk, Gio, GdkPixbuf
from odx11 import state
from .. import __version__
from ..paths import ROOT
from ..video import VideoOptions
from .panels import ConnectionPanel, VideoPanel, card, label, page, styled


class Window(Gtk.ApplicationWindow):
    def __init__(self, app, saved):
        super().__init__(application=app, title='PadBridge')
        self.set_default_size(880, 820)
        self.set_size_request(760, 580)
        self.set_icon_from_file(str(ROOT / 'padbridge.svg'))
        styled(self, 'padbridge')
        header = Gtk.HeaderBar(title='PadBridge', show_close_button=True)
        menu_button = Gtk.MenuButton()
        menu_button.add(Gtk.Image.new_from_icon_name('open-menu-symbolic', Gtk.IconSize.BUTTON))
        menu = Gio.Menu()
        menu.append('退出 PadBridge', 'app.quit')
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)
        self.set_titlebar(header)
        self.connect('delete-event', lambda *_: app.hide_window())
        shell = Gtk.Box()
        self.add(shell)
        sidebar = styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), 'sidebar')
        sidebar.set_size_request(175, -1)
        logo = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(
                                        str(ROOT / 'padbridge.svg'), 32, 32, True))
        brand = Gtk.Box(spacing=8, margin_bottom=26)
        brand.pack_start(logo, False, False, 0)
        brand.pack_start(label('PadBridge', 'brand'), False, False, 0)
        sidebar.pack_start(brand, False, False, 0)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        self.stack.set_hexpand(True)
        self.navigation = {}
        for name, text, icon in (('connection','屏幕连接','video-display-symbolic'),
                                 ('video','画面设置','preferences-system-symbolic'),
                                 ('about','关于','help-about-symbolic')):
            button = styled(Gtk.Button(), 'nav')
            content = Gtk.Box(spacing=10)
            content.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0)
            content.pack_start(label(text), False, False, 0)
            button.add(content)
            button.connect('clicked', lambda _, key=name: self.show_page(key))
            sidebar.pack_start(button, False, False, 0)
            self.navigation[name] = button
        sidebar.pack_end(label(f'v{__version__}', 'version'), False, False, 0)
        shell.pack_start(sidebar, False, False, 0)
        shell.pack_start(self.stack, True, True, 0)
        self.connection = ConnectionPanel(saved, app.settings_changed, app.connect_display,
                        app.disconnect_display, app.search, lambda: self.show_page('video'), app.arrange)
        self.video = VideoPanel(saved['video_options'], app.settings_changed)
        about = page('关于 PadBridge', 'Ubuntu 24.04 · x86_64')
        info = card()
        info.pack_start(label('iPad 扩展与镜像', 'section-title'), False, False, 0)
        info.pack_start(label('电脑需使用 Xorg 会话。扩展模式还需要一个空闲的 Intel / AMD 显示接口。', 'muted', True), False, False, 0)
        info.pack_start(label('镜像模式直接读取主屏。未连接时不运行截图或视频编码。', 'muted', True), False, False, 0)
        link = Gtk.LinkButton.new_with_label('https://apps.apple.com/app/id6780264891', '获取 iPad 接收端 OpenDisplay')
        link.set_halign(Gtk.Align.START)
        info.pack_start(link, False, False, 0)
        info.pack_start(label('基于 OpenDisplay for X11 · GPL-3.0-or-later', 'muted'), False, False, 0)
        about.pack_start(info, False, False, 0)
        for name, widget in (('connection',self.connection.widget),('video',self.video.widget),('about',about)):
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.add(widget)
            self.stack.add_named(scroll, name)
        self.show_page('connection')

    def show_page(self, name):
        self.stack.set_visible_child_name(name)
        for key, button in self.navigation.items():
            context = button.get_style_context()
            (context.add_class if key == name else context.remove_class)('active')

    def reveal(self):
        self.show_all()
        self.connection.update_visibility()
        self.video.update_visibility()
        self.present()

    def render(self, facts, running, busy=False):
        panel = self.connection
        mirror = panel.mode.get() == 'mirror'
        panel.controls.set_sensitive(not running and not busy)
        self.video.controls.set_sensitive(not running and not busy)
        panel.connect_button.set_visible(not running)
        panel.connect_button.set_sensitive(not busy)
        panel.stop_button.set_visible(running)
        panel.stop_button.set_sensitive(not busy)
        panel.arrange_button.set_sensitive(not busy)
        panel.update_visibility()
        self.video.update_visibility()
        if busy:
            panel.spinner.start()
            return
        panel.spinner.stop()
        kind = facts.get('state') if running else state.OFF
        if not running and facts.get('state') == state.PROBLEM:
            kind = state.PROBLEM
        if kind == state.STREAMING:
            title = '镜像已连接' if mirror else '扩展屏已连接'
            size = facts.get('video_size') or (facts.get('monitor') or [])[:2]
            text = f'{size[0]} × {size[1]}' if len(size)==2 else '正在传送画面'
            actual = facts.get('actual_fps')
            text += (f' · {actual:.1f} FPS' if isinstance(actual, (int, float)) else
                     f' · 目标 {facts.get("fps_target",60)} FPS')
            text += f' · 目标 {facts.get("bitrate_mbps",24):g} Mbps'
            if mirror:
                text += '\n保留主屏设置，iPad 等比显示'
        else:
            title, text = {
                state.OFF: ('未连接', '请在 iPad 上打开 OpenDisplay'),
                state.IDLE: ('等待 iPad', '请连接设备，并打开 OpenDisplay'),
                state.DIALING: ('正在连接', '请保持 iPad 解锁，OpenDisplay 在前台'),
                state.GRACE: ('连接中断', '正在尝试重新连接'),
                state.PAUSED: ('显示屏已停用', '启用屏幕后，断开并重新连接'),
                state.PROBLEM: ('连接未完成', facts.get('problem','请检查设备连接')),
            }.get(kind, ('准备中', '正在初始化显示服务'))
        panel.heading.set_text(title)
        panel.detail.set_text(text)
        self.video.hint.set_text('连接中，断开后可修改画面参数。' if running else
                '扩展模式设置副屏大小；镜像模式等比缩放画面，保留电脑主屏设置。')
