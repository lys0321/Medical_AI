"""共享底座：路径、锁、SQLite 连接、学习状态读写。所有域模块只通过这里碰数据库。"""
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

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("MEDNEXUS_DB", str(ROOT / "data" / "learning.sqlite3")))
QUICK_NOTES_PATH = ROOT / "data" / "quick_notes_cards.json"
QUICK_NOTES_SOURCE = ROOT / "data" / "quick_notes_source.pdf"
LOCK = threading.RLock()
TUTOR_LOCKS = [threading.Lock() for _ in range(64)]
API_KEY = os.environ.get("MEDNEXUS_API_KEY", "")
MODEL = os.environ.get("MEDNEXUS_MODEL", "deepseek-chat")
BASE_URL = os.environ.get("MEDNEXUS_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
DEFAULT_LEARNER = hashlib.sha256(b"mednexus-local").hexdigest()[:48]
def is_private_ip(ip):
    """内网地址判断：10/8、172.16/12、192.168/16、127/8。"""
    try:
        parts = [int(x) for x in ip.split(".")]
    except ValueError:
        return False
    if len(parts) != 4:
        return False
    if parts[0] == 10 or parts[0] == 127:
        return True
    if parts[0] == 192 and parts[1] == 168:
        return True
    if parts[0] == 172 and 16 <= parts[1] <= 31:
        return True
    return False


class InputError(Exception):
    pass


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS learners(id TEXT PRIMARY KEY, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, learner TEXT, token TEXT UNIQUE,
          concept TEXT, question TEXT, kind TEXT, score REAL, payload TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, learner TEXT, kind TEXT, concept TEXT, payload TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS sources(learner TEXT, id TEXT, payload TEXT, PRIMARY KEY(learner,id));
        CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, payload TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS tutor_conversations(learner TEXT, token TEXT, payload TEXT NOT NULL,
          PRIMARY KEY(learner,token));
        CREATE TABLE IF NOT EXISTS text_attempts(id INTEGER PRIMARY KEY, learner TEXT, token TEXT,
          concept TEXT, question TEXT, payload TEXT NOT NULL, created REAL);
        CREATE TABLE IF NOT EXISTS fulltext(pmid TEXT PRIMARY KEY, pmcid TEXT, license TEXT,
          status TEXT, payload TEXT NOT NULL, created REAL);
        """)


def state_get(db, learner):
    row = db.execute("SELECT state FROM learners WHERE id=?", (learner,)).fetchone()
    return json.loads(row[0]) if row else {"concept": "oculomotor", "active": None}


def state_save(db, learner, state):
    db.execute("INSERT OR REPLACE INTO learners VALUES(?,?)", (learner, json.dumps(state, ensure_ascii=False)))


def event(db, learner, kind, cid="", payload=None):
    db.execute("INSERT INTO events(learner,kind,concept,payload,created) VALUES(?,?,?,?,?)", (learner, kind, cid, json.dumps(payload or {}, ensure_ascii=False), time.time()))


def attempts_get(db, learner):
    return [dict(r) for r in db.execute("SELECT * FROM attempts WHERE learner=? ORDER BY id", (learner,))]


def progress(db, learner):
    attempts = attempts_get(db, learner)
    views = {r[0] for r in db.execute("SELECT DISTINCT concept FROM events WHERE learner=? AND kind='study'", (learner,))}
    items = []
    for c in CONCEPTS:
        rows = [a for a in attempts if a["concept"] == c["id"]]
        ema = None
        for a in rows:
            ema = a["score"] if ema is None else .4 * ema + .6 * a["score"]
        latest = {}
        for a in rows:
            latest[a["question"]] = a
        independent = lambda a: not json.loads(a["payload"]).get("assisted", False)
        passed = [a for a in latest.values() if a["score"] >= .8 and independent(a)]
        mastered = (len(passed) >= 2 and any(a["kind"] == "transfer" for a in passed)
                    and len(rows) >= 2 and all(a["score"] >= .8 and independent(a) for a in rows[-2:]) and ema >= .8)
        status = "已掌握" if mastered else ("初步达标" if rows and rows[-1]["score"] >= .8 else ("需巩固" if rows else "未测评"))
        items.append({**{k: c[k] for k in ("id", "name", "unit", "level")}, "status": status, "score": round(ema * 100) if ema is not None else None,
                      "attempts": len(rows), "distinct": len(latest), "viewed": c["id"] in views,
                      "pre": round(rows[0]["score"] * 100) if rows else None,
                      "post": round(rows[-1]["score"] * 100) if len(rows) > 1 else None,
                      "last_score": rows[-1]["score"] if rows else None,
                      "last_assisted": not independent(rows[-1]) if rows else False,
                      "syllabus_refs": c.get("syllabus_refs", [])})
    return items


def recommend(items):
    # 课程包被整包判为不可用时 items 可能为空，这里必须给调用方一个明确的 None，
    # 而不是 IndexError——空课程也要能打开页面看到报错，而不是 500。
    weak = [i for i in items if i["status"] == "需巩固"]
    if weak:
        return min(weak, key=lambda i: i["score"])
    uncertain = [i for i in items if i["status"] == "初步达标"]
    if uncertain:
        return uncertain[0]
    return next((i for i in items if i["status"] == "未测评"), items[0] if items else None)
