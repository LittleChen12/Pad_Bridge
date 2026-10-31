# SPDX-License-Identifier: GPL-3.0-or-later
"""Bonjour discovery and Apple's Windows usbmux service (loopback TCP 27015)."""
import plistlib
import socket
import threading
import time
from odx11 import protocol, usbmux
from ..network import Receiver, SERVICE, parse_endpoint

MUX_ADDRESS = ('127.0.0.1', 27015)


def mux_request(message, endpoint=MUX_ADDRESS, timeout=3):
    sock = socket.create_connection(endpoint, timeout=timeout)
    try:
        sock.sendall(usbmux.encode(message))
        head = usbmux.HEADER.unpack(usbmux._recv_exact(sock, usbmux.HEADER.size))
        length, version, kind, tag = head
        if not usbmux.HEADER.size < length <= protocol.MAX_INBOUND or (version, kind, tag) != (1, 8, 1):
            raise ValueError('Apple USB 服务返回了无效数据。')
        reply = plistlib.loads(usbmux._recv_exact(sock, length-usbmux.HEADER.size))
        if not isinstance(reply, dict):
            raise ValueError('Apple USB 服务响应无效。')
        return sock, reply
    except BaseException:
        sock.close()
        raise


def list_devices(endpoint=MUX_ADDRESS, timeout=3):
    try:
        sock, reply = mux_request({'MessageType': 'ListDevices'}, endpoint, timeout)
        with sock:
            if reply.get('Number', 0):
                raise usbmux.MuxError(reply['Number'])
            return [d for d in reply.get('DeviceList', [])
                    if isinstance(d, dict) and usbmux.is_usb(d)]
    except OSError as exc:
        raise RuntimeError('无法连接 Apple Mobile Device Service。请安装/修复 Apple Devices 或 iTunes '
                           '提供的 Apple 移动设备支持，并确认服务正在运行；Wi-Fi 不依赖此服务。') from exc


def connect_usb(device_id, endpoint=MUX_ADDRESS, timeout=3):
    sock, reply = mux_request({'MessageType': 'Connect', 'DeviceID': device_id,
                              'PortNumber': socket.htons(9000)}, endpoint, timeout)
    if reply.get('Number') != 0:
        sock.close()
        raise usbmux.MuxError(reply.get('Number'))
    return sock


def discover(timeout=4.0):
    from zeroconf import IPVersion, ServiceBrowser, ServiceListener, Zeroconf
    kind = SERVICE + '.local.'
    names, lock = set(), threading.Lock()

    class Listener(ServiceListener):
        def add_service(self, zc, service_type, name):
            with lock:
                names.add(name)

        update_service = add_service

        def remove_service(self, zc, service_type, name):
            with lock:
                names.discard(name)

    # Callbacks only collect names. Resolving on the caller avoids blocking the
    # zeroconf service thread, and the whole operation has one shared deadline.
    deadline = time.monotonic() + max(0.1, timeout)
    found = {}
    with Zeroconf(ip_version=IPVersion.All) as zc:
        browser = ServiceBrowser(zc, kind, Listener())
        try:
            resolved = set()
            while time.monotonic() < deadline:
                with lock:
                    pending = names - resolved
                for name in pending:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    info = zc.get_service_info(kind, name, timeout=max(1, int(min(0.4, remaining)*1000)))
                    if info is None:
                        continue
                    resolved.add(name)
                    identifier = info.properties.get(b'id', b'') or b''
                    for address in sorted(info.parsed_scoped_addresses(), key=lambda a: ':' in a):
                        receiver = Receiver(name.removesuffix('.'+kind), info.server or '', address,
                                            info.port, identifier.decode('utf-8', errors='replace'))
                        try:
                            parse_endpoint(receiver.endpoint)
                        except ValueError:
                            continue
                        found[name] = receiver
                        break
                time.sleep(min(0.05, max(0, deadline-time.monotonic())))
            with lock:
                return sorted((r for name, r in found.items() if name in names), key=lambda r: r.name.casefold())
        finally:
            browser.cancel()
