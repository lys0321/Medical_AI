"""学习域：资料来源、检索、补学、导入与组胚识图练习。"""
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

from api.answer import grade
from api.core import InputError, state_get, state_save, event, progress
from api.core import InputError, state_get, state_save, event, progress

def builtins():
    return [{"id": "note-" + c["id"], "book": "MedNexus 自编学习卡", "chapter": "脑神经 · " + c["name"], "page": None,
             "text": c["note"], "keywords": c["terms"], "url": SOURCES[c["source"]]["url"], "locator": SOURCES[c["source"]]["section"],
             "reference": SOURCES[c["source"]]["title"], "kind": "note", "provenance": "自编教学摘要，参考公开资料；不是原书逐字摘录", "concept": c["id"]} for c in CONCEPTS]


def textbook_sources():
    """教材页级索引（由书页项目并入）。没有索引文件时返回空列表。"""
    try:
        return [{k: v for k, v in s.items() if k != "coverage"} for s in textbook.ensure()["sources"]]
    except Exception:
        return []


def all_sources(db, learner):
    return textbook_sources() + builtins() + [json.loads(r[0]) for r in db.execute("SELECT payload FROM sources WHERE learner=?", (learner,))]


def tokenize(text):
    text = str(text).lower()
    terms = re.findall(r"[a-z0-9]+", text)
    for chunk in re.findall(r"[\u4e00-\u9fff]+", text):
        terms += [chunk[i:i+2] for i in range(len(chunk) - 1)]
    return set(terms) - {"什么", "怎么", "为什么", "如何", "一个", "哪些", "可以", "以及", "还是", "有没有"}


def retrieve(query, sources):
    # 先查教材索引：命中就返回带印刷页码的原文段落，避免对 5,667 条逐条分词
    try:
        hits = textbook.search(query)
    except Exception:
        hits = []
    if hits:
        keep = {s["id"] for s in sources}
        hits = [h for h in hits if h["id"] in keep] or hits
        return [{**h, "coverage": h.get("coverage", 0)} for h in hits]

    qt = tokenize(query)
    if not qt:
        return []
    docs = [tokenize(s["chapter"] + s.get("text", "") + " ".join(s.get("keywords", []))) for s in sources]
    weights = {t: math.log(1 + (len(docs) + 1) / (1 + sum(t in d for d in docs))) for t in qt}
    denom = sum(weights.values()) or 1
    ranked = []
    for s, dt in zip(sources, docs):
        cov = sum(w for t, w in weights.items() if t in dt) / denom
        explicit = any(term.lower() in query.lower() for term in s.get("keywords", []) if len(term) > 2)
        if cov >= .33 and (len(qt & dt) >= 2 or explicit):
            ranked.append({**s, "coverage": round(cov, 3)})
    return sorted(ranked, key=lambda s: s["coverage"], reverse=True)[:3]


def verify_citation(source, quote, sources):
    # Verifies index identity and exact excerpt, not truth or semantic entailment.
    original = next((s for s in sources if s["id"] == source["id"]), None)
    return bool(original and original["book"] == source["book"] and original.get("page") == source.get("page") and quote and quote in original.get("text", ""))


def study_payload(db, learner, cid):
    """Build remediation from the learner's saved assessment and scoped sources."""
    c = CONCEPT_MAP[cid]
    row = db.execute("SELECT score,payload FROM attempts WHERE learner=? AND concept=? ORDER BY id DESC LIMIT 1",
                     (learner, cid)).fetchone()
    last_result = json.loads(row["payload"]) if row else None
    focus = [{k: p[k] for k in ("label", "reason", "expected")}
             for p in (last_result or {}).get("rubric", []) if p.get("correct") is False]
    study_mode = "targeted" if focus else "overview"

    # Search this authorized candidate set directly. retrieve() can fall back to
    # global textbook hits, which must not displace a learner's local evidence.
    sources, seen = [], set()
    for source in all_sources(db, learner):
        page = source.get("page")
        if (source.get("kind") not in ("local", "metadata", "textbook")
                or type(page) is not int or page < 1 or not source.get("book") or not source.get("id")):
            continue
        identity = (source["id"], source["book"], page, source["kind"])
        if identity in seen:
            continue
        seen.add(identity)
        source = dict(source)
        # A locator without supplied source text is never treated as a quotation.
        if source["kind"] == "metadata":
            source["text"] = ""
        blob = " ".join((source.get("chapter", ""), source.get("text", ""),
                         " ".join(source.get("keywords", []))))
        if not any(term.lower() in blob.lower() for term in c["terms"]):
            continue
        sources.append((source, tokenize(blob)))

    def matches(query):
        terms = tokenize(query)
        if not terms:
            return []
        weights = {t: math.log(1 + (len(sources) + 1) / (1 + sum(t in dt for _, dt in sources))) for t in terms}
        total = sum(weights.values()) or 1
        ranked = []
        for source, tokens in sources:
            overlap = terms & tokens
            coverage = sum(weights[t] for t in overlap) / total
            explicit = any(term.lower() in query.lower() for term in source.get("keywords", []) if len(term) > 2)
            if coverage >= .33 and (len(overlap) >= 2 or explicit):
                ranked.append((coverage, source))
        return sorted(ranked, key=lambda item: item[0], reverse=True)[:3]

    def evidence_for(queries):
        candidates = {}
        for query in queries:
            for score, source in matches(query):
                identity = (source["id"], source["book"], source["page"], source["kind"])
                if identity not in candidates or score > candidates[identity][0]:
                    candidates[identity] = (score, source)
        evidence = []
        terms = tokenize(" ".join(queries))
        for _, source in sorted(candidates.values(), key=lambda item: item[0], reverse=True)[:3]:
            text = source.get("text", "")
            sentences = list(re.finditer(r"[^。！？；;\n]+[。！？；;]?", text))
            best = max(sentences, key=lambda m: len(terms & tokenize(m.group())), default=None)
            # Keep an exact contiguous excerpt, including original punctuation.
            excerpt = best.group()[:600] if best else ""
            evidence.append({**source, "excerpt": excerpt,
                             "evidence_type": "text" if excerpt else "locator",
                             "evidence_notice": "相关原文摘录；是否支持该要点仍需对照原书核验" if excerpt else
                             "仅作书页定位，未提供可核对原文，不能作为解释依据"})
        return evidence

    local_sources = []
    for point in focus:
        point["evidence"] = evidence_for([point["label"], point["expected"], point["reason"]])
        local_sources.extend(point["evidence"])
    if not focus:
        local_sources = evidence_for([c["name"]] + c["terms"])
    unique = {(s["id"], s["book"], s["page"], s["kind"]): s for s in local_sources}
    state = state_get(db, learner)
    state["concept"] = cid
    state_save(db, learner, state)
    event(db, learner, "study", cid, {"study_mode": study_mode, "focus": [p["label"] for p in focus]})
    return {"concept": c["id"], "name": c["name"], "note": c["note"], "source": SOURCES[c["source"]],
            "goals": COURSE["goal_source"], "local_sources": list(unique.values()), "last_result": last_result,
            "focus": focus, "study_mode": study_mode,
            "retest_kind": "diagnostic" if not row or row["score"] == 0 else "transfer"}


def import_sources(db, learner, records):
    if not isinstance(records, list) or not 1 <= len(records) <= 1000:
        raise InputError("每次导入 1–1000 条记录")
    cleaned = []
    for i, s in enumerate(records):
        if not isinstance(s, dict) or not all(isinstance(s.get(k), str) and s[k].strip() for k in ("book", "chapter")):
            raise InputError(f"第 {i+1} 条必须包含 book 和 chapter 字符串")
        page = s.get("page")
        if type(page) is not int or not 1 <= page <= 100000:
            raise InputError(f"第 {i+1} 条 page 必须是正整数印刷页码")
        text = str(s.get("text", ""))
        if len(text) > 2000:
            raise InputError(f"第 {i+1} 条文本超过 2000 字；请只保留有权使用的短段落")
        url = str(s.get("url", ""))
        if url and urllib.parse.urlparse(url).scheme != "https":
            raise InputError("来源链接只支持 https")
        keywords = s.get("keywords", [])
        if not isinstance(keywords, list) or any(not isinstance(t, str) for t in keywords) or len(keywords) > 100:
            raise InputError("keywords 必须是最多 100 个字符串组成的数组")
        clean = {"book": s["book"][:200], "chapter": s["chapter"][:200], "page": page, "text": text, "keywords": [t[:100] for t in keywords], "url": url[:2000], "locator": str(s.get("edition", "版本未注明"))[:100], "kind": "local" if text else "metadata", "provenance": "用户导入索引；页码真实性待对照正版教材人工核验", "reference": "用户本地资料"}
        clean["id"] = "local-" + hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
        cleaned.append(clean)
    # Entire batch is validated before inserting any record.
    for s in cleaned:
        db.execute("INSERT OR REPLACE INTO sources VALUES(?,?,?)", (learner, s["id"], json.dumps(s, ensure_ascii=False)))
    event(db, learner, "import", payload={"count": len(cleaned)})
    return {"count": len(cleaned), "message": "已导入本地资料。页码来自你的索引，系统不会将其标为已核验教材原页。"}


def image_attempts(db, learner):
    return [dict(r) for r in db.execute(
        "SELECT id, token, score, created, payload FROM attempts WHERE learner=? AND kind='image' ORDER BY id",
        (learner,))]


def image_stats(db, learner):
    """图片题单独统计，不进 progress()/掌握度。"""
    return histology_quiz.summarize(image_attempts(db, learner))


def image_quiz(db, learner, body):
    """组胚识图：出题与作答。题目标注全部来自本机待审核标注文件。"""
    action = body.get("action") or "next"
    labels = histology_quiz.load_labels()
    if not labels.get("available"):
        return {"available": False, "reason": labels.get("reason", "no_labels"),
                "message": labels.get("message", ""), "stats": image_stats(db, learner)}

    if action == "next":
        question = histology_quiz.build_question(labels)
        if question is None:
            return {"available": False, "reason": "not_enough_labels",
                    "message": "标注不足以出题（至少需要 4 条不同的小标题）。",
                    "stats": image_stats(db, learner)}
        token = secrets.token_hex(16)
        state = state_get(db, learner)
        state["image"] = {"token": token, "question": question, "created": time.time()}
        state_save(db, learner, state)
        event(db, learner, "image-quiz", "histology", {"image_number": question["image_number"], "action": "task"})
        return {"available": True, "question": histology_quiz.public(question, token),
                "assist_available": bool(vision.configured_model()),
                "stats": image_stats(db, learner)}

    if action == "assist":
        state = state_get(db, learner)
        pending = state.get("image")
        if not isinstance(pending, dict):
            raise InputError("请先出一道识图题")
        question = pending["question"]
        path = materials.image_path(question.get("image", ""))
        assist = vision.describe(path) if path else None
        return {"available": assist is not None, "assist": assist,
                "message": "" if assist else "本机没有配置视觉模型，或模型未返回可用描述。",
                "notice": vision.NOTICE}

    if action == "answer":
        token, choice = body.get("token"), body.get("choice")
        existing = db.execute("SELECT payload FROM attempts WHERE learner=? AND token=?",
                              (learner, token)).fetchone()
        if existing:
            stored = json.loads(existing[0])
            return {"result": stored, "correct": stored.get("correct"), "answer": stored.get("answer"),
                    "stats": image_stats(db, learner)}
        state = state_get(db, learner)
        pending = state.get("image")
        if not isinstance(pending, dict) or pending.get("token") != token:
            raise InputError("这道识图题已切换，请刷新后重试")
        question = pending["question"]
        try:
            outcome = histology_quiz.grade(question, choice)
        except ValueError as error:
            raise InputError(str(error))
        payload = {"kind": "image", "image_number": question["image_number"],
                   "question": "image-%d" % question["image_number"],
                   "prompt": question["prompt"], "answer": outcome["answer"], "choice": outcome["choice"],
                   "correct": outcome["correct"], "tissue": question.get("tissue", ""),
                   "stains": question.get("stains", []),
                   "review_status": question.get("review_status") or "pending"}
        db.execute("INSERT INTO attempts(learner,token,concept,question,kind,score,payload,created) "
                   "VALUES(?,?,?,?,?,?,?,?)",
                   (learner, token, "histology", payload["question"], "image",
                    1.0 if outcome["correct"] else 0.0, json.dumps(payload, ensure_ascii=False), time.time()))
        state["image"] = None
        state_save(db, learner, state)
        event(db, learner, "image-quiz", "histology",
              {"image_number": question["image_number"], "correct": outcome["correct"]})
        return {"result": payload, "correct": outcome["correct"], "answer": outcome["answer"],
                "stats": image_stats(db, learner)}

    raise InputError("未知的识图操作")
