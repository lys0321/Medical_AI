# -*- coding: utf-8 -*-
"""教材精练：把《系统解剖学》考点速记整理成可按章节作答的单选题。

题面的每一句话都来自考点原文（OCR 校对后的 940 条），选项也全部是原文里的
其他考点，因此学生选中后能直接回书核对，不需要模型编造。

题型：
    term   给术语选原文解释
    define 给原文解释选术语（等于把术语挖空）
"""
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANDIDATES = (ROOT.parent / "kaodian.json", ROOT / "data" / "kaodian.json")

_CACHE = {}


def load():
    if "data" not in _CACHE:
        data = {}
        for path in CANDIDATES:
            path = Path(path)
            try:
                if path.is_file():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    break
            except (OSError, ValueError):
                continue
        _CACHE["data"] = data if isinstance(data, dict) else {}
    return _CACHE["data"]


def available():
    return bool(load())


def catalog():
    """教材 → 章节列表（含条目数），前端用它渲染两级选择。"""
    out = []
    for book, chapters in load().items():
        rows = []
        for c in chapters:
            count = sum(len(s["items"]) for s in c.get("sections", []))
            rows.append({"no": c.get("no"), "title": c.get("title") or ("第%s章" % c.get("no")),
                         "count": count,
                         "sections": [{"name": s.get("name", ""), "count": len(s["items"])}
                                      for s in c.get("sections", [])]})
        out.append({"book": book, "chapters": rows, "total": sum(r["count"] for r in rows)})
    return out


def chapter_items(book, no):
    for c in load().get(book, []):
        if c.get("no") == no:
            return [(s.get("name", ""), it) for s in c.get("sections", []) for it in s["items"]]
    return []


BAD_HEAD_TAIL = ("于", "为", "是", "在", "有", "包括", "起", "使", "称", "位于", "属于", "分为", "由")
DEFINITION_HINTS = ("是", "指", "包括", "由", "分为", "位于", "属于", "呈")


def _split(text):
    """考点原文多是「术语：解释」，没有冒号时整句算解释。"""
    parts = re.split(r"[：:]", text, maxsplit=1)
    if len(parts) == 2:
        head, tail = parts[0].strip(), parts[1].strip()
        # 单字术语（如「骨：…」「肌：…」）也是真考点，允许 1 个字，但必须是汉字。
        if 1 <= len(head) <= 16 and re.search(r"[\u4e00-\u9fff]", head):
            return head, tail
    return "", text.strip()


def is_definition(term, tail):
    """只有「名词：一句完整解释」的考点才适合出定义题。

    「胸大肌止于：肱骨大结节嵴。」这类是简短填空式答案，拿它出题会变成
    「『胸大肌止于』在教材里指的是？」这种不通顺的题干，所以直接排除。
    """
    if len(tail) < 14 or len(term) > 14:
        return False
    if term.endswith(BAD_HEAD_TAIL):
        return False
    if not re.search(r"[\u4e00-\u9fff]", term):
        return False
    return any(hint in tail for hint in DEFINITION_HINTS) or tail.endswith("。")


def _shorten(text, limit=58):
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip("，、；") + "…"


def _masked(tail):
    """挖空题题面：把定义句开头的连接词去掉，避免出现「是……描述的是？」这种话。"""
    text = tail.strip()
    for lead in ("参与构成", "主要位于", "主要", "包括", "分为", "具有", "位于", "是由", "是", "由"):
        if text.startswith(lead):
            text = text[len(lead):].lstrip("，、 ")
            break
    return _shorten(text, 90)


def build(book, no, rng=None):
    """出一道单选题；题目与选项都只从这一章的原文里取。"""
    entries = chapter_items(book, no)
    if len(entries) < 4:
        raise ValueError("这一章的考点不足 4 条，暂时不能出题")

    rng = rng or random.SystemRandom()
    parsed = []
    for section, item in entries:
        term, tail = _split(item["text"])
        if not term or not is_definition(term, tail):
            continue
        parsed.append({"no": item["no"], "section": section, "text": item["text"].strip(),
                       "term": term, "tail": tail})
    if len(parsed) < 4:
        raise ValueError("这一章可成题的考点不足 4 条")

    target = rng.choice(parsed)
    pool = [p for p in parsed if p["no"] != target["no"]]

    if rng.random() < 0.5:
        kind = "term"
        prompt = "「%s」在教材里指的是？" % target["term"]
        correct = _shorten(target["tail"])
        others = []
        for p in pool:
            value = _shorten(p["tail"])
            if value != correct and value not in others:
                others.append(value)
            if len(others) == 3:
                break
    else:
        kind = "define"
        prompt = "%s\n\n上面这段描述的是？" % _masked(target["tail"])
        correct = target["term"]
        others = []
        for p in pool:
            if p["term"] != correct and p["term"] not in others:
                others.append(p["term"])
            if len(others) == 3:
                break

    if len(others) < 3:
        raise ValueError("这一章的干扰项不足，暂时不能出题")

    options = others + [correct]
    rng.shuffle(options)
    return {"book": book, "chapter": no, "kind": kind, "prompt": prompt,
            "options": options, "answer": correct,
            "source": {"no": target["no"], "section": target["section"], "text": target["text"]}}


def grade(task, choice):
    """判分并给出原文出处；不调用模型，也不补写教材之外的内容。"""
    options = task["options"]
    if choice not in options:
        raise ValueError("请选择一个选项")
    correct = choice == task["answer"]
    return {"book": task["book"], "chapter": task["chapter"], "kind": task["kind"],
            "prompt": task["prompt"], "options": options, "choice": choice,
            "answer": task["answer"], "correct": correct, "score": 100 if correct else 0,
            "source": task["source"],
            "notice": "答案与选项都摘自考点原文第 %s 条，可回书核对。" % task["source"]["no"]}