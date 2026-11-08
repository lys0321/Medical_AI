"""识图接口：出题、作答、独立统计，以及“图片题不影响文本题错点”的回归。"""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

LABELS = {'available': True, 'reason': '', 'requires_teacher_review': True, 'message': '',
          'notice': '标注待教师审核', 'pages': []}

ANSWER = '被覆上皮的类型'
QUESTION = {'image_number': 2, 'image': 'histology-2.png',
            'image_url': '/api/course-materials/images/histology-2.png',
            'prompt': '第 2 页资料的小标题是下面哪一项？',
            'options': [ANSWER, '红细胞形态', '白细胞分类', '血小板结构'],
            'answer': ANSWER, 'tissue': '结缔组织', 'stains': [],
            'source_page': 2, 'review_status': 'pending'}


def fake_build(labels, rng=None, option_count=4):
    return {**QUESTION, 'options': list(QUESTION['options'])}


class ImageQuizHttpTests(unittest.TestCase):
    learner = 'b' * 48

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db_patch = patch.object(server, 'DB_PATH', Path(cls.temp.name) / 'image.sqlite3')
        cls.db_patch.start()
        server.init_db()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.http.server_port)
        cls.patches = [patch.object(server.histology_quiz, 'load_labels', return_value=LABELS),
                       patch.object(server.histology_quiz, 'build_question', side_effect=fake_build)]
        for item in cls.patches:
            item.start()

    @classmethod
    def tearDownClass(cls):
        for item in reversed(cls.patches):
            item.stop()
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=3)
        cls.db_patch.stop()
        cls.temp.cleanup()

    def setUp(self):
        with server.connect() as db:
            db.execute('DELETE FROM attempts')
            db.execute('DELETE FROM learners')
            db.execute('DELETE FROM events')

    def post(self, path, body):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode(),
            headers={'X-Learner-ID': self.learner, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def next_question(self):
        status, payload = self.post('/api/image-quiz', {'action': 'next'})
        self.assertEqual(status, 200)
        self.assertTrue(payload['available'])
        return payload['question']

    def answer(self, token, choice):
        return self.post('/api/image-quiz', {'action': 'answer', 'token': token, 'choice': choice})

    def seed_text_error(self):
        concept, question = server.QUESTION_MAP['oculomotor-pre']
        rubric = []
        for index, point in enumerate(question['points']):
            rubric.append({'label': point['label'],
                           'selected': point['options'][0] if index else point['correct'],
                           'correct': index == 0, 'expected': point['correct'],
                           'reason': point['reason'], 'category': point['category']})
        payload = {'question': question['id'], 'concept': concept['id'], 'kind': question['kind'],
                   'score': 33, 'rubric': rubric, 'assisted': False, 'confidence': '未填写'}
        with server.connect() as db:
            db.execute('INSERT INTO attempts(learner,token,concept,question,kind,score,payload,created) '
                       'VALUES(?,?,?,?,?,?,?,?)',
                       (self.learner, 'text-token', concept['id'], question['id'], question['kind'],
                        1 / 3, json.dumps(payload, ensure_ascii=False), time.time()))

    # --- 出题 ---

    def test_next_returns_four_options_without_the_answer(self):
        question = self.next_question()
        self.assertEqual(len(question['options']), 4)
        self.assertEqual(len(set(question['options'])), 4)
        self.assertNotIn('answer', question)
        self.assertEqual(question['kind'], 'image')
        self.assertEqual(question['review_status'], 'pending')
        self.assertIn('待', question['notice'])
        self.assertTrue(question['image_url'].startswith('/api/course-materials/images/'))

    def test_no_labels_means_no_question(self):
        with patch.object(server.histology_quiz, 'load_labels',
                          return_value={'available': False, 'reason': 'no_labels',
                                        'message': '本机还没有组胚识图标注'}):
            status, payload = self.post('/api/image-quiz', {'action': 'next'})
        self.assertEqual(status, 200)
        self.assertFalse(payload['available'])
        self.assertEqual(payload['reason'], 'no_labels')
        self.assertNotIn('question', payload)

    def test_not_enough_labels_means_no_question(self):
        with patch.object(server.histology_quiz, 'build_question', return_value=None):
            status, payload = self.post('/api/image-quiz', {'action': 'next'})
        self.assertEqual(status, 200)
        self.assertFalse(payload['available'])
        self.assertEqual(payload['reason'], 'not_enough_labels')

    # --- 作答 ---

    def test_correct_answer_is_recorded_as_image_attempt(self):
        question = self.next_question()
        status, payload = self.answer(question['token'], ANSWER)
        self.assertEqual(status, 200)
        self.assertTrue(payload['correct'])
        with server.connect() as db:
            rows = db.execute("SELECT concept, kind, score FROM attempts WHERE learner=?",
                              (self.learner,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['kind'], 'image')
        self.assertEqual(rows[0]['concept'], 'histology')
        self.assertEqual(rows[0]['score'], 1.0)

    def test_wrong_answer_scores_zero(self):
        question = self.next_question()
        wrong = next(option for option in question['options'] if option != ANSWER)
        status, payload = self.answer(question['token'], wrong)
        self.assertEqual(status, 200)
        self.assertFalse(payload['correct'])
        self.assertEqual(payload['answer'], ANSWER)
        with server.connect() as db:
            row = db.execute("SELECT score FROM attempts WHERE learner=?", (self.learner,)).fetchone()
        self.assertEqual(row['score'], 0.0)

    def test_repeated_answer_is_idempotent(self):
        question = self.next_question()
        first = self.answer(question['token'], ANSWER)[1]
        second = self.answer(question['token'], ANSWER)[1]
        self.assertEqual(first['result'], second['result'])
        with server.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM attempts WHERE learner=?",
                               (self.learner,)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_unknown_token_and_bad_choice_are_rejected(self):
        self.assertEqual(self.answer('f' * 32, '任意')[0], 400)
        question = self.next_question()
        self.assertEqual(self.answer(question['token'], '不存在的选项')[0], 400)

    # --- 与文本题隔离 ---

    def test_image_stats_are_separate_from_text_mastery(self):
        self.seed_text_error()
        question = self.next_question()
        self.answer(question['token'], ANSWER)
        with server.connect() as db:
            overview = server.overview_payload(db, self.learner)
            report = server.report(db, self.learner)
        self.assertEqual(overview['image_quiz']['attempts'], 1)
        self.assertEqual(overview['image_quiz']['correct'], 1)
        # 文本侧完全不受影响：只有 1 个知识点被测评，历史里没有 histology。
        self.assertEqual(overview['stats']['assessed'], 1)
        self.assertEqual(len(report['history']), 1)
        self.assertNotIn('histology', [item['concept'] for item in report['history']])
        self.assertIn('组胚识图题单独统计', report['method'])

    def test_wrong_image_answer_does_not_clear_text_error_points(self):
        self.seed_text_error()
        with server.connect() as db:
            before = server.report(db, self.learner)
        question = self.next_question()
        wrong = next(option for option in question['options'] if option != ANSWER)
        self.answer(question['token'], wrong)
        with server.connect() as db:
            after = server.report(db, self.learner)
        self.assertEqual(after['errors'], before['errors'])
        self.assertGreaterEqual(len(after['evidence_report']['review_items']), 1)
        self.assertEqual(after['evidence_report']['counts']['missing_points'],
                         before['evidence_report']['counts']['missing_points'])
        self.assertEqual(after['evidence_report']['review_items'],
                         before['evidence_report']['review_items'])


if __name__ == '__main__':
    unittest.main()