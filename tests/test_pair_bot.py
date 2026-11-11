import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

class PairTests(unittest.TestCase):
    def test_only_matching_private_message_can_pair(self):
        import pair_bot as p
        event = {'op': 0, 't': 'C2C_MESSAGE_CREATE', 'd': {'content': '绑定通知 TEST', 'author': {'user_openid': 'fake-recipient'}}}
        self.assertEqual(p.recipient_for(event, '绑定通知 TEST'), 'fake-recipient')
        self.assertIsNone(p.recipient_for(event, 'other'))
        event['t'] = 'GROUP_AT_MESSAGE_CREATE'
        self.assertIsNone(p.recipient_for(event, '绑定通知 TEST'))

    def test_main_rebinding_preserves_notification_settings(self):
        import pair_bot as p

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            credentials = root / 'fake-credentials.txt'
            credentials.write_text('123456789\nfake-new-secret\n', encoding='utf-8')
            env = root / '.env'
            env.write_text(
                'NOTIFY_FORMAT=text\nSUMMARY_CHARS=731\n'
                'QQ_APPID=987654321\nQQ_SECRET=fake-old-secret\n'
                'QQ_OPENID=fake-old-recipient\nQQ_SANDBOX=0\n'
                'QQ_BOUND_APPID=987654321\nQQ_BOUND_SANDBOX=0\n',
                encoding='utf-8',
            )
            token_response = MagicMock()
            token_response.__enter__.return_value.read.return_value = json.dumps(
                {'access_token': 'fake-token'}
            ).encode()
            gateway_response = MagicMock()
            gateway_response.__enter__.return_value.read.return_value = json.dumps(
                {'url': 'wss://fake-gateway.invalid'}
            ).encode()
            ws = MagicMock()
            ws.recv.side_effect = [
                json.dumps({'op': 10, 'd': {'heartbeat_interval': 30000}}),
                json.dumps({'op': 0, 't': 'READY', 'd': {}}),
                json.dumps({
                    'op': 0, 't': 'C2C_MESSAGE_CREATE',
                    'd': {'content': '绑定通知 ABCDEF',
                          'author': {'user_openid': 'fake-new-recipient'}},
                }),
            ]
            websocket = SimpleNamespace(
                create_connection=MagicMock(return_value=ws),
                WebSocketTimeoutException=TimeoutError,
            )
            with (
                patch.object(p, 'ROOT', root),
                patch.object(sys, 'argv', ['pair_bot.py', '--credentials', str(credentials),
                                         '--environment', 'sandbox']),
                patch.dict(sys.modules, {'websocket': websocket}),
                patch.object(p.urllib.request, 'urlopen',
                             side_effect=[token_response, gateway_response]),
                patch.object(p.secrets, 'token_hex', return_value='abcdef'),
                patch.object(p.time, 'monotonic', return_value=0),
                patch('socket.socket.connect', side_effect=AssertionError('No real network')),
                patch('builtins.print'),
            ):
                self.assertEqual(p.main(), 0)

            stored = dict(line.split('=', 1) for line in env.read_text(encoding='utf-8').splitlines())
            self.assertEqual({key: stored[key] for key in (
                'QQ_APPID', 'QQ_SECRET', 'QQ_OPENID', 'QQ_SANDBOX',
                'QQ_BOUND_APPID', 'QQ_BOUND_SANDBOX',
            )}, {
                'QQ_APPID': '123456789', 'QQ_SECRET': 'fake-new-secret',
                'QQ_OPENID': 'fake-new-recipient', 'QQ_SANDBOX': '1',
                'QQ_BOUND_APPID': '123456789', 'QQ_BOUND_SANDBOX': '1',
            })
            self.assertEqual(stored['NOTIFY_FORMAT'], 'text')
            self.assertEqual(stored['SUMMARY_CHARS'], '731')
            websocket.create_connection.assert_called_once_with('wss://fake-gateway.invalid', timeout=2)
            ws.close.assert_called_once_with()

if __name__ == '__main__':
    unittest.main()
