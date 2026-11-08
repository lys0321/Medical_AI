import copy
from datetime import datetime
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from planning import build_plan, SHANGHAI, DAY


def at(day, hour=12):
    return datetime(2026, 10, day, hour, tzinfo=SHANGHAI).timestamp()


def concepts(count=10):
    return [{'id':f'c{index}', 'name':f'知识点{index}', 'status':'未测评',
             'attempts':0, 'score':None} for index in range(count)]


def attempt(cid='c0', when=None, kind='diagnostic', score=1, assisted=False, rubric=None):
    payload = {'rubric': rubric or [], 'assisted':assisted}
    return {'concept':cid, 'created':at(25) if when is None else when, 'score':score,
            'question':cid+'-'+kind, 'kind':kind, 'payload':json.dumps(payload,ensure_ascii=False)}


class PlanningTests(unittest.TestCase):
    def test_empty_history_has_two_new_tasks_and_no_fake_scores(self):
        plan = build_plan(concepts(), [], now=at(29))
        self.assertEqual(plan['scope'],'脑神经示例章节 · 10个知识点')
        self.assertEqual(plan['counts'],{'due':0,'weak':0,'new':10,'practiced_today':0})
        self.assertEqual([item['concept'] for item in plan['items']],['c0','c1'])
        self.assertTrue(all(item['last_score'] is None and item['due_at'] is None for item in plan['items']))

    def test_latest_failure_is_immediate_and_extracts_only_error_labels(self):
        rows = [attempt(score=1),attempt(when=at(29,10),score=1/3,rubric=[
            {'label':'上睑变化','correct':True,'expected':'private fixture'},
            {'label':'静息眼位','correct':False,'expected':'private fixture'},
            {'label':'瞳孔变化','correct':False,'expected':'private fixture'}])]
        plan = build_plan(concepts(), rows, now=at(29))
        item = plan['items'][0]
        self.assertEqual(item['kind'],'diagnostic')
        self.assertEqual(item['last_score'],33)
        self.assertEqual(item['weak_points'],['静息眼位','瞳孔变化'])
        self.assertNotIn('private fixture',json.dumps(plan))
        self.assertEqual(plan['counts']['weak'],1)
        self.assertEqual(plan['counts']['due'],1)

    def test_diagnostic_success_requires_independent_transfer(self):
        plan = build_plan(concepts(), [attempt(when=at(29,10))], now=at(29))
        self.assertEqual(plan['items'][0]['kind'],'transfer')
        self.assertEqual(plan['items'][0]['action'],'review')
        self.assertEqual(plan['counts']['due'],1)

    def test_assisted_success_is_not_an_independent_transfer(self):
        rows = [attempt(),attempt(kind='transfer',assisted=True)]
        item = build_plan(concepts(),rows,now=at(29))['items'][0]
        self.assertEqual(item['concept'],'c0')
        self.assertEqual(item['kind'],'transfer')
        self.assertIn('提示',item['reason'])

    def test_legacy_attempt_without_assisted_field_is_independent(self):
        rows = [attempt(when=at(28)),attempt(when=at(28),kind='transfer')]
        for row in rows:
            row['payload'] = '{"rubric":[]}'
        plan = build_plan(concepts(),rows,now=at(28,13))
        self.assertEqual(plan['counts']['due'],0)
        self.assertEqual(plan['next_due_at'],at(28)+DAY)

    def test_repeated_success_same_day_cannot_extend_review_interval(self):
        rows = [attempt(when=at(28,9)),attempt(when=at(28,9),kind='transfer'),
                attempt(when=at(28,14),kind='transfer')]
        plan = build_plan(concepts(),rows,now=at(28,18))
        self.assertEqual(plan['next_due_at'],at(28,9)+DAY)
        due = build_plan(concepts(),rows,now=at(29,9))
        self.assertEqual(due['items'][0]['concept'],'c0')
        self.assertEqual(due['items'][0]['due_at'],at(29,9))

    def test_cross_day_success_advances_interval_and_assistance_does_not(self):
        first_day = [attempt(when=at(25)), attempt(when=at(25), kind='transfer')]
        with_second = first_day + [attempt(when=at(26), kind='transfer')]
        late = at(29, 13) + 60 * DAY          # 早已到期，条目才会出现在计划里
        one = build_plan(concepts(), first_day, now=late)['items'][0]
        two = build_plan(concepts(), with_second, now=late)['items'][0]
        # 第二次独立迁移成功让间隔变长：不再是固定的 1/3/7/14 表。
        self.assertGreater(two['interval_days'], one['interval_days'])
        self.assertGreater(two['stability_days'], one['stability_days'])
        rows = with_second + [attempt(when=at(27), kind='transfer', assisted=True)]
        self.assertEqual(build_plan(concepts(), rows, now=at(27, 13))['next_due_at'],
                         two['due_at'])

    def test_a_failure_pulls_review_back_within_one_day_and_recovery_is_shorter(self):
        good = [attempt(when=at(23)), attempt(when=at(23), kind='transfer'),
                attempt(when=at(24), kind='transfer')]
        failed = good + [attempt(when=at(25), kind='transfer', score=0)]
        right_after = build_plan(concepts(), failed, now=at(25, 13))['items'][0]
        self.assertEqual(right_after['action'], 'review')
        self.assertLessEqual(right_after['due_at'], at(25) + DAY)
        late = at(29, 13) + 60 * DAY
        before = build_plan(concepts(), good, now=late)['items'][0]
        recovered = build_plan(concepts(), failed + [attempt(when=at(26)),
                                                    attempt(when=at(26), kind='transfer')],
                               now=late)['items'][0]
        self.assertLess(recovered['stability_days'], before['stability_days'])

    def test_consecutive_independent_success_keeps_making_intervals_longer(self):
        rows, intervals = [], []
        for day in (20, 21, 22, 23):
            rows += [attempt(when=at(day)), attempt(when=at(day), kind='transfer')]
            plan = build_plan(concepts(), rows, now=at(day, 13) + 60 * DAY)
            intervals.append(plan['items'][0]['interval_days'])
        for earlier, later in zip(intervals, intervals[1:]):
            self.assertLess(earlier, later)
        self.assertEqual(intervals, sorted(intervals))

    def test_active_task_is_first_deduplicated_and_reserves_new_budget(self):
        plan = build_plan(concepts(),[],active={'concept':'c7','kind':'diagnostic'},now=at(29))
        self.assertEqual([item['action'] for item in plan['items']],['resume','learn'])
        self.assertEqual(plan['items'][0]['concept'],'c7')
        plan = build_plan(concepts(),[attempt(score=0)],active={'concept':'c0'},now=at(29))
        self.assertEqual(sum(item['concept']=='c0' for item in plan['items']),1)
        self.assertEqual(plan['items'][0]['action'],'resume')

    def test_two_first_practices_today_exhaust_new_task_budget(self):
        rows = [attempt(when=at(29,9)),attempt(cid='c1',when=at(29,10),score=0)]
        plan = build_plan(concepts(),rows,now=at(29))
        self.assertEqual(plan['counts']['practiced_today'],2)
        self.assertEqual(plan['counts']['new'],8)
        self.assertFalse(any(item['action']=='learn' for item in plan['items']))

    def test_today_uses_shanghai_date_not_host_timezone(self):
        # 16:30 UTC on Oct 28 is 00:30 in Shanghai on Oct 29.
        when = at(29,0)+1800
        plan = build_plan(concepts(),[attempt(when=when)],now=at(29,1))
        self.assertEqual(plan['counts']['practiced_today'],1)
        self.assertEqual(sum(item['action']=='learn' for item in plan['items']),1)

    def test_plan_caps_visible_tasks_but_counts_all_due_items(self):
        rows = [attempt(cid=f'c{index}',score=0) for index in range(8)]
        plan = build_plan(concepts(),rows,now=at(29))
        self.assertEqual(len(plan['items']),5)
        self.assertEqual(plan['counts']['due'],8)
        self.assertEqual(plan['counts']['weak'],8)

    def test_input_is_not_mutated_and_unrelated_or_future_records_do_not_count(self):
        source_concepts=concepts()
        rows=[attempt(cid='unrelated',score=0),attempt(when=at(30),score=0)]
        original=copy.deepcopy((source_concepts,rows))
        result=build_plan(source_concepts,rows,now=at(29))
        self.assertEqual((source_concepts,rows),original)
        self.assertEqual(result['counts']['new'],10)
        self.assertEqual(result['counts']['due'],0)

    def test_backwards_clock_and_future_attempts_do_not_crash(self):
        rows = [attempt(when=at(29)), attempt(when=at(29), kind='transfer')]
        # now 早于作答时间：未来记录不计入，也不能抛异常。
        earlier = build_plan(concepts(), rows, now=at(28))
        self.assertEqual(earlier['counts']['due'], 0)
        self.assertEqual(earlier['counts']['new'], 10)
        # now 远早于所有记录（时钟回拨）。
        backwards = build_plan(concepts(), rows, now=at(20, 3))
        self.assertEqual(backwards['counts']['due'], 0)
        # 记录时间早于 now 但顺序混乱时，重放仍按时间排序。
        shuffled = [rows[1], rows[0]]
        self.assertEqual(build_plan(concepts(), shuffled, now=at(29, 13))['next_due_at'],
                         build_plan(concepts(), rows, now=at(29, 13))['next_due_at'])

    def test_daily_new_limit_and_plan_limit_are_configurable(self):
        plan = build_plan(concepts(), [], now=at(29), daily_new_limit=1, plan_limit=2)
        self.assertEqual([item['concept'] for item in plan['items']], ['c0'])
        self.assertEqual(plan['srs']['daily_new_limit'], 1)
        plan = build_plan(concepts(), [], now=at(29), plan_limit=7)
        self.assertEqual(len(plan['items']), 2)          # 受每日新知识点上限约束
        weak = [attempt(cid=f'c{index}', score=0) for index in range(8)]
        capped = build_plan(concepts(), weak, now=at(29), plan_limit=2)
        self.assertEqual(len(capped['items']), 2)
        self.assertEqual(capped['counts']['due'], 8)
        self.assertEqual(capped['srs']['plan_limit'], 2)

    def test_target_retention_is_configurable(self):
        rows = [attempt(when=at(28)), attempt(when=at(28), kind='transfer')]
        now = at(28, 13) + 60 * DAY
        low = build_plan(concepts(), rows, now=now, target_retention=0.8)['items'][0]
        high = build_plan(concepts(), rows, now=now, target_retention=0.95)['items'][0]
        # 目标保持率越低，允许拖得越久。
        self.assertGreater(low['interval_days'], high['interval_days'])
        with self.assertRaises(ValueError):
            build_plan(concepts(), rows, now=now, target_retention=1.2)


if __name__ == '__main__':
    unittest.main()
