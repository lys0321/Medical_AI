"""组胚识图练习：从本机“待审核”标注生成选择题。

为什么是选择题而不是“在图上点结构”
------------------------------------
本机的 55 张图是**复习笔记扫描页**，OCR 框是文字行的框，不是切片里的解剖结构位置。
凭空给结构画框等于编造医学标注，所以这里只做能核实的事：给一页图，问它的小标题是哪个。

题目、选项和正确答案全部来自本机 ``histology_labels.json`` 里由 OCR 抽出的编号小标题，
正确答案本身就在那张图上，可人工核对。标注仍标 ``pending``（待教师审核）。

可选视觉模型只用于生成"描述辅助"，不参与判分、不进选项、不作为答案依据。
"""
import json
import random
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_LABELS = HERE / 'data' / 'course_materials' / 'histology_labels.json'

OPTION_COUNT = 4
MAX_HEADING = 24
REVIEW_NOTICE = ('标注待教师审核：由 OCR 机械抽取、未经医学教师核对；'
                 '本练习只考查能否认出资料页的小标题，不代表能辨认切片结构或染色结果。')
NO_LABELS = ('本机还没有组胚识图标注。先运行 tools/build_histology_labels.py 生成，'
             '或直接在“课程资料与题库”里阅读原图。')


def load_labels(path=DEFAULT_LABELS):
    """读取标注；文件缺失或损坏时返回不可用，不抛异常。"""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        return {'available': False, 'reason': 'no_labels', 'message': NO_LABELS,
                'pages': [], 'detail': str(error)[:200]}
    pages = data.get('pages')
    if not isinstance(pages, list):
        return {'available': False, 'reason': 'no_labels', 'message': NO_LABELS,
                'pages': [], 'detail': '标注文件缺少 pages'}
    cleaned = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        number = page.get('image_number')
        image = page.get('image')
        structures = [item for item in page.get('structures', [])
                      if isinstance(item, str) and item.strip()][:6]
        if not isinstance(number, int) or not isinstance(image, str) or not structures:
            continue
        cleaned.append({'image_number': number, 'image': image, 'structures': structures,
                        'tissue': page.get('tissue') if isinstance(page.get('tissue'), str) else '',
                        'stains': [s for s in page.get('stains', []) if isinstance(s, str)][:4],
                        'source_page': page.get('source_page'),
                        'review_status': page.get('review_status') or 'pending'})
    if not cleaned:
        return {'available': False, 'reason': 'no_usable_labels', 'pages': [],
                'message': '组胚标注里没有可出题的条目（缺少编号小标题），请先补充或重新抽取。'}
    return {'available': True, 'reason': '', 'pages': cleaned,
            'requires_teacher_review': bool(data.get('requires_teacher_review')),
            'notice': data.get('notice', ''), 'message': ''}


def _headings(pages):
    out = []
    for page in pages:
        for heading in page['structures']:
            text = re.sub(r'\s+', '', heading)[:MAX_HEADING]
            if len(text) >= 3 and text not in out:
                out.append(text)
    return out


def candidates(labels):
    """可出题的页：必须有小标题，且全局小标题足够凑出选项。"""
    if not labels.get('available'):
        return []
    if len(_headings(labels['pages'])) < OPTION_COUNT:
        return []
    return list(labels['pages'])


def build_question(labels, rng=None, option_count=OPTION_COUNT):
    """随机挑一页出题；返回的字典含 answer，调用方必须剔除后再下发。"""
    pool = candidates(labels)
    if not pool:
        return None
    rng = rng or random.SystemRandom()
    page = rng.choice(pool)
    answer = re.sub(r'\s+', '', page['structures'][0])[:MAX_HEADING]
    others = [heading for heading in _headings(labels['pages']) if heading != answer]
    if len(others) < option_count - 1:
        return None
    distractors = rng.sample(others, option_count - 1)
    options = [answer] + distractors
    rng.shuffle(options)
    return {'image_number': page['image_number'], 'image': page['image'],
            'image_url': '/api/course-materials/images/' + page['image'],
            'prompt': '第 %d 页资料的小标题是下面哪一项？' % page['image_number'],
            'options': options, 'answer': answer,
            'tissue': page['tissue'], 'stains': page['stains'],
            'source_page': page['source_page'], 'review_status': page['review_status']}


def public(question, token):
    """下发给浏览器的题目：不含正确答案。"""
    return {'token': token, 'kind': 'image', 'mode': 'page-heading',
            'image_number': question['image_number'], 'image_url': question['image_url'],
            'prompt': question['prompt'], 'options': list(question['options']),
            'review_status': question['review_status'] or 'pending',
            'notice': REVIEW_NOTICE}


def grade(question, choice):
    if not isinstance(choice, str) or choice not in question['options']:
        raise ValueError('请选择一个选项')
    return {'correct': choice == question['answer'], 'answer': question['answer'], 'choice': choice}


def summarize(rows):
    """图片题的独立统计；绝不与三要点分数混合。"""
    total = len(rows)
    correct = sum(1 for row in rows if float(row.get('score') or 0) >= 1)
    numbers = set()
    for row in rows:
        payload = row.get('payload')
        try:
            payload = json.loads(payload) if isinstance(payload, str) else payload
        except ValueError:
            payload = {}
        if isinstance(payload, dict) and isinstance(payload.get('image_number'), int):
            numbers.add(payload['image_number'])
    return {'attempts': total, 'correct': correct,
            'accuracy': round(correct / total, 3) if total else None,
            'pages_seen': len(numbers),
            'last_at': max((row.get('created') or 0) for row in rows) if rows else None,
            'scope': '仅组胚识图练习；不计入三要点评分或掌握度'}