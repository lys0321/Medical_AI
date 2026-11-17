# -*- coding: utf-8 -*-
"""教材精练域：按「教材 → 章节」出原文单选题，并判分给出原句。

和知识点练习（task/answer）分开：这里不做掌握度判定，只做「读完这一章，
随手考自己一下」，所以记录成 drill 事件，不影响知识点掌握结论。
"""
import random
import secrets
import time

import kaodian
import kaodian_drill
from api.core import InputError, event, state_get, state_save

_TRIPLE_CACHE = None


def _triple_questions():
    """把考点库转成三要点题，进程内缓存一次；失败返回空列表而非崩溃。"""
    global _TRIPLE_CACHE
    if _TRIPLE_CACHE is None:
        try:
            _TRIPLE_CACHE = kaodian_drill.build_questions()
        except Exception:
            _TRIPLE_CACHE = []
    return list(_TRIPLE_CACHE)


def catalog():
    if not kaodian.available():
        return {"available": False, "books": [],
                "message": "本机还没有考点题库，先运行 tools/build_kaodian.py 生成 kaodian.json"}
    return {"available": True, "books": kaodian.catalog()}


def _public(task, token):
    return {"token": token, "book": task["book"], "chapter": task["chapter"],
            "kind": task["kind"], "prompt": task["prompt"], "options": task["options"]}


def make_task(db, learner, body):
    book, chapter = body.get("book"), body.get("chapter")
    if not isinstance(book, str) or not book:
        raise InputError("请先选择教材")
    if type(chapter) is not int:
        raise InputError("请先选择章节")
    state = state_get(db, learner)
    previous = state.get("drill") or {}
    task = None
    for _ in range(4):
        try:
            task = kaodian.build(book, chapter)
        except ValueError as exc:
            raise InputError(str(exc))
        if task["source"]["no"] != (previous.get("source") or {}).get("no"):
            break
    token = secrets.token_hex(16)
    state["drill"] = {"token": token, **task, "created": time.time()}
    state_save(db, learner, state)
    event(db, learner, "drill", book, {"chapter": chapter, "no": task["source"]["no"], "kind": task["kind"]})
    return _public(task, token)


def answer(db, learner, body):
    token, choice = body.get("token"), body.get("choice")
    if not isinstance(token, str) or not token:
        raise InputError("这道题已切换，请重新出一道")
    if not isinstance(choice, str):
        raise InputError("请选择一个选项")
    state = state_get(db, learner)
    task = state.get("drill")
    if not task or task.get("token") != token:
        raise InputError("这道题已切换，请重新出一道")
    try:
        result = kaodian.grade(task, choice)
    except ValueError as exc:
        raise InputError(str(exc))
    state["drill"] = None
    state["last_drill"] = result
    state_save(db, learner, state)
    event(db, learner, "drill-answer", task["book"],
          {"chapter": task["chapter"], "no": task["source"]["no"], "score": result["score"]})
    return result


# ---- 三要点原文自测（把 940 条考点并入三要点结构，但明确不计入掌握度） ----
# 与单选 drill 分开放在 state['triple_drill']，互不覆盖；事件单独记为 triple-*。

def triple_catalog():
    """按教材/章列出可转三要点题的考点数量；数据缺失时安全降级。"""
    try:
        stats = kaodian_drill.catalog()
    except Exception:
        return {"available": False, "books": [], "message": "考点题库暂不可用"}
    return {"available": True, "books": stats,
            "notice": "由考点原文自动转成的三要点自测，仅供对照原文自测，不计入掌握度，也未作学习效果验证。"}


def triple_task(db, learner, body):
    book, chapter = body.get("book"), body.get("book_chapter")
    # chapter 同时兼容整数字号或标题字符串
    wanted = body.get("chapter", chapter)
    pool = _triple_questions()
    if book is not None:
        pool = [q for q in pool if q.get("book") == book]
    if isinstance(wanted, int):
        pool = [q for q in pool if q.get("chapter") == wanted]
    elif isinstance(wanted, str) and wanted:
        pool = [q for q in pool if str(q.get("chapter")) == wanted or wanted in str(q.get("source", {}).get("section", ""))]
    if not pool:
        raise InputError("这一范围暂时凑不出合格的三要点自测题（要点不足或缺少可核对原文）")
    state = state_get(db, learner)
    previous = (state.get("triple_drill") or {}).get("id")
    candidates = [q for q in pool if q["id"] != previous] or pool
    question = random.SystemRandom().choice(candidates)

    rng = random.SystemRandom()
    options = []
    for point in question["points"]:
        opts = list(point["options"])
        rng.shuffle(opts)
        options.append(opts)
    token = secrets.token_hex(16)
    state["triple_drill"] = {"token": token, "id": question["id"], "question": question,
                             "options": options, "created": time.time()}
    state_save(db, learner, state)
    event(db, learner, "triple-task", question.get("book") or "考点",
          {"chapter": question.get("chapter"), "qid": question["id"]})
    return {"token": token, "book": question.get("book"), "chapter": question.get("chapter"),
            "kind": "triple", "prompt": question["prompt"],
            "term": question.get("source", {}).get("term"),
            "points": [{"label": p["label"]} for p in question["points"]],
            "options": options,
            "notice": "每题三个要点选自同一条考点原文；答案可回书核对。自测不计入掌握度。"}


def triple_answer(db, learner, body):
    token, answers = body.get("token"), body.get("answers")
    if not isinstance(token, str) or not token:
        raise InputError("这道题已切换，请重新出一道")
    if not isinstance(answers, list) or len(answers) != 3:
        raise InputError("请完成三个要点的选择")
    state = state_get(db, learner)
    task = state.get("triple_drill")
    if not task or task.get("token") != token:
        raise InputError("这道题已切换，请重新出一道")
    options = task.get("options") or []
    if any(not isinstance(a, str) or a not in opts for a, opts in zip(answers, options)):
        raise InputError("请从给定选项中选择")
    question = task["question"]
    points = question["points"]
    rubric = [{"label": p["label"], "selected": a, "correct": a == p["correct"],
               "expected": p["correct"], "reason": p.get("reason", ""),
               "category": p.get("category")}
              for a, p in zip(answers, points)]
    right = sum(1 for r in rubric if r["correct"])
    result = {"book": question.get("book"), "chapter": question.get("chapter"),
              "kind": "triple", "rubric": rubric, "correct": right,
              "score": round(right / 3 * 100),
              "source": question.get("source"),
              "mastery_counted": False,
              "notice": "自测成绩仅供对照原文，不计入掌握度或迁移判定；选项与答案均摘自考点原文。"}
    state["triple_drill"] = None
    state["last_triple"] = result
    state_save(db, learner, state)
    event(db, learner, "triple-answer", question.get("book") or "考点",
          {"chapter": question.get("chapter"), "score": result["score"], "qid": question.get("id")})
    return result