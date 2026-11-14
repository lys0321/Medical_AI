# -*- coding: utf-8 -*-
"""教材精练：题面与选项必须来自考点原文，判分不依赖模型。"""
import json
import os
import tempfile
import unittest

import kaodian


SAMPLE = {"测试教材（第1版）": [
    {"no": 1, "title": "测试章", "sections": [
        {"name": "第一小节", "items": [
            {"no": 1, "text": "骨：以骨组织为主体构成的器官，成人有206块。"},
            {"no": 2, "text": "长骨：分布于四肢，呈长管状，分为一体两端。"},
            {"no": 3, "text": "短骨：形似立方体，多成群分布于连结牢固的部位，如腕骨和跗骨。"},
            {"no": 4, "text": "扁骨：呈板状，参与构成颅腔、胸腔和盆腔壁。"},
            {"no": 5, "text": "胸大肌止于：肱骨大结节嵴。"},
        ]},
    ]},
    {"no": 2, "title": "单条章", "sections": [
        {"name": "只有一条", "items": [{"no": 9, "text": "只：有一条。"}]},
    ]},
]}


class KaodianTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(SAMPLE, self.tmp, ensure_ascii=False)
        self.tmp.close()
        self.saved = kaodian.CANDIDATES
        kaodian.CANDIDATES = (self.tmp.name,)
        kaodian._CACHE.pop("data", None)

    def tearDown(self):
        kaodian.CANDIDATES = self.saved
        kaodian._CACHE.pop("data", None)
        os.unlink(self.tmp.name)

    def test_catalog_counts_items_per_chapter(self):
        books = kaodian.catalog()
        self.assertEqual(books[0]["book"], "测试教材（第1版）")
        self.assertEqual(books[0]["chapters"][0]["count"], 5)
        self.assertEqual(books[0]["chapters"][1]["count"], 1)

    def test_question_and_options_come_from_source_text(self):
        task = kaodian.build("测试教材（第1版）", 1)
        self.assertIn(len(task["options"]), (4,))
        self.assertIn(task["answer"], task["options"])
        self.assertIn(task["source"]["text"], [it["text"] for it in SAMPLE["测试教材（第1版）"][0]["sections"][0]["items"]])
        for option in task["options"]:
            self.assertTrue(option.strip())

    def test_short_answer_items_never_become_questions(self):
        # 「胸大肌止于：肱骨大结节嵴。」是填空式答案，不能出成定义题。
        for _ in range(30):
            task = kaodian.build("测试教材（第1版）", 1)
            self.assertNotIn("胸大肌止于", task["prompt"])
            self.assertNotEqual(task["answer"], "肱骨大结节嵴。")

    def test_grade_marks_right_and_wrong(self):
        task = kaodian.build("测试教材（第1版）", 1)
        right = kaodian.grade(task, task["answer"])
        self.assertTrue(right["correct"])
        self.assertEqual(right["score"], 100)
        wrong_option = next(o for o in task["options"] if o != task["answer"])
        wrong = kaodian.grade(task, wrong_option)
        self.assertFalse(wrong["correct"])
        self.assertEqual(wrong["score"], 0)
        self.assertIn("可回书核对", wrong["notice"])

    def test_grade_rejects_option_outside_question(self):
        task = kaodian.build("测试教材（第1版）", 1)
        with self.assertRaises(ValueError):
            kaodian.grade(task, "这段选项根本不在题里")

    def test_chapter_with_too_few_items_is_refused(self):
        with self.assertRaises(ValueError):
            kaodian.build("测试教材（第1版）", 2)
        with self.assertRaises(ValueError):
            kaodian.build("不存在的教材", 1)


if __name__ == "__main__":
    unittest.main()