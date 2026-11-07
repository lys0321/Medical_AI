import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from course_loader import load_course_package, CoursePackageError

PACKAGE_PATH = Path(__file__).resolve().parents[1] / 'data' / 'courses' / 'anatomy.json'


class CourseLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = json.loads(PACKAGE_PATH.read_text(encoding='utf-8'))

    def tearDown(self):
        self.temp.cleanup()

    def load(self, data):
        path = Path(self.temp.name) / 'variant.json'
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return load_course_package(path)

    def assert_invalid(self, data, *fragments):
        with self.assertRaises(CoursePackageError) as ctx:
            self.load(data)
        message = str(ctx.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)

    def test_shipped_package_loads_all_concepts_and_questions(self):
        package = load_course_package(PACKAGE_PATH)
        self.assertEqual(len(package['concepts']), 10)
        self.assertEqual(len(package['concept_map']), 10)
        self.assertEqual(len(package['question_map']), 20)
        self.assertEqual(len(set(package['question_map'])), 20)
        self.assertTrue(all(qid.endswith('-pre') or qid.endswith('-transfer')
                            for qid in package['question_map']))
        for concept in package['concepts']:
            kinds = {q['kind'] for q in concept['questions']}
            self.assertEqual(kinds, {'diagnostic', 'transfer'})
            for question in concept['questions']:
                self.assertIs(package['question_map'][question['id']][0], concept)
                self.assertIs(package['question_map'][question['id']][1], question)
        self.assertEqual(package['course']['units'],
                         ['眼球运动与瞳孔', '面部感觉与运动', '延髓与颈舌运动'])

    def test_every_required_top_level_key_is_reported(self):
        for key in ('course', 'chapters', 'sources', 'concepts', 'questions', 'hints', 'query'):
            with self.subTest(key=key):
                data = copy.deepcopy(self.data)
                del data[key]
                self.assert_invalid(data, key)

    def test_all_problems_are_collected_into_one_error(self):
        data = copy.deepcopy(self.data)
        del data['concepts']
        del data['query']
        data['course']['goal_source'] = ''
        with self.assertRaises(CoursePackageError) as ctx:
            self.load(data)
        lines = str(ctx.exception).splitlines()
        self.assertTrue(any('concepts' in line for line in lines))
        self.assertTrue(any('query' in line for line in lines))
        self.assertTrue(any('goal_source' in line for line in lines))
        self.assertGreater(len(lines), 3)

    def test_duplicate_question_id_is_rejected(self):
        data = copy.deepcopy(self.data)
        data['questions'][1]['id'] = data['questions'][0]['id']
        self.assert_invalid(data, '重复', data['questions'][0]['id'])

    def test_concept_without_transfer_question_is_rejected(self):
        data = copy.deepcopy(self.data)
        data['questions'] = [q for q in data['questions']
                             if not (q['concept'] == 'light' and q['kind'] == 'transfer')]
        self.assert_invalid(data, 'light', 'transfer')

    def test_question_points_must_be_exactly_three(self):
        for count in (2, 4):
            with self.subTest(count=count):
                data = copy.deepcopy(self.data)
                points = data['questions'][0]['points']
                data['questions'][0]['points'] = (points + [points[-1]])[:count]
                self.assert_invalid(data, data['questions'][0]['id'], '3')

    def test_goal_source_is_required_and_non_empty(self):
        for variant in ('missing', 'empty'):
            with self.subTest(variant=variant):
                data = copy.deepcopy(self.data)
                if variant == 'missing':
                    del data['course']['goal_source']
                else:
                    data['course']['goal_source'] = '   '
                self.assert_invalid(data, 'goal_source')

    def test_missing_syllabus_refs_defaults_to_empty_list(self):
        data = copy.deepcopy(self.data)
        del data['concepts'][0]['syllabus_refs']
        package = self.load(data)
        self.assertEqual(package['concepts'][0]['syllabus_refs'], [])

    def test_non_list_syllabus_refs_is_rejected(self):
        data = copy.deepcopy(self.data)
        data['concepts'][0]['syllabus_refs'] = 'syllabus-128'
        self.assert_invalid(data, 'syllabus_refs')

    def test_syllabus_refs_must_be_strings(self):
        data = copy.deepcopy(self.data)
        data['concepts'][0]['syllabus_refs'] = ['syllabus-128', 7]
        self.assert_invalid(data, 'syllabus_refs')

    def test_query_entry_for_unknown_concept_is_rejected(self):
        data = copy.deepcopy(self.data)
        data['query']['ghost'] = 'optic nerve[Title/Abstract]'
        self.assert_invalid(data, 'ghost')

    def test_question_with_duplicate_options_is_rejected(self):
        data = copy.deepcopy(self.data)
        options = data['questions'][0]['points'][0]['options']
        options[1] = options[2]
        self.assert_invalid(data, 'options')

    def test_question_referencing_unknown_concept_is_rejected(self):
        data = copy.deepcopy(self.data)
        data['questions'][0]['concept'] = 'ghost'
        self.assert_invalid(data, data['questions'][0]['id'], 'ghost')

    def test_unreadable_or_non_object_package_is_rejected(self):
        path = Path(self.temp.name) / 'broken.json'
        path.write_text('{not json', encoding='utf-8')
        with self.assertRaises(CoursePackageError):
            load_course_package(path)
        path.write_text('[1,2,3]', encoding='utf-8')
        with self.assertRaises(CoursePackageError):
            load_course_package(path)


if __name__ == '__main__':
    unittest.main()
