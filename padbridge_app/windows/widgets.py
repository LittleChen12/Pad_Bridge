# SPDX-License-Identifier: GPL-3.0-or-later
"""Qt equivalents of the existing GTK panels, using the same design and wording."""
from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QComboBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QVBoxLayout, QWidget)
from ..video import VideoOptions


def styled(widget, role):
    widget.setProperty('role', role)
    return widget


def label(text='', role=None, wrap=False):
    item = QLabel(text)
    item.setTextFormat(Qt.TextFormat.PlainText)
    item.setWordWrap(wrap)
    if role:
        styled(item, role)
    return item


def icon(name, color='#656a7e', size=20):
    paths = {
        'display': '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M12 17v4m-4 0h8"/>',
        'settings': '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="white"/><circle cx="15" cy="17" r="3" fill="white"/>',
        'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.5"/>',
        'search': '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
        'refresh': '<path d="M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-3l2 3M4 16l2 3a8 8 0 0 0 13-3"/>',
        'menu': '<path d="M5 6h14M5 12h14M5 18h14"/>',
    }
    data = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{paths[name]}</g></svg>'
    pixmap = QPixmap(size*3, size*3)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(data.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(3)
    return QIcon(pixmap)


def button(text, callback, role=None):
    result = QPushButton(text)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    if role:
        styled(result, role)
    result.clicked.connect(callback)
    return result


def row(*items, spacing=12):
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for item in items:
        if item is None:
            layout.addStretch()
        else:
            layout.addWidget(item)
    return widget


def card():
    widget = styled(QFrame(), 'card')
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(16)
    return widget, layout


def page(title, subtitle):
    widget = styled(QWidget(), 'page')
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(26, 26, 26, 26)
    layout.setSpacing(20)
    head = QWidget()
    heading = QVBoxLayout(head)
    heading.setContentsMargins(0, 0, 0, 0)
    heading.setSpacing(6)
    heading.addWidget(label(title, 'page-title'))
    heading.addWidget(label(subtitle, 'page-subtitle'))
    layout.addWidget(head)
    return widget, layout


class Choice(QWidget):
    changed = Signal()

    def __init__(self, choices, value):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for key, text in choices:
            item = styled(QPushButton(text), 'choice')
            item.setCheckable(True)
            item.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(item)
            self.buttons[key] = item
            layout.addWidget(item, 1)
        self.set(value)
        self.group.buttonToggled.connect(lambda _, checked: self.changed.emit() if checked else None)

    def get(self):
        return next(key for key, item in self.buttons.items() if item.isChecked())

    def set(self, value):
        if value in self.buttons:
            self.buttons[value].setChecked(True)


class Switch(QAbstractButton):
    """Keyboard-accessible switch matching the GTK automatic-bitrate control."""
    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(44, 26)
        self.setAccessibleName('自动码率')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#6962df' if self.isChecked() else '#d5d9e5'))
        if not self.isEnabled():
            painter.setOpacity(0.45)
        painter.drawRoundedRect(QRectF(1, 2, 42, 22), 11, 11)
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(QRectF(23 if self.isChecked() else 4, 5, 16, 16))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor('#9d96ed'))
            painter.drawRoundedRect(QRectF(0, 1, 43, 24), 12, 12)


class ConnectionPanel:
    def __init__(self, saved, changed, connect, disconnect, search, video_page, arrange, install):
        self.driver_ready = False
        self.widget, layout = page('屏幕连接', '把 iPad 变成随身显示器')
        self.controls, controls = card()
        controls.addWidget(label('显示模式', 'field-label'))
        self.mode = Choice((('extend', '扩展屏幕'), ('mirror', '镜像主屏')), saved['display_mode'])
        controls.addWidget(self.mode)
        self.mode_hint = label('', 'hint', True)
        controls.addWidget(self.mode_hint)
        self.position = Choice((('left', '左侧'), ('right', '右侧')), saved.get('display_position', 'right'))
        self.position.setToolTip('选择副屏默认放在电脑桌面左侧或右侧；下次连接时生效。')
        self.position_row = row(label('副屏位置', 'field-label'), self.position, spacing=25)
        self.position_row.layout().setStretch(1, 1)
        controls.addWidget(self.position_row)
        self.install_button = button('安装扩展组件', install, 'plain')
        controls.addWidget(self.install_button, 0, Qt.AlignmentFlag.AlignLeft)
        separator = styled(QFrame(), 'separator')
        separator.setFixedHeight(1)
        controls.addWidget(separator)
        self.transport = Choice((('usb', 'USB'), ('wifi', 'Wi-Fi')), saved['transport'])
        transport_row = row(label('连接方式', 'field-label'), self.transport, spacing=25)
        transport_row.layout().setStretch(1, 1)
        controls.addWidget(transport_row)
        self.address = QLineEdit(saved['address'])
        self.address.setPlaceholderText('iPad IP 地址，留空自动搜索')
        self.address.setAccessibleName('iPad IP 地址')
        self.search_button = button('', search)
        self.search_button.setIcon(icon('search'))
        self.search_button.setToolTip('搜索同一局域网中的 iPad')
        self.search_button.setAccessibleName('搜索 iPad')
        self.network = row(self.address, self.search_button, spacing=10)
        self.network.layout().setStretch(0, 1)
        controls.addWidget(self.network)
        layout.addWidget(self.controls)
        status, status_layout = card()
        badge = label('', 'status-icon')
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(62, 62)
        badge.setPixmap(icon('display', '#7770de', 34).pixmap(QSize(34, 34)))
        words = QWidget()
        word_layout = QVBoxLayout(words)
        word_layout.setContentsMargins(0, 0, 0, 0)
        word_layout.setSpacing(7)
        self.heading = label('未连接', 'status-title')
        self.detail = label('请在 iPad 上打开 OpenDisplay', 'status-detail', True)
        word_layout.addWidget(self.heading)
        word_layout.addWidget(self.detail)
        status_row = row(badge, words, spacing=16)
        status_row.layout().setStretch(1, 1)
        status_layout.addWidget(status_row)
        self.summary = label('原生 · 60 FPS · 自动码率', 'muted')
        self.video_link = button('调整画面', video_page, 'plain')
        status_layout.addWidget(row(self.summary, None, self.video_link))
        self.connect_button = button('连接 iPad', connect, 'primary')
        self.stop_button = button('断开连接', disconnect, 'disconnect')
        self.arrange_button = button('排列屏幕', arrange, 'plain')
        self.busy_label = label('', 'muted')
        status_layout.addWidget(row(self.connect_button, self.stop_button, self.busy_label, None,
                                   self.arrange_button, spacing=10))
        layout.addWidget(status)
        layout.addStretch()
        self.footer = label('关闭窗口后保留在托盘；托盘菜单可彻底退出。', 'muted', True)
        layout.addWidget(self.footer)
        self.mode.changed.connect(changed)
        self.position.changed.connect(changed)
        self.transport.changed.connect(changed)
        self.address.textChanged.connect(changed)
        self.update_visibility()

    def update_visibility(self):
        extend = self.mode.get() == 'extend'
        self.position_row.setVisible(extend)
        self.install_button.setVisible(extend and not self.driver_ready)
        self.arrange_button.setVisible(extend)
        self.network.setVisible(self.transport.get() == 'wifi')
        extension_hint = ('把窗口拖到 iPad，扩展你的桌面。' if self.driver_ready else
                          '首次使用扩展屏幕需要安装扩展组件。')
        self.mode_hint.setText(extension_hint if extend else
                               '镜像直接读取主屏，保留电脑的分辨率与屏幕布局。')


class VideoPanel:
    PRESETS = ('native', '2224x1668', '1920x1440', '1920x1200', '1600x1200', '1280x960')

    def __init__(self, data, changed):
        self.widget, layout = page('画面设置', '未连接时可修改，连接时自动应用')
        self.controls, controls = card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(24)
        grid.setColumnStretch(1, 1)
        controls.addLayout(grid)
        self.resolution = QComboBox()
        self.resolution.setAccessibleName('分辨率')
        for value in self.PRESETS:
            self.resolution.addItem('自动原生' if value == 'native' else value.replace('x', ' × '), value)
        self.resolution.addItem('自定义…', 'custom')
        grid.addWidget(label('分辨率', 'field-label'), 0, 0)
        grid.addWidget(self.resolution, 0, 1)
        self.width = self.spin(320, 3840, 8, '自定义宽度')
        self.height = self.spin(320, 3840, 2, '自定义高度')
        self.custom = row(self.width, label('×'), self.height, label('像素', 'muted'), None, spacing=8)
        grid.addWidget(self.custom, 1, 1)
        self.fps = self.spin(15, 60, 1, '目标帧率')
        grid.addWidget(label('目标帧率', 'field-label'), 2, 0)
        grid.addWidget(row(self.fps, label('FPS', 'muted'), None), 2, 1)
        self.auto = Switch()
        grid.addWidget(label('自动码率', 'field-label'), 3, 0)
        grid.addWidget(row(self.auto, label('USB 24 · Wi-Fi 10 Mbps', 'muted'), None), 3, 1)
        self.bitrate = self.spin(1, 50, 1, '手动码率')
        self.manual = row(self.bitrate, label('Mbps · 1–50', 'muted'), None)
        grid.addWidget(self.manual, 4, 1)
        layout.addWidget(self.controls)
        self.hint = label('画面等比缩放，保留电脑显示设置；扩展屏尺寸在 Windows 显示设置中调整。', 'hint', True)
        layout.addWidget(self.hint)
        self.notice = label('', 'error', True)
        layout.addWidget(self.notice)
        layout.addStretch()
        self.load(data)
        self.resolution.currentIndexChanged.connect(changed)
        for item in (self.width, self.height, self.fps, self.bitrate):
            item.valueChanged.connect(changed)
        self.auto.toggled.connect(changed)

    @staticmethod
    def spin(minimum, maximum, step, name):
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setSingleStep(step)
        widget.setFixedWidth(104)
        widget.setAccessibleName(name)
        return widget

    def load(self, data):
        video = VideoOptions.from_dict(data)
        value = video.resolution if video.resolution in self.PRESETS else 'custom'
        self.resolution.setCurrentIndex(self.resolution.findData(value))
        width, height = video.size or (2224, 1668)
        self.width.setValue(width)
        self.height.setValue(height)
        self.fps.setValue(video.fps)
        self.auto.setChecked(video.bitrate_mbps == 0)
        self.bitrate.setValue(video.bitrate_mbps or 10)
        self.update_visibility()

    def values(self):
        value = self.resolution.currentData()
        if value == 'custom':
            value = f'{self.width.value()}x{self.height.value()}'
        return VideoOptions(value, self.fps.value(), 0 if self.auto.isChecked() else self.bitrate.value())

    def update_visibility(self):
        self.custom.setVisible(self.resolution.currentData() == 'custom')
        self.manual.setVisible(not self.auto.isChecked())
