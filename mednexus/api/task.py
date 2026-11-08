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
from tutoring import hint_text
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

def public_active(active):
    if not active:
        return None
    c, q = QUESTION_MAP[active["question"]]
    return {"token": active["token"], "concept": c["id"], "kind": q["kind"], "prompt": q["prompt"],
            "points": [{"label": p["label"], "options": opts,
                        "hints": [hint_text(q, i, step) for step in range(1, active.get("hints", {}).get(str(i), 0) + 1)]}
                       for i, (p, opts) in enumerate(zip(q["points"], active["options"]))]}


def make_task(db, learner, cid, kind="auto"):
    c = CONCEPT_MAP.get(cid)
    if c is None:
        raise InputError("未知知识点")
    state = state_get(db, learner)
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
    _, question = QUESTION_MAP[active['question']]
    hints = active.setdefault('hints', {})
    previous = hints.get(str(index), 0)
    if level > previous + 1:
        raise InputError('请先查看第一步思路提示')
    if level > previous:
        hints[str(index)] = level
        state_save(db, learner, state)
        event(db, learner, 'hint', active['concept'], {'point': index, 'level': level})
    return {'point': index, 'level': level, 'text': hint_text(question, index, level),
            'notice': '提示只提供分析思路；本次作答计为辅助练习，不能作为独立掌握证据。'}


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
