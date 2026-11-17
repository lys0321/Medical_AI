"""Three-point self-check from the 940-point bank: API contract + isolation."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from api import drill


class TripleDrillApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / 'triple.sqlite3'
        server.init_db()
        self.learner = 'c' * 48

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def test_catalog_reports_eligible_questions(self):
        cat = drill.triple_catalog()
        self.assertTrue(cat['available'])
        self.assertIn('不计入掌握度', cat['notice'])
        total = sum(b['eligible'] for b in cat['books'].values())
        self.assertGreater(total, 0)

    def test_task_then_answer_round_trip(self):
        with server.connect() as db:
            task = drill.triple_task(db, self.learner, {'book': '系统解剖学（第10版）', 'chapter': 1})
            self.assertEqual(task['kind'], 'triple')
            self.assertEqual(len(task['points']), 3)
            self.assertEqual(len(task['options']), 3)
            self.assertTrue(all(len(o) == 4 for o in task['options']))
            self.assertIn('不计入掌握度', task['notice'])

            # Answer every point with its correct option extracted from saved state.
            state = server.state_get(db, self.learner)
            saved = state['triple_drill']['question']
            answers = [p['correct'] for p in saved['points']]
            result = drill.triple_answer(db, self.learner, {'token': task['token'], 'answers': answers})
            self.assertEqual(result['score'], 100)
            self.assertEqual(result['correct'], 3)
            self.assertFalse(result['mastery_counted'])
            self.assertEqual(len(result['rubric']), 3)

    def test_wrong_answers_score_zero_and_do_not_touch_mastery(self):
        with server.connect() as db:
            before = server.progress(db, self.learner)
            task = drill.triple_task(db, self.learner, {'book': '系统解剖学（第10版）'})
            state = server.state_get(db, self.learner)
            saved = state['triple_drill']['question']
            wrong = []
            for p in saved['points']:
                wrong.append(next(o for o in p['options'] if o != p['correct']))
            result = drill.triple_answer(db, self.learner, {'token': task['token'], 'answers': wrong})
            self.assertEqual(result['score'], 0)
            after = server.progress(db, self.learner)
            self.assertEqual([i['attempts'] for i in before], [i['attempts'] for i in after])

    def test_stale_token_and_bad_answers_are_rejected(self):
        with server.connect() as db:
            task = drill.triple_task(db, self.learner, {'book': '组织学与胚胎学（第10版）'})
            with self.assertRaises(server.InputError):
                drill.triple_answer(db, self.learner, {'token': task['token'], 'answers': ['x', 'y', 'z']})
            # After a valid clear, a reused token fails.
            state = server.state_get(db, self.learner)
            saved = state['triple_drill']['question']
            good = [p['correct'] for p in saved['points']]
            drill.triple_answer(db, self.learner, {'token': task['token'], 'answers': good})
            with self.assertRaises(server.InputError):
                drill.triple_answer(db, self.learner, {'token': task['token'], 'answers': good})


if __name__ == '__main__':
    unittest.main()
