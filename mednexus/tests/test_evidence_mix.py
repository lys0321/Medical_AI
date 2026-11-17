"""文献类型构成画像（evidence_mix）的单元测试。

核心契约：只按 PubMed 官方 PublicationType 统计分布，不评分、不推断设计、
不给医学结论；每篇文献只归一类，且必须显著声明"不是质量评级"。
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evidence
from api import core as api_core
from api import research as research_api


def paper(types):
    return {'pmid': '1', 'types': list(types)}


class EvidenceMixTests(unittest.TestCase):
    def test_empty_is_neutral(self):
        out = evidence.evidence_mix([])
        self.assertEqual(out['total'], 0)
        self.assertEqual(out['buckets'], [])
        self.assertIn('没有文献', out['summary'])
        self.assertFalse(out['has_primary'])
        self.assertFalse(out['has_synthesis'])

    def test_classifies_by_official_publication_type(self):
        papers = [
            paper(['Guideline']),
            paper(['Meta-Analysis', 'Journal Article']),
            paper(['Randomized Controlled Trial']),
            paper(['Observational Study']),
            paper(['Review']),
            paper(['Case Reports']),
            paper(['Editorial']),  # 未映射 → 其他
        ]
        out = evidence.evidence_mix(papers)
        self.assertEqual(out['total'], 7)
        by_key = {b['key']: b['count'] for b in out['buckets']}
        self.assertEqual(by_key['guideline'], 1)
        self.assertEqual(by_key['meta'], 1)
        self.assertEqual(by_key['rct'], 1)
        self.assertEqual(by_key['observational'], 1)
        self.assertEqual(by_key['review'], 1)
        self.assertEqual(by_key['case'], 1)
        self.assertEqual(by_key['other'], 1)

    def test_each_paper_counted_once_by_priority(self):
        # 系统综述常同时带 Review；RCT 也可能带 Clinical Trial。
        # 每篇只归一类，按证据层级优先级取最高命中的那一类。
        out = evidence.evidence_mix([
            paper(['Systematic Review', 'Review']),
            paper(['Randomized Controlled Trial', 'Clinical Trial']),
        ])
        by_key = {b['key']: b['count'] for b in out['buckets']}
        self.assertEqual(by_key['meta'], 1, 'Systematic Review 优先于 Review')
        self.assertEqual(by_key['rct'], 1, 'RCT 优先于宽泛的 Clinical Trial')
        self.assertNotIn('review', by_key)
        self.assertEqual(sum(b['count'] for b in out['buckets']), 2)

    def test_summary_is_descriptive_not_prescriptive(self):
        out = evidence.evidence_mix([
            paper(['Randomized Controlled Trial']),
            paper(['Randomized Controlled Trial']),
            paper(['Case Reports']),
            paper(['Case Reports']),
        ])
        self.assertIn('4 篇', out['summary'])
        self.assertIn('随机对照试验 2 篇', out['summary'])
        # 只描述分布，不出现"建议/首选/应信任/高质量"等裁决性措辞。
        for word in ('建议', '首选', '应信任', '高质量', '推荐等级'):
            self.assertNotIn(word, out['summary'] + out['notice'])

    def test_notice_explicitly_denies_quality_grading(self):
        out = evidence.evidence_mix([paper(['Case Reports'])])
        self.assertIn('不是证据质量评级', out['notice'])
        self.assertIn('偏倚风险', out['notice'])

    def test_flags_primary_and_synthesis(self):
        primary = evidence.evidence_mix([paper(['Randomized Controlled Trial'])])
        self.assertTrue(primary['has_primary'])
        self.assertFalse(primary['has_synthesis'])
        synthesis = evidence.evidence_mix([paper(['Meta-Analysis'])])
        self.assertTrue(synthesis['has_synthesis'])
        self.assertFalse(synthesis['has_primary'])
        other = evidence.evidence_mix([paper(['Editorial'])])
        self.assertFalse(other['has_primary'])
        self.assertFalse(other['has_synthesis'])

    def test_percent_are_whole_numbers_summing_about_100(self):
        out = evidence.evidence_mix([
            paper(['Randomized Controlled Trial']),
            paper(['Randomized Controlled Trial']),
            paper(['Case Reports']),
        ])
        for b in out['buckets']:
            self.assertIsInstance(b['percent'], int)
        self.assertEqual(sum(b['percent'] for b in out['buckets']), 100)

    def test_does_not_mutate_input_and_handles_malformed_types(self):
        papers = [{'pmid': '1', 'types': ['Review']}, {'pmid': '2', 'types': 'BadString'},
                  {'pmid': '3'}, paper(['Randomized Controlled Trial'])]
        snapshot = [dict(p) for p in papers]
        out = evidence.evidence_mix(papers)
        self.assertEqual(papers, snapshot, 'input must not be mutated')
        self.assertEqual(out['total'], 4)
        by_key = {b['key']: b['count'] for b in out['buckets']}
        self.assertEqual(by_key['review'], 1)
        self.assertEqual(by_key['rct'], 1)
        self.assertEqual(by_key['other'], 2)


class EvidenceMixWiringTests(unittest.TestCase):
    def test_pubmed_compat_exposes_evidence_mix(self):
        """前端实际走的 pubmed_compat 必须把类型构成带回给 UI。"""
        docs = [
            {'pmid': '1', 'types': ['Meta-Analysis']},
            {'pmid': '2', 'types': ['Randomized Controlled Trial']},
            {'pmid': '3', 'types': ['Case Reports']},
        ]
        fake = {'papers': docs, 'count': 3, 'fetched_at': 0, 'cached': False,
                'evidence_mix': evidence.evidence_mix(docs)}
        with tempfile.TemporaryDirectory() as d, \
             patch.object(api_core, 'DB_PATH', Path(d) / 'c.sqlite3'), \
             patch.object(research_api, 'pubmed', return_value=fake), \
             patch.object(research_api, 'event'):
            api_core.init_db()
            with api_core.connect() as db:
                out = research_api.pubmed_compat(
                    db, 'learner', {'question': '机制', 'query': 'x', 'concept': None},
                    request={'question': '机制', 'query': 'x', 'concept': None,
                             'eligible': True, 'reason': '', 'mapping': ''})
        mix = out['evidence_mix']
        self.assertEqual(mix['total'], 3)
        by_key = {b['key']: b['count'] for b in mix['buckets']}
        self.assertEqual((by_key['meta'], by_key['rct'], by_key['case']), (1, 1, 1))
        self.assertIn('不是证据质量评级', mix['notice'])


if __name__ == '__main__':
    unittest.main()
