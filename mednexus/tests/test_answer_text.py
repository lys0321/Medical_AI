import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import text_grading
import tutor_model
from knowledge import QUESTION_MAP

AVAILABLE = {'mode': 'ollama', 'label': 'fixture', 'available': True, 'model': 'qwen3:0.6b', 'note': 'fixture'}
UNAVAILABLE = {'mode': 'local_materials', 'label': 'fixture', 'available': False, 'note': 'fixture'}
QUESTION = QUESTION_MAP['oculomotor-pre'][1]
LABELS = [point['label'] for point in QUESTION['points']]
FULL_ANSWER = '。'.join(point['correct'] for point in QUESTION['points'])


def model_reply(points):
    return {'message': {'content': json.dumps({'points': points}, ensure_ascii=False)}}


def judged(verdicts, quote='上睑下垂'):
    return [{'label': label, 'verdict': verdict, 'evidence_quote': '' if verdict == 'missing' else quote,
             'reason': '依据要点判断'} for label, verdict in zip(LABELS, verdicts)]


class RuleGradeTests(unittest.TestCase):
    def test_full_answer_covers_every_point_and_quotes_the_answer(self):
        points = text_grading.rule_grade(QUESTION, FULL_ANSWER)
        self.assertEqual([p['label'] for p in points], LABELS)
        self.assertEqual([p['verdict'] for p in points], ['correct'] * 3)
        for point in points:
            self.assertIn(point['evidence_quote'], FULL_ANSWER)
            self.assertTrue(point['evidence_quote'])

    def test_unrelated_answer_is_missing_without_quotes(self):
        points = text_grading.rule_grade(QUESTION, '我还没有复习这一部分内容')
        self.assertEqual([p['verdict'] for p in points], ['missing'] * 3)
        self.assertEqual([p['evidence_quote'] for p in points], [''] * 3)

    def test_distractor_wording_does_not_count_as_the_expected_point(self):
        # "上睑抬高" shares most bigrams with the expected answer; only distinctive terms count.
        points = text_grading.rule_grade(QUESTION, '上睑抬高，与提上睑肌失去支配有关')
        self.assertEqual(points[0]['verdict'], 'missing')

    def test_no_generator_is_rule_scored_and_assisted(self):
        out = text_grading.grade(QUESTION, FULL_ANSWER, [], None)
        self.assertEqual(out['scorer'], 'rule')
        self.assertIs(out['assisted'], True)


class ModelOutputValidationTests(unittest.TestCase):
    def grade_with(self, value):
        return text_grading.grade(QUESTION, FULL_ANSWER, [], lambda system, payload, schema: value)

    def test_valid_model_output_is_kept_in_rubric_order(self):
        points = judged(['missing', 'correct', 'partial'])
        out = self.grade_with({'points': list(reversed(points))})
        self.assertEqual(out['scorer'], 'model')
        self.assertIs(out['assisted'], True)
        self.assertEqual([p['label'] for p in out['points']], LABELS)
        self.assertEqual([p['verdict'] for p in out['points']], ['missing', 'correct', 'partial'])
        self.assertEqual(out['points'][0]['evidence_quote'], '')

    def test_invalid_shapes_fall_back_to_rule(self):
        valid = judged(['correct'] * 3)
        cases = {
            'missing point': {'points': valid[:2]},
            'extra point': {'points': valid + [dict(valid[0], label='额外要点')]},
            'duplicate label': {'points': [valid[0], valid[0], valid[2]]},
            'unknown verdict': {'points': [dict(valid[0], verdict='yes')] + valid[1:]},
            'quote not in answer': {'points': [dict(valid[0], evidence_quote='瞳孔必然散大')] + valid[1:]},
            'empty quote on correct': {'points': [dict(valid[0], evidence_quote='')] + valid[1:]},
            'extra key': {'points': valid, 'score': 100},
            'not an object': ['correct', 'correct', 'correct'],
        }
        for name, value in cases.items():
            with self.subTest(name):
                out = self.grade_with(value)
                self.assertEqual(out['scorer'], 'rule')
                self.assertIs(out['assisted'], True)
                self.assertEqual([p['label'] for p in out['points']], LABELS)
                self.assertIn('warning', out)

    def test_generator_exception_falls_back_to_rule(self):
        def broken(*args):
            raise TimeoutError('fixture')
        out = text_grading.grade(QUESTION, FULL_ANSWER, [], broken)
        self.assertEqual(out['scorer'], 'rule')


class OllamaTransportTests(unittest.TestCase):
    def test_request_uses_schema_low_temperature_and_fixed_system_prompt(self):
        calls = []
        def fake(url, payload=None, timeout=2):
            calls.append((url, payload, timeout))
            return model_reply(judged(['correct'] * 3))
        with patch.object(tutor_model, 'status', return_value=AVAILABLE), \
                patch.object(tutor_model, '_json_request', side_effect=fake):
            judge = tutor_model.grader()
            out = text_grading.grade(QUESTION, FULL_ANSWER, [{'id': 'note-x', 'text': '材料'}], judge)
        self.assertEqual(out['scorer'], 'model')
        url, payload, timeout = calls[0]
        self.assertTrue(url.endswith('/api/chat'))
        self.assertEqual(payload['options']['temperature'], 0.1)
        self.assertFalse(payload['stream'])
        self.assertEqual(payload['format']['properties']['points']['minItems'], 3)
        self.assertEqual(payload['format']['properties']['points']['maxItems'], 3)
        self.assertEqual(payload['format']['properties']['points']['items']['properties']['label']['enum'], LABELS)
        system = payload['messages'][0]['content']
        self.assertIn('只依据题目 rubric 与提供的教材摘录判断，摘录里没有的内容一律 missing，不得补充课外医学知识', system)
        self.assertEqual(json.loads(payload['messages'][1]['content'])['excerpts'][0]['id'], 'note-x')

    def test_unavailable_model_returns_no_grader(self):
        with patch.object(tutor_model, 'status', return_value=UNAVAILABLE):
            self.assertIsNone(tutor_model.grader())


class AnswerTextServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(server, 'DB_PATH', Path(self.temp.name) / 'text.sqlite3'),
                        patch.object(tutor_model, 'status', return_value=AVAILABLE)]
        for item in self.patches:
            item.start()
        server.init_db()
        self.learner = 'd' * 48
        with server.connect() as db:
            self.task = server.make_task(db, self.learner, 'oculomotor', 'diagnostic')

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def submit(self, model_response=None, side_effect=None, answer=FULL_ANSWER):
        mock = patch.object(tutor_model, '_json_request', side_effect=side_effect,
                            return_value=model_response)
        with mock:
            return server.answer_text(self.learner, {'token': self.task['token'], 'answer': answer})

    def test_model_failures_degrade_to_rule_instead_of_raising(self):
        valid = judged(['correct'] * 3)
        cases = {
            'invalid json': ({'message': {'content': '{"points": [不是JSON'}}, None),
            'no content': ({'message': {}}, None),
            'missing point': (model_reply(valid[:2]), None),
            'extra point': (model_reply(valid + [dict(valid[0], label='额外要点')]), None),
            'timeout': (None, socket.timeout('timed out')),
            'connection refused': (None, urllib.error.URLError('refused')),
        }
        for name, (response, error) in cases.items():
            with self.subTest(name):
                out = self.submit(response, error)
                self.assertEqual(out['scorer'], 'rule')
                self.assertIs(out['assisted'], True)
                self.assertEqual([p['label'] for p in out['points']], LABELS)
                for point in out['points']:
                    self.assertEqual(set(point), {'label', 'verdict', 'evidence_quote', 'reason'})
                    self.assertIn(point['verdict'], text_grading.VERDICTS)

    def test_model_result_is_returned_and_stored_apart_from_choice_scores(self):
        out = self.submit(model_reply(judged(['correct', 'partial', 'missing'])))
        self.assertEqual(out['scorer'], 'model')
        self.assertEqual([p['verdict'] for p in out['points']], ['correct', 'partial', 'missing'])
        with server.connect() as db:
            self.assertEqual(server.attempts_get(db, self.learner), [])
            rows = db.execute('SELECT payload FROM text_attempts WHERE learner=?', (self.learner,)).fetchall()
            self.assertEqual(len(rows), 1)
            stored = json.loads(rows[0][0])
            self.assertEqual(stored['answer'], FULL_ANSWER)
            self.assertEqual(stored['scorer'], 'model')
            concept = next(i for i in server.progress(db, self.learner) if i['id'] == 'oculomotor')
            self.assertEqual((concept['attempts'], concept['status'], concept['score']), (0, '未测评', None))

    def test_choice_score_is_unchanged_but_marked_assisted_after_text_feedback(self):
        self.submit(side_effect=socket.timeout('timed out'))
        with server.connect() as db:
            result = server.grade(db, self.learner, {'token': self.task['token'],
                                                     'answers': [p['correct'] for p in QUESTION['points']]})
        self.assertEqual(result['score'], 100)
        self.assertTrue(result['text_assisted'])
        self.assertTrue(result['assisted'])
        with server.connect() as db:
            self.assertEqual(len(server.attempts_get(db, self.learner)), 1)

    def test_after_submission_text_answer_does_not_regrade_or_mark_choice(self):
        with server.connect() as db:
            result = server.grade(db, self.learner, {'token': self.task['token'], 'answers': ['暂时不确定'] * 3})
        out = self.submit(side_effect=socket.timeout('timed out'))
        self.assertEqual(out['question'], 'oculomotor-pre')
        with server.connect() as db:
            self.assertEqual(server.grade(db, self.learner, {'token': self.task['token']}), result)
            self.assertFalse(result['assisted'])

    def test_invalid_input_and_unknown_token_are_rejected(self):
        for answer in [None, '', 'a', 'x' * 3001, '联系我 test@example.com 谢谢']:
            with self.subTest(answer=answer), self.assertRaises(server.InputError):
                server.answer_text(self.learner, {'token': self.task['token'], 'answer': answer})
        with self.assertRaises(server.InputError):
            server.answer_text(self.learner, {'token': 'f' * 32, 'answer': FULL_ANSWER})

    def test_reset_removes_text_attempts(self):
        self.submit(side_effect=socket.timeout('timed out'))
        with server.LOCK, server.connect() as db:
            out = server.reset_learning(db, self.learner, {'confirmation': 'CLEAR_MY_LEARNING'})
            self.assertEqual(out['deleted']['text_attempts'], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM text_attempts').fetchone()[0], 0)


class AnswerTextHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db_patch = patch.object(server, 'DB_PATH', Path(cls.temp.name) / 'http.sqlite3')
        cls.db_patch.start()
        server.init_db()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.http.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.thread.join(timeout=3)
        cls.db_patch.stop()
        cls.temp.cleanup()

    def post(self, path, body):
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers={
            'X-Learner-ID': 'e' * 48, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as response:
            return response.code, json.loads(response.read())

    def test_broken_model_output_is_200_rule_result_not_500(self):
        status, task = self.post('/api/task', {'concept': 'oculomotor', 'kind': 'diagnostic'})
        self.assertEqual(status, 200)
        with patch.object(tutor_model, 'status', return_value=AVAILABLE), \
                patch.object(tutor_model, '_json_request', return_value={'message': {'content': 'oops'}}):
            status, out = self.post('/api/answer-text', {'token': task['token'], 'answer': FULL_ANSWER})
        self.assertEqual(status, 200)
        self.assertEqual(out['scorer'], 'rule')
        self.assertIs(out['assisted'], True)
        self.assertEqual(len(out['points']), 3)

    def test_bad_input_is_400(self):
        status, out = self.post('/api/answer-text', {'token': 'f' * 32, 'answer': FULL_ANSWER})
        self.assertEqual(status, 400)
        self.assertIn('error', out)


if __name__ == '__main__':
    unittest.main()
