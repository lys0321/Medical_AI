# -*- coding: utf-8 -*-
"""教材精练域：按「教材 → 章节」出原文单选题，并判分给出原句。

和知识点练习（task/answer）分开：这里不做掌握度判定，只做「读完这一章，
随手考自己一下」，所以记录成 drill 事件，不影响知识点掌握结论。
"""
import secrets
import time

import kaodian
from api.core import InputError, event, state_get, state_save


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