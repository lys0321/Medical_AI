"""第五代编排闭环的单元测试（纯函数，不碰数据库/网络/模型）。"""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orchestration
import srs
from planning import SHANGHAI, DAY


BASE = datetime(2026, 11, 1, 12, tzinfo=SHANGHAI)


def at(day, hour=12):
    return (BASE + timedelta(days=day)).replace(hour=hour).timestamp()


def make_question(qid='c0-diagnostic', cats=None, token='rubric原文'):
    cats = cats or ['概念记忆', '机制理解', '应用迁移']
    labels = ['要点一', '要点二', '要点三']
    points = []
    for label, category in zip(labels, cats):
        correct = '%s-%s' % (token, label)
        points.append({'label': label, 'correct': correct,
                       'options': [correct, '干扰项甲', '干扰项乙', '暂时不确定'],
                       'reason': '教学要点原文-%s' % label, 'category': category})
    return {'id': qid, 'concept': 'c0', 'kind': 'diagnostic',
            'prompt': '题目原文prompt', 'points': points}


def point(label, correct, category=None):
    result = {'label': label, 'correct': correct}
    if category is not None:
        result['category'] = category
    return result


def attempt(rubric=None, *, when=None, score=0.33, cid='c0', kind='diagnostic',
            assisted=False, qid='c0-diagnostic', payload=True):
    rubric = rubric or []
    row = {'concept': cid, 'created': at(24) if when is None else when,
           'score': score, 'question': qid, 'kind': kind}
    data = {'rubric': rubric, 'assisted': assisted}
    if payload:
        row['payload'] = json.dumps(data, ensure_ascii=False)
    else:
        row['rubric'] = rubric
    return row


def concept(cid='c0', questions=None):
    item = {'id': cid, 'name': '知识点' + cid, 'status': '未测评',
            'attempts': 0, 'score': None}
    if questions is not None:
        item['questions'] = questions
    return item


class DiagnosisTests(unittest.TestCase):
    def test_single_point_uses_question_category(self):
        question = make_question()
        row = attempt([point('要点一', False), point('要点二', True), point('要点三', True)])
        result = orchestration.diagnose_misconception(row, question)
        self.assertEqual(result['category'], '记忆缺失')
        self.assertEqual(result['wrong_labels'], ['要点一'])
        self.assertEqual(result['evidence'], [{'label': '要点一', 'category': '概念记忆'}])
        self.assertEqual(result['counts'], {'概念记忆': 1})
        self.assertEqual(result['remediation'], orchestration.REMEDIATION_TEXT['记忆缺失'])
        self.assertTrue(result['basis'])

    def test_majority_category_decides_and_all_categories_are_available(self):
        question = make_question(cats=['机制理解', '机制理解', '应用迁移'])
        row = attempt([point('要点一', False), point('要点二', False), point('要点三', False)])
        result = orchestration.diagnose_misconception(row, question)
        self.assertEqual(result['category'], '概念混淆')
        self.assertEqual(result['counts'], {'机制理解': 2, '应用迁移': 1})
        self.assertEqual(set(orchestration.MISCONCEPTION_BY_CATEGORY.values()),
                         {'记忆缺失', '概念混淆', '推理断裂'})

    def test_tie_break_follows_question_order_deterministically(self):
        question = make_question(cats=['应用迁移', '概念记忆', '机制理解'])
        row = attempt([point('要点一', False), point('要点二', False), point('要点三', False)])
        result = orchestration.diagnose_misconception(row, question)
        self.assertEqual(result['category'], '推理断裂')
        self.assertEqual(result, orchestration.diagnose_misconception(row, question))

    def test_rubric_category_overrides_question_mapping(self):
        question = make_question()
        row = attempt([point('要点一', False, '应用迁移')])
        self.assertEqual(orchestration.diagnose_misconception(row, question)['category'], '推理断裂')

    def test_no_rubric_degrades_to_unknown(self):
        question = make_question()
        for row in (attempt(), attempt(payload=False), {'concept': 'c0', 'score': 0},
                    None, 'broken'):
            result = orchestration.diagnose_misconception(row, question)
            self.assertEqual(result['category'], 'unknown')
            self.assertEqual(result['wrong_labels'], [])
            self.assertEqual(result['remediation'], orchestration.REMEDIATION_TEXT['unknown'])

    def test_corrupted_rubric_entries_are_ignored(self):
        question = make_question()
        rubric = [None, 'wrong', point('要点一', None), point(7, False),
                  {'label': '要点二', 'correct': False}, point('要点二', False)]
        result = orchestration.diagnose_misconception(attempt(rubric), question)
        self.assertEqual(result['wrong_labels'], ['要点二'])
        self.assertEqual(result['category'], '概念混淆')

    def test_broken_payload_json_does_not_crash(self):
        row = attempt()
        row['payload'] = '{not json'
        self.assertEqual(orchestration.diagnose_misconception(row, make_question())['category'],
                         'unknown')


class RemediationTests(unittest.TestCase):
    def test_variation_uses_only_question_source_text(self):
        question = make_question(token='PRIVATE-FIXTURE')
        result = orchestration.build_remediation(
            concept(), question, {'category': '记忆缺失', 'wrong_labels': ['要点一']}, now=at(24))
        source = {p['label']: p for p in question['points']}
        self.assertEqual(len(result['variation']['materials']), 1)
        for material in result['variation']['materials']:
            original = source[material['label']]
            self.assertEqual(material['correct'], original['correct'])
            self.assertEqual(material['reason'], original['reason'])
            self.assertEqual(material['options'], original['options'])
            self.assertEqual(material['category'], original['category'])
        self.assertEqual(result['variation']['source'], 'question.points')
        self.assertNotIn('PRIVATE-FIXTURE', result['variation']['angle'])
        self.assertNotIn('PRIVATE-FIXTURE', result['reason'])
        self.assertEqual(json.dumps(result, ensure_ascii=False).count('PRIVATE-FIXTURE'), 3)

    def test_missing_labels_fall_back_to_all_points(self):
        question = make_question()
        result = orchestration.build_remediation(
            concept(), question, {'category': 'unknown', 'wrong_labels': ['不存在']}, now=at(24))
        self.assertEqual(result['variation']['point_count'], 3)

    def test_no_state_schedules_immediate_retest(self):
        result = orchestration.build_remediation(concept(), make_question(), '记忆缺失', now=at(24))
        self.assertEqual(result['due_at'], at(24))
        self.assertEqual(result['interval_days'], 0.0)
        self.assertIsNone(result['model_due_at'])

    def test_uses_srs_interval_and_due_within_one_day(self):
        question = make_question()
        events = [{'created': at(20, 9), 'score': 1, 'kind': 'transfer', 'assisted': False},
                  {'created': at(21, 9), 'score': 1, 'kind': 'transfer', 'assisted': False}]
        state = srs.derive_state(events)
        now = at(21, 12)
        result = orchestration.build_remediation(concept(), question, '概念混淆',
                                                  srs_state=state, now=now)
        self.assertAlmostEqual(result['interval_days'], round(srs.interval_days(state['stability']), 2))
        self.assertEqual(result['model_due_at'], srs.due_at(state))
        self.assertGreaterEqual(result['due_at'], now)
        self.assertLessEqual(result['due_at'], now + DAY)

    def test_future_state_is_clamped_within_one_day(self):
        state = srs.new_state()
        state.update({'last_review': at(40), 'stability': 5.0})
        now = at(24)
        result = orchestration.build_remediation(concept(), make_question(), 'unknown',
                                                  srs_state=state, now=now)
        self.assertEqual(result['due_at'], now + DAY)
        self.assertGreater(result['model_due_at'], now + DAY)

    def test_corrupted_state_and_nonfinite_now(self):
        result = orchestration.build_remediation(concept(), make_question(), 'unknown',
                                                  srs_state={'last_review': 'x', 'stability': None},
                                                  now=at(24))
        self.assertEqual(result['due_at'], at(24))
        with self.assertRaises(ValueError):
            orchestration.build_remediation(concept(), make_question(), 'unknown', now=float('inf'))

    def test_never_claims_mastery(self):
        result = orchestration.build_remediation(concept(), make_question(), '记忆缺失', now=at(24))
        self.assertFalse(result['mastery_claimed'])
        self.assertFalse(result['assisted'])
        self.assertFalse(any(item in result['reason'] for item in ('已掌握', '掌握正确')))


class LoopStepTests(unittest.TestCase):
    def test_full_closed_loop_is_json_serializable(self):
        question = make_question()
        rows = [attempt([point('要点一', False), point('要点二', True), point('要点三', True)],
                        when=at(24))]
        snapshot = orchestration.loop_step([concept(questions=[question])], rows, now=at(25))
        json.dumps(snapshot, ensure_ascii=False)
        self.assertEqual(snapshot['observation']['weak_concepts'], ['c0'])
        self.assertEqual(snapshot['observation']['weak_points'], ['要点一'])
        self.assertEqual(snapshot['diagnoses'][0]['category'], '记忆缺失')
        self.assertEqual(snapshot['next_activity']['misconception'], '记忆缺失')
        self.assertEqual(snapshot['next_activity']['retest_points'][0]['label'], '要点一')
        self.assertIn(snapshot['hint_source']['method'], ('hint_text', 'page_hint_text'))
        self.assertEqual(snapshot['retest_at'], snapshot['next_activity']['due_at'])
        self.assertEqual(snapshot['plan_update']['action'], 'prepend')
        self.assertEqual(snapshot['plan_update']['position'], 0)
        self.assertFalse(snapshot['evidence_discipline']['mastery_claimed'])

    def test_clean_history_has_no_remediation(self):
        snapshot = orchestration.loop_step([concept()], [], now=at(25))
        self.assertEqual(snapshot['diagnoses'], [])
        self.assertIsNone(snapshot['next_activity'])
        self.assertIsNone(snapshot['retest_at'])
        self.assertEqual(snapshot['plan_update']['action'], 'none')

    def test_future_and_damaged_records_are_ignored(self):
        source = [concept()]
        rows = [attempt([point('要点一', False)], when=at(30)),
                attempt([point('要点二', False)], when='not a timestamp'),
                {'concept': 'missing', 'created': at(24), 'score': 0},
                'broken']
        snapshot = orchestration.loop_step(source, rows, now=at(25))
        self.assertEqual(snapshot['diagnoses'], [])
        self.assertEqual(snapshot['observation']['weak_points'], [])

    def test_pure_function_does_not_mutate_and_is_deterministic(self):
        question = make_question()
        source = [concept(questions=[question])]
        rows = [attempt([point('要点二', False)], when=at(24))]
        snapshot = (copy.deepcopy(source), copy.deepcopy(rows))
        first = orchestration.loop_step(source, rows, now=at(25))
        second = orchestration.loop_step(source, rows, now=at(25))
        self.assertEqual((source, rows), snapshot)
        self.assertEqual(first, second)
        self.assertEqual(first['diagnoses'][0]['category'], '概念混淆')


if __name__ == '__main__':
    unittest.main()
