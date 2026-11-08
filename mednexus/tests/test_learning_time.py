"""学习时长与章节完成度：心跳只累加，统计不推断学习行为。"""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from planning import SHANGHAI


class LearningTimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / 'study.sqlite3'
        server.init_db()
        self.learner = 'b' * 48

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def today(self):
        return datetime.now(SHANGHAI).date()

    def test_heartbeat_accumulates_today_and_is_exposed_by_overview(self):
        with server.connect() as db:
            server.record_study_seconds(db, self.learner, 60)
            server.record_study_seconds(db, self.learner, 90)
            stats = server.time_stats(db, self.learner)
            overview = server.overview_payload(db, self.learner)
        self.assertEqual(stats['today_minutes'], 2.5)
        self.assertEqual(stats['total_minutes'], 2.5)
        self.assertEqual(overview['learning_time']['today_minutes'], 2.5)
        self.assertEqual(len(overview['learning_time']['series']), 7)
        self.assertEqual(overview['learning_time']['series'][-1]['date'], self.today().isoformat())

    def test_heartbeat_rejects_impossible_values(self):
        with server.connect() as db:
            for bad in (0, -5, 601, 'abc', None, True):
                with self.assertRaises(server.InputError):
                    server.record_study_seconds(db, self.learner, bad)

    def test_streak_counts_consecutive_days_without_guessing_today(self):
        day = self.today()
        with server.connect() as db:
            for back in (1, 2):
                db.execute('INSERT INTO study_time(learner,day,seconds) VALUES(?,?,?)',
                           (self.learner, (day - timedelta(days=back)).isoformat(), 600))
            # 今天还没学：连续天数从昨天往前数，不把今天算成 0 天或 3 天。
            self.assertEqual(server.time_stats(db, self.learner)['streak_days'], 2)
            server.record_study_seconds(db, self.learner, 60)
            self.assertEqual(server.time_stats(db, self.learner)['streak_days'], 3)

    def test_units_report_progress_and_completion_by_assessed_points(self):
        with server.connect() as db:
            items = server.progress(db, self.learner)
            units = server.unit_stats(items)
        self.assertEqual([u['name'] for u in units], list(server.COURSE['units']))
        self.assertEqual(sum(u['total'] for u in units), len(items))
        self.assertFalse(any(u['completed'] for u in units))
        self.assertTrue(all(u['progress'] == 0 for u in units))

    def test_reset_learning_clears_time_for_that_learner_only(self):
        other = 'c' * 48
        with server.connect() as db:
            server.record_study_seconds(db, self.learner, 120)
            server.record_study_seconds(db, other, 120)
            result = server.reset_learning(db, self.learner, {
                'scope': 'learning', 'confirmation': 'CLEAR_MY_LEARNING'})
            self.assertEqual(result['deleted']['study_time'], 1)
            self.assertEqual(server.time_stats(db, self.learner)['total_minutes'], 0)
            self.assertGreaterEqual(server.time_stats(db, other)['total_minutes'], 2)


if __name__ == '__main__':
    unittest.main()