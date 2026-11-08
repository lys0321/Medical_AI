"""任务域：出题、恢复、提示与多轮辅导。"""
import argparse
import collections
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import random
import re
import secrets
import shutil
import sqlite3
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime

from knowledge import CONCEPTS, CONCEPT_MAP, QUESTION_MAP, SOURCES, COURSE
import textbook
import materials
import pages
from tutoring import hint_text, page_hint_text
from planning import build_plan, SHANGHAI
from reporting import build_report_evidence
from reading import build_reading
from research_query import build_query_proposal
import tutor_chat
import tutor_model
import text_grading
import citations
import evidence
import pmc
import histology_quiz
import vision

from api.core import InputError, connect, state_get, state_save, event
from api.core import InputError, connect, state_get, state_save, event, LOCK, TUTOR_LOCKS

_PAGE_HINT_CACHE = {}


def _page_hits(concept, question, index):
    """某个要点在教材里的出处（书 + 印刷页码 + 这一页讲了什么 + 原句）。

    以前提示给的是「分析思路」，学生反馈对记忆型知识点没用；改成回书核对。
    页码优先取 pages.py 里人工校对过的表：检索出来的常常是解剖操作步骤，而且
    同一知识点的三个要点会全部命中同一页。表里没有该页原文时才回落到检索，
    两者都取不到就如实说没有，绝不编页。

    三个要点轮转取不同的页，避免整道题都指向同一处。
    """
    key = (concept["id"], question["id"], index)
    if key in _PAGE_HINT_CACHE:
        return _PAGE_HINT_CACHE[key]

    entries = pages.curated(concept["id"])
    if entries:
        count = len(entries)
        ordered = [entries[(index + step) % count] for step in range(count)]
        hits = []
        for entry in ordered:
            try:
                text = textbook.page_text(entry["book"], entry["page"])
            except Exception:
                text = ""
            if entry["anchor"] not in text:
                continue
            hits.append({"book": entry["book"], "page": entry["page"],
                         "label": entry["label"],
                         "snippet": textbook.snippet(text, entry["anchor"], 42)})
        if hits:
            _PAGE_HINT_CACHE[key] = hits
            return hits

    terms = concept.get("terms") or []
    core = terms[0] if terms else concept["name"]
    hits = []
    for query in ["%s %s %s" % (concept["name"], " ".join(terms), question["points"][index]["label"]),
                  "%s %s" % (concept["name"], " ".join(terms)),
                  " ".join(terms)]:
        try:
            found = textbook.related(query, require=core, top_k=2)
        except Exception:
            found = []
        if found:
            hits = [{"book": h["book"], "page": h["page"], "label": "",
                     "snippet": textbook.snippet(h["text"], core, 42)} for h in found]
            break
    _PAGE_HINT_CACHE[key] = hits
    return hits


def public_active(active):
    if not active:
        return None
    c, q = QUESTION_MAP[active["question"]]
    return {"token": active["token"], "concept": c["id"], "kind": q["kind"], "prompt": q["prompt"],
            "points": [{"label": p["label"], "options": opts,
                        "hints": [page_hint_text(c, q, i, step, _page_hits)
                                  for step in range(1, active.get("hints", {}).get(str(i), 0) + 1)]}
                       for i, (p, opts) in enumerate(zip(q["points"], active["options"]))]}


def make_task(db, learner, cid, kind="auto"):
    c = CONCEPT_MAP.get(cid)
    if c is None:
        raise InputError("未知知识点")
    state = state_get(db, learner)
    if kind == "refresh":
        # 「换一题」：同一知识点换另一种题型，且不能还是刚才那道。
        rows = db.execute("SELECT question,kind,score FROM attempts WHERE learner=? AND concept=? ORDER BY id", (learner, cid)).fetchall()
        previous = (state.get("active") or {}).get("question") or (rows[-1]["question"] if rows else "")
        state.update(active=None)
        state_save(db, learner, state)
        others = [q for q in c["questions"] if q["id"] != previous]
        question = others[0] if others else c["questions"][0]
        kind = question["kind"]
    else:
        if state.get("active") and state["active"]["concept"] == cid and kind == "auto":
            return public_active(state["active"])
        rows = db.execute("SELECT question,kind,score FROM attempts WHERE learner=? AND concept=? ORDER BY id", (learner, cid)).fetchall()
        if kind not in ("auto", "diagnostic", "transfer"):
            raise InputError("未知测试模式")
        if kind == "auto":
            kind = "transfer" if rows and rows[-1]["kind"] == "diagnostic" and rows[-1]["score"] >= .8 else "diagnostic"
    q = next(q for q in c["questions"] if q["kind"] == kind)
    options = []
    for p in q["points"]:
        opts = p["options"][:-1].copy()
        random.SystemRandom().shuffle(opts)
        options.append(opts + ["暂时不确定"])
    active = {"token": secrets.token_hex(16), "concept": cid, "question": q["id"], "options": options}
    state.update(concept=cid, active=active)
    state_save(db, learner, state)
    event(db, learner, "task", cid, {"question": q["id"]})
    return public_active(active)


def request_hint(db, learner, body):
    state = state_get(db, learner)
    active = state.get('active')
    if not active or active['token'] != body.get('token'):
        raise InputError('这道题已切换，请回到当前学习任务')
    index, level = body.get('point'), body.get('level')
    if type(index) is not int or not 0 <= index < 3 or type(level) is not int or level not in (1, 2):
        raise InputError('请选择有效的要点与提示步骤')
    concept, question = QUESTION_MAP[active['question']]
    hints = active.setdefault('hints', {})
    previous = hints.get(str(index), 0)
    if level > previous + 1:
        raise InputError('请先查看第一处教材出处')
    if level > previous:
        hints[str(index)] = level
        state_save(db, learner, state)
        event(db, learner, 'hint', active['concept'], {'point': index, 'level': level})
    return {'point': index, 'level': level, 'text': page_hint_text(concept, question, index, level, _page_hits),
            'notice': '出处来自本地教材索引（%d 段原文），页码为印刷页码，请回书核对原句；'
                      '看过提示的要点计为辅助练习，不能作为独立掌握证据。' % textbook.status()['loaded']}


def tutor_context(db, learner, token):
    if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{32}', token):
        raise InputError('请选择当前练习后再开始教学对话')
    state = state_get(db, learner)
    active = state.get('active')
    if active and active['token'] == token:
        c, q = QUESTION_MAP[active['question']]
        return c, q, False
    attempt = db.execute('SELECT question FROM attempts WHERE learner=? AND token=?', (learner, token)).fetchone()
    if attempt:
        c, q = QUESTION_MAP[attempt['question']]
        return c, q, True
    raise InputError('这道题已切换或记录已清理，请打开当前练习')


def tutor_messages(db, learner, token):
    row = db.execute('SELECT payload FROM tutor_conversations WHERE learner=? AND token=?', (learner, token)).fetchone()
    return json.loads(row[0]) if row else []


def tutor_snapshot(db, learner, token, provider=None):
    c, _, completed = tutor_context(db, learner, token)
    messages = tutor_messages(db, learner, token)
    return {'token': token, 'concept': c['id'], 'name': c['name'], 'completed': completed,
            'messages': messages, 'remaining': max(0, 12 - len(messages)//2),
            'provider': provider or tutor_model.status()}


def tutor_turn(learner, body):
    token, message, request_id = body.get('token'), body.get('message'), body.get('request_id')
    if not isinstance(message, str) or not 2 <= len(message.strip()) <= 1000:
        raise InputError('请输入2–1000字的想法或疑问')
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id):
        raise InputError('对话请求编号无效，请刷新重试')
    if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{32}', token):
        raise InputError('请选择当前练习后再开始教学对话')
    message = message.strip()
    # Network generation never holds the global learning/SQLite lock. A bounded
    # striped lock serializes a session and makes uncertain client retries safe.
    index = int(hashlib.sha256((learner + token).encode()).hexdigest()[:8], 16) % len(TUTOR_LOCKS)
    with TUTOR_LOCKS[index]:
        with LOCK, connect() as db:
            c, q, completed = tutor_context(db, learner, token)
            messages = tutor_messages(db, learner, token)
            prior = next((m for m in messages if m.get('request_id') == request_id), None)
            if prior:
                if prior['content'] != message:
                    raise InputError('同一请求编号不能用于不同问题')
                return tutor_snapshot(db, learner, token)
            if len(messages) >= 24:
                raise InputError('本题已完成12轮对话，请独立复测或开启下一题')
            if not completed:
                state = state_get(db, learner)
                state['active']['tutor_assisted'] = True
                state_save(db, learner, state)
        history = [{'role': m['role'], 'content': m['content'],
                    **({'follow_up': m['follow_up']} if m['role'] == 'assistant' and isinstance(m.get('follow_up'), str) else {})}
                   for m in messages]
        history.append({'role': 'user', 'content': message})
        generated = tutor_chat.reply(c, q, history, completed=completed, generate=tutor_model.generator())
        source = SOURCES[c['source']]
        citations = [{**s, 'title': 'MedNexus 自编学习卡 · ' + c['name'],
                      'url': source['url'], 'provenance': '自编教学摘要，非教材原文；无可核对书页'}
                     for s in generated.get('sources', [])]
        answer = {'role': 'assistant', 'content': generated['message'], 'follow_up': generated['follow_up'],
                  'mode': generated['mode'], 'sources': citations, 'warning': generated.get('warning', '')}
        with LOCK, connect() as db:
            # Recheck after generation: reset or a switched, unsubmitted task must
            # not be recreated by a late response.
            tutor_context(db, learner, token)
            messages.extend([{'role': 'user', 'content': message, 'request_id': request_id}, answer])
            db.execute('INSERT OR REPLACE INTO tutor_conversations VALUES(?,?,?)',
                       (learner, token, json.dumps(messages, ensure_ascii=False)))
            event(db, learner, 'tutor-turn', c['id'], {'mode': generated['mode']})
            return tutor_snapshot(db, learner, token)
