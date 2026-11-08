"""科研接口：全文层、证据提示与引文导出的 HTTP 回归（网络全部打桩）。"""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server

PMID = '12345678'

PAPER = {
    'pmid': PMID, 'title': 'Effect of X on Y', 'journal': 'Journal of Testing', 'year': '2024',
    'authors': ['Liang W', 'He Y'], 'types': ['Randomized Controlled Trial'], 'evidence': '随机对照试验',
    'doi': 'https://doi.org/10.1000/xyz', 'url': 'https://pubmed.ncbi.nlm.nih.gov/%s/' % PMID,
    'abstract': [{'label': 'METHODS', 'category': 'METHODS',
                  'text': 'We randomized 120 patients and assessed outcomes double-blind.'},
                 {'label': 'RESULTS', 'category': 'RESULTS', 'text': 'Response was higher (P<0.05).'}],
}

OK = {
    'status': 'ok', 'pmid': PMID, 'pmcid': 'PMC123', 'license': 'CC BY', 'license_raw': 'CC BY',
    'reason': '', 'title': 'Effect of X on Y',
    'document': {'available': True, 'paragraph_count': 2, 'sections': [
        {'id': 'results', 'title': '研究结果', 'paragraphs': [
            {'number': 1, 'section': 'results', 'text': 'We enrolled 120 patients.',
             'truncated': False, 'title': 'Results', 'citation': '[PMID:1]'},
            {'number': 2, 'section': 'results', 'text': 'Response was higher.',
             'truncated': False, 'title': 'Results', 'citation': '[PMID:2]'}]}]},
}
DENIED = {'status': 'license_denied', 'pmid': PMID, 'pmcid': 'PMC123', 'license': 'CC BY-ND',
          'reason': '许可为 CC BY-ND，不允许摘录或再分发正文', 'document': None, 'title': ''}
NO_BODY = {'status': 'no_fulltext', 'pmid': PMID, 'pmcid': 'PMC123', 'license': 'CC BY',
           'reason': 'PMC 记录没有可用的正文（可能仅摘要或非开放获取）', 'document': None, 'title': ''}


class ResearchHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db_patch = patch.object(server, 'DB_PATH', Path(cls.temp.name) / 'research.sqlite3')
        cls.db_patch.start()
        server.init_db()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.http.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=3)
        cls.db_patch.stop()
        cls.temp.cleanup()

    def seed(self):
        with server.connect() as db:
            db.execute('DELETE FROM cache')
            db.execute('DELETE FROM fulltext')
            db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                       ('fixture', json.dumps({'schema_version': 2, 'papers': [PAPER]}, ensure_ascii=False),
                        __import__('time').time()))

    def post(self, path, body):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode(),
            headers={'X-Learner-ID': 'a' * 48, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def with_harvest(self, result):
        return patch.object(server.pmc, 'harvest', side_effect=lambda pmid, fetch: result)

    def test_fulltext_endpoint_returns_paragraphs_with_citations(self):
        self.seed()
        with self.with_harvest(OK):
            status, payload = self.post('/api/fulltext', {'pmid': PMID})
        self.assertEqual(status, 200)
        self.assertTrue(payload['available'])
        self.assertEqual(payload['license'], 'CC BY')
        paragraphs = [p for section in payload['sections'] for p in section['paragraphs']]
        self.assertEqual([p['citation'] for p in paragraphs], ['[PMID:1]', '[PMID:2]'])

    def test_license_denied_returns_no_fulltext_at_all(self):
        self.seed()
        with self.with_harvest(DENIED):
            status, payload = self.post('/api/fulltext', {'pmid': PMID})
        self.assertEqual(status, 200)
        self.assertFalse(payload['available'])
        self.assertEqual(payload['reason'], 'license_denied')
        self.assertIn('许可', payload['message'])
        self.assertNotIn('120 patients', json.dumps(payload, ensure_ascii=False))

    def test_missing_fulltext_degrades_to_abstract(self):
        self.seed()
        with self.with_harvest(NO_BODY):
            status, payload = self.post('/api/fulltext', {'pmid': PMID})
        self.assertEqual(status, 200)
        self.assertFalse(payload['available'])
        self.assertIn('摘要', payload['message'])

    def test_read_paper_without_fulltext_is_not_requested(self):
        self.seed()
        status, payload = self.post('/api/read-paper', {'pmid': PMID, 'question': '这个干预的效果如何？'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['fulltext']['reason'], 'not_requested')
        self.assertEqual([layer['id'] for layer in payload['layers']], ['abstract', 'fulltext'])
        self.assertIn('fields', payload['evidence_grade'])
        self.assertIn('不能凭文献类型判定质量', payload['evidence_grade']['reminder'])

    def test_read_paper_layers_abstract_and_fulltext(self):
        self.seed()
        with self.with_harvest(OK):
            status, payload = self.post('/api/read-paper', {'pmid': PMID, 'question': '这个干预的效果如何？',
                                                           'include_fulltext': True})
        self.assertEqual(status, 200)
        self.assertTrue(payload['fulltext']['available'])
        self.assertEqual(payload['fulltext']['license'], 'CC BY')
        self.assertEqual([item['citation'] for item in payload['fulltext_citations']],
                         ['[PMID:1]', '[PMID:2]'])
        self.assertTrue(payload['layers'][1]['available'])
        self.assertIn('全文', payload['mode'])

    def test_read_paper_degrades_when_license_is_denied(self):
        self.seed()
        with self.with_harvest(DENIED):
            status, payload = self.post('/api/read-paper', {'pmid': PMID, 'question': '这个干预的效果如何？',
                                                           'include_fulltext': True})
        self.assertEqual(status, 200)
        self.assertFalse(payload['fulltext']['available'])
        self.assertEqual(payload['fulltext_citations'], [])
        self.assertNotIn('We enrolled', json.dumps(payload, ensure_ascii=False))

    def test_export_citations_bibtex_and_ris(self):
        self.seed()
        status, payload = self.post('/api/export-citations', {'pmids': [PMID], 'format': 'bibtex'})
        self.assertEqual(status, 200)
        self.assertEqual(payload['count'], 1)
        self.assertTrue(payload['content'].startswith('@article{pmid' + PMID))
        status, payload = self.post('/api/export-citations', {'pmids': [PMID], 'format': 'ris'})
        self.assertEqual(status, 200)
        self.assertIn('TY  - JOUR', payload['content'])
        self.assertIn('AN  - ' + PMID, payload['content'])

    def test_export_rejects_bad_format_and_unknown_pmids(self):
        self.seed()
        self.assertEqual(self.post('/api/export-citations', {'pmids': [PMID], 'format': 'docx'})[0], 400)
        status, payload = self.post('/api/export-citations', {'pmids': ['999999'], 'format': 'ris'})
        self.assertEqual(status, 400)
        self.assertIn('缓存', payload['error'])


class FulltextCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(server, 'DB_PATH', Path(self.temp.name) / 'cache.sqlite3')
        self.db_patch.start()
        server.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_second_call_uses_cache(self):
        calls = []

        def fake_harvest(pmid, fetch):
            calls.append(pmid)
            return OK
        with patch.object(server.pmc, 'harvest', side_effect=fake_harvest):
            with server.connect() as db:
                first = server.fetch_fulltext(db, PMID)
                second = server.fetch_fulltext(db, PMID)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first['status'], 'ok')
        self.assertEqual(second['paragraph_count'], first['paragraph_count'])

    def test_denial_is_cached_without_paragraphs(self):
        with patch.object(server.pmc, 'harvest', side_effect=lambda pmid, fetch: DENIED):
            with server.connect() as db:
                record = server.fetch_fulltext(db, PMID)
                row = db.execute('SELECT license, status, payload FROM fulltext WHERE pmid=?', (PMID,)).fetchone()
        self.assertEqual(record['status'], 'license_denied')
        self.assertEqual(row['status'], 'license_denied')
        self.assertEqual(json.loads(row['payload'])['sections'], [])

    def test_cached_paper_only_returns_cached_records(self):
        with server.connect() as db:
            self.assertIsNone(server.cached_paper(db, PMID))
            db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',
                       ('k', json.dumps({'schema_version': 2, 'papers': [PAPER]}), 1.0))
            self.assertEqual(server.cached_paper(db, PMID)['title'], PAPER['title'])


if __name__ == '__main__':
    unittest.main()