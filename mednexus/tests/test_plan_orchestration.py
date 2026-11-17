"""把 G5 闭环并入今日计划：weave_plan 纯函数与 overview 接线测试。"""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orchestration
import server
import knowledge


def sample_plan(items=None, limit=3):
    return {
        'scope': '测试章节',
        'method': '测试',
        'items': items if items is not None else [
            {'concept': 'a', 'name': '知识点A', 'action': 'review', 'kind': 'diagnostic', 'reason': '原A'},
            {'concept': 'b', 'name': '知识点B', 'action': 'learn', 'kind': 'diagnostic', 'reason': '原B'},
        ],
        'srs': {'plan_limit': limit},
        'counts': {'weak': 1, 'new': 1, 'due': 0, 'practiced_today': 0},
    }


def loop_with(proposal, action='prepend'):
    return {
        'plan_update': {'action': action, 'position': 0, 'proposed_item': proposal},
        'next_activity': {'misconception': '概念混淆'},
        'retest_at': 123.0,
    }


PROPOSAL = {'concept': 'a', 'name': '知识点A', 'action': 'review', 'kind': 'transfer',
            'reason': '诊断后变式重测', 'due_at': 123.0, 'weak_points': ['要点一']}


class WeavePlanTests(unittest.TestCase):
    def test_prepend_remediation_and_mark_origin(self):
        plan = sample_plan()
        out = orchestration.weave_plan(plan, loop_with(PROPOSAL))
        self.assertEqual(out['items'][0]['concept'], 'a')
        self.assertEqual(out['items'][0]['origin'], 'orchestration')
        self.assertEqual(out['items'][0]['reason'], '诊断后变式重测')
        self.assertTrue(out['orchestrated'])
        self.assertEqual([i['concept'] for i in out['items']], ['a', 'b'])

    def test_same_concept_replaced_not_duplicated(self):
        plan = sample_plan(items=[
            {'concept': 'a', 'name': 'A', 'action': 'review', 'reason': '旧建议'},
            {'concept': 'c', 'name': 'C', 'action': 'review', 'reason': 'C建议'},
        ])
        out = orchestration.weave_plan(plan, loop_with(PROPOSAL))
        concepts = [i['concept'] for i in out['items']]
        self.assertEqual(concepts.count('a'), 1, '同一知识点不应出现两条')
        self.assertEqual(concepts[0], 'a', '补救项应前置')
        self.assertEqual(out['items'][0]['reason'], '诊断后变式重测')

    def test_respects_plan_limit(self):
        plan = sample_plan(items=[
            {'concept': 'x', 'name': 'X', 'action': 'review'},
            {'concept': 'y', 'name': 'Y', 'action': 'review'},
            {'concept': 'z', 'name': 'Z', 'action': 'review'},
        ], limit=2)
        out = orchestration.weave_plan(plan, loop_with(PROPOSAL))
        self.assertEqual(len(out['items']), 2)
        self.assertEqual(out['items'][0]['concept'], 'a')

    def test_pending_input_unchanged(self):
        plan = sample_plan()
        original = [dict(i) for i in plan['items']]
        orchestration.weave_plan(plan, loop_with(PROPOSAL))
        self.assertEqual(plan['items'], original, '不得改动入参')
        self.assertNotIn('orchestrated', plan)

    def test_no_prepend_returns_same_object(self):
        plan = sample_plan()
        out = orchestration.weave_plan(plan, loop_with(PROPOSAL, action='none'))
        self.assertIs(out, plan, '无需编排时应原样返回同一对象')

    def test_bad_inputs_degrade_without_raising(self):
        plan = sample_plan()
        bad_loops = [None, {}, {'plan_update': 'x'},
                     {'plan_update': {'action': 'prepend'}},
                     {'plan_update': {'action': 'prepend', 'proposed_item': {'concept': 123}}}]
        for loop in bad_loops:
            self.assertIs(orchestration.weave_plan(plan, loop), plan)
        self.assertIs(orchestration.weave_plan(None, loop_with(PROPOSAL)), None)

    def test_never_claims_mastery(self):
        out = orchestration.weave_plan(sample_plan(), loop_with(PROPOSAL))
        text = repr(out['items'][0])
        self.assertNotIn('mastery_claimed', text)
        self.assertNotIn('已掌握', text)


class OverviewWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = server.DB_PATH
        server.DB_PATH = Path(self.temp.name) / 'orch.sqlite3'
        server.init_db()
        self.learner = 'o' * 48

    def tearDown(self):
        server.DB_PATH = self.old_db
        self.temp.cleanup()

    def test_overview_plan_has_orchestration_key_when_weak(self):
        """构造一次答错记录，确认首页计划真的并入闭环补救项。"""
        db = server.connect()
        concept = knowledge.CONCEPTS[0]
        question = concept['questions'][0]
        payload = {'rubric': [
            {'label': p['label'], 'correct': False, 'category': p.get('category')}
            for p in question['points']
        ]}
        db.execute(
            'INSERT INTO attempts(learner,token,concept,question,kind,score,payload,created) '
            'VALUES(?,?,?,?,?,?,?,?)',
            (self.learner, 'tok', concept['id'], question['id'], 'diagnostic', 0.33,
             json.dumps(payload), time.time() - 20))
        db.commit()
        overview = server.overview_payload(db, self.learner)
        plan = overview['learning_plan']
        self.assertTrue(plan.get('orchestrated'), '有薄弱点时应并入编排补救项')
        self.assertTrue(any(i.get('origin') == 'orchestration' for i in plan['items']))
        db.close()

    def test_overview_plan_without_attempts_has_no_orchestration(self):
        """没有作答记录时不该凭空产生补救项。"""
        db = server.connect()
        overview = server.overview_payload(db, self.learner)
        plan = overview['learning_plan']
        self.assertNotIn('orchestrated', plan)
        self.assertFalse(any(i.get('origin') == 'orchestration' for i in plan['items']))
        db.close()

    def test_overview_scope_uses_real_course_name(self):
        """首页计划范围应显示真实课程名，而非写死的示例章节。"""
        import orchestration as _o  # noqa: F401  (确保模块可导入)
        db = server.connect()
        plan = server.overview_payload(db, self.learner)['learning_plan']
        self.assertIn('系统解剖学', plan['scope'])
        self.assertNotIn('脑神经示例章节', plan['scope'])
        db.close()


if __name__ == '__main__':
    unittest.main()
