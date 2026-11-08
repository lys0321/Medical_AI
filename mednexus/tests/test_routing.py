"""HTTP 层：request_id、耗时日志与 SSE 流式辅导。

这些用例守住三件事：
  · 每个响应都带 X-Request-Id，日志不泄露请求内容；
  · /api/tutor 的 JSON 契约没变（拆分前的断言在 test_tutor_chat / test_http 里）；
  · /api/tutor/stream 只在“已完成引用校验”之后才分段下发。
"""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

TOKEN = 'a' * 48


class RoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db_patch = patch.object(server.core, 'DB_PATH', Path(cls.temp.name) / 'routing.sqlite3')
        cls.db_patch.start()
        server.init_db()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.http.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=3)
        cls.db_patch.stop()
        cls.temp.cleanup()

    def post(self, path, body):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode(),
            headers={'X-Learner-ID': TOKEN, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def get(self, path):
        request = urllib.request.Request(self.base + path, headers={'X-Learner-ID': TOKEN})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read()

    def make_task(self):
        status, _, raw = self.post('/api/task', {'concept': 'oculomotor'})
        self.assertEqual(status, 200)
        return json.loads(raw)['token']

    def test_every_response_carries_a_request_id(self):
        for path in ('/api/health', '/api/overview'):
            status, headers, _ = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertRegex(headers.get('X-Request-Id', ''), r'^[0-9a-f]{12}$', path)

    def test_request_log_hides_query_and_body(self):
        with patch.object(sys, 'stderr') as stderr:
            self.get('/api/health?token=secret-token')
        logged = ''.join(str(call) for call in stderr.write.call_args_list)
        self.assertIn('[http] GET /api/health', logged)
        self.assertIn('rid=', logged)
        self.assertNotIn('secret-token', logged)

    def test_stream_emits_validated_chunks_and_done(self):
        token = self.make_task()
        with patch.object(server.tutor_model, 'generator', return_value=None):
            status, headers, raw = self.post('/api/tutor/stream',
                                             {'token': token, 'message': '为什么瞳孔不一定散大？',
                                              'request_id': 'b' * 32})
        self.assertEqual(status, 200)
        self.assertTrue(headers.get('Content-Type', '').startswith('text/event-stream'))
        text = raw.decode('utf-8')
        events = [line[7:].strip() for line in text.splitlines() if line.startswith('event: ')]
        self.assertEqual(events[0], 'meta')
        self.assertEqual(events[-1], 'done')
        self.assertIn('chunk', events)
        chunks = [json.loads(line[6:])['text'] for line in text.splitlines()
                  if line.startswith('data: ') and '"text"' in line]
        self.assertTrue(chunks)
        done = json.loads([line[6:] for line in text.splitlines()
                           if line.startswith('data: ')][-1])
        assistant = [item for item in done['messages'] if item['role'] == 'assistant'][-1]
        self.assertEqual(''.join(chunks), assistant['content'])
        self.assertIn('sources', assistant)

    def test_stream_reports_errors_as_events(self):
        status, headers, raw = self.post('/api/tutor/stream',
                                         {'token': '0' * 32, 'message': '为什么', 'request_id': 'c' * 32})
        self.assertEqual(status, 200)
        self.assertTrue(headers.get('Content-Type', '').startswith('text/event-stream'))
        text = raw.decode('utf-8')
        self.assertIn('event: error', text)
        self.assertIn('error', json.loads(text.split('data: ', 1)[1].splitlines()[0]))


if __name__ == '__main__':
    unittest.main()