"""课程包的容错路径：坏条目只丢自己，服务照样能起来。

与 test_course_loader.py 的分工：
  · test_course_loader.py 测严格模式（有问题就抛 CoursePackageError）；
  · 本文件测非严格模式（坏条目被跳过、问题被记录、其余照常可用），
    以及大纲映射的完整性。
"""
import copy
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import knowledge
import server
import tutoring
from course_loader import CoursePackageError, load_course_package

HERE = Path(__file__).resolve().parents[1]
PACKAGE_PATH = HERE / 'data' / 'courses' / 'anatomy.json'
SYLLABUS_PATH = HERE / 'data' / 'course_materials' / 'syllabus.json'


def load(data, **kwargs):
    """把改坏的课程包写到临时文件，再用非严格模式加载。"""
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'variant.json'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return load_course_package(path, **kwargs)


class PartialLoadTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(PACKAGE_PATH.read_text(encoding='utf-8'))

    def test_broken_concept_is_skipped_and_others_stay_usable(self):
        self.data['concepts'][0].pop('name')
        package = load(self.data, strict=False)
        self.assertTrue(package['problems'])
        self.assertEqual(len(package['concepts']), 9)
        self.assertNotIn('oculomotor', package['concept_map'])
        self.assertEqual(len(package['question_map']), 18)

    def test_broken_question_removes_only_its_concept(self):
        self.data['questions'][0]['points'] = self.data['questions'][0]['points'][:2]
        package = load(self.data, strict=False)
        self.assertIn('oculomotor', [problem for problem in package['problems']
                                     if 'oculomotor' in problem][0])
        self.assertNotIn('oculomotor', package['concept_map'])
        self.assertEqual(len(package['concepts']), 9)

    def test_bad_chapter_reference_drops_only_that_concept(self):
        self.data['concepts'][2]['chapter'] = 'nope'
        package = load(self.data, strict=False)
        self.assertNotIn('abducens', package['concept_map'])
        self.assertEqual(len(package['concepts']), 9)

    def test_orphan_question_becomes_a_warning(self):
        package = load(self.data, strict=False)
        self.assertEqual(package['warnings'], [])
        self.data['questions'].append(copy.deepcopy(self.data['questions'][0]))
        package = load(self.data, strict=False)
        self.assertTrue(any('题号' in problem or '重复' in problem for problem in package['problems']))

    def test_question_of_dropped_concept_does_not_crash(self):
        self.data['concepts'][0].pop('name')
        package = load(self.data, strict=False)
        self.assertTrue(any('没有可用的知识点' in warning for warning in package['warnings']))

    def test_unreadable_package_returns_empty_package_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'broken.json'
            path.write_text('{not json', encoding='utf-8')
            package = load_course_package(path, strict=False)
        self.assertEqual(package['concepts'], [])
        self.assertEqual(package['question_map'], {})
        self.assertTrue(package['problems'])

    def test_missing_package_file_returns_empty_package_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as temp:
            package = load_course_package(Path(temp) / 'none.json', strict=False)
        self.assertEqual(package['concepts'], [])
        self.assertTrue(package['problems'])

    def test_strict_mode_still_raises_for_the_same_package(self):
        self.data['concepts'][0].pop('name')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'variant.json'
            path.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
            with self.assertRaises(CoursePackageError):
                load_course_package(path)


class SyllabusMappingTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(PACKAGE_PATH.read_text(encoding='utf-8'))

    def test_empty_mapping_is_a_warning_not_an_error(self):
        self.data['concepts'][0]['syllabus_refs'] = []
        package = load(self.data, strict=True)
        self.assertTrue(any('还没有映射' in warning for warning in package['warnings']))
        self.assertIn('oculomotor', package['concept_map'])

    def test_unknown_ref_warns_when_the_local_outline_is_known(self):
        package = load(self.data, strict=False, syllabus_ids={'syllabus-333'})
        self.assertTrue(any('syllabus-290' in warning and '不在本机大纲' in warning
                            for warning in package['warnings']))

    def test_refs_are_not_checked_without_a_local_outline(self):
        package = load(self.data, strict=False, syllabus_ids=None)
        self.assertFalse(any('不在本机大纲' in warning for warning in package['warnings']))

    def test_every_shipped_concept_is_mapped(self):
        package = load_course_package(PACKAGE_PATH, strict=False)
        for concept in package['concepts']:
            self.assertTrue(concept['syllabus_refs'], concept['id'])

    def test_shipped_refs_exist_in_the_local_outline(self):
        if not SYLLABUS_PATH.is_file():
            self.skipTest('本机没有大纲资料（data/course_materials/syllabus.json），跳过')
        ids = knowledge.local_syllabus_ids()
        package = load_course_package(PACKAGE_PATH, strict=False, syllabus_ids=ids)
        self.assertEqual([w for w in package['warnings'] if '不在本机大纲' in w], [])
        used = {ref for concept in package['concepts'] for ref in concept['syllabus_refs']}
        self.assertTrue(used)
        self.assertTrue(used.issubset(ids), used - ids)


class StartupResilienceTests(unittest.TestCase):
    def test_server_imports_with_a_broken_course_package(self):
        """课程包写坏时 server 仍然能 import（页面能打开），只是知识点变少。"""
        data = json.loads(PACKAGE_PATH.read_text(encoding='utf-8'))
        data['concepts'][0].pop('name')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'broken.json'
            path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            env = {**os.environ, 'MEDNEXUS_COURSE_PACKAGE': str(path),
                   'PYTHONPATH': str(HERE)}
            result = subprocess.run([sys.executable, '-c',
                                     'import server; print(len(server.CONCEPTS))'],
                                    cwd=str(HERE), env=env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace',
                                    timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '9')
        self.assertIn('course-package', result.stderr)

    def test_server_imports_even_when_the_package_is_unreadable(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'broken.json'
            path.write_text('{not json', encoding='utf-8')
            env = {**os.environ, 'MEDNEXUS_COURSE_PACKAGE': str(path),
                   'PYTHONPATH': str(HERE)}
            result = subprocess.run([sys.executable, '-c',
                                     'import server; print(len(server.CONCEPTS))'],
                                    cwd=str(HERE), env=env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace',
                                    timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '0')

    def test_recommendation_is_none_for_an_empty_course(self):
        self.assertIsNone(server.recommend([]))

    def test_snapshot_survives_an_empty_course(self):
        """空课程时 /api/bootstrap 仍能返回 200。"""
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(server, 'DB_PATH', Path(temp) / 'empty.sqlite3'), \
                    patch.object(server, 'CONCEPTS', []), \
                    patch.object(server, 'CONCEPT_MAP', {}), \
                    patch.object(server, 'QUESTION_MAP', {}):
                server.init_db()
                with server.connect() as db:
                    snap = server.snapshot(db, 'f' * 48)
        self.assertEqual(snap['concepts'], [])
        self.assertIsNone(snap['recommendation'])

    def test_hint_text_falls_back_when_templates_are_missing(self):
        question = knowledge.QUESTION_MAP['oculomotor-pre'][1]
        with patch.object(tutoring, 'HINTS', {}):
            text = tutoring.hint_text(question, 0, 1)
        self.assertIn('先单独分析', text)
        self.assertIn(question['points'][0]['label'], text)


if __name__ == '__main__':
    unittest.main()