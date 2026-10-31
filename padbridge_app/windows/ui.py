# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows Qt controller preserving the Ubuntu sidebar/cards and tray lifecycle."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import signal

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QHBoxLayout, QInputDialog,
                               QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QScrollArea,
                               QStackedWidget, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget)
from .. import __version__, network
from ..paths import ROOT
from ..preferences import preferences, save_preferences
from ..video import VideoOptions
from . import service, storage, virtual_display
from .widgets import ConnectionPanel, VideoPanel, button, card, icon, label, page, row, styled

log = logging.getLogger(__name__)


class Window(QMainWindow):
    def __init__(self, saved=None, tray=True):
        super().__init__()
        self.busy = self.running = self.quitting = False
        self.updating = True
        self.error_message = ''
        self.shown_pid = None
        self.events = queue.Queue()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='padbridge-ui')
        self.tray = None
        self.saved = saved or preferences()
        self.setWindowTitle('PadBridge')
        self.setWindowIcon(QIcon(str(ROOT / 'padbridge.svg')))
        self.resize(880, 690)
        self.setMinimumSize(760, 580)
        self.setStyleSheet(Path(__file__).with_name('styles.qss').read_text(encoding='utf-8'))
        shell = QWidget()
        shell.setObjectName('shell')
        layout = QHBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(shell)
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(203)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 24, 14, 16)
        side.setSpacing(8)
        logo = label()
        logo.setPixmap(self.windowIcon().pixmap(QSize(32, 32)))
        side.addWidget(row(logo, label('PadBridge', 'brand'), None, spacing=8))
        side.addSpacing(26)
        self.stack = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        self.navigation = {}
        for name, text, glyph in (('connection', '屏幕连接', 'display'),
                                  ('video', '画面设置', 'settings'), ('about', '关于', 'info')):
            item = button(text, lambda checked=False, key=name: self.show_page(key), 'nav')
            item.setIcon(icon(glyph))
            item.setIconSize(QSize(18, 18))
            item.setCheckable(True)
            self.nav_group.addButton(item)
            self.navigation[name] = item
            side.addWidget(item)
        side.addStretch()
        side.addWidget(label(f'v{__version__}', 'version'))
        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.connection = ConnectionPanel(self.saved, self.settings_changed, self.connect_display,
                        self.disconnect_display, self.search, lambda: self.show_page('video'),
                        lambda: os.startfile('ms-settings:display'), self.install_extension)
        self.video = VideoPanel(self.saved['video_options'], self.settings_changed)
        self.pages = {}
        for name, widget in (('connection', self.connection.widget), ('video', self.video.widget),
                             ('about', self.about_page())):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(widget)
            self.pages[name] = scroll
            self.stack.addWidget(scroll)
        self.menu = QMenu(self)
        self.menu.addAction('显示窗口', self.reveal)
        self.menu.addSeparator()
        self.menu.addAction('诊断', self.diagnose)
        self.menu.addAction('打开日志目录', self.open_logs)
        self.menu.addSeparator()
        self.menu.addAction('退出 PadBridge', self.request_quit)
        self.menu_button = styled(QToolButton(self), 'plain')
        self.menu_button.setIcon(icon('menu'))
        self.menu_button.setAccessibleName('菜单')
        self.menu_button.setToolTip('菜单')
        self.menu_button.setMenu(self.menu)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_button.setFixedSize(36, 32)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(500)
        self.save_timer.timeout.connect(self.save_settings)
        self.refresh_extension()
        self.updating = False
        self.show_page('connection')
        if tray:
            self.setup_tray()
        self.event_timer = QTimer(self)
        self.event_timer.setInterval(100)
        self.event_timer.timeout.connect(self.consume_events)
        self.event_timer.start()
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1000)
        self.status_timer.timeout.connect(self.refresh)
        self.status_timer.start()
        self.settings_changed()
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'menu_button'):
            self.menu_button.move(self.width()-54, 20)

    def about_page(self):
        widget, layout = page('关于 PadBridge', 'Windows 11 · x86_64')
        info, content = card()
        content.addWidget(label('iPad 扩展与镜像', 'section-title'))
        content.addWidget(label('镜像模式直接读取主屏。未连接时不运行截图或视频编码。', 'muted', True))
        content.addWidget(label('选择扩展屏幕后，连接时启用 iPad 副屏，断开后收回。', 'muted', True))
        content.addWidget(label('USB 连接需要 Apple 移动设备支持。Wi-Fi 需同一局域网，并允许 OpenDisplay 本地网络权限。', 'muted', True))
        link = button('获取 iPad 接收端 OpenDisplay', lambda: QDesktopServices.openUrl(
                      QUrl('https://apps.apple.com/app/id6780264891')), 'plain')
        content.addWidget(link, 0, Qt.AlignmentFlag.AlignLeft)
        content.addWidget(label('基于 OpenDisplay for X11 · GPL-3.0-or-later', 'muted'))
        layout.addWidget(info)
        layout.addWidget(row(button('连接诊断', self.diagnose), button('打开日志目录', self.open_logs), None))
        layout.addStretch()
        return widget

    def show_page(self, name):
        self.stack.setCurrentWidget(self.pages[name])
        for key, item in self.navigation.items():
            item.setChecked(key == name)

    def refresh_extension(self):
        try:
            self.connection.driver_ready = virtual_display.available()
            self.connection.update_visibility()
        except OSError as exc:
            self.show_error(str(exc))

    def settings_changed(self, *_):
        if self.updating:
            return
        self.connection.update_visibility()
        self.video.update_visibility()
        try:
            video = self.video.values()
            resolution = '原生' if video.resolution == 'native' else video.resolution.replace('x', ' × ')
            bitrate = '自动码率' if not video.bitrate_mbps else f'{video.bitrate_mbps} Mbps'
            self.connection.summary.setText(f'{resolution} · {video.fps} FPS · {bitrate}')
            self.video.notice.clear()
        except ValueError as exc:
            self.video.notice.setText(str(exc))
        self.save_timer.start()

    def save_settings(self):
        if self.running or self.busy or self.updating:
            return
        try:
            video = self.video.values()
            saved = preferences()
            data = {**saved, 'transport': self.connection.transport.get(),
                    'display_mode': self.connection.mode.get(), 'address': self.connection.address.text().strip(),
                    'display_position': self.connection.position.get(),
                    'monitor': virtual_display.AUTO if self.connection.mode.get() == 'extend' else '',
                    'video_options': video.to_dict()}
            if data != saved:
                save_preferences(data)
        except (ValueError, OSError) as exc:
            self.video.notice.setText(str(exc))

    def refresh(self):
        if self.busy or self.quitting:
            return
        facts = service.current_status()
        self.running = service.active()
        if self.running and facts.get('pid') != self.shown_pid:
            self.shown_pid = facts.get('pid')
            # A new worker is a new connection attempt, including one started
            # from the CLI. Do not cover its live state with a previous error.
            self.error_message = ''
            self.updating = True
            self.connection.mode.set(facts.get('display_mode', 'mirror'))
            self.connection.position.set(facts.get('display_position', 'right'))
            self.connection.transport.set(facts.get('transport', 'usb'))
            self.connection.address.setText(facts.get('address', ''))
            self.video.load(facts.get('video_options', VideoOptions().to_dict()))
            self.refresh_extension()
            self.updating = False
            self.settings_changed()
        self.render({'state': 'problem', 'problem': self.error_message} if self.error_message else facts)

    def render(self, facts):
        panel = self.connection
        enabled = not self.running and not self.busy and not self.quitting
        panel.controls.setEnabled(enabled)
        self.video.controls.setEnabled(enabled)
        panel.connect_button.setVisible(not self.running)
        panel.connect_button.setEnabled(not self.busy and not self.quitting)
        panel.stop_button.setVisible(self.running)
        panel.stop_button.setEnabled(not self.busy and not self.quitting)
        panel.busy_label.setText('请稍候…' if self.busy or self.quitting else '')
        panel.update_visibility()
        self.video.update_visibility()
        if self.tray:
            self.tray_stop.setEnabled(self.running and not self.busy)
            self.tray.setToolTip('PadBridge · ' + ('已连接' if self.running else '未连接'))
        if self.busy or self.quitting:
            return
        kind = facts.get('state', 'off')
        if kind == 'streaming':
            title = '镜像已连接' if panel.mode.get() == 'mirror' else '扩展屏已连接'
            width, height = facts.get('stream_size', [0, 0])
            rate = VideoOptions.from_dict(facts.get('video_options')).bitrate(facts.get('transport', 'usb'))/1000
            detail = f'{width} × {height} · {facts.get("target_fps", 60)} FPS · {rate:g} Mbps（目标）'
            if panel.mode.get() == 'mirror':
                detail += '\n保留主屏设置，iPad 等比显示'
        else:
            title, detail = {'off': ('未连接', '请在 iPad 上打开 OpenDisplay'),
                             'idle': ('等待 iPad', facts.get('problem') or '请连接设备，并打开 OpenDisplay'),
                             'dialing': ('正在连接', facts.get('problem') or '请保持 iPad 解锁，OpenDisplay 在前台'),
                             'problem': ('连接未完成', facts.get('problem') or '请检查设备连接')}.get(
                                 kind, ('准备中', '正在初始化显示服务'))
        panel.heading.setText(title)
        panel.detail.setText(detail)
        self.video.hint.setText('连接中，断开后可修改画面参数。' if self.running else
            '画面等比缩放，保留电脑显示设置；扩展屏尺寸在 Windows 显示设置中调整。')

    def work(self, function, message, done=None):
        if self.busy or self.quitting:
            return
        self.error_message = ''
        self.busy = True
        self.connection.heading.setText(message)
        self.connection.detail.setText('请稍候…')
        self.render({})
        future = self.pool.submit(function)
        future.add_done_callback(lambda result: self.events.put((result, done, False)))

    def consume_events(self):
        try:
            while True:
                future, done, exiting = self.events.get_nowait()
                self.busy = False
                try:
                    result = future.result()
                    if exiting:
                        self.finish_quit()
                        return
                    if done:
                        done(result)
                except Exception as exc:
                    log.exception('操作未完成')
                    if exiting:
                        self.quitting = False
                    self.show_error(str(exc))
                self.refresh()
        except queue.Empty:
            pass

    def show_error(self, text):
        self.error_message = text
        self.show_page('connection')
        self.reveal()
        self.render({'state': 'problem', 'problem': text})

    def connect_display(self):
        try:
            video = self.video.values()
            mode = self.connection.mode.get()
            monitor = virtual_display.AUTO if mode == 'extend' else ''
            if mode == 'extend' and not virtual_display.available():
                raise ValueError('首次扩展需要安装虚拟显示组件，请点击“安装扩展组件”。')
            args = (self.connection.transport.get(), self.connection.address.text().strip(), mode, video)
            position = self.connection.position.get()
            self.save_settings()
            self.work(lambda: service.start(*args, monitor=monitor, display_position=position), '正在连接 iPad')
        except ValueError as exc:
            self.video.notice.setText(str(exc))
            self.show_error(str(exc))

    def disconnect_display(self):
        self.work(service.stop, '正在断开连接')

    def install_extension(self):
        from .driver_setup import install
        def installed(_):
            self.error_message = ''
            self.refresh_extension()
            self.connection.detail.setText('扩展组件已就绪，请点击“连接 iPad”。')
        self.work(lambda: install(interactive=True), '正在安装扩展组件，请留意 Windows 确认窗口', installed)

    def search(self):
        def found(receivers):
            if not receivers:
                raise RuntimeError('未发现 iPad。请确认同一 Wi-Fi 和“本地网络”权限，或直接填写 IP 地址。')
            if len(receivers) == 1:
                self.connection.address.setText(receivers[0].endpoint)
            else:
                choices = [f'{r.name} · {r.endpoint}' for r in receivers]
                value, accepted = QInputDialog.getItem(self, '选择 iPad', '设备', choices, 0, False)
                if accepted:
                    self.connection.address.setText(receivers[choices.index(value)].endpoint)
        self.work(network.discover, '正在搜索 iPad', found)

    def diagnose(self):
        def show(facts):
            dialog = QDialog(self)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.setWindowTitle('PadBridge 连接诊断')
            dialog.resize(700, 500)
            layout = QVBoxLayout(dialog)
            text = QPlainTextEdit(json.dumps(facts, ensure_ascii=False, indent=2))
            text.setReadOnly(True)
            layout.addWidget(text)
            dialog.show()
        self.work(service.doctor, '正在检查连接环境', show)

    def open_logs(self):
        storage.LOG.parent.mkdir(parents=True, exist_ok=True)
        os.startfile(str(storage.LOG.parent))

    def setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.connection.footer.setText('系统托盘不可用；请使用窗口菜单退出。')
            return
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu(self)
        menu.addAction('显示窗口', self.reveal)
        self.tray_stop = menu.addAction('断开连接', self.disconnect_display)
        menu.addSeparator()
        menu.addAction('退出 PadBridge', self.request_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.reveal() if reason in (
            QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.show()

    def reveal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        self.save_settings()
        event.ignore()
        if self.tray and self.tray.isVisible() and QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
        else:
            QMessageBox.information(self, '系统托盘不可用', '请从右上角菜单选择“退出 PadBridge”。')

    def request_quit(self):
        if self.quitting:
            return
        self.save_settings()
        self.quitting = True
        self.connection.heading.setText('正在退出')
        self.render({})
        future = self.pool.submit(service.stop)
        future.add_done_callback(lambda result: self.events.put((result, None, True)))

    def finish_quit(self):
        self.status_timer.stop()
        self.event_timer.stop()
        self.save_timer.stop()
        if self.tray:
            self.tray.hide()
        self.pool.shutdown(wait=False)
        self.hide()
        QApplication.instance().quit()


def run():
    storage.LOG.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(storage.LOG.with_name('controller.log'), maxBytes=2*1024*1024,
                                   backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.getLogger().addHandler(handler)
    app = QApplication([])
    app.setApplicationName('PadBridge')
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    window = Window()
    signal.signal(signal.SIGINT, lambda *_: window.request_quit())
    window.show()
    QTimer.singleShot(0, lambda: window.work(service.cleanup_idle, '正在检查显示状态',
                                             lambda _: window.refresh_extension()))
    try:
        return app.exec()
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
