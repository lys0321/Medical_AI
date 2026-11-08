"""作答域：三要点选择题判分与自由文本逐要点判分。"""
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
from api.research import _check_research_privacy
from api.task import tutor_context
from api.core import InputError, connect, state_get, state_save, event, LOCK

def grade(db, learner, body):
    token = body.get("token")
    existing = db.execute("SELECT payload FROM attempts WHERE learner=? AND token=?", (learner, token)).fetchone()
    if existing:
        return json.loads(existing[0])
    state = state_get(db, learner)
    active = state.get("active")
    if not active or token != active["token"]:
        raise InputError("这道题已切换，请刷新后继续当前任务")
    answers = body.get("answers")
    if not isinstance(answers, list) or len(answers) != 3 or any(not isinstance(a, str) or a not in opts for a, opts in zip(answers, active["options"])):
        raise InputError("请完成三个要点的选择；不会时可以选暂时不确定")
    confidence = body.get("confidence", "未填写")
    if confidence not in ("未填写", "不确定", "一般", "很有把握"):
        raise InputError("未知信心选项")
    reasoning = body.get("reasoning", "")
    if not isinstance(reasoning, str) or len(reasoning) > 3000:
        raise InputError("补充推理须为不超过3000字的文字")
    _check_research_privacy(reasoning, "补充推理")
    c, q = QUESTION_MAP[active["question"]]
    rubric = [{"label": p["label"], "selected": a, "correct": a == p["correct"], "expected": p["correct"], "reason": p["reason"], "category": p["category"]} for a, p in zip(answers, q["points"])]
    score = sum(p["correct"] for p in rubric) / len(rubric)
    if score == 0:
        action, label, why = "study", "先补回基础，再试一次", "三个关键要点尚未获得作答证据，先拆开结构、功能和表现。"
    elif score < .8:
        action, label, why = "followup", "补上缺失环节，再做迁移题", "已有部分理解；缺失要点会决定本次补学的重点。"
    elif q["kind"] == "diagnostic":
        action, label, why = "transfer", "换个情境，验证能否迁移", "这道题已达标，但单题正确还不足以判定掌握。"
    else:
        action, label, why = "next", "查看学习结果与下一知识点", "迁移题已达标；掌握判断还会检查不同题目与最近表现。"
    result = {"concept": c["id"], "question": q["id"], "kind": q["kind"], "score": round(score * 100), "rubric": rubric,
              "action": action, "label": label, "why": why, "confidence": confidence,
              "confidence_source": "omitted" if confidence == "未填写" else "self_reported",
              "calibration": "信心与表现有差异，建议回看推理依据。" if confidence == "很有把握" and score < .8 else "",
              "reasoning": reasoning.strip(), "grading": "结构化要点评分；补充推理仅记录，未自动评分"}
    result['hinted_points'] = sorted(int(i) for i in active.get('hints', {}))
    result['tutor_token'] = token
    result['dialogue_assisted'] = bool(active.get('tutor_assisted'))
    result['text_assisted'] = bool(active.get('text_assisted'))
    result['assisted'] = bool(result['hinted_points']) or result['dialogue_assisted'] or result['text_assisted']
    if result['assisted']:
        result['why'] += ' 本次使用过提示、教学对话或自由文本判分，分数属于辅助练习；请再独立作答验证掌握。'
    db.execute("INSERT INTO attempts(learner,token,concept,question,kind,score,payload,created) VALUES(?,?,?,?,?,?,?,?)", (learner, token, c["id"], q["id"], q["kind"], score, json.dumps(result, ensure_ascii=False), time.time()))
    state.update(active=None, last_result=result)
    state_save(db, learner, state)
    event(db, learner, "decision", c["id"], {"action": action, "why": why})
    return result


def answer_text(learner, body):
    """Judge a free-text answer point by point; stored apart from structured scores."""
    token, answer = body.get('token'), body.get('answer')
    if not isinstance(answer, str) or not 2 <= len(answer.strip()) <= 3000:
        raise InputError('请输入2–3000字的自由文本作答')
    answer = answer.strip()
    _check_research_privacy(answer, '自由文本作答')
    with LOCK, connect() as db:
        c, q, completed = tutor_context(db, learner, token)
        if not completed:
            # Seeing per-point feedback before choosing makes the later choice answer assisted.
            state = state_get(db, learner)
            state['active']['text_assisted'] = True
            state_save(db, learner, state)
    try:
        judge = tutor_model.grader()
    except Exception:
        judge = None
    judged = text_grading.grade(q, answer, text_excerpts(c, q), judge)
    with LOCK, connect() as db:
        tutor_context(db, learner, token)
        record = {'concept': c['id'], 'question': q['id'], 'kind': q['kind'], 'answer': answer, **judged}
        db.execute('INSERT INTO text_attempts(learner,token,concept,question,payload,created) VALUES(?,?,?,?,?,?)',
                   (learner, token, c['id'], q['id'], json.dumps(record, ensure_ascii=False), time.time()))
        event(db, learner, 'text-answer', c['id'], {'question': q['id'], 'scorer': judged['scorer']})
    return {'token': token, 'concept': c['id'], 'question': q['id'], 'kind': q['kind'], **judged}


def text_excerpts(c, q):
    """Only the authored learning card and matching local textbook passages are given to the judge."""
    out = [{'id': 'note-' + c['id'], 'kind': 'learning_card', 'text': c['note']}]
    try:
        hits = textbook.search(q['prompt'] + ' ' + ' '.join(p['correct'] for p in q['points']))
    except Exception:
        hits = []
    return out + [{'id': h['id'], 'kind': 'textbook', 'book': h['book'], 'page': h['page'], 'text': h['text'][:1200]}
                  for h in hits]
