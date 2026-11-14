# -*- coding: utf-8 -*-
"""把《系统解剖学》考点速记的 OCR 文本整理成结构化题库 kaodian.json。

用法：
    python tools/build_kaodian.py <ocr_text.txt> [out.json]

这份 PDF 的考点编号是单独一列文字，OCR 后常常出现「237 ·」这样的纯编号行，
正文行在它后面。所以解析时要先把编号排进队列，再按顺序配给后面的正文行。

输出结构：
    {"系统解剖学（第10版）": [{"no": 1, "title": "运动系统",
        "sections": [{"name": "骨", "items": [{"no": 8, "text": "..."}]}]}]}
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOK = "系统解剖学（第10版）"

CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
      "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15, "十六": 16, "十七": 17, "十八": 18,
      "十九": 19, "二十": 20}

# 水印与页眉：就地删掉，不能整行丢弃
NOISE = ("更多医学资料", "医考侠整理", "医路有我", "请关注微信公众号", "公众号", "考点速记",
         "版适配", "资料长期优化更新")

NUM_ONLY = re.compile(r"^(\d{1,3})\s*[.．·、,，]?$")
CHAPTER = re.compile(r"^第([一二三四五六七八九十]{1,3})章\s*(.*)$")
SECTION = re.compile(r"^第(\d{1,2})节\s*(.*)$")
ITEM = re.compile(r"^(\d{1,3})\s*[.．·、,，]\s*(.+)$")


def despace(line):
    """OCR 在汉字之间插了空格，这里去掉中文之间的空格。"""
    line = line.replace("\u3000", " ")
    cjk = "\u4e00-\u9fff，。；：、？！“”‘’（）《》"
    line = re.sub(r"(?<=[%s])\s+(?=[%s])" % (cjk, cjk), "", line)
    line = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=\d)", "", line)
    line = re.sub(r"(?<=\d)\s+(?=[\u4e00-\u9fff])", "", line)
    return line.strip()


def clean(line):
    line = despace(line)
    for bad in NOISE:
        line = line.replace(bad, "")
    line = re.sub(r"(?<=\d)\s+(?=\d)", "", line)
    line = re.sub(r"\d{1,3}页共37页", "", line)
    line = re.sub(r"第\d{1,3}页", "", line)
    line = re.sub(r"^[\s·、,，.．\-—_！!]+", "", line)
    return line.strip()


def noise_only(line):
    """只剩数字与符号的行（OCR 把编号拆成「3 10 ·」这种），不能当正文。"""
    return not re.search(r"[\u4e00-\u9fffA-Za-z]", line)


def digits_of(line):
    digits = re.sub(r"\D", "", line)
    return int(digits) if digits and len(digits) <= 3 else None


def cjk_len(text):
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def valid_item(text):
    """OCR 残渣（「巧0 ·」「ll 0 ·」「第题库、资讯：」）不能进题库。"""
    if cjk_len(text) < 6 or len(text) < 8:
        return False
    if text.endswith("第") or text.endswith("：") and cjk_len(text) < 8:
        return False
    return True


def main():
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "kaodian.json")

    raw_lines = []
    with open(src, encoding="utf-8") as f:
        for raw in f:
            line = clean(raw)
            if line:
                raw_lines.append(line)

    chapters = []
    cur_chapter = None
    cur_section = None
    numbers = []
    pending = None
    seq = 0

    def ensure_section():
        nonlocal cur_chapter, cur_section
        if cur_chapter is None:
            cur_chapter = {"no": 0, "title": "绪论", "sections": []}
            chapters.append(cur_chapter)
        if cur_section is None:
            cur_section = {"name": "本章", "items": []}
            cur_chapter["sections"].append(cur_section)
        return cur_section

    def flush():
        nonlocal pending
        if pending is not None:
            text = pending["text"].strip()
            if text.endswith("第"):
                text = text[:-1].strip()
            if valid_item(text):
                ensure_section()["items"].append({"no": pending["no"], "text": text})
        pending = None

    for line in raw_lines:
        m = NUM_ONLY.match(line)
        if m:
            numbers.append(int(m.group(1)))
            continue
        if noise_only(line):
            num = digits_of(line)
            if num is not None and len(numbers) < 6:
                numbers.append(num)
            continue
        m = CHAPTER.match(line)
        if m and len(line) <= 30:
            flush()
            num = CN.get(m.group(1))
            if num is None:
                continue
            cur_chapter = {"no": num, "title": m.group(2).strip(), "sections": []}
            chapters.append(cur_chapter)
            cur_section = None
            continue
        m = SECTION.match(line)
        if m and len(line) <= 24:
            flush()
            ensure_section()
            cur_section = {"name": m.group(2).strip() or ("第%s节" % m.group(1)), "items": []}
            cur_chapter["sections"].append(cur_section)
            continue
        m = ITEM.match(line)
        if m:
            flush()
            pending = {"no": int(m.group(1)), "text": m.group(2).strip()}
            continue
        if line in ("绪论", "目录") or line.startswith("绪论"):
            flush()
            if not chapters or chapters[-1]["title"] != "绪论":
                cur_chapter = {"no": 0, "title": "绪论", "sections": []}
                chapters.append(cur_chapter)
                cur_section = None
            continue
        # 正文行：过短的碎片多半是上一行被切断的尾巴，直接续接
        if len(line) <= 5 and pending is not None and not numbers:
            pending["text"] += line
            continue
        if numbers:
            num = numbers.pop(0)
            flush()
            pending = {"no": num, "text": line}
        elif pending is not None:
            pending["text"] += line
        else:
            seq += 1
            pending = {"no": seq, "text": line}
    flush()

    for c in chapters:
        c["sections"] = [s for s in c["sections"] if s["items"]]
    chapters = [c for c in chapters if c["sections"]]

    data = {BOOK: chapters}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    total = sum(len(s["items"]) for c in chapters for s in c["sections"])
    print("chapters", len(chapters), "items", total, "->", out)


if __name__ == "__main__":
    main()