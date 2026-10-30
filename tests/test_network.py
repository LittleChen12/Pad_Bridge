# SPDX-License-Identifier: GPL-3.0-or-later
"""Network boundaries: fragmented greetings, peer validation, and user addresses."""
import json
import socket
import struct
import threading
import unittest
from unittest.mock import patch

from padbridge_app import network
from odx11 import protocol


HELLO = {'type': 'hello', 'device': 'iPad', 'pv': 3, 'id': 'test-ipad',
         'panel': {'pixelsWide': 2224, 'pixelsHigh': 1668, 'scale': 2}}


class Server:
    def __init__(self, payload, fragmented=False):
        self.payload = payload
        self.fragmented = fragmented
        self.received = None
        self.server = socket.socket()
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(1)
        self.endpoint = self.server.getsockname()

    def __enter__(self):
        def serve():
            self.server.settimeout(3)
            try:
                with self.server.accept()[0] as client:
                    client.settimeout(3)
                    if self.fragmented:
                        for i in range(0, len(self.payload), 3):
                            client.sendall(self.payload[i:i+3])
                    else:
                        client.sendall(self.payload)
                    self.received = client.recv(1)
            except (OSError, TimeoutError):
                pass
            finally:
                self.server.close()
        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.thread.join(4)
        self.server.close()


class AddressTests(unittest.TestCase):
    def test_common_lan_addresses(self):
        for raw, expected in (
            ('192.168.8.42', ('192.168.8.42', 9000)),
            ('192.168.8.42:9001', ('192.168.8.42', 9001)),
            ('iPad.local', ('iPad.local', 9000)),
            ('[fe80::1%wlo1]:9000', ('fe80::1%wlo1', 9000)),
        ):
            self.assertEqual(network.parse_endpoint(raw), expected)

    def test_malformed_addresses_fail_before_connecting(self):
        for value in ('', 'https://ipad.local', 'iPad.local;command', '1.2.3.4:0',
                      '1.2.3.4:65536', '1.2.3.4:text', '239.1.2.3', '0.0.0.0',
                      '[::1]:-1', 'host.invalid', 'iPad.local\ncommand'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                network.parse_endpoint(value)

    def test_txt_records_can_include_unknown_and_bad_values(self):
        self.assertEqual(network.parse_txt([list(b'id=abc'), b'pv=3', b'flag', b'bad=\xff']),
                         {'id': 'abc', 'pv': '3'})

    def test_multiple_receivers_require_a_selection(self):
        receivers = [network.Receiver('one', 'one.local', '192.168.1.2'),
                     network.Receiver('two', 'two.local', '192.168.1.3')]
        with patch.object(network, 'discover', return_value=receivers), patch.object(network, 'probe') as probe:
            with self.assertRaisesRegex(RuntimeError, '多个'):
                network.resolve_target('')
            probe.assert_not_called()


class ProbeTests(unittest.TestCase):
    def test_tcp_backlog_is_bounded_without_system_changes(self):
        with socket.socket() as sock:
            network.configure_video_socket(sock)
            # Linux reports twice the requested value for bookkeeping overhead.
            self.assertLessEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF), 128 * 1024)
            if hasattr(socket, 'TCP_NOTSENT_LOWAT'):
                self.assertEqual(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NOTSENT_LOWAT), 16 * 1024)

    def test_fragmented_greeting_and_non_disruptive_probe(self):
        data = protocol.encode_control(HELLO)
        with Server(data, fragmented=True) as peer:
            hello = network.probe(peer.endpoint, 'test-ipad')
            self.assertEqual(hello['panel']['pixelsHigh'], 1668)
        self.assertEqual(peer.received, b'', 'A probe must not send takeover bytes')

    def test_wrong_peer_identity_is_rejected(self):
        with Server(protocol.encode_control(HELLO)) as peer:
            with self.assertRaisesRegex(ValueError, '身份'):
                network.probe(peer.endpoint, 'different-ipad')

    def test_oversized_and_empty_greetings_are_rejected_without_body(self):
        for size in (0, protocol.MAX_INBOUND, 0xffffffff):
            with Server(struct.pack('!I', size)) as peer:
                with self.assertRaises(ValueError):
                    network.probe(peer.endpoint)

    def test_other_services_and_future_protocol_are_rejected(self):
        for hello in ({'type': 'ping'}, {'type': 'hello', 'pv': 3}, {**HELLO, 'pv': 4}):
            with Server(protocol.encode_control(hello)) as peer:
                with self.assertRaises(ValueError):
                    network.probe(peer.endpoint)

    def test_truncated_greeting(self):
        with Server(struct.pack('!I', 100)) as peer:
            with self.assertRaises((OSError, EOFError)):
                network.probe(peer.endpoint, timeout=0.05)


if __name__ == '__main__':
    unittest.main()
