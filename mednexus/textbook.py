# -*- coding: utf-8 -*-
"""教材页级检索层（由「书页」项目并入）。

职责：把本地教材索引 chunks.jsonl 变成 MedNexus 可用的 source 记录，
让「补学」与「自由提问」都能给出**可核验的印刷页码**，而不是自编摘要。

索引文件位置（按顺序查找，取第一个存在的）：
    <仓库根>/chunks.jsonl
    <仓库根>/mednexus/data/chunks.jsonl

索引由 tools/pdf_extract.py + shuye/index.py 生成，格式每行：
    {"id": "...", "book": "生理学（第10版）", "page": 321, "text": "..."}

设计要点：
  · BM25（术语精确）+ IDF 加权覆盖率（判断该不该拒答）
  · 索引只在首次使用时构建，之后走模块级缓存
  · 覆盖率低于 MIN_COVERAGE 时返回空列表，由上层走拒答/回退
  · 每段再切成句子并记录字符偏移，结果附带命中句摘录，便于前端只高亮那一句
  · 可选语义重排：本机 Ollama 有嵌入模型时，仅对已通过拒答门槛的结果按
    0.5×归一化BM25 + 0.5×cosine 重排；向量相似度不参与“教材里有没有”的判断
"""
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

CANDIDATES = [ROOT / "chunks.jsonl", HERE / "data" / "chunks.jsonl"]
EMBED_CACHE = HERE / "data" / "embeddings.jsonl"

MIN_COVERAGE = 0.30      # 查询词覆盖率下限，低于此值判为“教材里没有”
TOP_K = 3
MAX_SENTENCE = 160       # 无标点的长段按固定窗口切，避免整段高亮

_CJK = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("的了是在和与或有不为以及等这那其即由对可会要将把被")
_SENTENCE = re.compile(r"[^。！？；!?;\n]+[。！？；!?;]*")

_index = None
_status = {"loaded": 0, "path": ""}
_vectors = {}


# ---------- 索引构建 ----------

def _tokens(text):
    text = str(text).lower()
    toks = _WORD.findall(text)
    chars = _CJK.findall(text)
    toks += [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
    return toks


def _query_terms(query):
    """查询词：去停用字的二元组 + 英文词。用于覆盖率判定。"""
    text = str(query).lower()
    terms = set(_WORD.findall(text))
    chars = [c for c in _CJK.findall(text) if c not in _STOP]
    terms.update(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
    return terms


def _sentences(text):
    """切句并保留偏移：text[start:end] 恒等于句子原文；切分失败时退回整段。"""
    spans = []
    for m in _SENTENCE.finditer(text):
        start, end = m.start(), m.end()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        for cut in range(start, end, MAX_SENTENCE):
            spans.append((cut, min(cut + MAX_SENTENCE, end)))
    return spans or [(0, len(text))]


def _excerpt(source, spans, terms):
    """命中查询词最多的一句；并列取靠前的句子。"""
    text = source["text"]
    counts = [sum(t in text[a:b] for t in terms) for a, b in spans]
    best = max(range(len(spans)), key=lambda i: (counts[i], -i))
    start, end = spans[best]
    return {"text": text[start:end], "start": start, "end": end, "index": best,
            "matched": counts[best], "page": source["page"]}


def _find_index_file():
    for p in CANDIDATES:
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


def _build():
    global _index
    path = _find_index_file()
    if path is None:
        _status["loaded"] = 0
        _index = {"sources": [], "sentences": [], "postings": {}, "df": {}, "len": [], "avg": 1.0}
        return _index

    sources = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            text = str(rec.get("text", "")).strip()
            page = rec.get("page")
            if not text or not isinstance(page, int) or page < 1:
                continue
            book = str(rec.get("book", "")).strip()
            if not book:
                continue
            sid = "tb-" + hashlib.sha256(
                (book + "|" + str(page) + "|" + text[:40]).encode("utf-8")
            ).hexdigest()[:16]
            sources.append({
                "id": sid,
                "book": book,
                "chapter": rec.get("chapter", "") or "",
                "page": page,
                "text": text,
                "keywords": rec.get("keywords", []),
                "url": "",
                "locator": "P%d" % page,
                "reference": book,
                "kind": "textbook",
                "provenance": "本地教材索引；页码为印刷页码，需对照正版核验",
            })

    postings = defaultdict(list)
    df = Counter()
    lengths = []
    for i, s in enumerate(sources):
        tf = Counter(_tokens(s["text"]))
        lengths.append(sum(tf.values()))
        for t, c in tf.items():
            postings[t].append((i, c))
            df[t] += 1
    avg = (sum(lengths) / len(lengths)) if lengths else 1.0

    # 句子偏移单独存放，不混进 source 记录，避免随来源列表下发给其他接口
    sentences = [_sentences(s["text"]) for s in sources]
    _index = {"sources": sources, "sentences": sentences, "postings": postings, "df": df, "len": lengths, "avg": avg}
    _status["loaded"] = len(sources)
    _status["path"] = str(path)
    return _index


def ensure():
    if _index is None:
        _build()
    return _index


def status():
    idx = ensure()
    return {"loaded": len(idx["sources"]), "path": _status["path"],
            "min_coverage": MIN_COVERAGE, "top_k": TOP_K}


def reload():
    global _index
    _index = None
    _vectors.clear()
    return ensure()


# ---------- 可选语义重排 ----------

def _embedder():
    try:
        import tutor_model
        return tutor_model.embedder()
    except Exception:
        return None


def _vector(value):
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in value):
        return None
    return [float(x) for x in value]


def _cache_key(model, text):
    return hashlib.sha256((model + "\n" + text).encode("utf-8")).hexdigest()[:32]


def _cached_vectors(model):
    """读取嵌入缓存；坏行、别的模型或非数值向量一律跳过。"""
    if model in _vectors:
        return _vectors[model]
    found = {}
    try:
        lines = EMBED_CACHE.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("model") == model and isinstance(rec.get("key"), str):
            vec = _vector(rec.get("vector"))
            if vec:
                found[rec["key"]] = vec
    _vectors[model] = found
    return found


def _cosine(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        raise ValueError("零向量")
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _semantic(query, items):
    """返回每条的 cosine；任何异常、缺向量或维度不一致都返回 None，调用方退回纯 BM25。"""
    found = _embedder()
    if not found:
        return None
    model, embed = found
    try:
        qv = _vector(embed(query))
        if qv is None:
            return None
        cache = _cached_vectors(model)
        scores, fresh = [], []
        for s in items:
            key = _cache_key(model, s["text"])
            vec = cache.get(key)
            if vec is None:
                vec = _vector(embed(s["text"]))
                if vec is None:
                    return None
                cache[key] = vec
                fresh.append({"key": key, "model": model, "id": s["id"], "dim": len(vec), "vector": vec})
            if len(vec) != len(qv):
                return None
            scores.append(_cosine(qv, vec))
    except Exception:
        return None
    if fresh:
        try:
            EMBED_CACHE.parent.mkdir(parents=True, exist_ok=True)
            with io.open(EMBED_CACHE, "a", encoding="utf-8") as f:
                for rec in fresh:
                    f.write(json.dumps(rec) + "\n")
        except OSError:
            pass
    return scores


# ---------- 检索 ----------

def search(query, top_k=TOP_K):
    """返回 [{source...}, coverage]，按相关性降序；覆盖率不足返回 []。"""
    idx = ensure()
    if not idx["sources"]:
        return []

    terms = _query_terms(query)
    if not terms:
        return []

    N = len(idx["sources"])
    scores = defaultdict(float)
    for t in terms:
        post = idx["postings"].get(t)
        if not post:
            continue
        df = idx["df"][t]
        idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
        for did, tf in post:
            dl = idx["len"][did] or 1
            denom = tf + 1.2 * (0.25 + 0.75 * dl / idx["avg"])
            scores[did] += idf * (tf * 2.2) / denom

    if not scores:
        return []

    ranked = sorted(scores.items(), key=lambda x: -x[1])[: max(top_k * 4, 12)]

    # IDF 加权覆盖率：生僻词命中才算真的相关
    total_w = 0.0
    for t in terms:
        df = idx["df"].get(t, 0)
        total_w += math.log(1 + (N - df + 0.5) / (df + 0.5))

    out = []
    for did, sc in ranked:
        s = idx["sources"][did]
        blade = s["text"]
        got = 0.0
        matched = 0
        for t in terms:
            if t in blade:
                matched += 1
                df = idx["df"].get(t, 0)
                got += math.log(1 + (N - df + 0.5) / (df + 0.5))
        cov = got / total_w if total_w else 0.0
        # 双重门槛：覆盖率达标 + 至少命中 2 个不同查询词，挡住单点误命中
        if cov >= MIN_COVERAGE and matched >= 2:
            spans = idx["sentences"][did] if did < len(idx.get("sentences", [])) else _sentences(blade)
            out.append((sc, {**s, "coverage": round(cov, 3), "excerpt": _excerpt(s, spans, terms)}))

    out.sort(key=lambda x: -x[0])
    # 语义分只在门槛之后参与排序：向量相似度不能把没通过覆盖率的段落变成“教材依据”
    cosines = _semantic(query, [item for _, item in out]) if out else None
    if cosines is not None:
        top = out[0][0] or 1.0
        mixed = []
        for (sc, item), cos in zip(out, cosines):
            hybrid = 0.5 * (sc / top) + 0.5 * max(cos, 0.0)
            mixed.append((hybrid, {**item, "retrieval": "hybrid", "semantic": round(cos, 3)}))
        out = sorted(mixed, key=lambda x: -x[0])
    return [item for _, item in out[:top_k]]


def coverage_of(items):
    if not items:
        return 0.0
    return max(float(i.get("coverage", 0)) for i in items)


# ---------- 练习提示用：按知识点找“教材哪一页讲过” ----------

_INDEX_LIKE = re.compile(r"[，,]\s*\d")
_SPACE = re.compile(r"\s+")
# PDF 抽取常见：汉字之间夹一个空格（"病 变"），汉字与标点之间的空格一并去掉
_CJK_GAP = re.compile(
    r"(?<=[\u4e00-\u9fff，。；：、？！“”‘’（）《》])\s+(?=[\u4e00-\u9fff，。；：、？！“”‘’（）《》])")
# 汉字后面直接跟一长串英文，多半是双栏串行（也要排除正常的中英混排术语）
_COLUMN_JUMP = re.compile(r"(?<=[\u4e00-\u9fff])\s+[a-zA-Z]{4,}")


def _looks_like_index(text):
    """书后索引页：『舌下神经 hypoglossal nerve 44，45 …』这类条目堆叠，不适合作学习出处。"""
    return len(_INDEX_LIKE.findall(text)) >= 3


def snippet(text, term, width=90):
    """截取包含关键词的一段原句，用于回书核对。

    教材 PDF 抽出来的句子常带断行空格（"病 变"），这里先去掉汉字之间的空格，
    否则提示里读起来像错字。
    """
    clean = _CJK_GAP.sub("", _SPACE.sub(" ", str(text)).strip())
    pos = clean.find(term) if term else -1
    if pos < 0:
        return clean[:width]
    start = max(0, pos - width // 3)
    end = min(len(clean), pos + len(term) + width)
    body = clean[start:end].lstrip(" 。，、；：？！…")
    if start:
        body = "…" + body
    # 双栏排版抽出来时常把下一栏的英文词接在汉字后面（"眼睑不 buccal branch"），
    # 遇到这种跳字就截断，宁短一点也不要读不通的句子。
    jump = _COLUMN_JUMP.search(body)
    if jump:
        return body[: jump.start()].rstrip() + "…"
    return body + ("…" if end < len(clean) else "")


def page_text(book, page):
    """按书名 + 印刷页码取出该页全部原文，用于「回书核对」。

    同一页可能被切成多段，这里按原顺序拼回去，段间用空格分隔。
    """
    idx = ensure()
    parts = [s["text"] for s in idx["sources"] if s["book"] == book and s["page"] == page]
    return " ".join(parts)


def related(query, require=None, top_k=2, min_coverage=MIN_COVERAGE):
    """按知识点检索教材页：放宽排序数量，但要求正文出现核心词、且不是索引页。

    与 search() 的区别：search() 用于「回答问题」，宁缺毋滥；
    related() 用于「回书核对」，可以给出相关度中等但确实讲到了本词的页。
    """
    idx = ensure()
    if not idx["sources"]:
        return []

    terms = _query_terms(query)
    if not terms:
        return []

    N = len(idx["sources"])
    scores = defaultdict(float)
    for t in terms:
        post = idx["postings"].get(t)
        if not post:
            continue
        idf = math.log(1 + (N - idx["df"][t] + 0.5) / (idx["df"][t] + 0.5))
        for did, tf in post:
            dl = idx["len"][did] or 1
            denom = tf + 1.2 * (0.25 + 0.75 * dl / idx["avg"])
            scores[did] += idf * (tf * 2.2) / denom

    if not scores:
        return []

    total_w = 0.0
    for t in terms:
        df = idx["df"].get(t, 0)
        total_w += math.log(1 + (N - df + 0.5) / (df + 0.5))

    out, seen = [], set()
    for did, _ in sorted(scores.items(), key=lambda x: -x[1])[:60]:
        s = idx["sources"][did]
        text = s["text"]
        if require and require not in text:
            continue
        if _looks_like_index(text):
            continue
        key = (s["book"], s["page"])
        if key in seen:
            continue
        got = 0.0
        for t in terms:
            if t in text:
                df = idx["df"].get(t, 0)
                got += math.log(1 + (N - df + 0.5) / (df + 0.5))
        cov = got / total_w if total_w else 0.0
        if cov < min_coverage:
            continue
        seen.add(key)
        out.append({**s, "coverage": round(cov, 3)})
        if len(out) >= top_k:
            break
    return out
