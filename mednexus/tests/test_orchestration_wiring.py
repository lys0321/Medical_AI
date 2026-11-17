"""Report endpoint exposes the G5 orchestration loop without changing scores."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from knowledge import QUESTION_MAP


class OrchestrationWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / 'loop.sqlite3'
        server.init_db()
        self.learner = 'b' * 48

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def answer_wrong(self, db):
        task = server.make_task(db, self.learner, 'oculomotor', 'diagnostic')
        active = server.state_get(db, self.learner)['active']
        _, question = QUESTION_MAP[active['question']]
        answers = ['暂时不确定' for _ in question['points']]
        return server.grade(db, self.learner, {'token': task['token'], 'answers': answers})

    def test_report_includes_next_loop_after_a_wrong_answer(self):
        with server.connect() as db:
            self.answer_wrong(db)
            report = server.report(db, self.learner)
        loop = report.get('next_loop')
        self.assertIsInstance(loop, dict)
        self.assertIn('observation', loop)
        self.assertIn('diagnoses', loop)
        self.assertIn('next_activity', loop)
        self.assertIn('plan_update', loop)
        self.assertGreaterEqual(loop['observation']['weak_count'], 1)
        activity = loop['next_activity']
        self.assertIsInstance(activity, dict)
        self.assertEqual(activity['kind'], 'transfer')
        self.assertTrue(activity['retest_points'])
        self.assertFalse(activity['mastery_claimed'])
        self.assertIn('重测', activity['reason'])

    def test_next_loop_never_claims_mastery_and_uses_original_points(self):
        with server.connect() as db:
            self.answer_wrong(db)
            loop = server.report(db, self.learner)['next_loop']
        self.assertFalse(loop['evidence_discipline']['mastery_claimed'])
        for point in loop['next_activity']['retest_points']:
            for key in ('label', 'correct', 'reason'):
                self.assertIn(key, point)

    def test_no_attempts_still_returns_a_safe_loop(self):
        with server.connect() as db:
            loop = server.report(db, self.learner)['next_loop']
        self.assertIsInstance(loop, dict)
        self.assertEqual(loop['diagnoses'], [])
        self.assertIsNone(loop['next_activity'])
        self.assertEqual(loop['plan_update']['action'], 'none')


if __name__ == '__main__':
    unittest.main()
