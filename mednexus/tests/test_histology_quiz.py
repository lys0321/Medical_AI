"""组胚识图题的生成与判分（纯函数，不联网）。"""
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import histology_quiz


def labels(pages=None, requires_review=True):
    return {'schema_version': 1, 'requires_teacher_review': requires_review,
            'notice': '待教师审核', 'pages': pages if pages is not None else [
                {'image_number': 1, 'image': 'histology-1.png', 'structures': ['普通光学显微镜技术', '标本制作：切片法'],
                 'tissue': '上皮组织', 'stains': ['HE染色'], 'source_page': 1, 'review_status': 'pending'},
                {'image_number': 2, 'image': 'histology-2.png', 'structures': ['疏松结缔组织的特点', '成纤维细胞'],
                 'tissue': '结缔组织', 'stains': [], 'source_page': 2, 'review_status': 'pending'},
                {'image_number': 3, 'image': 'histology-3.jpeg', 'structures': ['红细胞形态', '白细胞分类'],
                 'tissue': '血液', 'stains': ['瑞氏-姬姆萨'], 'source_page': 3, 'review_status': 'pending'},
            ]}


def write(temp, payload):
    path = Path(temp) / 'histology_labels.json'
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return path


class LoadTests(unittest.TestCase):
    def test_missing_file_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as temp:
            result = histology_quiz.load_labels(Path(temp) / 'none.json')
        self.assertFalse(result['available'])
        self.assertEqual(result['reason'], 'no_labels')
        self.assertIn('课程资料', result['message'])

    def test_invalid_json_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'broken.json'
            path.write_text('{not json', encoding='utf-8')
            result = histology_quiz.load_labels(path)
        self.assertFalse(result['available'])

    def test_pages_without_headings_are_dropped(self):
        with tempfile.TemporaryDirectory() as temp:
            result = histology_quiz.load_labels(write(temp, labels([
                {'image_number': 1, 'image': 'a.png', 'structures': []},
                {'image_number': 2, 'image': 'b.png', 'structures': ['有标题的页']},
            ])))
        self.assertTrue(result['available'])
        self.assertEqual([page['image_number'] for page in result['pages']], [2])

    def test_no_usable_pages_reports_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            result = histology_quiz.load_labels(write(temp, labels([
                {'image_number': 1, 'image': 'a.png', 'structures': []}])))
        self.assertFalse(result['available'])
        self.assertEqual(result['reason'], 'no_usable_labels')


class QuestionTests(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as temp:
            self.labels = histology_quiz.load_labels(write(temp, labels()))

    def test_question_is_built_from_a_real_heading(self):
        question = histology_quiz.build_question(self.labels, rng=random.Random(1))
        page = next(p for p in self.labels['pages'] if p['image_number'] == question['image_number'])
        self.assertIn(question['answer'], page['structures'])
        self.assertIn(question['answer'], question['options'])
        self.assertEqual(len(question['options']), 4)
        self.assertEqual(len(set(question['options'])), 4)
        self.assertEqual(question['image_url'],
                         '/api/course-materials/images/' + page['image'])
        self.assertIn(str(question['image_number']), question['prompt'])

    def test_public_payload_hides_the_answer(self):
        question = histology_quiz.build_question(self.labels, rng=random.Random(2))
        public = histology_quiz.public(question, 't' * 32)
        self.assertNotIn('answer', public)
        self.assertEqual(public['token'], 't' * 32)
        self.assertEqual(public['kind'], 'image')
        self.assertEqual(public['review_status'], 'pending')
        self.assertIn('待', public['notice'] + '待')
        self.assertEqual(set(public['options']), set(question['options']))

    def test_not_enough_headings_returns_none(self):
        with tempfile.TemporaryDirectory() as temp:
            small = histology_quiz.load_labels(write(temp, labels([
                {'image_number': 1, 'image': 'a.png', 'structures': ['只有一个标题']}])))
        self.assertEqual(histology_quiz.candidates(small), [])
        self.assertIsNone(histology_quiz.build_question(small))


class GradeTests(unittest.TestCase):
    def setUp(self):
        self.question = {'options': ['甲', '乙', '丙', '丁'], 'answer': '丙'}

    def test_correct_and_wrong(self):
        self.assertTrue(histology_quiz.grade(self.question, '丙')['correct'])
        result = histology_quiz.grade(self.question, '甲')
        self.assertFalse(result['correct'])
        self.assertEqual(result['answer'], '丙')

    def test_invalid_choice_is_rejected(self):
        with self.assertRaises(ValueError):
            histology_quiz.grade(self.question, '戊')
        with self.assertRaises(ValueError):
            histology_quiz.grade(self.question, None)


class SummaryTests(unittest.TestCase):
    def test_counts_accuracy_and_scope(self):
        rows = [{'score': 1, 'created': 10, 'payload': json.dumps({'image_number': 1})},
                {'score': 0, 'created': 20, 'payload': json.dumps({'image_number': 1})},
                {'score': 1, 'created': 30, 'payload': json.dumps({'image_number': 2})}]
        result = histology_quiz.summarize(rows)
        self.assertEqual((result['attempts'], result['correct']), (3, 2))
        self.assertEqual(result['accuracy'], 0.667)
        self.assertEqual(result['pages_seen'], 2)
        self.assertEqual(result['last_at'], 30)
        self.assertIn('不计入', result['scope'])

    def test_empty_history(self):
        result = histology_quiz.summarize([])
        self.assertEqual(result['attempts'], 0)
        self.assertIsNone(result['accuracy'])
        self.assertIsNone(result['last_at'])


if __name__ == '__main__':
    unittest.main()