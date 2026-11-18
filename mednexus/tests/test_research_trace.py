"""循证研究链路（research_trace）的单元测试。

契约：只把真实疑问、检索式、PubMed 结果与官方文献类型排成五步路线；
未检索时后几步必须留空，不给医学结论、不做质量评级。
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evidence
import research_trace
from api import research as research_api


def paper(pmid, types, abstract=''):
    return {
        'pmid': pmid,
        'types': types,
        'abstract': [{'label': '', 'category': '', 'text': abstract}],
    }


class ResearchTraceTests(unittest.TestCase):
    def test_question_type_only_selects_checklist(self):
        cases = {
            '不同病因的动眼神经麻痹瞳孔受累有差异吗？': 'mechanism',
            '显微手术治疗这两个区域的脑膜瘤效果如何？': 'intervention',
            'MRI 对早期诊断是否准确？': 'diagnosis',
            '恢复过程与随访时间有什么关系？': 'prognosis',
            '这个评分量表的可重复性如何？': 'measurement',
            '小胶质细胞': 'explore',
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(research_trace.question_type(question)[0], expected)

    def test_empty_results_leave_later_stages_pending(self):
        trace = research_trace.build_trace('这个差异有证据吗？', 'microglia[Title]', '模板')
        states = {stage['key']: stage['state'] for stage in trace['stages']}
        self.assertEqual(states['question'], 'ready')
        self.assertEqual(states['query'], 'ready')
        self.assertEqual(states['evidence'], 'pending')
        self.assertEqual(states['reading'], 'pending')
        self.assertEqual(states['boundary'], 'pending')
        self.assertIn('还没有检索结果', trace['checkpoints'][0]['text'])
        self.assertIn('不代表全部已发表证据', trace['legal_note'])

    def test_full_trace_uses_real_pmids_and_official_types(self):
        papers = [
            paper('111', ['Randomized Controlled Trial'], 'randomized, n = 120, double-blind'),
            paper('222', ['Case Reports'], ''),
        ]
        mix = evidence.evidence_mix(papers)
        trace = research_trace.build_trace('治疗效果有差异吗？',
                                           '("a"[Title]) AND ("b"[Title])', '核对后的检索式',
                                           papers, mix)
        self.assertEqual([s['state'] for s in trace['stages']],
                         ['ready'] * 5)
        self.assertIn('PMID 111', trace['stages'][3]['value'])
        self.assertIn('PMID 222', trace['stages'][3]['value'])
        self.assertEqual(trace['stages'][2]['value'], mix['summary'])
        self.assertEqual(trace['question_type'], 'intervention')
        self.assertEqual(trace['audit']['total'], 2)
        self.assertEqual(trace['audit']['sample_reported'], 1)
        self.assertEqual(trace['audit']['randomization_mentioned'], 1)
        self.assertEqual(trace['audit']['blinding_mentioned'], 1)

    def test_trace_is_deterministic_and_does_not_mutate_inputs(self):
        papers = [paper('333', ['Review'], 'review of studies')]
        mix = evidence.evidence_mix(papers)
        papers_before = repr(papers)
        mix_before = repr(mix)
        first = research_trace.build_trace('机制是什么？', 'term[Title]', '说明', papers, mix)
        second = research_trace.build_trace('机制是什么？', 'term[Title]', '说明', papers, mix)
        self.assertEqual(first, second)
        self.assertEqual(repr(papers), papers_before)
        self.assertEqual(repr(mix), mix_before)

    def test_boundary_never_prescribes_or_grades_evidence(self):
        trace = research_trace.build_trace('这个指标能诊断吗？', 'test[Title]', '',
                                           [paper('444', ['Case Reports'], '')])
        rendered = ' '.join(c['text'] for c in trace['checkpoints'])
        trace_text = rendered + ' ' + trace['legal_note'] + ' ' + trace['stages'][2]['detail']
        for banned in ['推荐等级', '首选', '应信任', '高质量证据', '可以确诊', '证明有效']:
            self.assertNotIn(banned, trace_text)
        self.assertIn('不能仅凭摘要里的敏感度或特异度下诊断结论', trace_text)
        self.assertIn('不是证据质量评级', trace['legal_note'])

    def test_gate_response_carries_partial_trace(self):
        concept = {
            'id': 'demo', 'name': '示例知识点',
            'terms': ['microglia'],
            'research': 'microglia 的功能与证据有什么差异？',
            'query': '("microglia"[Title]) AND ("function"[Title/Abstract])',
            'hints': [],
        }
        gate = research_api.research_gate(concept, 'microglia 的证据有什么差异？')
        self.assertTrue(gate['eligible'])
        trace = gate['research_trace']
        self.assertEqual(trace['stages'][0]['key'], 'question')
        self.assertEqual(trace['stages'][2]['state'], 'pending')
        self.assertIn('microglia', trace['stages'][1]['value'])


if __name__ == '__main__':
    unittest.main()
