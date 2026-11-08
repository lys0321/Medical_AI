"""PMC 解析、license 闸门与降级路径的单元测试（不联网）。"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pmc


def jats(license_ref='CC BY', body=True, extra=''):
    block = ''
    if body:
        block = (
            '<body>'
            '<sec sec-type="methods"><title>Methods</title><p>We enrolled 120 patients.</p></sec>'
            '<sec sec-type="results"><title>Results</title>'
            '<p>Response was higher in the treated group.</p>'
            '<p>Adverse events were similar.</p></sec>'
            '<sec sec-type="discussion"><title>Discussion</title>'
            '<p>Follow-up was short.</p></sec>'
            '</body>'
        )
    license_meta = ''
    if license_ref is not None:
        license_meta = ('<custom-meta><meta-name>pmc-license-ref</meta-name>'
                        '<meta-value>%s</meta-value></custom-meta>' % license_ref)
    return ('<?xml version="1.0"?><article article-type="research-article">'
            '<front><article-meta><title-group><article-title>Fixture title</article-title></title-group>'
            '<custom-meta-group>%s</custom-meta-group></article-meta></front>%s%s</article>'
            % (license_meta, block, extra)).encode('utf-8')


class LicenseTests(unittest.TestCase):
    def test_normalizes_common_spellings(self):
        self.assertEqual(pmc.normalize_license('CC BY'), 'CC BY')
        self.assertEqual(pmc.normalize_license('CC-BY-4.0'), 'CC BY')
        self.assertEqual(pmc.normalize_license('cc by 4.0'), 'CC BY')
        self.assertEqual(pmc.normalize_license('https://creativecommons.org/licenses/by/4.0/'), 'CC BY')
        self.assertEqual(pmc.normalize_license('CC BY-NC'), 'CC BY-NC')
        self.assertEqual(pmc.normalize_license('  '), '')

    def test_allowed_and_denied(self):
        for allowed in ('CC BY', 'CC BY 4.0', 'CC0', 'CC BY-NC'):
            self.assertTrue(pmc.license_allowed(allowed), allowed)
        for denied in ('CC BY-ND', 'CC BY-NC-ND', 'All rights reserved', ''):
            self.assertFalse(pmc.license_allowed(denied), denied)


class ExtractTests(unittest.TestCase):
    def test_extracts_three_sections_with_sequential_citations(self):
        document = pmc.extract(jats(), '12345678')
        self.assertTrue(document['available'])
        self.assertEqual(document['license'], 'CC BY')
        self.assertEqual([section['id'] for section in document['sections']],
                         ['methods', 'results', 'discussion'])
        paragraphs = [p for section in document['sections'] for p in section['paragraphs']]
        self.assertEqual([p['number'] for p in paragraphs], [1, 2, 3, 4])
        self.assertEqual([p['citation'] for p in paragraphs],
                         ['[PMID:1]', '[PMID:2]', '[PMID:3]', '[PMID:4]'])
        self.assertIn('120 patients', paragraphs[0]['text'])

    def test_section_type_beats_title(self):
        xml = ('<article><front><article-meta><custom-meta><meta-name>pmc-license-ref</meta-name>'
               '<meta-value>CC BY</meta-value></custom-meta></article-meta></front>'
               '<body><sec sec-type="results"><title>Something else</title>'
               '<p>Measured outcome.</p></sec></body></article>').encode('utf-8')
        document = pmc.extract(xml, '1')
        self.assertEqual(document['sections'][0]['id'], 'results')

    def test_missing_body_is_reported_not_fabricated(self):
        document = pmc.extract(jats(body=False), '1')
        self.assertFalse(document['available'])
        self.assertEqual(document['sections'], [])
        self.assertIn('没有可用的正文', document['reason'])

    def test_unknown_sections_are_ignored(self):
        xml = ('<article><front><article-meta><custom-meta><meta-name>pmc-license-ref</meta-name>'
               '<meta-value>CC BY</meta-value></custom-meta></article-meta></front><body>'
               '<sec sec-type="introduction"><title>Introduction</title><p>Background.</p></sec>'
               '<sec sec-type="methods"><title>Methods</title><p>How.</p></sec></body></article>').encode('utf-8')
        document = pmc.extract(xml, '1')
        self.assertEqual([section['id'] for section in document['sections']], ['methods'])

    def test_broken_xml_is_reported(self):
        document = pmc.extract(b'<article><body>', '1')
        self.assertFalse(document['available'])
        self.assertIn('XML', document['reason'])

    def test_license_falls_back_to_license_url(self):
        xml = ('<article><front><article-meta><permissions><license>'
               '<license_ref>https://creativecommons.org/licenses/by-nc/4.0/</license_ref>'
               '</license></permissions></article-meta></front>'
               '<body><sec sec-type="results"><title>Results</title><p>R.</p></sec></body></article>').encode('utf-8')
        document = pmc.extract(xml, '1')
        self.assertEqual(document['license'], 'CC BY-NC')

    def test_missing_license_is_empty_not_guessed(self):
        document = pmc.extract(jats(license_ref=None), '1')
        self.assertEqual(document['license'], '')


class IdconvTests(unittest.TestCase):
    def test_reads_pmcid(self):
        payload = b'{"records":[{"pmid":"41101592","pmcid":"PMC11232191"}]}'
        self.assertEqual(pmc.parse_idconv(payload)['pmcid'], 'PMC11232191')

    def test_missing_record_explains_why(self):
        payload = b'{"records":[{"pmid":"1","status":"error","errmsg":"Identifier not found in PMC"}]}'
        result = pmc.parse_idconv(payload)
        self.assertEqual(result['pmcid'], '')
        self.assertIn('not found', result['reason'])

    def test_garbage_payload(self):
        self.assertEqual(pmc.parse_idconv(b'not json')['pmcid'], '')


class HarvestTests(unittest.TestCase):
    def fetch(self, xml_bytes, conv=b'{"records":[{"pmcid":"PMC123"}]}', error=None):
        calls = []

        def fetch(url):
            calls.append(url)
            if error:
                raise error
            if 'idconv' in url:
                return conv
            return xml_bytes
        return fetch, calls

    def test_ok_path_returns_document(self):
        fetch, calls = self.fetch(jats())
        result = pmc.harvest('123', fetch)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['pmcid'], 'PMC123')
        self.assertEqual(result['document']['paragraph_count'], 4)
        self.assertEqual(len(calls), 2)

    def test_no_pmcid_degrades(self):
        fetch, _ = self.fetch(jats(), conv=b'{"records":[{"pmid":"1","errmsg":"not in PMC"}]}')
        result = pmc.harvest('1', fetch)
        self.assertEqual(result['status'], 'no_pmcid')
        self.assertNotIn('document', result)

    def test_license_denied_withholds_every_paragraph(self):
        fetch, _ = self.fetch(jats(license_ref='CC BY-ND'))
        result = pmc.harvest('1', fetch)
        self.assertEqual(result['status'], 'license_denied')
        self.assertIsNone(result['document'])
        self.assertIn('不允许', result['reason'])
        layer = pmc.reading_layer(result, '1')
        self.assertFalse(layer['available'])
        self.assertEqual(layer['sections'], [])

    def test_no_body_degrades_to_abstract_only(self):
        fetch, _ = self.fetch(jats(body=False))
        result = pmc.harvest('1', fetch)
        self.assertEqual(result['status'], 'no_fulltext')
        self.assertFalse(pmc.reading_layer(result, '1')['available'])

    def test_network_error_is_reported(self):
        fetch, _ = self.fetch(jats(), error=OSError('offline'))
        result = pmc.harvest('1', fetch)
        self.assertEqual(result['status'], 'error')
        self.assertIn('失败', result['reason'])


class LayerTests(unittest.TestCase):
    def test_ok_layer_carries_license_and_citations(self):
        fetch, _ = HarvestTests().fetch(jats())
        layer = pmc.reading_layer(pmc.harvest('123', fetch), '123')
        self.assertTrue(layer['available'])
        self.assertEqual(layer['license'], 'CC BY')
        citations = pmc.evidence_citations(layer)
        self.assertEqual([item['citation'] for item in citations],
                         ['[PMID:1]', '[PMID:2]', '[PMID:3]', '[PMID:4]'])

    def test_unavailable_layer_explains_reason(self):
        layer = pmc.layer_from_record({'status': 'license_denied', 'license': 'CC BY-ND'}, '1')
        self.assertFalse(layer['available'])
        self.assertEqual(layer['reason'], 'license_denied')
        self.assertIn('许可', layer['message'])
        self.assertEqual(pmc.evidence_citations(layer), [])

    def test_not_requested_reason(self):
        layer = pmc.layer_from_record({'status': 'not_requested'}, '1')
        self.assertEqual(layer['reason'], 'not_requested')
        self.assertFalse(layer['available'])


if __name__ == '__main__':
    unittest.main()