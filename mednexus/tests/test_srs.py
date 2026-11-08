"""FSRS-lite 公式的单元测试（纯函数，不碰数据库）。"""
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import srs

BASE = datetime(2026, 9, 1, 12, tzinfo=srs.SHANGHAI)


def at(day, hour=12):
    """第 day 天的 hour 点（从 9 月 1 日起算，允许超过一个月）。"""
    return (BASE + timedelta(days=day)).replace(hour=hour).timestamp()


def event(day, kind='transfer', score=1.0, assisted=False, hour=12):
    return {'created': at(day, hour), 'score': score, 'kind': kind, 'assisted': assisted}


class CurveTests(unittest.TestCase):
    def test_retrievability_decays_from_one(self):
        self.assertAlmostEqual(srs.retrievability(2.0, 0), 1.0)
        self.assertLess(srs.retrievability(2.0, 2), srs.retrievability(2.0, 1))
        self.assertLess(srs.retrievability(2.0, 30), 0.5)
        # 时间倒流按 0 处理，仍然是满概率，不报错。
        self.assertAlmostEqual(srs.retrievability(2.0, -5), 1.0)

    def test_interval_matches_target_retention(self):
        for stability in (0.5, 1, 3.5, 20):
            self.assertAlmostEqual(srs.interval_days(stability), stability, places=6)
        self.assertGreater(srs.interval_days(2, 0.8), srs.interval_days(2, 0.95))
        self.assertEqual(srs.interval_days(0), 0.0)
        with self.assertRaises(ValueError):
            srs.interval_days(2, 1.0)

    def test_due_at_is_none_before_evidence(self):
        state = srs.new_state()
        self.assertIsNone(srs.due_at(state))
        self.assertIsNone(srs.retrievability_now(state, at(29)))


class EvidenceTests(unittest.TestCase):
    def test_first_independent_transfer_sets_initial_stability(self):
        state = srs.review(srs.new_state(), event(29))
        self.assertAlmostEqual(state['stability'], srs.INITIAL_STABILITY)
        self.assertEqual(state['last_review'], at(29))
        self.assertEqual(state['reps'], 1)
        self.assertAlmostEqual(srs.due_at(state), at(29) + srs.INITIAL_STABILITY * srs.DAY)

    def test_diagnostic_success_does_not_advance(self):
        state = srs.new_state()
        for kind in ('diagnostic', 'auto', None):
            after = srs.review(state, event(29, kind=kind))
            self.assertEqual(after['stability'], 0.0, kind)
            self.assertIsNone(after['last_review'], kind)

    def test_assisted_success_does_not_advance(self):
        state = srs.new_state()
        after = srs.review(state, event(29, assisted=True))
        self.assertEqual(after['stability'], 0.0)
        self.assertEqual(after, srs.new_state())

    def test_same_day_repeats_do_not_stack(self):
        state = srs.review(srs.new_state(), event(29, hour=9))
        again = srs.review(state, event(29, hour=15))
        self.assertEqual(again['stability'], state['stability'])
        self.assertEqual(again['reps'], state['reps'])
        # 第二天再成功才推进
        next_day = srs.review(again, event(30))
        self.assertGreater(next_day['stability'], state['stability'])

    def test_consecutive_successes_grow_stability_monotonically(self):
        state, seen = srs.new_state(), []
        for day in (20, 21, 22, 23, 24):
            state = srs.review(state, event(day))
            seen.append(state['stability'])
        for earlier, later in zip(seen, seen[1:]):
            self.assertLess(earlier, later)

    def test_input_state_is_not_mutated(self):
        state = srs.new_state()
        snapshot = dict(state)
        srs.review(state, event(29))
        self.assertEqual(state, snapshot)


class LapseTests(unittest.TestCase):
    def test_failure_caps_stability_within_one_day(self):
        state = srs.review(srs.new_state(), event(20))
        state = srs.review(state, event(23))
        self.assertGreater(state['stability'], 1.0)
        lapsed = srs.review(state, event(30, score=0))
        self.assertLessEqual(lapsed['stability'], 1.0)
        self.assertLessEqual(srs.due_at(lapsed) - lapsed['last_review'], srs.DAY)
        self.assertEqual(lapsed['lapses'], 1)
        self.assertGreater(lapsed['difficulty'], state['difficulty'])

    def test_failure_before_any_success_still_produces_a_short_interval(self):
        state = srs.review(srs.new_state(), event(29, score=0, kind='diagnostic'))
        self.assertEqual(state['stability'], srs.MIN_STABILITY)
        self.assertLessEqual(srs.due_at(state) - state['last_review'], srs.DAY)

    def test_difficulty_stays_in_range(self):
        state = srs.new_state()
        for day in range(1, 12):
            state = srs.review(state, event(day, score=0))
        self.assertLessEqual(state['difficulty'], srs.MAX_DIFFICULTY)
        for day in range(12, 40):
            state = srs.review(state, event(day))
        self.assertGreaterEqual(state['difficulty'], srs.MIN_DIFFICULTY)

    def test_stability_is_capped(self):
        state = srs.new_state()
        for day in range(1, 40):
            state = srs.review(state, event(day, hour=1))
            state = srs.review(state, event(day, hour=2))  # 同日第二次不计数
        self.assertLessEqual(state['stability'], srs.MAX_STABILITY)


class RobustnessTests(unittest.TestCase):
    def test_unordered_events_are_replayed_in_time_order(self):
        shuffled = [event(22), event(20), event(21)]
        ordered = sorted(shuffled, key=lambda item: item['created'])
        self.assertEqual(srs.derive_state(shuffled), srs.derive_state(ordered))

    def test_backwards_timestamp_does_not_crash_or_jump(self):
        state = srs.review(srs.new_state(), event(25))
        backwards = srs.review(state, event(20))
        self.assertGreaterEqual(backwards['stability'], state['stability'])
        self.assertLessEqual(backwards['stability'], state['stability'] * srs.MAX_GROWTH)

    def test_future_last_review_is_not_due(self):
        state = srs.review(srs.new_state(), event(30))
        self.assertGreater(srs.due_at(state), at(29))
        self.assertAlmostEqual(srs.retrievability_now(state, at(29)), 1.0)

    def test_invalid_events_are_ignored(self):
        state = srs.new_state()
        self.assertEqual(srs.review(state, {'created': 'x', 'score': 1}), state)
        self.assertEqual(srs.review(state, {'created': at(29)}), state)

    def test_event_without_kind_or_assisted_is_treated_as_no_evidence(self):
        state = srs.review(srs.new_state(), {'created': at(29), 'score': 1})
        self.assertEqual(state['stability'], 0.0)


if __name__ == '__main__':
    unittest.main()