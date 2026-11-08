"""报告域：快照、学习报告、导出与首页总览。"""
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

from api.ask import ask
from api.core import InputError, state_get, attempts_get, progress, recommend
from api.research import pubmed
from api.study import textbook_sources, all_sources, image_stats, image_quiz
from api.task import public_active
from api.core import InputError, state_get, attempts_get, progress, recommend, API_KEY, MODEL

def snapshot(db, learner):
    items = progress(db, learner)
    state = state_get(db, learner)
    counts = collections.Counter(i["status"] for i in items)
    return {"course": COURSE, "concepts": items, "recommendation": recommend(items), "active": public_active(state.get("active")),
            "last_result": state.get("last_result"), "current": state.get("concept", "oculomotor"),
            "stats": {"mastered": counts["已掌握"], "weak": counts["需巩固"], "assessed": sum(i["attempts"] > 0 for i in items), "viewed": sum(i["viewed"] for i in items), "attempts": sum(i["attempts"] for i in items), "total": len(items)},
            "model": {"configured": bool(API_KEY), "name": MODEL if API_KEY else "本地规则引擎", "note": "评分和任务决策由可解释规则控制；接入模型后仅用于证据内辅导。"},
            "sources": [{k: v for k, v in s.items() if k != "text"} for s in all_sources(db, learner)]}


def report(db, learner):
    snap = snapshot(db, learner)
    rows = attempts_get(db, learner)
    errors = collections.Counter()
    for a in rows:
        # 识图题没有三要点 rubric，不能把它的 payload 当成文本题解析。
        try:
            payload = json.loads(a["payload"])
        except (TypeError, ValueError):
            continue
        for p in payload.get("rubric", []) if isinstance(payload, dict) else []:
            if isinstance(p, dict) and p.get("correct") is False:
                errors[p.get("category", "未分类")] += 1
    text_rows = [a for a in rows if a["kind"] != "image"]
    events = [dict(r) for r in db.execute("SELECT kind,concept,payload,created FROM events WHERE learner=? ORDER BY id DESC LIMIT 50", (learner,))]
    return {**snap, "errors": dict(errors), "history": [{"id": a["id"], "concept": a["concept"], "kind": a["kind"], "score": round(a["score"] * 100), "created": a["created"], "result": json.loads(a["payload"])} for a in text_rows], "events": events,
            "evidence_report": build_report_evidence(text_rows, QUESTION_MAP),
            "method": "要点等权计分；EMA=0.4×旧值+0.6×本次得分（首次为本次值）。掌握需两个不同题目独立达标、包含迁移题、最近两次均独立≥80%且EMA≥80%。提示作答属于辅助练习，看过不算掌握；组胚识图题单独统计，不计入这里。此规则是原型设计，未作学习效果验证。"}


def export_learning(db, learner):
    """Export an allowlisted learning summary, never the live state or sources."""
    current = report(db, learner)
    summary = {key: current[key] for key in
               ("course", "concepts", "stats", "recommendation", "errors", "method")}
    summary["history"] = []
    for attempt in current["history"]:
        result = attempt["result"]
        summary["history"].append({
            **{key: attempt[key] for key in ("concept", "kind", "score", "created")},
            "question": result["question"], "confidence": result["confidence"],
            "confidence_source": result.get("confidence_source", "legacy_default"),
            "assisted": result.get("assisted", False), "hinted_points": result.get("hinted_points", []),
            "dialogue_assisted": result.get("dialogue_assisted", False),
            "text_assisted": result.get("text_assisted", False),
            "rubric": [{key: point[key] for key in
                        ("label", "selected", "correct", "expected", "reason", "category")}
                       for point in result["rubric"]],
        })
    return {"version": 2, "scope": "learning_summary", "exported_at": time.time(),
            "excluded": ["身份标识与任务令牌", "教材索引与原文", "自由提问、教学对话、补充推理与自由文本作答", "浏览器速记记录"],
            "notice": "仅供归档的学习摘要，不能用于恢复学习身份或导入学习历史。结构化作答仍属于个人学习记录，请自行保管。",
            "report": summary}


def reset_learning(db, learner, body):
    """Delete only this learner's selected data after a matching confirmation."""
    scope = body.get("scope", "learning")
    if scope not in ("learning", "all"):
        raise InputError("清理范围必须为 learning 或 all")
    confirmation = "CLEAR_MY_DATA" if scope == "all" else "CLEAR_MY_LEARNING"
    if body.get("confirmation") != confirmation:
        raise InputError("清空需明确确认对应的数据范围")
    deleted = {"attempts": 0, "events": 0, "learners": 0, "sources": 0, "tutor_conversations": 0, "text_attempts": 0}
    for table in ("attempts", "events", "tutor_conversations", "text_attempts") + (("sources",) if scope == "all" else ()):
        deleted[table] = db.execute(f"DELETE FROM {table} WHERE learner=?", (learner,)).rowcount
    deleted["learners"] = db.execute("DELETE FROM learners WHERE id=?", (learner,)).rowcount
    remaining = db.execute("SELECT COUNT(*) FROM sources WHERE learner=?", (learner,)).fetchone()[0]
    return {"ok": True, "scope": scope, "deleted": deleted, "remaining_sources": remaining}


def _book_stats(db, learner):
    """教材来源按书汇总：段落数、页码范围。"""
    books = {}
    imports = [json.loads(row[0]) for row in db.execute(
        "SELECT payload FROM sources WHERE learner=?", (learner,))]
    for s in textbook_sources() + imports:
        if s.get("kind") not in ("textbook", "local", "metadata") or not s.get("book"):
            continue
        b = books.setdefault(s["book"], {"book": s["book"], "chunks": 0, "min": 10 ** 6, "max": 0})
        b["chunks"] += 1
        if isinstance(s.get("page"), int):
            b["min"] = min(b["min"], s["page"])
            b["max"] = max(b["max"], s["page"])
    out = []
    for b in books.values():
        if b["min"] == 10 ** 6:
            b["min"] = 0
        out.append(b)
    out.sort(key=lambda x: -x["chunks"])
    return out


def _recent(db, learner, limit=20):
    rows = db.execute("SELECT created,payload FROM events WHERE learner=? AND kind='ask' ORDER BY id DESC LIMIT ?",
                      (learner, limit)).fetchall()
    out = []
    for created, payload in rows:
        try:
            p = json.loads(payload)
        except Exception:
            p = {}
        out.append({"ts": created, "time": time.strftime("%m-%d %H:%M", time.localtime(created)),
                    "query": p.get("query", ""), "book": p.get("book", ""), "page": p.get("page", 0) or 0,
                    "mode": "教材检索", "cited_ok": bool(p.get("page"))})
    return out


def _weak(db, learner, limit=6):
    """反复提问的页段：按 ask 事件里的 book+page 十位分桶。"""
    rows = db.execute("SELECT payload FROM events WHERE learner=? AND kind='ask' ORDER BY id DESC LIMIT 200",
                      (learner,)).fetchall()
    counter = collections.Counter()
    for (payload,) in rows:
        try:
            p = json.loads(payload)
        except Exception:
            continue
        page, book = p.get("page"), p.get("book")
        if isinstance(page, int) and page > 0 and book:
            counter[(book, page // 10 * 10)] += 1
    out = []
    for (book, bucket), n in counter.most_common(limit):
        if n >= 2:
            out.append({"book": book, "page": bucket, "count": n})
    return out


def overview_payload(db, learner):
    snap = snapshot(db, learner)
    books = _book_stats(db, learner)
    now = time.time()
    local_date = datetime.fromtimestamp(now, SHANGHAI)
    day_start = local_date.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    ask_rows = db.execute("SELECT created,payload FROM events WHERE learner=? AND kind='ask'",
                          (learner,)).fetchall()
    cited = []
    for row in ask_rows:
        try:
            cited.append((row["created"], bool(json.loads(row["payload"]).get("page"))))
        except (ValueError, TypeError):
            cited.append((row["created"], False))
    week = [ok for created, ok in cited if now - 7 * 86400 <= created <= now]
    day = [ok for created, ok in cited if day_start <= created <= now]
    literature_week = db.execute(
        "SELECT COUNT(*) FROM events WHERE learner=? AND kind='literature' AND created BETWEEN ? AND ?",
        (learner, now - 7 * 86400, now)).fetchone()[0]
    literature_day = db.execute(
        "SELECT COUNT(*) FROM events WHERE learner=? AND kind='literature' AND created BETWEEN ? AND ?",
        (learner, day_start, now)).fetchone()[0]
    return {
        "course": snap["course"], "active": snap["active"],
        "day_date": local_date.strftime("%Y-%m-%d"),
        "questions": {"total": len(cited), "week": len(week), "week_cited": sum(week),
                      "day": len(day), "day_cited": sum(day)},
        "literature": {"week": literature_week, "day": literature_day},
        "books": books,
        "chunks": sum(b["chunks"] for b in books),
        "recent": _recent(db, learner),
        "weak": _weak(db, learner),
        "concepts": snap["concepts"],
        "recommendation": snap["recommendation"],
        "stats": snap["stats"],
        "learning_plan": build_plan(snap['concepts'], attempts_get(db, learner), snap['active']),
        "image_quiz": image_stats(db, learner),
        "status": {"llm": bool(API_KEY), "model": MODEL if API_KEY else "本地规则引擎",
                   "pubmed": True, "coverage_threshold": textbook.MIN_COVERAGE,
                   "textbook": textbook.status()["loaded"]},
    }
