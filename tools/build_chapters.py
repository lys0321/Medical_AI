# -*- coding: utf-8 -*-
"""从 chunks.jsonl 生成教材章节索引 chapters.json。

规则：章标题在正文里以「第X章 标题」出现，每章取第一次出现的页码作为起始页，
下一章起始页 - 1 作为结束页。宁可少识别，也不要把「见第十章」这类引用当标题。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHUNKS = os.path.join(ROOT, "chunks.jsonl")
OUT = os.path.join(ROOT, "chapters.json")

CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
      "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15, "十六": 16, "十七": 17, "十八": 18,
      "十九": 19, "二十": 20, "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24, "二十五": 25}

TITLE = r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z与和的、]{1,13})"


def norm(text):
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()


BAD_START = ("可", "是", "位于", "由", "在", "分", "包括", "又", "即", "为")


def clean_title(title):
    """正文句子里抓到的不像章名，就别硬当章名，宁可不显示。"""
    title = title.strip(" 　·、")
    if len(title) < 2:
        return ""
    if re.search(r"[。，；：！？]", title):
        return ""
    if title.startswith(BAD_START):
        return ""
    return title


def main():
    pages = {}
    with open(CHUNKS, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            book = d["book"]
            pages.setdefault(book, {})
            pages[book].setdefault(int(d["page"]), []).append(d["text"])

    result = {}
    for book, by_page in pages.items():
        found = {}
        matches = []
        for page in sorted(by_page):
            text = norm(" ".join(by_page[page]))
            # 人卫第10版里《系统解剖学》《生理学》用「第一章」，《组织学与胚胎学》用「第1章」，
            # 两种都要认，否则组胚会一章都识别不出来。
            for m in re.finditer(r"第\s*([一二三四五六七八九十]{1,3}|\d{1,2})\s*章\s*" + TITLE, text):
                raw = m.group(1)
                num = int(raw) if raw.isdigit() else CN.get(raw)
                if not num:
                    continue
                before = text[max(0, m.start() - 14):m.start()]
                matches.append((page, num, m.group(2), "本章" in before or m.start() <= 2))
        for page, num, title, strong in matches:
            if num in found:
                continue
            # 强证据：章首页带「本章思维导图 / 本章数字资源」标记，或标题在页首。
            # 弱证据：章号正好是下一个、页码在上一章之后（用来补识别不到的章）。
            if strong or (found and num > max(found) and page > found[max(found)][0]):
                found[num] = (page, clean_title(title))
        if not found:
            continue
        chapters = []
        nums = sorted(found)
        last_page = max(by_page)
        for i, num in enumerate(nums):
            page, title = found[num]
            end = found[nums[i + 1]][0] - 1 if i + 1 < len(nums) else last_page
            if end < page:
                end = page
            chapters.append({"no": num, "title": title, "start": page, "end": end})
        result[book] = chapters

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    for book, chapters in result.items():
        print(book, len(chapters))
        for c in chapters:
            print("   di%d zhang %s  P%d-P%d" % (c["no"], c["title"], c["start"], c["end"]))
    print("written", OUT)


if __name__ == "__main__":
    main()