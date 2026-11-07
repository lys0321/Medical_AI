"""Course package loading: every structural problem is reported before learning code sees the data."""
import json
from pathlib import Path


class CoursePackageError(ValueError):
    """The course package file is missing data or fails validation."""


REQUIRED_KEYS = ('course', 'chapters', 'sources', 'concepts', 'questions', 'hints', 'query')
QUESTION_KINDS = ('diagnostic', 'transfer')
# 提示模板的保留键；其余键按知识点 id 解释，必须指向已声明的知识点。
HINT_TEMPLATE_KEYS = frozenset({'level1', 'diagnostic', 'transfer'})


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _ref(valid_id, fallback):
    """错误信息里优先用条目 id，缺 id 时退回位置描述。"""
    return valid_id if _nonempty(valid_id) else fallback


def load_course_package(path):
    """读取 JSON 课程包并组装运行结构；任何问题都先汇总抛出，不做部分载入。"""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise CoursePackageError('课程数据包读取失败：{}（{}）'.format(path.name, exc)) from exc
    if not isinstance(data, dict):
        raise CoursePackageError('课程数据包必须是 JSON 对象：{}'.format(path.name))

    problems = []
    for key in REQUIRED_KEYS:
        if key not in data:
            problems.append('缺少必需的顶层字段：{}'.format(key))

    course = data.get('course')
    if isinstance(course, dict):
        if not _nonempty(course.get('goal_source')):
            problems.append('course.goal_source 必须是非空字符串')
    elif 'course' in data:
        problems.append('course 必须是对象')

    chapters = data.get('chapters') if isinstance(data.get('chapters'), list) else []
    if 'chapters' in data and not isinstance(data['chapters'], list):
        problems.append('chapters 必须是数组')
    chapter_ids = set()
    for index, chapter in enumerate(chapters, 1):
        if not isinstance(chapter, dict):
            problems.append('第 {} 个章节必须是对象'.format(index))
            continue
        cid = chapter.get('id')
        ref = _ref(cid, '第 {} 个章节'.format(index))
        if not _nonempty(cid):
            problems.append('{}缺少有效的 id'.format(ref))
        elif cid in chapter_ids:
            problems.append('章节 id 重复：{}'.format(cid))
        else:
            chapter_ids.add(cid)
        if not _nonempty(chapter.get('name')):
            problems.append('章节 {} 缺少有效的 name'.format(ref))

    sources = data.get('sources') if isinstance(data.get('sources'), dict) else {}
    if 'sources' in data and not isinstance(data['sources'], dict):
        problems.append('sources 必须是对象')
    source_ids = {key for key in sources if _nonempty(key)}

    raw_concepts = data.get('concepts') if isinstance(data.get('concepts'), list) else []
    if 'concepts' in data and not isinstance(data['concepts'], list):
        problems.append('concepts 必须是数组')
    concept_ids = set()
    for index, concept in enumerate(raw_concepts, 1):
        if not isinstance(concept, dict):
            problems.append('第 {} 个知识点必须是对象'.format(index))
            continue
        cid = concept.get('id')
        ref = _ref(cid, '第 {} 个知识点'.format(index))
        if not _nonempty(cid):
            problems.append('{}缺少有效的 id'.format(ref))
        elif cid in concept_ids:
            problems.append('知识点 id 重复：{}'.format(cid))
        else:
            concept_ids.add(cid)
        if not isinstance(concept.get('chapter'), str) or concept['chapter'] not in chapter_ids:
            problems.append('知识点 {} 的 chapter 引用无效：{!r}'.format(ref, concept.get('chapter')))
        if not isinstance(concept.get('source'), str) or concept['source'] not in source_ids:
            problems.append('知识点 {} 的 source 引用无效：{!r}'.format(ref, concept.get('source')))
        refs = concept.get('syllabus_refs', [])
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            problems.append('知识点 {} 的 syllabus_refs 必须是字符串数组'.format(ref))

    raw_questions = data.get('questions') if isinstance(data.get('questions'), list) else []
    if 'questions' in data and not isinstance(data['questions'], list):
        problems.append('questions 必须是数组')
    question_ids = set()
    kinds_by_concept = {}
    for index, question in enumerate(raw_questions, 1):
        if not isinstance(question, dict):
            problems.append('第 {} 道题目必须是对象'.format(index))
            continue
        qid = question.get('id')
        ref = _ref(qid, '第 {} 道题目'.format(index))
        if not _nonempty(qid):
            problems.append('{}缺少有效的 id'.format(ref))
        elif qid in question_ids:
            problems.append('题目 id 重复：{}'.format(qid))
        else:
            question_ids.add(qid)
        owner = question.get('concept')
        owner_known = isinstance(owner, str) and owner in concept_ids
        if not owner_known:
            problems.append('题目 {} 的 concept 引用无效：{!r}'.format(ref, owner))
        kind = question.get('kind')
        if kind not in QUESTION_KINDS:
            problems.append('题目 {} 的 kind 无效（只能是 diagnostic 或 transfer）'.format(ref))
        elif owner_known:
            kinds_by_concept.setdefault(owner, set()).add(kind)
        if not _nonempty(question.get('prompt')):
            problems.append('题目 {} 的 prompt 为空'.format(ref))
        points = question.get('points')
        if not isinstance(points, list) or len(points) != 3:
            problems.append('题目 {} 的 points 必须恰好包含 3 个要点'.format(ref))
        else:
            for p_index, point in enumerate(points, 1):
                if not isinstance(point, dict):
                    problems.append('题目 {} 第 {} 个要点必须是对象'.format(ref, p_index))
                    continue
                for field in ('label', 'correct', 'reason', 'category'):
                    if not _nonempty(point.get(field)):
                        problems.append('题目 {} 第 {} 个要点的 {} 为空'.format(ref, p_index, field))
                options = point.get('options')
                if (not isinstance(options, list) or len(options) != 4
                        or not all(_nonempty(option) for option in options)
                        or len(set(options)) != 4):
                    problems.append('题目 {} 第 {} 个要点的 options 必须是 4 个互不重复的非空字符串'.format(ref, p_index))
                elif _nonempty(point.get('correct')) and point['correct'] not in options:
                    problems.append('题目 {} 第 {} 个要点的 options 未包含 correct'.format(ref, p_index))

    for concept in raw_concepts:
        if isinstance(concept, dict) and _nonempty(concept.get('id')):
            missing = [kind for kind in QUESTION_KINDS
                       if kind not in kinds_by_concept.get(concept['id'], set())]
            for kind in missing:
                problems.append('知识点 {} 缺少 {} 题目'.format(concept['id'], kind))

    query = data.get('query') if isinstance(data.get('query'), dict) else {}
    if 'query' in data and not isinstance(data['query'], dict):
        problems.append('query 必须是对象')
    for concept in raw_concepts:
        if isinstance(concept, dict) and _nonempty(concept.get('id')):
            if not _nonempty(query.get(concept['id'])):
                problems.append('知识点 {} 缺少有效的 query'.format(concept['id']))
    for key in query:
        if key not in concept_ids:
            problems.append('query 包含未声明知识点的条目：{}'.format(key))

    hints = data.get('hints') if isinstance(data.get('hints'), dict) else {}
    if 'hints' in data and not isinstance(data['hints'], dict):
        problems.append('hints 必须是对象')
    for key in hints:
        if key not in HINT_TEMPLATE_KEYS and key not in concept_ids:
            problems.append('hints 包含未声明知识点的条目：{}'.format(key))

    if problems:
        raise CoursePackageError('课程数据包校验失败：\n' + '\n'.join(problems))

    # 校验通过后按运行时的既有结构组装：知识点归章节名，题目按文件顺序挂回知识点。
    chapter_names = {chapter['id']: chapter['name'] for chapter in chapters}
    question_objects = {q['id']: {k: v for k, v in q.items() if k != 'concept'}
                        for q in raw_questions}
    concepts = []
    for source in raw_concepts:
        item = dict(source)
        item['unit'] = chapter_names[item.pop('chapter')]
        item.setdefault('syllabus_refs', [])
        item['query'] = query[item['id']]
        item['questions'] = [question_objects[q['id']] for q in raw_questions
                             if q['concept'] == item['id']]
        concepts.append(item)

    concept_map = {concept['id']: concept for concept in concepts}
    question_map = {question['id']: (concept, question)
                    for concept in concepts for question in concept['questions']}
    course_out = dict(course)
    course_out['units'] = [chapter['name'] for chapter in chapters]
    return {'course': course_out, 'concepts': concepts, 'concept_map': concept_map,
            'question_map': question_map, 'sources': sources, 'hints': hints}
