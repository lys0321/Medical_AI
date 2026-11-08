import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import textbook

QUERY = '动眼神经损伤上睑下垂'
CHUNKS = [
    {'book': '局部解剖学（测试）', 'page': 10,
     'text': '眼外肌由多条脑神经支配。动眼神经损伤可出现上睑下垂和瞳孔散大。其余内容与本题无关。'},
    {'book': '局部解剖学（测试）', 'page': 20,
     'text': '上睑下垂常见于动眼神经损伤；动眼神经还含副交感纤维'},
    {'book': '生理学（测试）', 'page': 30, 'text': '心脏位于胸腔纵隔内，外有心包包裹。'},
]


class TextbookFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.chunks = root / 'chunks.jsonl'
        self.chunks.write_text('\n'.join(json.dumps(c, ensure_ascii=False) for c in CHUNKS), encoding='utf-8')
        self.cache = root / 'embeddings.jsonl'
        self.patches = [patch.object(textbook, 'CANDIDATES', [self.chunks]),
                        patch.object(textbook, 'EMBED_CACHE', self.cache)]
        for item in self.patches:
            item.start()
        textbook.reload()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        textbook.reload()
        self.temp.cleanup()

    def bm25(self):
        with patch.object(textbook, '_embedder', return_value=None):
            return textbook.search(QUERY)

    def with_embedder(self, embed, model='fixture-embed'):
        return patch.object(textbook, '_embedder', return_value=(model, embed))


class SentenceSplitTests(unittest.TestCase):
    def assert_offsets(self, text, spans):
        for start, end in spans:
            self.assertTrue(0 <= start <= end <= len(text))
            piece = text[start:end]
            self.assertEqual(piece, piece.strip())

    def test_sentences_keep_exact_offsets(self):
        text = '  第一句。第二句！\n第三句；最后没有标点'
        spans = textbook._sentences(text)
        self.assertEqual([text[a:b] for a, b in spans], ['第一句。', '第二句！', '第三句；', '最后没有标点'])
        self.assert_offsets(text, spans)

    def test_degenerate_inputs_fall_back_safely(self):
        self.assertEqual(textbook._sentences(''), [(0, 0)])
        self.assertEqual(textbook._sentences('。。。'), [(0, 3)])
        self.assertEqual(textbook._sentences('   '), [(0, 3)])
        long_text = '无标点长段' * 100
        spans = textbook._sentences(long_text)
        self.assertGreater(len(spans), 1)
        self.assertTrue(all(b - a <= textbook.MAX_SENTENCE for a, b in spans))
        self.assertEqual(''.join(long_text[a:b] for a, b in spans), long_text)


class ExcerptTests(TextbookFixture):
    def test_each_hit_carries_the_matched_sentence_with_offsets_and_page(self):
        hits = self.bm25()
        self.assertEqual({h['page'] for h in hits}, {10, 20})
        for hit in hits:
            excerpt = hit['excerpt']
            self.assertEqual(hit['text'][excerpt['start']:excerpt['end']], excerpt['text'])
            self.assertEqual(excerpt['page'], hit['page'])
            self.assertIn('上睑下垂', excerpt['text'])
            self.assertLess(len(excerpt['text']), len(hit['text']))
        first = next(h for h in hits if h['page'] == 10)['excerpt']
        self.assertEqual(first['text'], '动眼神经损伤可出现上睑下垂和瞳孔散大。')

    def test_sources_listing_does_not_expose_sentence_offsets(self):
        for source in textbook.ensure()['sources']:
            self.assertNotIn('excerpt', source)
            self.assertNotIn('sentences', source)


class NoIndexTests(unittest.TestCase):
    def test_missing_index_refuses_without_calling_the_embedder(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(textbook, 'CANDIDATES', [Path(temp) / 'missing.jsonl']), \
                patch.object(textbook, '_embedder') as embedder:
            textbook.reload()
            self.assertEqual(textbook.search(QUERY), [])
            self.assertEqual(textbook.status()['loaded'], 0)
            embedder.assert_not_called()
        textbook.reload()


class HybridTests(TextbookFixture):
    def test_without_ollama_results_match_pure_bm25_and_are_unmarked(self):
        hits = self.bm25()
        self.assertTrue(hits)
        self.assertTrue(all('retrieval' not in h and 'semantic' not in h for h in hits))
        self.assertEqual([h['id'] for h in hits], [h['id'] for h in self.bm25()])

    def test_cosine_reorders_only_results_that_already_passed_the_gate(self):
        plain = self.bm25()
        favoured = plain[-1]['text']
        heart = CHUNKS[2]['text']
        def embed(text):
            return [1.0, 0.0] if text in (QUERY, favoured, heart) else [0.0, 1.0]
        with self.with_embedder(embed):
            hits = textbook.search(QUERY)
        self.assertEqual(hits[0]['text'], favoured)
        self.assertEqual({h['id'] for h in hits}, {h['id'] for h in plain})
        self.assertNotIn(30, [h['page'] for h in hits])
        self.assertTrue(all(h['retrieval'] == 'hybrid' for h in hits))
        self.assertEqual([h['coverage'] for h in sorted(hits, key=lambda h: h['id'])],
                         [h['coverage'] for h in sorted(plain, key=lambda h: h['id'])])

    def test_semantic_similarity_never_rescues_a_refused_query(self):
        with self.with_embedder(lambda text: [1.0, 0.0]):
            self.assertEqual(textbook.search('量子纠缠的基本原理'), [])

    def test_vectors_are_cached_and_reused(self):
        calls = []
        def embed(text):
            calls.append(text)
            return [1.0, 0.5]
        with self.with_embedder(embed):
            textbook.search(QUERY)
            first = len(calls)
            textbook.reload()
            textbook.search(QUERY)
        self.assertEqual(len(calls) - first, 1)
        records = [json.loads(line) for line in self.cache.read_text(encoding='utf-8').splitlines()]
        self.assertTrue(all(r['model'] == 'fixture-embed' and r['dim'] == 2 for r in records))

    def test_corrupt_cache_lines_are_skipped(self):
        self.cache.write_text('\n'.join([
            'not json at all', '{"broken": ', json.dumps(['a', 'list']),
            json.dumps({'key': 'x', 'model': 'fixture-embed', 'vector': ['a', 'b']}),
            '{"key": "y", "model": "fixture-embed", "vector": [NaN, 1.0]}',
        ]), encoding='utf-8')
        textbook.reload()
        with self.with_embedder(lambda text: [1.0, 0.0]):
            hits = textbook.search(QUERY)
        self.assertTrue(hits)
        self.assertTrue(all(h['retrieval'] == 'hybrid' for h in hits))

    def test_unreadable_cache_file_falls_back_to_recomputing(self):
        self.cache.write_bytes(b'\xff\xfe\x00garbage')
        textbook.reload()
        with self.with_embedder(lambda text: [1.0, 0.0]):
            self.assertTrue(textbook.search(QUERY))

    def test_dimension_mismatch_falls_back_to_bm25(self):
        plain = self.bm25()
        dims = {'n': 2}
        def embed(text):
            return [1.0] * (3 if text != QUERY else dims['n'])
        with self.with_embedder(embed):
            hits = textbook.search(QUERY)
        self.assertEqual([h['id'] for h in hits], [h['id'] for h in plain])
        self.assertTrue(all('retrieval' not in h for h in hits))

    def test_stale_cached_vector_with_other_dimension_falls_back(self):
        plain = self.bm25()
        model = 'fixture-embed'
        lines = [json.dumps({'key': textbook._cache_key(model, h['text']), 'model': model, 'vector': [1.0, 2.0, 3.0]})
                 for h in plain]
        self.cache.write_text('\n'.join(lines), encoding='utf-8')
        textbook.reload()
        with self.with_embedder(lambda text: [1.0, 0.0], model):
            hits = textbook.search(QUERY)
        self.assertEqual([h['id'] for h in hits], [h['id'] for h in plain])
        self.assertTrue(all('retrieval' not in h for h in hits))

    def test_embedding_errors_and_bad_vectors_fall_back_to_bm25(self):
        plain = [h['id'] for h in self.bm25()]
        def boom(text):
            raise TimeoutError('fixture')
        for embed in (boom, lambda text: None, lambda text: [], lambda text: [0.0, 0.0],
                      lambda text: ['x'], lambda text: [True, False]):
            with self.subTest(embed=embed), self.with_embedder(embed):
                textbook.reload()
                hits = textbook.search(QUERY)
                self.assertEqual([h['id'] for h in hits], plain)
                self.assertTrue(all('retrieval' not in h for h in hits))


class EmbedderTransportTests(unittest.TestCase):
    def setUp(self):
        import tutor_model
        self.tutor_model = tutor_model
        tutor_model._embed_cache = None

    def tearDown(self):
        self.tutor_model._embed_cache = None

    def test_installed_embedding_model_posts_to_embeddings_endpoint(self):
        calls = []
        def fake(url, payload=None, timeout=2):
            calls.append((url, payload))
            if url.endswith('/api/tags'):
                return {'models': [{'name': 'qwen3:0.6b'}, {'name': 'nomic-embed-text:latest'}]}
            return {'embedding': [0.1, 0.2]}
        with patch.object(self.tutor_model, '_json_request', side_effect=fake):
            model, embed = self.tutor_model.embedder()
            self.assertEqual(model, 'nomic-embed-text:latest')
            self.assertEqual(embed('文本'), [0.1, 0.2])
        self.assertTrue(calls[-1][0].endswith('/api/embeddings'))
        self.assertEqual(calls[-1][1], {'model': 'nomic-embed-text:latest', 'prompt': '文本'})

    def test_absent_ollama_or_model_returns_none(self):
        with patch.object(self.tutor_model, '_json_request', side_effect=OSError('refused')):
            self.assertIsNone(self.tutor_model.embedder())
        self.tutor_model._embed_cache = None
        with patch.object(self.tutor_model, '_json_request', return_value={'models': [{'name': 'qwen3:0.6b'}]}):
            self.assertIsNone(self.tutor_model.embedder())


if __name__ == '__main__':
    unittest.main()
