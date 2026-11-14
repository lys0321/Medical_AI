# -*- coding: utf-8 -*-
"""从《组织学与胚胎学（第10版）》教材正文生成考点题库，并合并进 kaodian.json。

和《系统解剖学》考点速记那条链路不同：那本速记本身就是「术语：解释」的条目，
这本教材是连续正文，所以这里的条目由教材里的定义句自动抽取：
只认「术语（英文）是/由/包括/分为……」这种句式，抽出来的解释仍是原句，
不改写、不补写；页码取该段所在的印刷页，方便回书核对。

用法：
    python tools/build_kaodian_zzpx.py
需要仓库根有 chapters.json（tools/build_chapters.py 生成）与 book_zzpx.jsonl。
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHUNKS = os.path.join(ROOT, "book_zzpx.jsonl")
CHAPTERS = os.path.join(ROOT, "chapters.json")
OUT = os.path.join(ROOT, "kaodian.json")
BOOK = "组织学与胚胎学（第10版）"
# 这本书 PDF 页号比印刷页号大 23（tools/build_chunks.py 的 BOOKS 里是同一个偏移）。
PDF_TO_PRINTED = 23

DEF = re.compile(r"^([\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9（）()·、\- ]{0,13}?)\s*(?:（[^）]{0,48}）)?\s*"
                 r"(是|由|包括|分为|主要|位于|参与构成|具有)")
BAD_TERM = ("教材", "编委", "目录", "上篇", "下篇", "数字资源", "二维码", "本书", "本章", "我们", "以上",
            "但是", "因此", "所以", "如果", "例如", "其中", "同时", "此外", "另外")
BAD_PREFIX = ("的", "在", "从", "对", "把", "被", "这", "那", "其", "该", "此", "但", "而", "又", "即")
# 术语后面常跟着副词或情态词，被截进术语里就成了「分泌部完全」「完全」这种伪术语。
BAD_TAIL = ("完全", "都", "均", "也", "可", "能", "常", "会", "一般", "通常", "主要", "有的", "可以")


def norm(text):
    text = text.replace("\u3000", " ")
    return re.sub(r"[ \t]+", " ", text)


def clean_term(term):
    term = term.strip(" 　·、-—")
    if not 2 <= len(term) <= 14:
        return ""
    if any(word in term for word in BAD_TERM):
        return ""
    if term.endswith(BAD_PREFIX) or term.startswith(BAD_PREFIX):
        return ""
    if term.endswith(BAD_TAIL):
        return ""
    if not re.search(r"[\u4e00-\u9fff]", term):
        return ""
    return term


def sentences(page_text):
    """按句号/分号切句，并去掉页眉页脚残留。"""
    text = norm(page_text)
    text = re.sub(r"本章数字资源\s*\d+\s*", "", text)
    text = re.sub(r"第\s*\d+\s*章\s*[\u4e00-\u9fff]{2,10}", "", text)
    for part in re.split(r"[。；]", text):
        part = part.strip(" ，、")
        if 10 <= len(part) <= 150:
            yield part


def build():
    chapters = json.load(open(CHAPTERS, encoding="utf-8")).get(BOOK, [])
    if not chapters:
        raise SystemExit("chapters.json 里没有这本书，先跑 tools/build_chapters.py")
    by_page = {}
    with open(CHUNKS, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            printed = int(row["pdf_page"]) - PDF_TO_PRINTED
            if printed < 1:
                continue
            by_page.setdefault(printed, []).append(row["text"])

    out = []
    for chapter in chapters:
        seen = set()
        items = []
        pages = sorted(p for p in by_page if chapter["start"] <= p <= chapter["end"])
        for page in pages:
            for sentence in sentences(" ".join(by_page[page])):
                match = DEF.match(sentence)
                if not match:
                    continue
                term = clean_term(match.group(1))
                if not term or term in seen:
                    continue
                # 保留「是/由/包括/具有」这些连接词，否则会出现「复层扁平上皮：耐摩擦…」这种缺主谓的句子。
                tail = sentence[match.end(1):].lstrip()
                tail = re.sub(r"^（[^）]{0,48}）\s*", "", tail).strip()
                tail = re.sub(r"\s+", "", tail)
                if not 14 <= len(tail) <= 110:
                    continue
                seen.add(term)
                items.append({"no": len(items) + 1, "page": page,
                              "text": "%s：%s。" % (term, tail.rstrip("。"))})
                if len(items) >= 80:
                    break
            if len(items) >= 80:
                break
        if not items:
            continue
        out.append({"no": chapter["no"], "title": chapter["title"],
                    "sections": [{"name": "正文摘录 · 印刷页 P%d–P%d" % (chapter["start"], chapter["end"]),
                                  "items": items}]})
    return out


def main():
    data = {}
    if os.path.isfile(OUT):
        data = json.load(open(OUT, encoding="utf-8"))
    chapter_rows = build()
    data[BOOK] = chapter_rows
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    total = sum(len(c["sections"][0]["items"]) for c in chapter_rows)
    print("%s: %d 章 %d 条" % (BOOK, len(chapter_rows), total))
    for c in chapter_rows[:5]:
        print("   %s: %d 条" % (c["title"], len(c["sections"][0]["items"])))


if __name__ == "__main__":
    main()