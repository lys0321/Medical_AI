"""循证学习态势引擎 test：验证诚实、可核验、未测评不 punishment 的契约。"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pulse
import server
import knowledge
import tempfile
from pathlib import Path as _Path


def overview(**over):
    base = {
        "questions": {"total": 0, "week": 0, "week_cited": 0, "day": 0, "day_cited": 0},
        "stats": {"mastered": 0, "weak": 0, "assessed": 0, "viewed": 0, "attempts": 0, "total": 10},
        "learning_plan": {"items": []},
        "learning_time": {"streak_days": 0, "active_days": 0, "total_minutes": 0,
                          "week_minutes": 0, "today_minutes": 0, "series": []},
    }
    base.update(over)
    return base


class PulseTests(unittest.TestCase):
    def test_empty_learning_is_not_scored_as_failure(self):
        p = pulse.build_pulse(overview())
        self.assertIsNone(p["index"], "no data must not produce a fabricated score")
        self.assertEqual(p["level"], "尚未开始")
        for d in p["dimensions"]:
            self.assertIsNone(d["value"], d["key"] + " should be unmeasured")
        self.assertTrue(p["disclaimer"])
        self.assertIn("本地", p["source"])

    def test_evidence_rate_from_cited_questions(self):
        ov = overview(questions={"total": 8, "week": 5, "week_cited": 4, "day": 1, "day_cited": 1})
        p = pulse.build_pulse(ov)
        ev = next(d for d in p["dimensions"] if d["key"] == "evidence")
        self.assertEqual(ev["value"], 80)
        self.assertIn("4/5", ev["detail"])

    def test_evidence_zero_when_no_citations_but_asked(self):
        ov = overview(questions={"total": 5, "week": 5, "week_cited": 0, "day": 0, "day_cited": 0})
        ev = next(d for d in pulse.build_pulse(ov)["dimensions"] if d["key"] == "evidence")
        self.assertEqual(ev["value"], 0)

    def test_mastery_uses_assessed_not_total(self):
        ov = overview(stats={"mastered": 2, "weak": 1, "assessed": 3, "viewed": 3,
                             "attempts": 9, "total": 10})
        p = pulse.build_pulse(ov)
        ma = next(d for d in p["dimensions"] if d["key"] == "mastery")
        self.assertEqual(ma["value"], 67)
        self.assertIn("2/3", ma["detail"])
        self.assertNotIn("2/10", ma["detail"], "unassessed concepts must not count as failures")

    def test_mastery_unmeasured_when_nothing_assessed(self):
        ov = overview(stats={"mastered": 0, "weak": 0, "assessed": 0, "viewed": 2,
                             "attempts": 0, "total": 10})
        ma = next(d for d in pulse.build_pulse(ov)["dimensions"] if d["key"] == "mastery")
        self.assertIsNone(ma["value"])

    def test_loop_coverage_counts_orchestrated_remediation(self):
        ov = overview(
            stats={"mastered": 1, "weak": 3, "assessed": 4, "viewed": 4, "attempts": 12, "total": 10},
            learning_plan={"items": [
                {"concept": "a", "origin": "orchestration"},
                {"concept": "b", "origin": "srs"},
            ]},
        )
        p = pulse.build_pulse(ov)
        lo = next(d for d in p["dimensions"] if d["key"] == "loop")
        self.assertEqual(lo["value"], 33, "1 of 3 weak points arranged into plan")
        self.assertIn("3", lo["detail"])

    def test_loop_healthy_when_no_weak_after_assessment(self):
        ov = overview(stats={"mastered": 4, "weak": 0, "assessed": 4, "viewed": 4,
                             "attempts": 12, "total": 10})
        lo = next(d for d in pulse.build_pulse(ov)["dimensions"] if d["key"] == "loop")
        self.assertEqual(lo["value"], 100)

    def test_consistency_from_streak_and_active_days(self):
        ov = overview(learning_time={"streak_days": 5, "active_days": 12, "total_minutes": 300,
                                     "week_minutes": 90, "today_minutes": 15, "series": []})
        co = next(d for d in pulse.build_pulse(ov)["dimensions"] if d["key"] == "consistency")
        self.assertEqual(co["value"], 71)  # round(5/7*100)
        self.assertIn("5", co["detail"])

    def test_index_averages_only_measured_dimensions(self):
        ov = overview(
            questions={"total": 2, "week": 2, "week_cited": 2, "day": 0, "day_cited": 0},
            stats={"mastered": 1, "weak": 0, "assessed": 1, "viewed": 1, "attempts": 3, "total": 10},
            learning_time={"streak_days": 7, "active_days": 8, "total_minutes": 100,
                           "week_minutes": 60, "today_minutes": 10, "series": []},
        )
        p = pulse.build_pulse(ov)
        # evidence=100, mastery=100, loop=100(no weak), consistency=100
        self.assertEqual(p["index"], 100)
        self.assertIn(p["level"], ("扎实", "精进"))

    def test_index_ignores_unmeasured_dimensions(self):
        ov = overview(questions={"total": 3, "week": 3, "week_cited": 3, "day": 0, "day_cited": 0})
        p = pulse.build_pulse(ov)
        # only evidence measured = 100; others unmeasured
        self.assertEqual(p["index"], 100)

    def test_does_not_mutate_input(self):
        import copy
        ov = overview(questions={"total": 5, "week": 5, "week_cited": 4, "day": 0, "day_cited": 0})
        before = copy.deepcopy(ov)
        pulse.build_pulse(ov)
        self.assertEqual(ov, before)

    def test_headline_is_honest_without_boasting(self):
        ov = overview(questions={"total": 5, "week": 5, "week_cited": 5, "day": 1, "day_cited": 1},
                      stats={"mastered": 4, "weak": 0, "assessed": 4, "viewed": 4,
                             "attempts": 12, "total": 10})
        p = pulse.build_pulse(ov)
        self.assertIsInstance(p["headline"], str)
        self.assertTrue(p["headline"])
        self.assertIn("不是", pulse.build_pulse(overview())["disclaimer"])
        self.assertIn("能力", p["disclaimer"])

    def test_tolerates_missing_and_malformed_fields(self):
        p = pulse.build_pulse({})
        self.assertIsNone(p["index"])
        self.assertEqual(len(p["dimensions"]), 4)
        p2 = pulse.build_pulse({"questions": None, "stats": "bad", "learning_plan": {},
                                "learning_time": None})
        self.assertIsNone(p2["index"])


class PulseWiringTests(unittest.TestCase):
    def test_overview_exposes_honest_pulse_on_fresh_learner(self):
        temp = tempfile.TemporaryDirectory()
        old = server.DB_PATH
        try:
            server.DB_PATH = _Path(temp.name) / 'pulse.sqlite3'
            server.init_db()
            db = server.connect()
            ov = server.overview_payload(db, 'p' * 48)
            p = ov['pulse']
            self.assertIsNone(p['index'], 'fresh learner must not get a fabricated index')
            self.assertEqual(p['level'], '尚未开始')
            self.assertEqual(len(p['dimensions']), 4)
            self.assertIn('能力', p['disclaimer'])
            db.close()
        finally:
            server.DB_PATH = old
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
