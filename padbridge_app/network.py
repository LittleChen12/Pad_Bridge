# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenDisplay LAN discovery through the desktop's Avahi, without subnet scans."""
from dataclasses import asdict, dataclass
import ipaddress
import json
import logging
import re
import socket

from odx11 import protocol

SERVICE = '_opensidecar._tcp'
DEFAULT_PORT = 9000
log = logging.getLogger('padbridge.network')


def configure_video_socket(sock):
    """Bound this stream's TCP backlog so Wi-Fi stalls don't queue seconds of video.

    The existing leaky raw-frame queue keeps the newest capture while sendall is
    backpressured. Encoded H.264 frames must never be arbitrarily discarded.
    """
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 64 * 1024)
    if hasattr(socket, 'TCP_NOTSENT_LOWAT'):
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NOTSENT_LOWAT, 16 * 1024)
        except OSError:
            pass  # SO_SNDBUF still bounds the backlog on kernels without this option.
    log.info('Wi-Fi TCP 发送缓冲：%d bytes', sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF))


@dataclass(frozen=True)
class Receiver:
    name: str
    host: str
    address: str
    port: int = DEFAULT_PORT
    identifier: str = ''

    @property
    def endpoint(self):
        return format_endpoint(self.address, self.port)

    def to_dict(self):
        return {**asdict(self), 'endpoint': self.endpoint}


def format_endpoint(host, port=DEFAULT_PORT):
    return f'[{host}]:{port}' if ':' in host else f'{host}:{port}'


def parse_endpoint(text):
    """IPv4, bracketed IPv6, or an explicit .local hostname; optional TCP port."""
    value = text.strip()
    if not value or len(value) > 300:
        raise ValueError('请输入 iPad 的局域网 IP，或留空自动搜索。')
    port = DEFAULT_PORT
    if value.startswith('['):
        match = re.fullmatch(r'\[([^\]]+)\](?::([0-9]+))?', value)
        if not match:
            raise ValueError('IPv6 地址格式应为 [地址]:9000。')
        host = match.group(1)
        if match.group(2):
            port = int(match.group(2))
    elif value.count(':') == 1:
        host, raw_port = value.rsplit(':', 1)
        if not raw_port.isdecimal():
            raise ValueError('端口必须是数字。')
        port = int(raw_port)
    else:
        host = value
    if not 1 <= port <= 65535:
        raise ValueError('端口必须在 1–65535 之间。')
    try:
        address = ipaddress.ip_address(host)
        if address.is_unspecified or address.is_multicast:
            raise ValueError('需要 iPad 的单播 IP 地址。')
    except ValueError:
        labels = host.rstrip('.').split('.')
        if (len(labels) < 2 or labels[-1].lower() != 'local' or
                any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', p)
                    for p in labels)):
            raise ValueError('地址应为局域网 IP 或设备的 .local 主机名，不能是网页链接。') from None
    return host, port


def parse_txt(items):
    result = {}
    for item in items:
        try:
            key, sep, value = bytes(item).decode('utf-8').partition('=')
            if sep:
                result[key] = value
        except (UnicodeError, ValueError, TypeError):
            continue
    return result


def discover(timeout=4.0):
    """Browse IPv4 Bonjour advertisements, then resolve them asynchronously.

    A private GLib context makes this safe to invoke on a GTK worker thread.
    No port is probed and no connection is adopted during discovery.
    """
    from gi.repository import Gio, GLib
    context = GLib.MainContext.new()
    context.push_thread_default()
    loop = GLib.MainLoop.new(context, False)
    found, errors, subscriptions = {}, [], []
    browser = None
    timer = None
    bus = None
    cancelled = Gio.Cancellable()
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, cancelled)

        def resolved(conn, response, key):
            try:
                data = conn.call_finish(response).unpack()
                txt = parse_txt(data[9])
                receiver = Receiver(data[2], data[5], data[7], int(data[8]), txt.get('id', ''))
                parse_endpoint(receiver.endpoint)
                found[key] = receiver
            except (GLib.Error, ValueError, TypeError):
                pass

        def signal(conn, sender, path, interface, member, params, user_data):
            if browser and path != browser:
                return
            args = params.unpack()
            if member == 'Failure':
                errors.append(str(args[0]))
                loop.quit()
            elif member == 'ItemNew':
                i, p, name, kind, domain, flags = args
                key = (i, p, name, kind, domain)
                conn.call('org.freedesktop.Avahi', '/', 'org.freedesktop.Avahi.Server',
                          'ResolveService', GLib.Variant('(iisssiu)', (*key, 0, 0)),
                          None, Gio.DBusCallFlags.NONE, 2000, cancelled, resolved, key)
            elif member == 'ItemRemove':
                found.pop(tuple(args[:5]), None)

        subscriptions.append(bus.signal_subscribe(
            'org.freedesktop.Avahi', 'org.freedesktop.Avahi.ServiceBrowser', None,
            None, None, Gio.DBusSignalFlags.NONE, signal, None))
        browser = bus.call_sync('org.freedesktop.Avahi', '/', 'org.freedesktop.Avahi.Server',
                                'ServiceBrowserNew', GLib.Variant('(iissu)', (-1, 0, SERVICE, 'local', 0)),
                                None, Gio.DBusCallFlags.NONE, 2000, cancelled).unpack()[0]
        timer = GLib.timeout_source_new(max(100, int(timeout * 1000)))
        timer.set_callback(lambda *_: (loop.quit(), False)[1])
        timer.attach(context)
        loop.run()
        if errors and not found:
            raise RuntimeError('局域网设备搜索失败：' + errors[0])
        unique = {(r.address, r.port, r.identifier): r for r in found.values()}
        return sorted(unique.values(), key=lambda r: (r.name.casefold(), r.address, r.port))
    except GLib.Error as exc:
        raise RuntimeError('无法使用 Avahi 搜索设备；仍可直接输入 iPad 的 IP 地址。') from exc
    finally:
        cancelled.cancel()
        if timer:
            timer.destroy()
        if bus:
            for subscription in subscriptions:
                bus.signal_unsubscribe(subscription)
            if browser:
                try:
                    bus.call_sync('org.freedesktop.Avahi', browser,
                                  'org.freedesktop.Avahi.ServiceBrowser', 'Free', None,
                                  None, Gio.DBusCallFlags.NONE, 1000, None)
                except GLib.Error:
                    pass
        context.pop_thread_default()


def _exact(sock, length):
    data = bytearray()
    while len(data) < length:
        block = sock.recv(length - len(data))
        if not block:
            raise EOFError('iPad 提前关闭了连接。')
        data.extend(block)
    return bytes(data)


def probe(endpoint, expected_id='', timeout=3.0):
    """Validate the provisional hello without sending bytes or taking over a stream."""
    with socket.create_connection(endpoint, timeout=timeout) as sock:
        sock.settimeout(timeout)
        size = int.from_bytes(_exact(sock, 4), 'big')
        if not 0 < size < protocol.MAX_INBOUND:
            raise ValueError('目标设备返回了无效的 OpenDisplay 握手。')
        hello = protocol.decode_control(_exact(sock, size))
        if not hello or hello.get('type') != 'hello' or not protocol.panel_pixels(hello):
            raise ValueError('这个地址没有返回 OpenDisplay 接收端握手。')
        pv = hello.get('pv', 1)
        if not isinstance(pv, int) or isinstance(pv, bool) or not 1 <= pv <= 3:
            raise ValueError('接收端协议版本暂不兼容。')
        if expected_id and hello.get('id') != expected_id:
            raise ValueError('接收端身份与局域网广播不一致，请重新搜索。')
        return hello


def resolve_target(address=''):
    if address.strip():
        endpoint = parse_endpoint(address)
        receiver_id = ''
        name = endpoint[0]
    else:
        receivers = discover()
        if not receivers:
            raise RuntimeError('没有找到 iPad。请连接同一 Wi-Fi、允许 OpenDisplay 的“本地网络”权限，并保持 App 打开；也可手动填写 IP。')
        if len(receivers) > 1:
            choices = '；'.join(f'{r.name} ({r.endpoint})' for r in receivers)
            raise RuntimeError('发现多个接收端，请在列表中选择：' + choices)
        receiver = receivers[0]
        endpoint = (receiver.address, receiver.port)
        receiver_id, name = receiver.identifier, receiver.name
    try:
        hello = probe(endpoint, receiver_id)
    except (OSError, EOFError) as exc:
        raise RuntimeError(f'无法连接 {format_endpoint(*endpoint)}。请确认 iPad 与电脑在同一局域网，且 OpenDisplay 正在前台运行。') from exc
    return {'transport': 'wifi', 'address': format_endpoint(*endpoint), 'name': name,
            'receiver_id': hello.get('id', '')}
