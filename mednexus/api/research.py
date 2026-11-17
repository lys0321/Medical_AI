"""研究域：PubMed 检索、PMC 全文、证据与引文导出。"""
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

from api.core import InputError, connect, event

def research_gate(c, question, force=False):
    if not isinstance(question, str) or len(question.strip()) > 300:
        raise InputError("请输入不超过300字的研究疑问")
    question = question.strip()
    _check_research_privacy(question)
    if not question:
        question = c["research"]
    # Requiring a relevant topic prevents unrelated generic 'mechanism' prompts.
    relevant = any(t.lower() in question.lower() for t in c["terms"]) or question == c["research"]
    open_signal = question == c["research"] or bool(re.search(r"研究|证据|争议|尚不明确|未明|差异|恢复|病因|指标|是否|能否|影响|不同|前沿|验证", question))
    eligible = relevant and open_signal
    proposal = build_query_proposal(c, question) if eligible else None
    return {"eligible": eligible, "question": question, "reason": "疑问涉及可检验的差异、机制或证据，可以从研究文献继续探索；检索结果仍需人工评估相关性。" if eligible else "当前更像概念或通路问题，先用学习卡和定向练习补齐。可进一步明确要比较的机制、条件或证据。", "query": proposal["query"] if proposal else "", "suggestion": c["research"], "mapping": proposal["mapping"] if proposal else "尚未生成检索建议", "query_plan": proposal}


def ncbi_get(endpoint, params):
    """E-utilities 端点请求；追加统一的 tool/email 标识。"""
    params = {**params, "tool": "MedNexusLearning"}
    if NCBI_EMAIL and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", NCBI_EMAIL):
        params["email"] = NCBI_EMAIL
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/" + endpoint + "?" + urllib.parse.urlencode(params)
    return ncbi_get_url(url)


def ncbi_get_url(url):
    """所有 NCBI 请求的唯一出口：限速、体积上限、TLS 兼容回退。"""
    global NCBI_LAST
    if not url.startswith(NCBI_ALLOWED_PREFIXES):
        raise InputError("只允许访问 NCBI 官方接口")
    with NCBI_LOCK:
        time.sleep(max(0, .38 - (time.monotonic() - NCBI_LAST)))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MedNexus-Learning/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=18) as res:
                    return res.read(4_000_000)
            except urllib.error.URLError as error:
                if os.name == "nt" and isinstance(error.reason, ssl.SSLCertVerificationError):
                    return windows_https_get(url)
                raise
        finally:
            NCBI_LAST = time.monotonic()


def windows_https_get(url):
    """Use Windows' verified HTTPS trust stack; never disable TLS verification.

    Fixed script only, with the URL on stdin. No user text is evaluated as code.
    Available solely for the public NCBI endpoints (E-utilities and PMC services),
    never API secrets.
    """
    if not url.startswith(NCBI_ALLOWED_PREFIXES):
        raise InputError("Windows 兼容请求只允许 NCBI 官方接口")
    executable = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if not executable:
        raise RuntimeError("Windows HTTPS client unavailable")
    script = ("$ErrorActionPreference='Stop'; "
              "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
              "$u=[Console]::In.ReadToEnd(); "
              "$r=Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 18; "
              "[Console]::Out.Write($r.Content)")
    result = subprocess.run([executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                            input=url.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=25, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
    if len(result.stdout) > 4_000_000:
        raise RuntimeError("NCBI response exceeded limit")
    return result.stdout.lstrip(b"\xef\xbb\xbf")


def xmltext(node):
    return "".join(node.itertext()).strip() if node is not None else ""


def pubmed(query, sort="relevance"):
    key = hashlib.sha256(("abstract-category-v2\n" + sort + "\n" + query).encode()).hexdigest()
    with connect() as db:
        row = db.execute("SELECT payload,created FROM cache WHERE key=?", (key,)).fetchone()
    if row and time.time() - row["created"] < 86400:
        payload = json.loads(row["payload"])
        if "evidence_mix" not in payload:
            payload["evidence_mix"] = evidence.evidence_mix(payload.get("papers", []))
        return {**payload, "cached": True}
    result = json.loads(ncbi_get("esearch.fcgi", {"db": "pubmed", "term": query, "retmode": "json", "retmax": 20, "sort": sort}))
    search = result.get("esearchresult", {})
    if "ERROR" in result or search.get("errorlist"):
        raise InputError("PubMed 未能识别该检索式，请核对拼写或字段")
    ids = search.get("idlist", [])
    papers = []
    if ids:
        root = ET.fromstring(ncbi_get("efetch.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}))
        for node in root.findall(".//PubmedArticle"):
            med = node.find("MedlineCitation")
            article = med.find("Article")
            pmid = xmltext(med.find("PMID"))
            types = [xmltext(n) for n in article.findall("PublicationTypeList/PublicationType")]
            label = next((label for t, label in [("Meta-Analysis", "荟萃分析"), ("Systematic Review", "系统综述"), ("Randomized Controlled Trial", "随机对照试验"), ("Review", "综述"), ("Case Reports", "病例报告")] if t in types), "其他研究 · 请核对设计")
            abstract = [{"label": a.get("Label", ""), "category": a.get("NlmCategory", ""),
                         "text": xmltext(a)} for a in article.findall("Abstract/AbstractText")]
            authors = [" ".join(filter(None, [xmltext(a.find("LastName")), xmltext(a.find("Initials"))])) or xmltext(a.find("CollectiveName")) for a in article.findall("AuthorList/Author")]
            doi = next((xmltext(n) for n in node.findall("PubmedData/ArticleIdList/ArticleId") if n.get("IdType") == "doi"), "")
            year = xmltext(article.find("Journal/JournalIssue/PubDate/Year")) or xmltext(article.find("Journal/JournalIssue/PubDate/MedlineDate"))
            year_match = re.search(r"\b(?:19|20)\d{2}\b", year)
            if year_match and int(year_match.group()) > time.gmtime().tm_year:
                continue  # 预发表条目的未来卷期不放入“当前前沿”列表
            papers.append({"pmid": pmid, "title": xmltext(article.find("ArticleTitle")), "journal": xmltext(article.find("Journal/Title")), "year": year, "authors": authors[:8], "types": types, "evidence": label, "abstract": abstract, "url": "https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/", "doi": "https://doi.org/" + urllib.parse.quote(doi, safe="/") if doi else ""})
            if len(papers) >= 5:
                break
    out = {"schema_version": 2, "papers": papers, "count": int(search.get("count", 0)), "translation": search.get("querytranslation", query), "query": query, "cached": False, "fetched_at": time.time(), "evidence_mix": evidence.evidence_mix(papers)}
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (key, json.dumps(out, ensure_ascii=False), time.time()))
    return out


def cached_paper(db, pmid):
    """在检索缓存里按 PMID 找论文；优先保留 NLM 分类的新 schema。"""
    batches = [json.loads(r[0]) for r in db.execute(
        "SELECT payload FROM cache ORDER BY created DESC, rowid DESC")]
    batches.sort(key=lambda batch: batch.get("schema_version") != 2)
    for batch in batches:
        for paper in batch.get("papers", []):
            if paper.get("pmid") == pmid:
                return paper
    return None


def fetch_fulltext(db, pmid):
    """读本地缓存；过期或没有就抓一次。拒绝结果也缓存，避免反复打 NCBI。"""
    row = db.execute("SELECT payload, created FROM fulltext WHERE pmid=?", (pmid,)).fetchone()
    if row:
        record = json.loads(row["payload"])
        ttl = FULLTEXT_TTL if record.get("status") == "ok" else FULLTEXT_DENIAL_TTL
        if time.time() - row["created"] < ttl:
            return record
    result = pmc.harvest(pmid, ncbi_get_url)
    document = result.get("document") or {}
    record = {"pmid": pmid, "pmcid": result.get("pmcid", ""), "license": result.get("license", ""),
              "license_raw": result.get("license_raw", ""), "status": result.get("status", "error"),
              "reason": result.get("reason", ""), "title": result.get("title", ""),
              "sections": document.get("sections", []),
              "paragraph_count": document.get("paragraph_count", 0), "fetched_at": time.time()}
    db.execute("INSERT OR REPLACE INTO fulltext(pmid,pmcid,license,status,payload,created) "
               "VALUES(?,?,?,?,?,?)",
               (pmid, record["pmcid"], record["license"], record["status"],
                json.dumps(record, ensure_ascii=False), time.time()))
    return record


def export_citations(db, body):
    """只导出检索缓存里真实存在的条目，缺字段留空。"""
    fmt = body.get("format")
    if fmt not in ("bibtex", "ris"):
        raise InputError("格式只支持 bibtex 或 ris")
    pmids = body.get("pmids")
    if not isinstance(pmids, list) or not 1 <= len(pmids) <= 20:
        raise InputError("请选择 1–20 条文献")
    cleaned = []
    for pmid in pmids:
        value = str(pmid)
        if not re.fullmatch(r"\d{1,12}", value):
            raise InputError("PMID 格式不正确")
        if value not in cleaned:
            cleaned.append(value)
    papers, missing = [], []
    for pmid in cleaned:
        paper = cached_paper(db, pmid)
        (papers.append(paper) if paper else missing.append(pmid))
    if not papers:
        raise InputError("这些 PMID 都不在本次检索缓存中，请先检索再导出")
    return {"format": fmt, "count": len(papers), "missing": missing,
            "content": citations.export(papers, fmt),
            "notice": "引文来自 PubMed 检索时的原始字段；卷期页码等未获取的字段不会补造。"}


def _check_research_privacy(text, label="检索词"):
    if re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)\d{17}[0-9x](?!\d)", text, re.I) or re.search(
            r"(?:患者姓名|姓名|住址|病历号|住院号)\s*[:：]|(?:patient name|medical record(?: number)?|home address)\s*:", text, re.I):
        raise InputError(label + "疑似包含个人联系方式、身份或病历信息；请改用匿名的医学主题")


def research_query_for(question):
    """明确映射已支持的中文主题；绝不套用无关知识点的检索式。"""
    q = question.strip().lower()
    if not q or len(q) > 300:
        raise InputError("请输入 1–300 字的研究主题")
    _check_research_privacy(q)
    if re.fullmatch(r"[\x20-\x7e]+", q) and re.search(r"[a-z]{3}", q):
        return question.strip(), "直接使用输入的英文 PubMed 检索式"
    if "小胶质细胞" in q:
        if "突触" in q:
            focus, label = '"synaptic pruning"[Title/Abstract]', "突触修剪"
        elif "炎症" in q:
            focus, label = 'neuroinflammation[Title/Abstract]', "神经炎症"
        else:
            focus, label = '(function[Title/Abstract] OR role[Title/Abstract])', "功能"
        today = time.strftime("%Y/%m/%d", time.localtime())
        return ('(microglia[Title] OR microglial[Title]) AND '
                + focus + ' AND ("2021/01/01"[Date - Publication] : "' + today + '"[Date - Publication])',
                "小胶质细胞·%s；限定近年发表，按发表日期排序" % label)
    for concept in CONCEPTS:
        if any(term.lower() in q for term in concept["terms"] if len(term) >= 3):
            return concept["query"], "基于「%s」的英文检索模板；请核对与原问题的匹配度" % concept["name"]
    raise InputError("目前没有这个中文主题的英文检索模板。请在漫游页输入英文关键词或 PubMed 检索式。")


def research_request(body):
    """Keep the original gated question, selected concept and actual query together."""
    question = body.get("question", "")
    if not isinstance(question, str):
        raise InputError("研究疑问须为1–300字的文字")
    question = question.strip()
    cid = body.get("concept")
    if cid is None:
        query, mapping = research_query_for(question)
        return {"concept": "", "question": question, "query": query, "mapping": mapping}
    if not isinstance(cid, str) or cid not in CONCEPT_MAP:
        raise InputError("未知知识点")
    if not 1 <= len(question) <= 300:
        raise InputError("请输入 1–300 字的研究疑问")
    _check_research_privacy(question)
    concept = CONCEPT_MAP[cid]
    gate = research_gate(concept, question)
    if not gate["eligible"]:
        raise InputError("请先明确与当前知识点有关的开放性研究疑问")
    query = gate["query"]
    mapping = gate["mapping"]
    if body.get("query") is not None:
        if not isinstance(body["query"], str):
            raise InputError("请使用 3–1500 字符的英文检索式")
        query = body["query"].strip()
        if not 3 <= len(query) <= 1500 or not re.fullmatch(r"[\x20-\x7e]+", body["query"]) or not re.search(r"[a-zA-Z]{3}", query):
            raise InputError("请使用 3–1500 字符的英文检索式")
        _check_research_privacy(query)
        # Only use terms already present in the authored concept/template. This
        # does not infer a different topic from ambiguous words in the question.
        core_terms = [term for term in concept["terms"] if re.fullmatch(r"[a-zA-Z ]+", term)]
        subject = re.split(r"\bAND\b", concept["query"], maxsplit=1, flags=re.I)[0]
        subject = re.sub(r"\[[^\]]*\]", "", subject)
        core_terms.extend(term.strip(' ()\"') for term in re.split(r"\bOR\b", subject, flags=re.I))
        if not any(term and re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", query, re.I) for term in core_terms):
            raise InputError("检索式需保留当前知识点的英文核心词，请核对研究疑问与检索式的对应关系")
        mapping = "用户确认的英文检索式；已保留当前知识点核心词，相关性仍需人工评估"
    return {"concept": cid, "question": question, "query": query, "mapping": mapping}


def pubmed_compat(db, learner, body, request=None):
    """只在用户主动请求后查询 PubMed；返回真实 PMID 与摘要。"""
    request = research_request(body) if request is None else request
    out = pubmed(request["query"], sort="pub date")
    event(db, learner, "literature", request["concept"], {"question": request["question"], "query": request["query"],
          "pmids": [p["pmid"] for p in out["papers"]]})
    return {**request, "papers": out["papers"], "note": request["query"],
            "count": out["count"], "fetched_at": out["fetched_at"], "cached": out["cached"],
            "evidence_mix": out.get("evidence_mix")}

# ---- 研究域自有的连接状态（不放在 core：只有这里用）----
NCBI_LOCK = threading.Lock()
NCBI_LAST = 0.0
NCBI_EMAIL = os.environ.get("MEDNEXUS_NCBI_EMAIL", "").strip()
NCBI_ALLOWED_PREFIXES = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
    "https://www.ncbi.nlm.nih.gov/pmc/",
    "https://pmc.ncbi.nlm.nih.gov/",
)
FULLTEXT_TTL = 7 * 86400
FULLTEXT_DENIAL_TTL = 86400
