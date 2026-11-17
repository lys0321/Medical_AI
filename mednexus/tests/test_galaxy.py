"""医学知识星图布局（galaxy）单元测试。

核心契约：布局完全由真实掌握度数据决定、确定性可复现；每个节点可回溯到
真实知识点 id/status/score；薄弱点被显式标记；不改入参；空数据安全降级。
"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import galaxy
import server
import knowledge


def concept(cid, unit, status, score, attempts=1, **kw):
    return {'id': cid, 'name': cid + '名', 'unit': unit, 'level': '掌握',
            'status': status, 'score': score, 'attempts': attempts,
            'distinct': 1, 'viewed': True, **kw}


CONCEPTS = [
    concept('a', '单元一', '已掌握', 92, 3),
    concept('b', '单元一', '需巩固', 55, 2),
    concept('c', '单元二', '未测评', None, 0),
    concept('d', '单元二', '初步达标', 81, 2),
    concept('e', '单元二', '已掌握', 88, 4),
    concept('f', '单元三', '需巩固', 40, 5),
]


class GalaxyTests(unittest.TestCase):
    def test_empty_concepts_is_safe(self):
        out = galaxy.build_galaxy([], stats=None, weak=None)
        self.assertEqual(out['clusters'], [])
        self.assertEqual(out['nodes'], [])
        self.assertEqual(out['summary']['total'], 0)
        self.assertFalse(out['summary']['has_weak'])

    def test_groups_by_unit_into_clusters(self):
        out = galaxy.build_galaxy(CONCEPTS, stats=None, weak=None)
        units = [c['unit'] for c in out['clusters']]
        self.assertEqual(units, ['单元一', '单元二', '单元三'])
        self.assertEqual([c['count'] for c in out['clusters']], [2, 3, 1])
        # 节点总数守恒，且每个节点带真实 id
        self.assertEqual(len(out['nodes']), len(CONCEPTS))
        self.assertEqual(sorted(n['id'] for n in out['nodes']), ['a', 'b', 'c', 'd', 'e', 'f'])

    def test_nodes_carry_verifiable_real_data(self):
        out = galaxy.build_galaxy(CONCEPTS, stats=None, weak=None)
        by_id = {n['id']: n for n in out['nodes']}
        self.assertEqual(by_id['a']['status'], '已掌握')
        self.assertEqual(by_id['a']['score'], 92)
        self.assertEqual(by_id['b']['status'], '需巩固')
        self.assertEqual(by_id['c']['score'], None)

    def test_weak_nodes_are_explicitly_marked(self):
        out = galaxy.build_galaxy(CONCEPTS, stats=None, weak=None)
        by_id = {n['id']: n for n in out['nodes']}
        self.assertTrue(by_id['b']['is_weak'])
        self.assertTrue(by_id['f']['is_weak'])
        self.assertFalse(by_id['a']['is_weak'])
        self.assertFalse(by_id['c']['is_weak'], '未测评不算薄弱，不能制造焦虑')
        self.assertTrue(out['summary']['has_weak'])

    def test_tone_encodes_status_not_quality(self):
        out = galaxy.build_galaxy(CONCEPTS, stats=None, weak=None)
        by_id = {n['id']: n for n in out['nodes']}
        self.assertEqual(by_id['a']['tone'], 'mastered')
        self.assertEqual(by_id['b']['tone'], 'weak')
        self.assertEqual(by_id['c']['tone'], 'untested')
        self.assertEqual(by_id['d']['tone'], 'progressing')

    def test_layout_is_deterministic(self):
        a = galaxy.build_galaxy(CONCEPTS, stats=None, weak=None)
        b = galaxy.build_galaxy(CONCEPTS, stats=None, weak=None)
        self.assertEqual(a, b, 'same input must yield identical layout')

    def test_positions_are_within_viewbox_and_distinct(self):
        out = galaxy.build_galaxy(CONCEPTS, stats=None, weak=None)
        vb = out['viewBox']
        pts = [(n['x'], n['y']) for n in out['nodes']]
        self.assertEqual(len(set(pts)), len(pts), 'nodes must not overlap')
        for x, y in pts:
            self.assertTrue(vb[0] <= x <= vb[0] + vb[2])
            self.assertTrue(vb[1] <= y <= vb[1] + vb[3])
        for n in out['nodes']:
            self.assertGreaterEqual(n['r'], galaxy.MIN_R)

    def test_summary_counts_match_real_stats(self):
        stats = {'mastered': 2, 'weak': 2, 'assessed': 4, 'total': 6}
        out = galaxy.build_galaxy(CONCEPTS, stats=stats, weak=[{'book': 'x', 'page': 10, 'count': 3}])
        self.assertEqual(out['summary']['total'], 6)
        self.assertEqual(out['summary']['mastered'], 2)
        self.assertEqual(out['summary']['weak'], 2)
        self.assertEqual(out['summary']['pages_reviewed'], 1)
        self.assertEqual(out['summary']['source'], '本地真实作答数据')

    def test_input_is_not_mutated(self):
        snapshot = [dict(c) for c in CONCEPTS]
        galaxy.build_galaxy(CONCEPTS, stats={'total': 6}, weak=None)
        self.assertEqual(CONCEPTS, snapshot)

    def test_score_to_radius_is_monotonic_and_bounded(self):
        r_low = galaxy.score_radius(40, attempts=1)
        r_high = galaxy.score_radius(95, attempts=1)
        self.assertLess(r_low, r_high)
        self.assertLessEqual(galaxy.score_radius(None, attempts=0), galaxy.MIN_R + 0.01)
        self.assertLessEqual(galaxy.score_radius(100, attempts=99), galaxy.MAX_R)


class GalaxyWiringTests(unittest.TestCase):
    def test_overview_exposes_galaxy_from_real_concepts(self):
        temp = tempfile.TemporaryDirectory()
        old = server.DB_PATH
        try:
            server.DB_PATH = Path(temp.name) / 'galaxy.sqlite3'
            server.init_db()
            db = server.connect()
            overview = server.overview_payload(db, 'g' * 48)
            g = overview['galaxy']
            self.assertEqual(len(g['nodes']), len(knowledge.CONCEPTS))
            ids = {n['id'] for n in g['nodes']}
            self.assertIn(knowledge.CONCEPTS[0]['id'], ids)
            self.assertEqual(g['summary']['source'], '本地真实作答数据')
            self.assertEqual(len(g['clusters']), len({c['unit'] for c in knowledge.CONCEPTS}))
            db.close()
        finally:
            server.DB_PATH = old
            temp.cleanup()


if __name__ == '__main__':
    unittest.main()
