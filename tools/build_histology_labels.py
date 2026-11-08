#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从本机组胚资料生成识图标注（机械抽取，必须由教师审核）。

输入：mednexus/data/course_materials/histology.json（本机 OCR 结果，不入库）
输出：mednexus/data/course_materials/histology_labels.json（同样不入库）

抽什么
  tissue      该页出现的组织名，按关键词表计数取最高；抽不到就留空
  stain       该页提到的染色法（HE、苏木精-伊红、PAS、银染等）
  structures  该页的编号小标题（原文自己写的“1、……”），截断成短名
  source_page 来源页（图片序号；资料没有独立印刷页码）

不做的事
  · 不生成解剖结构坐标：OCR 框是**文字行**的框，不是切片里的结构位置；
  · 不猜没出现的组织或染色；
  · 不把置信度低的整行当成结构名。

所以本文件产出的标注一律带 ``review_status: pending``，界面必须显示“待教师审核”。
"""
import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE.parent / 'mednexus' / 'data' / 'course_materials' / 'histology.json'
DEFAULT_OUTPUT = HERE.parent / 'mednexus' / 'data' / 'course_materials' / 'histology_labels.json'

TISSUES = (
    ('上皮组织', ('上皮', '内皮', '间皮')),
    ('结缔组织', ('结缔组织', '疏松结缔', '致密结缔', '脂肪组织', '网状组织')),
    ('血液', ('血液', '血细胞', '红细胞', '白细胞', '血小板')),
    ('软骨', ('软骨',)),
    ('骨', ('骨组织', '骨单位', '骨松质', '骨密质')),
    ('肌组织', ('肌组织', '骨骼肌', '心肌', '平滑肌')),
    ('神经组织', ('神经组织', '神经元', '神经胶质', '突触')),
    ('循环系统', ('循环系统', '心脏', '动脉', '静脉', '毛细血管')),
    ('免疫系统', ('免疫系统', '淋巴结', '脾', '胸腺', '淋巴')),
    ('皮肤', ('皮肤', '表皮', '真皮', '毛囊', '汗腺')),
    ('消化管', ('消化管', '食管', '胃', '小肠', '大肠', '胃底腺')),
    ('消化腺', ('消化腺', '肝', '胰腺', '唾液腺')),
    ('呼吸系统', ('呼吸系统', '气管', '肺', '肺泡')),
    ('泌尿系统', ('泌尿系统', '肾', '肾单位', '膀胱')),
    ('男性生殖系统', ('男性生殖', '睾丸', '附睾', '前列腺')),
    ('女性生殖系统', ('女性生殖', '卵巢', '子宫', '输卵管')),
    ('内分泌系统', ('内分泌', '甲状腺', '肾上腺', '垂体', '胰岛')),
    ('感觉器官', ('感觉器官', '眼球', '内耳', '视网膜', '味蕾')),
    ('胚胎学', ('胚胎', '受精', '植入', '胎盘')),
)

STAINS = (
    ('HE染色', re.compile(r'\bH\s*[-／/]?\s*E\b|苏木精|伊红', re.I)),
    ('PAS染色', re.compile(r'\bPAS\b|过碘酸|雪夫', re.I)),
    ('银染', re.compile(r'银染|嗜银|亲银|硝酸银')),
    ('甲苯胺蓝', re.compile(r'甲苯胺蓝')),
    ('免疫组化', re.compile(r'免疫组化|免疫组织化学|免疫荧光')),
    ('瑞氏-姬姆萨', re.compile(r'瑞氏|姬姆萨|Giemsa', re.I)),
)

NUMBERED = re.compile(r'^\s*([1-9]\d{0,2})\s*[.．、]\s*(.+)$')
CJK = re.compile(r'[\u4e00-\u9fff]')


def _lines(page):
    return [line for line in page.get('lines', [])
            if isinstance(line, dict) and isinstance(line.get('text'), str)]


def _page_text(page):
    parts = [page.get('text')] if isinstance(page.get('text'), str) else []
    parts.extend(line['text'] for line in _lines(page))
    return ' '.join(parts)


def detect_tissue(text):
    scores = []
    for name, keywords in TISSUES:
        hits = sum(text.count(keyword) for keyword in keywords)
        if hits:
            scores.append((hits, name))
    if not scores:
        return '', 0
    scores.sort(reverse=True)
    return scores[0][1], scores[0][0]


def detect_stains(text):
    return [name for name, pattern in STAINS if pattern.search(text)]


def detect_structures(page, limit=6):
    """只取原文自己编号的小标题；截成短名，重复合并。"""
    found = []
    for line in _lines(page):
        match = NUMBERED.match(line['text'].strip())
        if not match:
            continue
        title = re.sub(r'\s+', '', match.group(2)).strip('：:。.,，')
        if not 3 <= len(title):
            continue
        short = title[:20]
        if short not in found:
            found.append(short)
        if len(found) >= limit:
            break
    return found


def build(source_path=DEFAULT_SOURCE, output_path=DEFAULT_OUTPUT):
    source = Path(source_path)
    if not source.is_file():
        raise SystemExit('找不到 %s；识图标注只能从本机组胚资料生成' % source)
    data = json.loads(source.read_text(encoding='utf-8'))

    pages = []
    for page in data.get('pages', []):
        if not isinstance(page, dict):
            continue
        number = page.get('image_number')
        image = page.get('image')
        if not isinstance(number, int) or not isinstance(image, str):
            continue
        text = _page_text(page)
        tissue, score = detect_tissue(text)
        structures = detect_structures(page)
        pages.append({
            'image_number': number,
            'image': image,
            'source_page': number,
            'tissue': tissue,
            'tissue_hits': score,
            'stains': detect_stains(text),
            'structures': structures,
            'review_status': 'pending',
            'provenance': '从本机 OCR 文本与原文编号小标题机械抽取；未经教师审核，可能错、可能漏',
        })

    payload = {
        'schema_version': 1,
        'generated_from': source.name,
        'requires_teacher_review': True,
        'notice': ('标注由脚本从 OCR 文本机械抽取，未经医学教师审核；'
                   '只能用于识别页面主题，不能据此认定切片结构或染色结果。'),
        'pages': pages,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    usable = [page for page in pages if page['tissue'] or page['structures']]
    print('已写入 %s：%d 页，其中可出题 %d 页' % (output.name, len(pages), len(usable)))
    return payload


def main():
    parser = argparse.ArgumentParser(description='从本机组胚 OCR 生成待审核标注')
    parser.add_argument('--source', default=str(DEFAULT_SOURCE))
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == '__main__':
    main()