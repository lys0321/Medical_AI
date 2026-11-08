"""证据字段提示与引文导出的单元测试。"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import citations
import evidence


def paper(**changes):
    base = {
        'pmid': '12345678', 'title': 'Effect of X on Y', 'journal': 'Journal of Testing',
        'year': '2024', 'authors': ['Liang W', 'He Y'], 'types': ['Randomized Controlled Trial'],
        'evidence': '随机对照试验', 'doi': 'https://doi.org/10.1000/xyz',
        'url': 'https://pubmed.ncbi.nlm.nih.gov/12345678/',
        'abstract': [
            {'label': 'METHODS', 'category': 'METHODS',
             'text': 'We randomized 120 patients to two groups and assessed outcomes double-blind.'},
            {'label': 'RESULTS', 'category': 'RESULTS', 'text': 'Response was higher (P<0.05).'},
        ],
    }
    base.update(changes)
    return base


class EvidenceTests(unittest.TestCase):
    def test_reports_only_verifiable_fields(self):
        result = evidence.assess(paper())
        fields = result['fields']
        self.assertEqual(fields['study_type']['value'], '随机对照试验')
        self.assertEqual(fields['sample_size']['value'], 120)
        self.assertEqual(fields['randomization']['status'], 'reported')
        self.assertEqual(fields['blinding']['status'], 'reported')

    def test_never_grades_quality(self):
        result = evidence.assess(paper())
        self.assertIn('不是质量评级', result['notice'])
        self.assertIn('不能凭文献类型判定质量', result['reminder'])
        self.assertNotIn('quality', {key.lower() for key in result})
        self.assertNotIn('level', result)

    def test_missing_sample_size_is_reported_as_missing(self):
        result = evidence.assess(paper(abstract=[{'label': 'RESULTS', 'category': 'RESULTS',
                                                 'text': 'No numbers here.'}]))
        self.assertEqual(result['fields']['sample_size']['status'], 'not_reported')
        self.assertTrue(any('没有报告样本量' in hint for hint in result['hints']))

    def test_small_sample_adds_a_precision_hint(self):
        result = evidence.assess(paper(abstract=[{'label': 'METHODS', 'category': 'METHODS',
                                                 'text': 'We enrolled 18 patients.'}]))
        self.assertEqual(result['fields']['sample_size']['value'], 18)
        self.assertTrue(any('样本量较小' in hint for hint in result['hints']))

    def test_absent_blinding_is_worded_as_not_mentioned(self):
        result = evidence.assess(paper(abstract=[{'label': 'METHODS', 'category': 'METHODS',
                                                 'text': 'We randomized 120 patients.'}]))
        self.assertEqual(result['fields']['blinding']['status'], 'not_reported')
        self.assertTrue(any('未提到盲法' in hint for hint in result['hints']))

    def test_review_type_gets_a_heterogeneity_hint(self):
        result = evidence.assess(paper(types=['Systematic Review'], evidence='系统综述'))
        self.assertEqual(result['fields']['study_type']['value'], '系统综述')
        self.assertTrue(any('纳入研究' in hint for hint in result['hints']))

    def test_unknown_type_is_not_inferred(self):
        result = evidence.assess(paper(types=['Journal Article'], evidence='其他研究'))
        self.assertEqual(result['fields']['study_type']['value'], '其他类型（未映射）')
        self.assertTrue(any('Publication Type' in hint for hint in result['hints']))

    def test_multiple_sample_sizes_are_flagged(self):
        result = evidence.assess(paper(abstract=[{'label': 'METHODS', 'category': 'METHODS',
                                                 'text': 'We enrolled 120 patients, and 40 patients completed follow-up.'}]))
        self.assertGreater(len(result['fields']['sample_size']['distinct_values']), 1)
        self.assertTrue(any('多个样本量' in hint for hint in result['hints']))


class BibtexTests(unittest.TestCase):
    def test_bibtex_entry(self):
        text = citations.bibtex([paper()])
        self.assertTrue(text.startswith('@article{pmid12345678,'))
        self.assertIn('title = {Effect of X on Y}', text)
        self.assertIn('author = {Liang W and He Y}', text)
        self.assertIn('journal = {Journal of Testing}', text)
        self.assertIn('doi = {10.1000/xyz}', text)
        self.assertIn('pmid = {12345678}', text)

    def test_special_characters_are_escaped(self):
        text = citations.bibtex([paper(title='X & Y: 50% effect_2024')])
        self.assertIn(r'X \& Y: 50\% effect\_2024', text)

    def test_entries_without_pmid_are_skipped(self):
        self.assertEqual(citations.bibtex([paper(pmid='')]), '')

    def test_multiple_entries_are_separated(self):
        text = citations.bibtex([paper(), paper(pmid='87654321')])
        self.assertEqual(text.count('@article{'), 2)
        self.assertIn('pmid87654321', text)


class RisTests(unittest.TestCase):
    def test_ris_entry(self):
        text = citations.ris([paper()])
        for line in ('TY  - JOUR', 'AU  - Liang, W', 'AU  - He, Y', 'TI  - Effect of X on Y',
                     'JO  - Journal of Testing', 'PY  - 2024', 'DO  - 10.1000/xyz',
                     'L1  - https://pubmed.ncbi.nlm.nih.gov/12345678/', 'AN  - 12345678', 'ER  - '):
            self.assertIn(line, text)

    def test_ris_keeps_ampersand_raw(self):
        self.assertIn('TI  - X & Y', citations.ris([paper(title='X & Y')]))

    def test_export_dispatch(self):
        self.assertIn('@article', citations.export([paper()], 'bibtex'))
        self.assertIn('TY  - JOUR', citations.export([paper()], 'ris'))
        with self.assertRaises(ValueError):
            citations.export([paper()], 'endnote')


if __name__ == '__main__':
    unittest.main()