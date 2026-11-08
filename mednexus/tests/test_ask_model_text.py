"""答疑答案文本收敛的回归测试。

背景：内置云端接口在没有强制 schema 时，偶尔把 answer 写成
{"结论": "...", "原文依据": "..."}。早期实现直接 str()，答案卡里出现过
{'结论': '小胶质细胞…'} 这样的 Python 字典字面量。这里锁住三条：
1) 字典/列表能按顺序摊平成段落；
2) 摊平后的文本不再被判定为 repr 残渣；
3) 真的摊不平时宁可回落到摘录式（返回 None），也不展示字典。
"""
import unittest
from unittest import mock

from api import ask as ask_api


class AnswerTextTest(unittest.TestCase):
    def test_dict_answer_is_flattened_in_order(self):
        text = ask_api._answer_text({"结论": "小胶质细胞是中枢神经系统的免疫细胞。",
                                     "原文依据": "原文提到它参与突触修剪。"})
        self.assertEqual(text, "小胶质细胞是中枢神经系统的免疫细胞。\n原文提到它参与突触修剪。")
        self.assertNotIn("{", text)
        self.assertFalse(ask_api._looks_like_repr(text))

    def test_list_answer_is_flattened(self):
        self.assertEqual(ask_api._answer_text(["第一句。", "第二句。"]), "第一句。\n第二句。")

    def test_python_repr_is_detected(self):
        self.assertTrue(ask_api._looks_like_repr("{'结论': '小胶质细胞'}"))
        self.assertTrue(ask_api._looks_like_repr("['结论', '依据']"))
        self.assertFalse(ask_api._looks_like_repr("原文说小胶质细胞参与突触修剪。"))

    def test_object_payload_is_flattened_not_shown_as_dict(self):
        payload = {"answer": {"结论": "小胶质细胞参与突触修剪和免疫监视，属于中枢的固有免疫细胞。",
                              "原文依据": "教材该页提到它具有吞噬与抗原提呈作用。"},
                   "covered": True}
        with mock.patch.object(ask_api, "cloud_json", return_value=payload):
            with mock.patch.object(ask_api, "API_KEY", "test-key"):
                result = ask_api._model_ask_answer("小胶质细胞有什么功能", "原文段落", "生理学（第10版）", 284)
        self.assertIsNotNone(result)
        text, covered = result
        self.assertTrue(covered)
        self.assertIn("小胶质细胞", text)
        self.assertNotIn("'结论'", text)

    def test_unflattenable_repr_falls_back(self):
        with mock.patch.object(ask_api, "cloud_json", return_value={"answer": {"a": {"b": {"c": 1}}}, "covered": True}):
            with mock.patch.object(ask_api, "API_KEY", "test-key"):
                self.assertIsNone(ask_api._model_ask_answer("小胶质细胞有什么功能", "原文段落", "生理学（第10版）", 284))


if __name__ == "__main__":
    unittest.main()