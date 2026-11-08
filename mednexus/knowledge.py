r"""Course content lives in data/courses/anatomy.json and is validated at import time.

Author-written teaching examples. All goals and rubrics require teacher review.
No textbook pages are asserted here. Questions use structured point-level answers
so offline grading does not mistake a keyword or a negated sentence for knowledge.

加载策略：用非严格模式。某个知识点或题目写坏了就单独丢掉并打印原因，其余内容照常
服务——课程包出错不应该让整个网页打不开。想让它有问题就报错退出，用
``python course_loader.py`` 跑严格校验。

换课程包（例如加一门新学科）不用改代码：
    set MEDNEXUS_COURSE_PACKAGE=D:\path\to\another.json
"""
import json
import os
import sys
from pathlib import Path

from course_loader import load_course_package

DATA = Path(__file__).resolve().parent / 'data'
DEFAULT_PACKAGE = DATA / 'courses' / 'anatomy.json'
SYLLABUS_PATH = DATA / 'course_materials' / 'syllabus.json'
PACKAGE_PATH = Path(os.environ.get('MEDNEXUS_COURSE_PACKAGE') or DEFAULT_PACKAGE)


def local_syllabus_ids(path=SYLLABUS_PATH):
    """本机大纲里可用的条目 id；没有这份私有资料时返回 None（不做命中校验）。"""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    items = data.get('items')
    if not isinstance(items, list):
        return None
    return {item['id'] for item in items
            if isinstance(item, dict) and isinstance(item.get('id'), str)}


_PACKAGE = load_course_package(PACKAGE_PATH, strict=False, syllabus_ids=local_syllabus_ids())
CONCEPTS = _PACKAGE['concepts']
CONCEPT_MAP = _PACKAGE['concept_map']
QUESTION_MAP = _PACKAGE['question_map']
COURSE = _PACKAGE['course']
SOURCES = _PACKAGE['sources']
HINTS = _PACKAGE['hints']
PACKAGE_PROBLEMS = tuple(_PACKAGE['problems'])
PACKAGE_WARNINGS = tuple(_PACKAGE['warnings'])


def _announce():
    for message in PACKAGE_PROBLEMS:
        print('[course-package] 错误：' + message, file=sys.stderr)
    for message in PACKAGE_WARNINGS:
        print('[course-package] 提示：' + message, file=sys.stderr)
    if PACKAGE_PROBLEMS:
        print('[course-package] 已跳过上述问题条目，其余内容照常提供；'
              '严格校验请运行 python course_loader.py', file=sys.stderr)


_announce()