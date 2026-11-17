# -*- coding: utf-8 -*-
"""考点题库 → 三要点诊断题：纯数据转换，无网络/模型/IO 副作用（读取本地题库除外）。

设计原则（与 kaodian.py 一致）：
    * 题面与选项都只来自 kaodian.json 原文，不编造任何医学内容；
    * 一个「术语：解释」考点拆成 3 个要点，每个要点是一个 4 选 1 的小题；
    * 干扰项取自同一章其它考点的「术语」，去重后凑够 3 个，故 4 选 1 且答案唯一；
    * 转换失败（解释太短 / 切不出 3 个要点 / 干扰项不够）明确跳过，不产出空题。

产出的题目字段与 data/courses/anatomy.json 的 questions 对齐：
    {id, concept, kind, prompt, points, book, chapter, source}
每个要点：
    {label, expected, correct, options, reason, category}
其中 expected 与 correct 同值（correct 是课程包校验器使用的字段名，
expected 是三要点诊断流程里 rubric 使用的字段名），文本均为解释原文片段。
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 与 kaodian.py 保持同样的候选路径：仓库根目录的 kaodian.json 优先。
CANDIDATES = (ROOT.parent / "kaodian.json", ROOT / "data" / "kaodian.json")

_CACHE = {}

# ---------------- 可调阈值（确定性，不依赖随机源） ----------------
MIN_EXPLANATION_LENGTH = 12   # 解释至少这么长才值得拆点
MIN_CLAUSE_LENGTH = 4         # 短于这个长度的标点片段丢弃
POINT_COUNT = 3               # 三要点
DISTRACTOR_COUNT = 3          # 每题 3 个错误选项 + 1 个正确选项
POINT_LABELS = ("要点一", "要点二", "要点三")
CATEGORY = "概念记忆"

# 跳过原因代码（catalog 用）；集中定义避免拼写漂移。
R_BAD_TEXT = "missing_or_bad_text"
R_NO_TERM = "no_term"
R_SHORT = "short_explanation"
R_FEW_POINTS = "too_few_points"
R_FEW_DISTRACTORS = "too_few_distractors"

_CLAUSE_SPLIT = re.compile(r"[，,；;。、\n\r]+")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_TERM_SPLIT = re.compile(r"[：:]")


# ---------------- 读取与规范化 ----------------

def _raw():
    """读取原始题库；与 kaodian.py 相同的容错策略，坏文件视为空题库。"""
    if "data" not in _CACHE:
        data = {}
        for path in CANDIDATES:
            try:
                path = Path(path)
                if path.is_file():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    break
            except (OSError, ValueError):
                continue
        _CACHE["data"] = data if isinstance(data, dict) else {}
    return _CACHE["data"]


def _split(text):
    """「术语：解释」切分，规则与 kaodian.py 一致（但不依赖该模块）。"""
    parts = _TERM_SPLIT.split(text, maxsplit=1)
    if len(parts) == 2:
        head, tail = parts[0].strip(), parts[1].strip()
        if 1 <= len(head) <= 16 and _HAN.search(head):
            return head, tail
    return "", text.strip()


def _chapter_matches(no, title, wanted):
    if isinstance(wanted, str) and wanted == title:
        return True
    return str(no) == str(wanted)


def _iter_raw(book=None, chapter=None):
    """遍历原始条目，产出 (book, chapter_no, chapter_title, section_name, entry)。

    任何一层结构不对都直接跳过，保证脏数据不会让整个转换崩溃。
    """
    for bk, chapters in _raw().items():
        if not isinstance(chapters, list):
            continue
        if book is not None and bk != book:
            continue
        for chapter_data in chapters:
            if not isinstance(chapter_data, dict):
                continue
            no = chapter_data.get("no")
            title = chapter_data.get("title") or ("第%s章" % no)
            if chapter is not None and not _chapter_matches(no, title, chapter):
                continue
            sections = chapter_data.get("sections")
            if not isinstance(sections, list):
                continue
            for section in sections:
                if not isinstance(section, dict):
                    continue
                name = section.get("name", "")
                items = section.get("items")
                if not isinstance(items, list):
                    continue
                for entry in items:
                    yield bk, no, title, name, entry


def _normalize(book, no, title, section, entry):
    """返回 (point, reason)；point 带来源信息，reason 非 None 表示应跳过。"""
    if not isinstance(entry, dict):
        return None, R_BAD_TEXT
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        return None, R_BAD_TEXT
    term, explanation = _split(text)
    if not term:
        return None, R_NO_TERM
    if len(explanation) < MIN_EXPLANATION_LENGTH:
        return None, R_SHORT
    point = {"term": term, "explanation": explanation,
             "book": book, "chapter": no, "title": title,
             "section": section, "no": entry.get("no"), "text": text.strip()}
    return point, None


def _collect(book=None, chapter=None):
    """产出通过规范化（字段合法、解释够长）的富信息考点。"""
    points = []
    for bk, no, title, section, entry in _iter_raw(book, chapter):
        point, reason = _normalize(bk, no, title, section, entry)
        if reason is None:
            points.append(point)
    return points


def load_points(book=None, chapter=None):
    """从 kaodian.json 读考点并规范化为 {term, explanation, book, chapter}。

    字段缺失、非字符串、空解释等脏数据一律跳过，不会抛异常。
    """
    return [{key: point[key] for key in ("term", "explanation", "book", "chapter")}
            for point in _collect(book, chapter)]


# ---------------- 题目生成 ----------------

def _clauses(explanation):
    """按标点切出原文片段；只保留够长的，最多取 POINT_COUNT 条。"""
    parts = [part.strip() for part in _CLAUSE_SPLIT.split(explanation)]
    kept = [part for part in parts if len(part) >= MIN_CLAUSE_LENGTH]
    return kept[:POINT_COUNT]


def _clean_distractors(point, clauses, distractors):
    """干扰项去重：排除空值、术语自身、与任一要点原文相同的项。"""
    banned = set(clauses) | {point.get("term")}
    seen = set()
    cleaned = []
    for item in distractors or []:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if not value or value in banned or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
        if len(cleaned) >= DISTRACTOR_COUNT:
            break
    return cleaned


def _digest(*parts):
    text = "|".join(str(part) for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _evaluate(point, distractors):
    """返回 (question, reason)；失败时 question 为 None。"""
    clauses = _clauses(point["explanation"])
    if len(clauses) < POINT_COUNT:
        return None, R_FEW_POINTS
    options = _clean_distractors(point, clauses, distractors)
    if len(options) < DISTRACTOR_COUNT:
        return None, R_FEW_DISTRACTORS

    concept = "kdc-" + _digest(point.get("book"), point.get("chapter"), point["term"])[:12]
    question_id = "kdq-" + _digest(point.get("book"), point.get("chapter"),
                                   point["term"], "||".join(clauses))[:12]
    out_points = []
    for index, clause in enumerate(clauses):
        # 正确选项的位置由原文摘要决定：同一条考点每次生成结果一致，又不会全落在 A。
        slot = int(_digest(point["term"], clause)[:8], 16) % (DISTRACTOR_COUNT + 1)
        four = list(options)          # options 是 3 个干扰项
        four.insert(slot, clause)     # 插入正确项，凑成 4 选 1
        out_points.append({
            "label": POINT_LABELS[index],
            "expected": clause,
            "correct": clause,
            "options": four,
            "reason": point["explanation"],
            "category": CATEGORY,
        })

    question = {
        "id": question_id,
        "concept": concept,
        "kind": "diagnostic",
        "prompt": "「%s」的教材原文要点：下面每个要点中，哪一项是原文的准确表述？" % point["term"],
        "points": out_points,
        "book": point.get("book"),
        "chapter": point.get("chapter"),
        "source": {"term": point["term"], "explanation": point["explanation"],
                   "no": point.get("no"), "section": point.get("section"),
                   "text": point.get("text")},
    }
    return question, None


def as_diagnostic(point, distractors):
    """把一个「术语：解释」考点转成三要点诊断题。

    干扰项应传入同章其它考点的术语；不足或原文切不出 3 个要点时抛 ValueError。
    """
    if not isinstance(point, dict):
        raise ValueError("考点必须是对象")
    if not isinstance(point.get("term"), str) or not isinstance(point.get("explanation"), str):
        raise ValueError("考点缺少 term/explanation")
    question, reason = _evaluate(point, distractors)
    if question is None:
        raise ValueError("该考点无法生成诊断题：%s" % reason)
    return question


def build_questions(book=None, chapter=None, limit=None):
    """批量转换；解释太短 / 切不出 3 要点 / 干扰项不够的考点直接跳过。"""
    groups = {}
    for point in _collect(book, chapter):
        groups.setdefault((point["book"], point["chapter"]), []).append(point)

    out = []
    for (_book, _chapter), items in groups.items():
        terms = [item["term"] for item in items]
        for point in items:
            distractors = [term for term in terms if term != point["term"]]
            question, reason = _evaluate(point, distractors)
            if question is not None:
                out.append(question)
                if limit is not None and len(out) >= limit:
                    return out[:limit]
    return out if limit is None else out[:limit]


# ---------------- 统计 ----------------

def catalog():
    """按书/章统计可成题考点数与跳过原因；用于评估覆盖面和降级情况。"""
    result = {}
    points_by_chapter = {}
    for bk, no, title, section, entry in _iter_raw():
        book_stat = result.setdefault(bk, {"total": 0, "eligible": 0,
                                           "skipped": {}, "chapters": {}})
        chapter_stat = book_stat["chapters"].setdefault(
            no, {"no": no, "title": title, "total": 0, "eligible": 0, "skipped": {}})

        point, reason = _normalize(bk, no, title, section, entry)
        book_stat["total"] += 1
        chapter_stat["total"] += 1
        if reason is not None:
            book_stat["skipped"][reason] = book_stat["skipped"].get(reason, 0) + 1
            chapter_stat["skipped"][reason] = chapter_stat["skipped"].get(reason, 0) + 1
            continue
        points_by_chapter.setdefault((bk, no), []).append(point)

    for (bk, no), points in points_by_chapter.items():
        chapter_stat = result[bk]["chapters"][no]
        terms = [point["term"] for point in points]
        for point in points:
            peers = [term for term in terms if term != point["term"]]
            question, reason = _evaluate(point, peers)
            if question is None:
                result[bk]["skipped"][reason] = result[bk]["skipped"].get(reason, 0) + 1
                chapter_stat["skipped"][reason] = chapter_stat["skipped"].get(reason, 0) + 1
            else:
                result[bk]["eligible"] += 1
                chapter_stat["eligible"] += 1

    for book_stat in result.values():
        book_stat["chapters"] = list(book_stat["chapters"].values())
    return result
