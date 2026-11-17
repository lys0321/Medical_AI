# -*- coding: utf-8 -*-
"""考点题库并入三要点诊断题：转换、兼容、降级与过滤的回归测试。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaodian_drill as drill

ANATOMY = Path(__file__).resolve().parents[1] / "data" / "courses" / "anatomy.json"

DIRTY = {
    "脏数据教材": [
        {"no": 1, "title": "测试章", "sections": [
            {"name": "小节", "items": [
                "这不是对象",
                {"no": 1, "text": None},
                {"no": 2, "text": "   "},
                {"no": 3, "text": 12345},
                {"no": 4, "text": "没有冒号的一段普通文本，长度也凑合，但切不出术语"},
                {"no": 5, "text": "太短：只有几个字"},
                {"no": 6, "text": "骨：以骨组织为主体构成的器官，成人有206块，分为骨膜、骨质和骨髓。"},
                {"no": 7, "text": "长骨：分布于四肢，呈长管状，分为一体两端，骨干与骺相邻。"},
                {"no": 8, "text": "短骨：形似立方体，多成群分布于连结牢固的部位，如腕骨和跗骨。"},
                {"no": 9, "text": "扁骨：呈板状，参与构成颅腔、胸腔和盆腔壁，可保护脏器。"},
            ]},
        ]},
    ],
}


class KaodianDrillTestCase(unittest.TestCase):
    def setUp(self):
        self.saved = drill.CANDIDATES
        drill._CACHE.pop("data", None)

    def tearDown(self):
        drill.CANDIDATES = self.saved
        drill._CACHE.pop("data", None)

    def use(self, data):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        with tmp:
            json.dump(data, tmp, ensure_ascii=False)
        drill.CANDIDATES = (tmp.name,)
        drill._CACHE.pop("data", None)
        self.addCleanup(lambda: os.unlink(tmp.name))

    # ---------------- 真实题库 ----------------

    def test_real_kaodian_produces_valid_questions(self):
        questions = drill.build_questions(limit=8)
        self.assertEqual(len(questions), 8)
        for question in questions:
            self.assertEqual(question["kind"], "diagnostic")
            self.assertEqual(len(question["points"]), 3)
            for point in question["points"]:
                self.assertEqual(len(point["options"]), 4)
                self.assertIn(point["expected"], point["options"])
                # 正确选项必须来自原文，不得编造。
                self.assertIn(point["expected"], question["source"]["explanation"])

    def test_generation_is_deterministic(self):
        first = drill.build_questions(limit=5)
        second = drill.build_questions(limit=5)
        self.assertEqual(first, second)

    def test_structure_matches_anatomy_questions(self):
        shipped = json.loads(ANATOMY.read_text(encoding="utf-8"))
        sample_question = shipped["questions"][0]
        sample_point = sample_question["points"][0]
        question = drill.build_questions(limit=1)[0]
        for key in sample_question:
            if key == "concept":  # 概念 id 由课程包声明，转换器只提供占位字段
                self.assertIn(key, question)
            else:
                self.assertIn(key, question)
        point = question["points"][0]
        for key in sample_point:
            self.assertIn(key, point)
        self.assertEqual(point["correct"], point["expected"])
        self.assertEqual(len(set(point["options"])), 4)

    # ---------------- 脏数据降级 ----------------

    def test_dirty_items_are_skipped_not_crashed(self):
        self.use(DIRTY)
        points = drill.load_points()
        self.assertEqual([p["term"] for p in points],
                         ["骨", "长骨", "短骨", "扁骨"])
        self.assertTrue(all(set(p) == {"term", "explanation", "book", "chapter"}
                            for p in points))
        questions = drill.build_questions()
        self.assertEqual(len(questions), 4)
        for question in questions:
            self.assertNotIn("没有冒号", question["prompt"])

    def test_as_diagnostic_rejects_unusable_points(self):
        with self.assertRaises(ValueError):
            drill.as_diagnostic({"term": "骨", "explanation": "太短"}, ["甲", "乙", "丙"])
        with self.assertRaises(ValueError):
            drill.as_diagnostic("not a dict", ["甲", "乙", "丙"])
        with self.assertRaises(ValueError):
            drill.as_diagnostic({"term": "骨", "explanation": "由骨组织构成，成人有206块，分为骨膜、骨质和骨髓。"},
                                ["甲", "乙"])  # 干扰项不足

    def test_catalog_reports_skip_reasons(self):
        self.use(DIRTY)
        stats = drill.catalog()["脏数据教材"]
        self.assertEqual(stats["total"], 10)
        self.assertEqual(stats["eligible"], 4)
        self.assertEqual(stats["skipped"]["missing_or_bad_text"], 4)
        self.assertEqual(stats["skipped"]["no_term"], 1)
        self.assertEqual(stats["skipped"]["short_explanation"], 1)
        self.assertEqual(len(stats["chapters"]), 1)
        self.assertEqual(stats["chapters"][0]["total"], 10)

    # ---------------- 干扰项与结构细节 ----------------

    def test_distractors_are_deduplicated_and_unique_in_options(self):
        self.use(DIRTY)
        point = {"term": "骨", "explanation": "以骨组织为主体构成的器官，成人有206块，分为骨膜、骨质和骨髓。"}
        question = drill.as_diagnostic(point, ["长骨", "长骨", "短骨", "短骨", "扁骨", "骨"])
        for item in question["points"]:
            options = item["options"]
            self.assertEqual(len(set(options)), 4)
            self.assertEqual(options.count(item["correct"]), 1)
            self.assertNotIn("骨", [o for o in options if o != item["correct"]])

    def test_catalog_on_real_data_has_both_books(self):
        stats = drill.catalog()
        self.assertEqual(set(stats), {"系统解剖学（第10版）", "组织学与胚胎学（第10版）"})
        for book, book_stat in stats.items():
            self.assertGreater(book_stat["eligible"], 0)
            self.assertLessEqual(book_stat["eligible"], book_stat["total"])
            self.assertTrue(book_stat["chapters"])

    # ---------------- 过滤与 limit ----------------

    def test_book_and_chapter_filters(self):
        self.use(DIRTY)
        points = drill.load_points(book="脏数据教材", chapter=1)
        self.assertEqual(len(points), 4)
        self.assertEqual(drill.load_points(book="不存在的书"), [])
        self.assertEqual(drill.load_points(book="脏数据教材", chapter=999), [])
        questions = drill.build_questions(book="脏数据教材", chapter=1)
        self.assertEqual(len(questions), 4)
        self.assertTrue(all(q["chapter"] == 1 for q in questions))

    def test_limit(self):
        self.assertEqual(len(drill.build_questions(limit=2)), 2)
        self.assertEqual(drill.build_questions(limit=0), [])
        all_questions = drill.build_questions()
        self.assertGreater(len(all_questions), 2)
        self.assertEqual(len(drill.build_questions(limit=10 ** 6)), len(all_questions))


if __name__ == "__main__":
    unittest.main()
