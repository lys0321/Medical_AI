"""Course package loading and validation.

两种模式，共用同一套检查逻辑：

``strict=True``（默认）
    汇总所有结构问题后抛出 ``CoursePackageError``。CI、发布前检查和测试用这个。

``strict=False``
    坏掉的条目单独丢弃，问题写进 ``problems``，其余条目照常可用。服务启动用这个，
    这样一个知识点写坏了不会把整个网页拖下水——页还能打开，控制台会明确报错。

``problems`` 与 ``warnings`` 分开：前者在 strict 模式下致命；后者只提示，例如某个
知识点还没有映射大纲条目。两者都会返回并由调用方打印。
"""
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


def _empty_package(problems=None, warnings=None):
    return {'course': {}, 'concepts': [], 'concept_map': {}, 'question_map': {},
            'sources': {}, 'hints': {}, 'problems': list(problems or []),
            'warnings': list(warnings or [])}


# ---------------------------------------------------------------- 单条校验

def _check_course(data, problems):
    course = data.get('course')
    if isinstance(course, dict):
        if not _nonempty(course.get('goal_source')):
            problems.append('course.goal_source 必须是非空字符串')
        return dict(course)
    if 'course' in data:
        problems.append('course 必须是对象')
    return {}


def _check_chapters(raw, problems):
    """返回 id -> 章节（只含通过校验的条目）。"""
    if 'chapters' in raw and not isinstance(raw['chapters'], list):
        problems.append('chapters 必须是数组')
    chapters = {}
    items = raw.get('chapters') if isinstance(raw.get('chapters'), list) else []
    for index, chapter in enumerate(items, 1):
        if not isinstance(chapter, dict):
            problems.append('第 {} 个章节必须是对象'.format(index))
            continue
        cid = chapter.get('id')
        ref = _ref(cid, '第 {} 个章节'.format(index))
        if not _nonempty(cid):
            problems.append('{}缺少有效的 id'.format(ref))
            continue
        if cid in chapters:
            problems.append('章节 id 重复：{}'.format(cid))
            continue
        if not _nonempty(chapter.get('name')):
            problems.append('章节 {} 缺少有效的 name'.format(ref))
            continue
        chapters[cid] = chapter
    return chapters


def _check_sources(raw, problems):
    if 'sources' in raw and not isinstance(raw['sources'], dict):
        problems.append('sources 必须是对象')
    sources = raw.get('sources') if isinstance(raw.get('sources'), dict) else {}
    return {key: value for key, value in sources.items() if _nonempty(key)}


def _check_syllabus_refs(concept, label, syllabus_ids, problems, warnings):
    """大纲映射：类型错误算问题，空映射和查不到的条目算警告（绝不猜测补全）。"""
    refs = concept.get('syllabus_refs', [])
    if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
        problems.append('知识点 {} 的 syllabus_refs 必须是字符串数组'.format(label))
        return []
    cleaned = [item.strip() for item in refs if _nonempty(item)]
    if not cleaned:
        warnings.append('知识点 {} 还没有映射任何大纲条目，界面不会显示“对应大纲要求”'.format(label))
        return []
    if syllabus_ids is not None:
        for item in cleaned:
            if item not in syllabus_ids:
                warnings.append('知识点 {} 映射的 {} 不在本机大纲中，界面不会显示该条'.format(label, item))
    return cleaned


def _check_concept(concept, index, chapters, sources, query, seen_ids, syllabus_ids, problems, warnings):
    """返回 (可用的知识点, 问题列表)；不合格时知识点为 None。"""
    if not isinstance(concept, dict):
        return None, ['第 {} 个知识点必须是对象'.format(index)]
    problems = []
    cid = concept.get('id')
    ref = _ref(cid, '第 {} 个知识点'.format(index))
    if not _nonempty(cid):
        return None, ['{}缺少有效的 id'.format(ref)]
    if cid in seen_ids:
        return None, ['知识点 id 重复：{}'.format(cid)]
    if not _nonempty(concept.get('name')):
        problems.append('知识点 {} 缺少有效的 name'.format(ref))
    if not isinstance(concept.get('chapter'), str) or concept['chapter'] not in chapters:
        problems.append('知识点 {} 的 chapter 引用无效：{!r}'.format(ref, concept.get('chapter')))
    if not isinstance(concept.get('source'), str) or concept['source'] not in sources:
        problems.append('知识点 {} 的 source 引用无效：{!r}'.format(ref, concept.get('source')))
    if not _nonempty(query.get(cid)):
        problems.append('知识点 {} 缺少有效的 query'.format(cid))
    refs = _check_syllabus_refs(concept, ref, syllabus_ids, problems, warnings)
    if problems:
        return None, problems
    item = dict(concept)
    item.pop('questions', None)
    item['syllabus_refs'] = refs
    item['query'] = query[cid]
    return item, []


def _check_question(question, index, declared_ids, seen_ids):
    """返回 (可用的题目, 问题列表)；不合格时题目为 None。"""
    if not isinstance(question, dict):
        return None, ['第 {} 道题目必须是对象'.format(index)]
    problems = []
    qid = question.get('id')
    ref = _ref(qid, '第 {} 道题目'.format(index))
    if not _nonempty(qid):
        return None, ['{}缺少有效的 id'.format(ref)]
    if qid in seen_ids:
        return None, ['题目 id 重复：{}'.format(qid)]
    owner = question.get('concept')
    if not (isinstance(owner, str) and owner in declared_ids):
        problems.append('题目 {} 的 concept 引用无效：{!r}'.format(ref, owner))
    if question.get('kind') not in QUESTION_KINDS:
        problems.append('题目 {} 的 kind 无效（只能是 diagnostic 或 transfer）'.format(ref))
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
    if problems:
        return None, problems
    # 保留 concept 字段用于挂载；真正挂到知识点上时会去掉它，运行结构里不重复。
    return dict(question), []


# ---------------------------------------------------------------- 入口

def load_course_package(path, strict=True, syllabus_ids=None):
    """读取并校验课程包。

    ``syllabus_ids``：本机大纲里可用的条目 id 集合。传 None 表示本机没有大纲，
    此时不校验映射是否命中，只提示“未映射”。
    """
    path = Path(path)
    problems, warnings = [], []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        message = '课程数据包读取失败：{}（{}）'.format(path.name, exc)
        if strict:
            raise CoursePackageError(message) from exc
        return _empty_package([message], warnings)
    if not isinstance(data, dict):
        message = '课程数据包必须是 JSON 对象：{}'.format(path.name)
        if strict:
            raise CoursePackageError(message)
        return _empty_package([message], warnings)

    for key in REQUIRED_KEYS:
        if key not in data:
            problems.append('缺少必需的顶层字段：{}'.format(key))

    course = _check_course(data, problems)
    chapters = _check_chapters(data, problems)
    sources = _check_sources(data, problems)

    if 'concepts' in data and not isinstance(data['concepts'], list):
        problems.append('concepts 必须是数组')
    if 'questions' in data and not isinstance(data['questions'], list):
        problems.append('questions 必须是数组')
    if 'query' in data and not isinstance(data['query'], dict):
        problems.append('query 必须是对象')
    if 'hints' in data and not isinstance(data['hints'], dict):
        problems.append('hints 必须是对象')

    raw_concepts = data.get('concepts') if isinstance(data.get('concepts'), list) else []
    raw_questions = data.get('questions') if isinstance(data.get('questions'), list) else []
    query = data.get('query') if isinstance(data.get('query'), dict) else {}
    hints = data.get('hints') if isinstance(data.get('hints'), dict) else {}

    declared_ids = {item['id'] for item in raw_concepts
                    if isinstance(item, dict) and _nonempty(item.get('id'))}
    for key in query:
        if key not in declared_ids:
            problems.append('query 包含未声明知识点的条目：{}'.format(key))
    for key in hints:
        if key not in HINT_TEMPLATE_KEYS and key not in declared_ids:
            problems.append('hints 包含未声明知识点的条目：{}'.format(key))

    concepts, concept_ids = [], set()
    for index, raw in enumerate(raw_concepts, 1):
        item, item_problems = _check_concept(raw, index, chapters, sources, query,
                                            concept_ids, syllabus_ids, problems, warnings)
        problems.extend(item_problems)
        if item is not None:
            concept_ids.add(item['id'])
            concepts.append(item)

    questions, question_ids = [], set()
    for index, raw in enumerate(raw_questions, 1):
        item, item_problems = _check_question(raw, index, declared_ids, question_ids)
        problems.extend(item_problems)
        if item is not None:
            question_ids.add(item['id'])
            questions.append(item)

    by_concept = {}
    for question in questions:
        by_concept.setdefault(question['concept'], []).append(question)

    kept = []
    for concept in concepts:
        attached = by_concept.get(concept['id'], [])
        kinds = {question['kind'] for question in attached}
        missing = [kind for kind in QUESTION_KINDS if kind not in kinds]
        if missing:
            for kind in missing:
                problems.append('知识点 {} 缺少 {} 题目'.format(concept['id'], kind))
            continue
        concept['questions'] = [{key: value for key, value in question.items() if key != 'concept'}
                                for question in attached]
        kept.append(concept)

    used = {question['id'] for concept in kept for question in concept['questions']}
    for question in questions:
        if question['id'] not in used:
            warnings.append('题目 {} 没有可用的知识点，未载入'.format(question['id']))

    if strict and problems:
        raise CoursePackageError('课程数据包校验失败：\n' + '\n'.join(problems))

    chapter_names = {cid: chapter['name'] for cid, chapter in chapters.items()}
    for concept in kept:
        concept['unit'] = chapter_names[concept['chapter']]

    concept_map = {concept['id']: concept for concept in kept}
    question_map = {question['id']: (concept, question)
                    for concept in kept for question in concept['questions']}
    course_out = dict(course)
    course_out['units'] = [chapter['name'] for chapter in chapters.values()]
    return {'course': course_out, 'concepts': kept, 'concept_map': concept_map,
            'question_map': question_map, 'sources': sources, 'hints': hints,
            'problems': problems, 'warnings': warnings}


def main():
    import argparse

    parser = argparse.ArgumentParser(description='校验课程包（严格模式，有问题就返回非零）')
    parser.add_argument('path', nargs='?', default=str(Path(__file__).resolve().parent / 'data' / 'courses' / 'anatomy.json'))
    args = parser.parse_args()
    package = load_course_package(args.path, strict=False)
    for message in package['problems']:
        print('[错误] ' + message)
    for message in package['warnings']:
        print('[警告] ' + message)
    print('知识点 %d 个，题目 %d 道，来源 %d 条'
          % (len(package['concepts']), len(package['question_map']), len(package['sources'])))
    return 0 if not package['problems'] else 1


if __name__ == '__main__':
    raise SystemExit(main())