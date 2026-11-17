"""第五代编排闭环：诊断误区 → 变式重测 → 遗忘曲线安排 → 计划更新建议。

纯函数（stdlib only）：没有数据库写入、网络或模型调用，也不读取全局课程数据。
所有医学文本都来自传入的 ``attempt`` 的 rubric 与 ``question`` 的 points 原文；
本模块只做归纳、编排与时间安排，不生成新的医学事实，也不判定"已掌握"。

与现有模块的分工：
  · srs.py       —— 提供重测时机（due_at / interval_days / lapse 约束）。
  · planning.py  —— 提供观察层（薄弱点、今日计划、作答历史清洗规则）。
  · tutoring.py  —— 提示来源：本模块只建议用哪一套提示，不生成提示文本。

证据纪律
--------
  · 变式只能用 question.points 原文（label/correct/reason/options/category）。
  · 误区类别只按 rubric 对错的 category 统计得出，不推断任何医学结论。
  · 只产出建议与重测安排，从不给出"已掌握"判断。
  · 未来时间戳、时间倒退、损坏记录一律安全降级，不崩溃。
"""
import json
import math
import time

import planning
import srs


DAY = 86400

# question.points.category -> 误区类别。只是归类规则，不含医学内容。
MISCONCEPTION_BY_CATEGORY = {
    '概念记忆': '记忆缺失',
    '机制理解': '概念混淆',
    '应用迁移': '推理断裂',
}
MISCONCEPTION_TYPES = ('记忆缺失', '概念混淆', '推理断裂', 'unknown')

# 可操作的补救方向：学习策略话术，不描述任何医学事实。
REMEDIATION_TEXT = {
    '记忆缺失': ('先按 rubric 原文逐字复述下列要点，再合上材料独立回忆；'
                 '重测仍以原题要点原文为准，用短间隔反复提取。'),
    '概念混淆': ('把下列要点与同题其它要点按 label 与 category 逐一对照，'
                 '说明各自考察的不同侧面，再独立复述；不要引入题目之外的推断。'),
    '推理断裂': ('沿题干给出的条件，按“条件 → 机制 → 表现”逐点口述依据，'
                 '检查是否跳步或扩大了题干支持的范围。'),
    'unknown': ('rubric 缺失，或没有可判定的错误要点；先用原题 rubric 做一次'
                '独立诊断作答，再据此判断误区类别，不凭猜测归类。'),
}

# 变式角度：同一个 category 决定"换哪个侧面复述"，全部复用题目原文。
VARIATION_ANGLE = {
    '记忆缺失': '换一个时间点复述同一要点的 rubric 原文（脱稿回忆），只考察是否记住原文表述。',
    '概念混淆': '把该要点与同题另一要点放在一起辨识，按各自 category 区分侧面，均只用题目原文。',
    '推理断裂': '只给题干条件，请按该要点 reason 原文的表述顺序重述依据链，不添加新信息。',
    'unknown': '按原 rubric 原文重述该要点并独立作答，先收集可判定的证据，不新增内容。',
}

# 提示来源：只建议调用 tutoring 的哪一套，不生成提示文本、不透露答案。
HINT_SOURCE = {
    '记忆缺失': {'method': 'page_hint_text',
                 'reason': '先回教材出处核对原 rubric 要点，再脱离材料回忆；提示只给定位，不给结论。'},
    '概念混淆': {'method': 'hint_text',
                 'reason': '用思路模板逐点列条件与限制，对照相邻要点辨析；提示不透露答案。'},
    '推理断裂': {'method': 'hint_text',
                 'reason': '用思路模板按条件→机制→表现逐点口述依据，检查是否跳步；提示不透露答案。'},
    'unknown': {'method': 'page_hint_text',
                'reason': '缺少可判定的误区证据，先按教材出处回看原题要点，独立作答后再诊断。'},
}

_EVIDENCE_NOTE = ('仅使用 attempts 的 rubric 原文与 question.points 原文；'
                  '变式不新增医学事实；重测时机由 srs 计算；不判定已掌握。')


# ---------------------------------------------------------------- 基础工具

def _now(now):
    """确定性的时间锚点：非有限 now 直接报错（与 planning.build_plan 一致）。"""
    if now is None:
        return time.time()
    value = float(now)
    if not math.isfinite(value):
        raise ValueError('now must be a finite timestamp')
    return value


def _finite_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _rubric_of(attempt):
    """兼容 {rubric:[...]}、payload dict 与 payload JSON 字符串三种形态。"""
    if not isinstance(attempt, dict):
        return []
    direct = attempt.get('rubric')
    if isinstance(direct, list):
        return direct
    payload = attempt.get('_payload')
    if payload is None:
        payload = attempt.get('payload')
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return []
    if isinstance(payload, dict):
        candidate = payload.get('rubric')
        if isinstance(candidate, list):
            return candidate
    return []


def _weak_labels(attempt):
    """严格按 correct is False 取错误要点标签（与 planning._weak_points 一致）。"""
    labels = []
    for point in _rubric_of(attempt):
        if (isinstance(point, dict) and point.get('correct') is False
                and isinstance(point.get('label'), str) and point['label'] not in labels):
            labels.append(point['label'])
    return labels


def _points_of(question):
    if not isinstance(question, dict):
        return []
    points = question.get('points')
    return points if isinstance(points, list) else []


def _category_map(question):
    """label -> category，只从 question.points 原文取。"""
    mapping = {}
    for point in _points_of(question):
        if (isinstance(point, dict) and isinstance(point.get('label'), str)
                and isinstance(point.get('category'), str) and point['category'].strip()):
            mapping.setdefault(point['label'], point['category'])
    return mapping


def _category_order(question):
    """category 在题目中首次出现的顺序，作为并列时的确定性 tie-break。"""
    order = []
    for point in _points_of(question):
        category = point.get('category') if isinstance(point, dict) else None
        if isinstance(category, str) and category not in order:
            order.append(category)
    return order


def _misconception_type(category):
    if not isinstance(category, str):
        return 'unknown'
    return MISCONCEPTION_BY_CATEGORY.get(category, category if category in MISCONCEPTION_TYPES else 'unknown')


def _valid_state(state):
    return (isinstance(state, dict)
            and _finite_number(state.get('last_review'))
            and _finite_number(state.get('stability')))


def _retest_timing(srs_state, now):
    """复用 srs 的间隔/due；把实际重测时间约束在 [now, now + DAY]。

    答错后的复习应在 1 天内；无有效证据则立即重测。未来/损坏时间戳经 clamp
    后不会给出离谱时间，也不会抛异常。
    """
    if not _valid_state(srs_state):
        return {'due_at': now, 'interval_days': 0.0, 'model_due_at': None,
                'basis': '无有效 srs 状态，按答错处理，立即安排重测。'}
    due = srs.due_at(srs_state)
    interval = srs.interval_days(srs_state['stability'])
    if due is None or due <= now:
        return {'due_at': now, 'interval_days': round(interval, 2), 'model_due_at': due,
                'basis': '尚无有效复习证据或已到期，立即重测（符合答错拉回近期的规则）。'}
    if due >= now + DAY:
        return {'due_at': now + DAY, 'interval_days': round(interval, 2), 'model_due_at': due,
                'basis': '模型到期时间超过 1 天，按答错后的上限约束到 1 天内重测。'}
    return {'due_at': due, 'interval_days': round(interval, 2), 'model_due_at': due,
            'basis': '按 srs.due_at 安排重测。'}


# ---------------------------------------------------------------- 公开 API

def diagnose_misconception(attempt, question):
    """从一次作答的 rubric 对错归纳误区类别，并给可操作补救方向。

    返回 ``{category, wrong_labels, evidence, counts, remediation, basis}``。
    category 由错误要点的 category 统计得出，只能是三类之一或 unknown；
    不编造任何医学结论，也不读取题目之外的知识。
    """
    rubric = _rubric_of(attempt)
    label_to_category = _category_map(question)

    evidence, counts = [], {}
    wrong_labels = []
    order = _category_order(question)
    for point in rubric:
        if not (isinstance(point, dict) and point.get('correct') is False
                and isinstance(point.get('label'), str)):
            continue
        label = point['label']
        if label not in wrong_labels:
            wrong_labels.append(label)
        category = point.get('category')
        if not isinstance(category, str) or not category.strip():
            category = label_to_category.get(label)
        if not isinstance(category, str) or not category.strip():
            continue
        if category not in order:
            order.append(category)
        evidence.append({'label': label, 'category': category})
        counts[category] = counts.get(category, 0) + 1

    category = 'unknown'
    if counts:
        dominant = sorted(counts.items(), key=lambda item: (-item[1], order.index(item[0])))[0][0]
        category = _misconception_type(dominant)

    return {
        'category': category,
        'wrong_labels': wrong_labels,
        'evidence': evidence,
        'counts': counts,
        'remediation': REMEDIATION_TEXT[category],
        'basis': 'rubric 中 correct is False 的要点 + question.points.category；未引入任何医学结论。',
    }


def build_remediation(concept, question, misconception, *, srs_state=None, now=None):
    """产出一次"变式重测"任务，只复用 question.points 原文，不新编医学事实。

    ``misconception`` 接受 :func:`diagnose_misconception` 的返回值或类别字符串。
    ``srs_state`` 为 srs.derive_state 的输出，用于计算重测时机。
    """
    anchor = _now(now)
    if isinstance(misconception, str):
        category = _misconception_type(misconception)
        labels = []
    elif isinstance(misconception, dict):
        category = _misconception_type(misconception.get('category'))
        raw_labels = misconception.get('wrong_labels')
        labels = [label for label in raw_labels if isinstance(label, str)] if isinstance(raw_labels, list) else []
    else:
        category, labels = 'unknown', []

    points = _points_of(question)
    by_label = {point['label']: point for point in points
                if isinstance(point, dict) and isinstance(point.get('label'), str)}
    # 优先重测诊断出的错误要点；诊断不出来时保守地覆盖原题全部要点。
    targets = [by_label[label] for label in labels if label in by_label]
    if not targets:
        targets = list(points)

    def material(point):
        options = point.get('options')
        return {
            'label': point.get('label'),
            'correct': point.get('correct'),
            'reason': point.get('reason'),
            'options': list(options) if isinstance(options, list) else [],
            'category': point.get('category'),
        }

    materials = [material(point) for point in targets if isinstance(point, dict)]
    timing = _retest_timing(srs_state, anchor)
    concept_id = concept.get('id') if isinstance(concept, dict) else None
    concept_name = concept.get('name') if isinstance(concept, dict) else None
    question_id = question.get('id') if isinstance(question, dict) else None
    count = len(materials)

    return {
        'concept': concept_id,
        'concept_name': concept_name,
        'question': question_id,
        'action': 'review',
        'kind': 'transfer',
        'misconception': category,
        'retest_points': [{'label': item['label'], 'category': item['category'],
                           'correct': item['correct'], 'reason': item['reason']}
                          for item in materials],
        'variation': {
            'angle': VARIATION_ANGLE[category],
            'source': 'question.points',
            'point_count': count,
            'materials': materials,
        },
        'due_at': timing['due_at'],
        'interval_days': timing['interval_days'],
        'model_due_at': timing['model_due_at'],
        'timing_basis': timing['basis'],
        'reason': ('围绕%s安排 %d 个原题要点的变式重测：%s 重测时间 %s。'
                   % (category, count, timing['basis'],
                      '立即' if timing['due_at'] <= anchor else '按 srs 到期时间')),
        'assisted': False,
        'mastery_claimed': False,
        'evidence_note': _EVIDENCE_NOTE,
    }


def _find_question(concept, attempt):
    """question 可能是对象，也可能是指向 concept['questions'] 的 id。"""
    if not isinstance(attempt, dict):
        return None
    reference = attempt.get('question')
    if isinstance(reference, dict):
        return reference
    if not isinstance(concept, dict):
        return None
    questions = concept.get('questions')
    if not isinstance(questions, list):
        return None
    for question in questions:
        if isinstance(question, dict) and question.get('id') == reference:
            return question
    return None


def _events(rows):
    """把清洗后的作答行整理成 srs.review 所需的纯数据。"""
    return [{'created': row['created'], 'score': row['score'], 'kind': row.get('kind'),
             'assisted': _assisted(row)}
            for row in rows]


def _assisted(row):
    payload = row.get('_payload')
    return isinstance(payload, dict) and payload.get('assisted') is True


def _clean_attempts(concepts, attempts, now):
    """按 planning 的规则清洗：未知概念、未来/损坏记录一律不进入闭环。"""
    known = {concept['id']: concept for concept in concepts
             if isinstance(concept, dict) and isinstance(concept.get('id'), str)}
    histories = {cid: [] for cid in known}
    for order, row in enumerate(attempts if isinstance(attempts, list) else []):
        if not isinstance(row, dict) or row.get('concept') not in known:
            continue
        created, score = row.get('created'), row.get('score')
        if not (_finite_number(created) and _finite_number(score)):
            continue
        if not 0 <= score <= 1 or created > now:
            continue
        payload = row.get('_payload', row.get('payload'))
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (ValueError, TypeError):
                payload = {'assisted': True}
        if not isinstance(payload, dict):
            payload = {'assisted': True}
        histories[row['concept']].append({**row, 'created': created, 'score': score,
                                          '_payload': payload, '_order': order})
    for rows in histories.values():
        rows.sort(key=lambda row: (row['created'], row['_order']))
    return known, histories


def loop_step(concepts, attempts, *, now=None):
    """把学习者当前状态编排成闭环快照。

    观察(薄弱点) → 诊断 → 选下一个补救活动 → 提示来源 → 重测时间 → 计划更新建议。
    返回全为 JSON 可序列化的纯数据，可直接交给 /api/report 或前端消费。
    """
    anchor = _now(now)
    # planning.build_plan 假定每条记录是 dict；先在这里挡掉完全损坏的项，
    # 让整个闭环对残缺历史也不崩溃（不改原列表，只传清洗后的副本）。
    rows = [row for row in attempts if isinstance(row, dict)] if isinstance(attempts, list) else []
    plan = planning.build_plan(concepts, rows, now=anchor)
    known, histories = _clean_attempts(concepts, rows, anchor)

    plan_order = {item.get('concept'): index for index, item in enumerate(plan['items'])}

    def finding(cid):
        rows = histories.get(cid) or []
        if not rows:
            return None
        last = rows[-1]
        weak = _weak_labels(last)
        if last['score'] >= 0.8 and not weak:
            return None
        target = last if last['score'] < 0.8 else next(
            (row for row in reversed(rows) if row['score'] < 0.8), last)
        question = _find_question(known[cid], target)
        return {'concept': cid, 'name': known[cid].get('name'),
                'weak_points': weak or _weak_labels(target),
                'question': question, 'rows': rows,
                'last_created': last['created']}

    findings = [item for item in (finding(cid) for cid in known) if item is not None]
    findings.sort(key=lambda item: (plan_order.get(item['concept'], len(plan_order)),
                                    -item['last_created']))

    diagnoses = []
    for item in findings[:5]:
        result = diagnose_misconception(item['rows'][-1] if item['rows'][-1]['score'] < 0.8
                                        else next((row for row in reversed(item['rows'])
                                                   if row['score'] < 0.8), item['rows'][-1]),
                                        item['question'])
        diagnoses.append({'concept': item['concept'], 'name': item['name'],
                          'question': item['question'].get('id') if isinstance(item['question'], dict) else None,
                          **result})

    next_activity, hint_source, plan_update = None, HINT_SOURCE['unknown'], {
        'action': 'none', 'position': None, 'proposed_item': None,
        'reason': '当前没有需要补救的薄弱点，保持现有计划不变。',
    }
    retest_at = None
    if diagnoses:
        primary = diagnoses[0]
        target = next(item for item in findings if item['concept'] == primary['concept'])
        state = srs.derive_state(_events(target['rows']))
        next_activity = build_remediation(known[primary['concept']], target['question'],
                                          primary, srs_state=state, now=anchor)
        hint_source = HINT_SOURCE[primary['category']]
        retest_at = next_activity['due_at']
        proposal = {
            'concept': primary['concept'],
            'name': primary['name'],
            'action': 'review',
            'kind': 'transfer',
            'reason': next_activity['reason'],
            'due_at': retest_at,
            'weak_points': primary['wrong_labels'],
        }
        plan_update = {
            'action': 'prepend',
            'position': 0,
            'proposed_item': proposal,
            'reason': ('把诊断后的变式重测前置到今日计划；只新增建议，不改写历史记录，'
                       '也不判定已掌握。'),
        }

    all_weak = list(dict.fromkeys(label for item in findings for label in item['weak_points']))
    return {
        'observed_at': anchor,
        'observation': {
            'weak_count': plan['counts']['weak'],
            'weak_concepts': [item['concept'] for item in findings],
            'weak_points': all_weak,
            'plan_counts': plan['counts'],
            'source': 'planning.build_plan + 结构化作答记录',
        },
        'diagnoses': diagnoses,
        'next_activity': next_activity,
        'hint_source': hint_source,
        'retest_at': retest_at,
        'plan_update': plan_update,
        'evidence_discipline': {'mastery_claimed': False, 'note': _EVIDENCE_NOTE},
    }
