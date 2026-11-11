# SPDX-License-Identifier: GPL-3.0-or-later
"""View widgets only: no subprocesses, display mutations, or service lifecycle."""
from gi.repository import Gtk
from ..video import VideoOptions


def styled(widget, *classes):
    for name in classes:
        widget.get_style_context().add_class(name)
    return widget


def label(text, style=None, wrap=False):
    item = Gtk.Label(label=text, xalign=0, wrap=wrap)
    if style:
        styled(item, style)
    return item


def card():
    return styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16), 'card')


def page(title, subtitle):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20, margin=26)
    head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    head.pack_start(label(title, 'page-title'), False, False, 0)
    head.pack_start(label(subtitle, 'page-subtitle'), False, False, 0)
    box.pack_start(head, False, False, 0)
    return box


class Choice(Gtk.Box):
    def __init__(self, choices, value, changed):
        super().__init__(spacing=10)
        self.buttons = {}
        first = None
        for key, text in choices:
            button = Gtk.RadioButton.new_with_label_from_widget(first, text)
            first = first or button
            button.set_mode(False)
            styled(button, 'choice')
            self.pack_start(button, True, True, 0)
            self.buttons[key] = button
        self.set(value)
        for button in self.buttons.values():
            button.connect('toggled', lambda b: changed() if b.get_active() else None)

    def get(self):
        return next(key for key, button in self.buttons.items() if button.get_active())

    def set(self, value):
        if value in self.buttons and not self.buttons[value].get_active():
            self.buttons[value].set_active(True)


class ConnectionPanel:
    def __init__(self, saved, changed, connect, disconnect, search, video_page, arrange):
        self.widget = page('屏幕连接', '把 iPad 变成随身显示器')
        self.controls = card()
        self.controls.pack_start(label('显示模式', 'field-label'), False, False, 0)
        self.mode = Choice((('extend', '扩展屏幕'), ('mirror', '镜像主屏')),
                           saved['display_mode'], changed)
        self.controls.pack_start(self.mode, False, False, 0)
        self.mode_hint = label('镜像请在此处切换，系统“镜像”暂不支持。', 'hint')
        self.controls.pack_start(self.mode_hint, False, False, 0)
        self.position_row = Gtk.Box(spacing=25)
        self.position_row.pack_start(label('副屏位置', 'field-label'), False, False, 0)
        self.position = Choice((('left', '左侧'), ('right', '右侧'), ('below', '下方')),
                               saved.get('display_position', 'right'), changed)
        self.position_row.pack_start(self.position, True, True, 0)
        self.position_row.set_no_show_all(True)
        self.controls.pack_start(self.position_row, False, False, 0)
        self.controls.pack_start(Gtk.Separator(), False, False, 0)
        row = Gtk.Box(spacing=25)
        row.pack_start(label('连接方式', 'field-label'), False, False, 0)
        self.transport = Choice((('usb', 'USB'), ('wifi', 'Wi-Fi')), saved['transport'], changed)
        row.pack_start(self.transport, True, True, 0)
        self.controls.pack_start(row, False, False, 0)
        self.network = Gtk.Box(spacing=10)
        self.address = Gtk.Entry(text=saved['address'], placeholder_text='iPad IP 地址，留空自动搜索')
        self.address.set_hexpand(True)
        self.address.connect('changed', lambda _: changed())
        self.network.pack_start(self.address, True, True, 0)
        self.search_button = Gtk.Button.new_from_icon_name('edit-find-symbolic', Gtk.IconSize.BUTTON)
        self.search_button.set_tooltip_text('搜索同一局域网中的 iPad')
        self.search_button.connect('clicked', lambda _: search())
        self.network.pack_start(self.search_button, False, False, 0)
        self.network.set_no_show_all(True)
        self.controls.pack_start(self.network, False, False, 0)
        self.widget.pack_start(self.controls, False, False, 0)

        status = card()
        row = Gtk.Box(spacing=16)
        icon = styled(Gtk.Image.new_from_icon_name('video-display-symbolic', Gtk.IconSize.DIALOG), 'status-icon')
        row.pack_start(icon, False, False, 0)
        words = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.heading = label('未连接', 'status-title')
        self.detail = label('请在 iPad 上打开 OpenDisplay', 'status-detail', True)
        self.detail.set_max_width_chars(44)
        words.pack_start(self.heading, False, False, 0)
        words.pack_start(self.detail, False, False, 0)
        row.pack_start(words, True, True, 0)
        status.pack_start(row, False, False, 0)
        self.summary = label('原生画质 · 60 FPS · 自动码率', 'muted')
        self.video_link = styled(Gtk.Button(label='调整画面'), 'plain', 'small')
        self.video_link.connect('clicked', lambda _: video_page())
        settings_row = Gtk.Box()
        settings_row.pack_start(self.summary, True, True, 0)
        settings_row.pack_start(self.video_link, False, False, 0)
        status.pack_start(settings_row, False, False, 0)
        buttons = Gtk.Box(spacing=10)
        self.connect_button = styled(Gtk.Button(label='连接 iPad'), 'primary')
        self.connect_button.connect('clicked', lambda _: connect())
        self.stop_button = styled(Gtk.Button(label='断开连接'), 'disconnect')
        self.stop_button.connect('clicked', lambda _: disconnect())
        self.stop_button.set_no_show_all(True)
        self.arrange_button = styled(Gtk.Button(label='排列屏幕'), 'plain')
        self.arrange_button.set_tooltip_text('打开系统设置调整扩展屏布局。镜像请用 PadBridge 切换。')
        self.arrange_button.connect('clicked', lambda _: arrange())
        self.spinner = Gtk.Spinner()
        buttons.pack_start(self.connect_button, False, False, 0)
        buttons.pack_start(self.stop_button, False, False, 0)
        buttons.pack_start(self.spinner, False, False, 0)
        buttons.pack_end(self.arrange_button, False, False, 0)
        status.pack_start(buttons, False, False, 0)
        self.widget.pack_start(status, False, False, 0)
        self.footer = label('关闭窗口后保留在托盘；托盘菜单可彻底退出。', 'muted')
        self.widget.pack_end(self.footer, False, False, 0)

    def update_visibility(self):
        wifi = self.transport.get() == 'wifi'
        if wifi:
            self.network.show()
            self.network.foreach(lambda child: child.show())
        else:
            self.network.hide()
        self.arrange_button.set_visible(self.mode.get() == 'extend')
        if self.mode.get() == 'extend':
            self.position_row.show()
            self.position_row.foreach(lambda child: child.show_all())
        else:
            self.position_row.hide()


class VideoPanel:
    PRESETS = ('native', '2224x1668', '1920x1440', '1920x1200', '1600x1200', '1280x960')

    def __init__(self, data, changed):
        self.widget = page('画面设置', '未连接时可修改，连接时自动应用')
        self.controls = card()
        grid = Gtk.Grid(column_spacing=22, row_spacing=24)
        self.controls.pack_start(grid, False, False, 0)
        self.resolution = Gtk.ComboBoxText()
        for value in self.PRESETS:
            self.resolution.append(value, '自动原生' if value == 'native' else value.replace('x', ' × '))
        self.resolution.append('custom', '自定义…')
        self.resolution.set_hexpand(True)
        grid.attach(label('分辨率', 'field-label'), 0, 0, 1, 1)
        grid.attach(self.resolution, 1, 0, 1, 1)
        self.custom = Gtk.Box(spacing=8)
        self.width = Gtk.SpinButton.new_with_range(320, 3840, 8)
        self.height = Gtk.SpinButton.new_with_range(320, 3840, 2)
        for widget in (self.width, label('×'), self.height, label('像素', 'muted')):
            self.custom.pack_start(widget, False, False, 0)
        self.custom.set_no_show_all(True)
        grid.attach(self.custom, 1, 1, 1, 1)
        self.fps = Gtk.SpinButton.new_with_range(15, 60, 1)
        rate_row = Gtk.Box(spacing=12)
        rate_row.pack_start(self.fps, False, False, 0)
        rate_row.pack_start(label('FPS', 'muted'), False, False, 0)
        grid.attach(label('目标帧率', 'field-label'), 0, 2, 1, 1)
        grid.attach(rate_row, 1, 2, 1, 1)
        self.auto = Gtk.Switch()
        self.auto.set_halign(Gtk.Align.START)
        grid.attach(label('自动码率', 'field-label'), 0, 3, 1, 1)
        auto_row = Gtk.Box(spacing=12)
        auto_row.pack_start(self.auto, False, False, 0)
        auto_row.pack_start(label('USB 24 · Wi-Fi 10 Mbps', 'muted'), False, False, 0)
        grid.attach(auto_row, 1, 3, 1, 1)
        self.bitrate = Gtk.SpinButton.new_with_range(1, 50, 1)
        self.manual = Gtk.Box(spacing=12)
        self.manual.pack_start(self.bitrate, False, False, 0)
        self.manual.pack_start(label('Mbps · 1–50', 'muted'), False, False, 0)
        self.manual.set_no_show_all(True)
        grid.attach(self.manual, 1, 4, 1, 1)
        self.widget.pack_start(self.controls, False, False, 0)
        self.hint = label('扩展模式设置副屏大小；镜像模式等比缩放画面，保留电脑主屏设置。', 'hint', True)
        self.hint.set_max_width_chars(48)
        self.widget.pack_start(self.hint, False, False, 0)
        self.notice = label('', 'error', True)
        self.widget.pack_start(self.notice, False, False, 0)
        self.load(data)
        for widget, signal in ((self.resolution,'changed'),(self.width,'value-changed'),
                               (self.height,'value-changed'),(self.fps,'value-changed'),(self.bitrate,'value-changed')):
            widget.connect(signal, lambda _: changed())
        self.auto.connect('notify::active', lambda *_: changed())

    def load(self, data):
        video = VideoOptions.from_dict(data)
        self.resolution.set_active_id(video.resolution if video.resolution in self.PRESETS else 'custom')
        w, h = video.size or (2224,1668)
        self.width.set_value(w)
        self.height.set_value(h)
        self.fps.set_value(video.fps)
        self.auto.set_active(video.bitrate_mbps == 0)
        self.bitrate.set_value(video.bitrate_mbps or 10)

    def values(self):
        value = self.resolution.get_active_id()
        if value == 'custom':
            value = f'{self.width.get_value_as_int()}x{self.height.get_value_as_int()}'
        return VideoOptions(value, self.fps.get_value_as_int(),
                            0 if self.auto.get_active() else self.bitrate.get_value_as_int())

    def update_visibility(self):
        for box, show in ((self.custom,self.resolution.get_active_id()=='custom'),
                          (self.manual,not self.auto.get_active())):
            if show:
                box.show()
                box.foreach(lambda child: child.show())
            else:
                box.hide()
