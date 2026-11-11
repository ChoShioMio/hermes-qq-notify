import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_original_read = Path.read_text

def isolated_read(path, *args, **kwargs):
    if path in (ROOT / '.env', ROOT / 'state.json'):
        return ''
    return _original_read(path, *args, **kwargs)

with patch.object(Path, 'read_text', isolated_read), patch.dict(os.environ, {'HERMES_HOME': str(ROOT / 'tests' / 'fake-home')}, clear=True):
    import notifier as n


class MediaTests(unittest.TestCase):
    def test_check_exits_before_qq_or_server_start(self):
        with patch.object(sys, 'argv', ['notifier.py', '--check']), patch.object(n, 'preflight', return_value=True), patch.object(n.QQ, 'token', side_effect=AssertionError('network forbidden')), patch.object(n.QQ, 'send_notification', side_effect=AssertionError('send forbidden')), patch.object(n.threading, 'Thread', side_effect=AssertionError('worker forbidden')), patch.object(n, 'ThreadingHTTPServer', side_effect=AssertionError('listener forbidden')):
            self.assertEqual(n.main(), 0)

    def test_missing_title_database_is_optional(self):
        with patch.object(n, 'APPID', 'fake-app'), patch.object(n, 'SECRET', 'fake'), patch.object(n, 'OPENID', 'fake-user'), patch.object(n, 'NOTIFY_SECRET', 'fake-hmac'), patch.object(n, 'HOST', '127.0.0.1'), patch.object(n, 'SANDBOX', False), patch.object(n, 'ENV', {'QQ_BOUND_APPID': 'fake-app', 'QQ_BOUND_SANDBOX': '0'}), patch.object(Path, 'exists', return_value=False), patch.object(n, 'log'):
            self.assertTrue(n.preflight())

    def test_batch_clarify_renders_questions_choices_and_call_identity(self):
        payload = {'session_id': 'fake', 'tool_name': 'clarify', 'tool_input': {'questions': [
            {'question': '是否继续？', 'choices': ['继续', '停止']},
            {'question': '选择模块', 'choices': ['甲', '乙'], 'multi_select': True},
        ]}, 'extra': {'tool_call_id': 'call-one'}}
        with patch.object(n, 'meta_lines', return_value=[]):
            first = n.build_message('pre_tool_call', payload)
            self.assertIsNotNone(first)
            key, text = first
            for value in ('是否继续？', '继续 / 停止', '选择模块', '甲 / 乙', '多选'):
                self.assertIn(value, text)
            self.assertEqual(n.build_message('pre_tool_call', payload)[0], key)
            payload['extra']['tool_call_id'] = 'call-two'
            self.assertNotEqual(n.build_message('pre_tool_call', payload)[0], key)

    def test_batch_clarify_fallback_identity_includes_all_questions_and_choices(self):
        payload = {'session_id': 'fake', 'tool_name': 'clarify', 'tool_input': {'questions': [{'question': '相同问题', 'choices': ['甲', '乙']}]}}
        with patch.object(n, 'meta_lines', return_value=[]):
            first = n.build_message('pre_tool_call', payload)
            self.assertIsNotNone(first)
            payload['tool_input']['questions'][0]['choices'] = ['甲', '丙']
            self.assertNotEqual(n.build_message('pre_tool_call', payload)[0], first[0])

    def test_legacy_clarify_still_renders(self):
        with patch.object(n, 'meta_lines', return_value=[]):
            built = n.build_message('pre_tool_call', {'session_id': 'fake', 'tool_name': 'clarify', 'tool_input': {'question': '旧格式', 'options': [{'label': '是'}, {'label': '否'}]}})
        self.assertIsNotNone(built)
        self.assertIn('是 / 否', built[1])

    def test_image_send_timeout_does_not_fallback_and_duplicate(self):
        client = n.QQClient('fake-app', 'fake-secret', 'https://example.invalid', openid='fake-user')
        with patch.object(client, 'token', return_value='fake-token'), patch.object(client, '_request', side_effect=[(200, {'file_info': 'fake-info'}), TimeoutError()]) as request, patch.dict(sys.modules, {'message_card': SimpleNamespace(render_card=lambda text: b'fake-png')}), patch.object(n, 'log'):
            self.assertFalse(client.send_notification('通知'))
        self.assertEqual(request.call_count, 2)

    def test_upload_failure_falls_back_to_short_text(self):
        client = n.QQClient('fake-app', 'fake-secret', 'https://example.invalid', openid='fake-user')
        with patch.object(client, 'token', return_value='fake-token'), patch.object(client, '_request', side_effect=[(403, {'code': '10000'}), (200, {'id': 'fake-id'})]) as request, patch.dict(sys.modules, {'message_card': SimpleNamespace(render_card=lambda text: b'fake-png')}), patch.object(n, 'log'):
            self.assertTrue(client.send_notification('通知正文' * 600))
        body = request.call_args.args[1]
        self.assertEqual(body['msg_type'], 0)
        self.assertLess(len(body['content']), 600)

    def test_smart_approval_and_pure_chat_are_suppressed(self):
        with patch.object(n, 'meta_lines', return_value=[]), patch.object(n, 'log'), patch.object(n, 'ONLY_TOOL_TURNS', True):
            self.assertIsNone(n.build_message('pre_approval_request', {'extra': {'surface': 'smart', 'command': 'fake'}}))
            self.assertIsNone(n.build_message('post_llm_call', {'extra': {'assistant_response': '收到', 'conversation_history': [{'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': '收到'}]}}))

    def test_preflight_refuses_unsigned_or_cross_bot_binding(self):
        with patch.object(n, 'APPID', 'new-app'), patch.object(n, 'SECRET', 'fake'), patch.object(n, 'OPENID', 'fake-user'), patch.object(n, 'NOTIFY_SECRET', ''), patch.object(n, 'HOST', '127.0.0.1'), patch.object(n, 'ENV', {'QQ_BOUND_APPID': 'old-app'}), patch.object(Path, 'exists', return_value=True), patch.object(n, 'log'):
            self.assertFalse(n.preflight())

    def test_completion_keeps_markdown_for_image_rendering(self):
        payload = {'session_id': 'fake', 'extra': {'turn_id': 'one', 'assistant_response': '## 结果\n**已完成**\n```python\nsecret_code()\n```'}}
        with patch.object(n, 'meta_lines', return_value=[]), patch.object(n, 'ONLY_TOOL_TURNS', False):
            text = n.build_message('post_llm_call', payload)[1]
        self.assertIn('**已完成**', text)
        self.assertIn('## 结果', text)
        self.assertIn('[代码块已省略]', text)
        self.assertNotIn('secret_code', text)

    def test_notification_uploads_inline_png_and_sends_media(self):
        client = n.QQClient('fake-app', 'fake-secret', 'https://example.invalid', openid='fake-user')
        calls = []
        def request(path, payload, token):
            calls.append((path, payload))
            if path.endswith('/files'):
                return 200, {'file_info': 'fake-file-info'}
            return 200, {'id': 'fake-message'}
        with patch.object(client, 'token', return_value='fake-token'), patch.object(client, '_request', side_effect=request), patch.dict(sys.modules, {'message_card': SimpleNamespace(render_card=lambda text: b'fake-png')}), patch.object(n, 'log'):
            self.assertTrue(client.send_notification('# 标题\n**通知正文**'))
        self.assertEqual(calls[0][0], '/v2/users/fake-user/files')
        self.assertFalse(calls[0][1]['srv_send_msg'])
        self.assertEqual(calls[0][1]['file_data'], 'ZmFrZS1wbmc=')
        self.assertEqual(calls[1][1]['msg_type'], 7)
        self.assertEqual(calls[1][1]['media']['file_info'], 'fake-file-info')
        self.assertNotIn('**', calls[1][1].get('content', ''))

if __name__ == '__main__':
    unittest.main()
