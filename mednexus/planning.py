"""Deterministic learning suggestions from this learner's actual structured attempts.

This module has no database writes, model calls or inferred medical answers.
复习间隔由 ``srs.py`` 的 FSRS-lite 模型算出：状态由作答历史重放得到，没有新增
数据库字段。它仍是工程近似，不是经过验证的记忆模型。

证据纪律保持不变：只有"独立完成的迁移题"推进稳定度；借助提示、教学对话、同日
重复作答都不推进；答错立刻把复习拉回 1 天内。
"""
from datetime import datetime, timedelta, timezone
import json
import math
import os
import time

import srs


SHANGHAI = timezone(timedelta(hours=8))
DAY = 86400


def _env_int(name, default):
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_ratio(name, default):
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if 0 < value < 1 else default


# 每日新知识点上限、计划条数、目标保持率都可配置（环境变量或 build_plan 参数）。
DAILY_NEW_LIMIT = _env_int('MEDNEXUS_DAILY_NEW_LIMIT', 2)
PLAN_LIMIT = _env_int('MEDNEXUS_PLAN_LIMIT', 5)
TARGET_RETENTION = _env_ratio('MEDNEXUS_SRS_TARGET', srs.TARGET_RETENTION)


def _day(timestamp):
    return datetime.fromtimestamp(timestamp, SHANGHAI).date()


def _payload(row):
    value = row.get('payload', {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {'assisted': True}
    # A damaged historical record cannot establish independent success.
    return value if isinstance(value, dict) else {'assisted': True}


def _weak_points(row):
    rubric = row['_payload'].get('rubric', []) if row else []
    if not isinstance(rubric, list):
        return []
    return list(dict.fromkeys(
        point['label'][:100] for point in rubric
        if isinstance(point, dict) and point.get('correct') is False
        and isinstance(point.get('label'), str)
    ))[:3]


def _events(rows):
    """把作答记录整理成 srs 需要的纯数据。"""
    return [{'created': row['created'], 'score': row['score'], 'kind': row.get('kind'),
             'assisted': row['_payload'].get('assisted') is True}
            for row in rows]


def build_plan(concepts, attempts, active=None, now=None, *,
               daily_new_limit=None, plan_limit=None, target_retention=None):
    """Return at most ``plan_limit`` actionable items; callers filter attempts by learner.

    ``concepts`` is the existing progress() output and ``attempts`` comes from
    attempts_get(). IDs outside these concepts, future entries, and invalid scores
    do not affect the plan. Legacy payloads without ``assisted`` are independent.

    Due/weak counts concern the entire chapter, not just the visible items.
    ``new`` counts all unassessed concepts. ``practiced_today`` counts distinct
    concepts attempted on the current Shanghai day. New items in the daily plan
    are capped, less concepts first attempted today and an unfinished new item
    already shown as ``resume``.

    复习排序：先按"弱项 / 待迁移 / 到期复习"分组，同一组内按当前可提取度从低到高，
    也就是最可能已经忘掉的排在前面。
    """
    now = time.time() if now is None else float(now)
    if not math.isfinite(now):
        raise ValueError('now must be a finite timestamp')
    daily_new_limit = DAILY_NEW_LIMIT if daily_new_limit is None else int(daily_new_limit)
    plan_limit = PLAN_LIMIT if plan_limit is None else int(plan_limit)
    target = TARGET_RETENTION if target_retention is None else float(target_retention)
    if not 0 < target < 1:
        raise ValueError('目标保持率必须在 0 与 1 之间')

    today = _day(now)
    known = {concept['id']: concept for concept in concepts}
    histories = {cid: [] for cid in known}
    for order, row in enumerate(attempts):
        if row.get('concept') not in known:
            continue
        try:
            created, score = float(row['created']), float(row['score'])
        except (KeyError, ValueError, TypeError):
            continue
        if not math.isfinite(created) or not math.isfinite(score) or not 0 <= score <= 1 or created > now:
            continue
        histories[row['concept']].append({**row, 'created': created, 'score': score,
                                         '_payload': _payload(row), '_order': order})
    for rows in histories.values():
        rows.sort(key=lambda row: (row['created'], row['_order']))

    reviews, upcoming, unseen = [], [], []
    weak_count = 0
    practiced_today = 0
    new_started_today = 0
    for position, concept in enumerate(concepts):
        cid = concept['id']
        rows = histories[cid]
        if not rows:
            unseen.append(concept)
            continue
        practiced_today += any(_day(row['created']) == today for row in rows)
        new_started_today += _day(rows[0]['created']) == today
        last = rows[-1]
        item = {'concept': cid, 'name': concept['name'], 'action': 'review',
                'kind': 'diagnostic', 'reason': '', 'due_at': last['created'],
                'last_score': round(last['score'] * 100), 'weak_points': _weak_points(last)}
        if last['score'] < .8:
            weak_count += 1
            item['reason'] = '最近作答未达标，先回顾缺失要点，再独立复测基础。'
            reviews.append((0, last['score'], last['created'], position, item))
            continue

        last_failure = next((index for index in range(len(rows)-1, -1, -1)
                             if rows[index]['score'] < .8), -1)
        cycle = rows[last_failure + 1:]
        independent = [row for row in cycle if row['score'] >= .8
                       and row['_payload'].get('assisted') is not True]
        diagnostic = [row for row in independent if row.get('kind') == 'diagnostic']
        transfer = [row for row in independent if row.get('kind') == 'transfer']
        if not transfer:
            item['kind'] = 'transfer'
            item['reason'] = ('上次借助提示完成，仍需独立完成迁移复测。'
                              if last['_payload'].get('assisted') is True else
                              '诊断题已达标，再换一个情境独立完成迁移题。')
            reviews.append((1, 0, last['created'], position, item))
            continue
        if not diagnostic:
            item['reason'] = '迁移题已有独立作答，基础诊断仍需独立复核。'
            reviews.append((1, 0, last['created'], position, item))
            continue

        # 稳定度只由"独立迁移成功"推进；同日重复与辅助作答在 srs.review 里被忽略。
        state = srs.derive_state(_events(rows), target)
        info = srs.describe(state, now, target)
        due = srs.due_at(state, target)
        if due is None:                      # 已有独立迁移成功，理论上不会为空
            due = last['created']
        retrievability = info['retrievability'] if info['retrievability'] is not None else 1.0
        item['due_at'] = due
        item['kind'] = 'transfer'
        item['difficulty'] = info['difficulty']
        item['stability_days'] = info['stability_days']
        item['interval_days'] = info['interval_days']
        item['retrievability'] = info['retrievability']
        item['reason'] = ('独立迁移达标后按遗忘曲线安排复习：稳定度 {:.1f} 天，建议间隔 {:.1f} 天，'
                          '当前可提取度 {:.0%}；请独立回忆再作答。'
                          .format(info['stability_days'], info['interval_days'], retrievability))
        if due <= now:
            reviews.append((2, retrievability, due, position, item))
        else:
            upcoming.append(due)

    reviews.sort(key=lambda entry: entry[:4])
    items = []
    active_cid = active.get('concept') if isinstance(active, dict) else None
    if active_cid in known:
        concept = known[active_cid]
        rows = histories[active_cid]
        existing = next((entry[-1] for entry in reviews if entry[-1]['concept'] == active_cid), None)
        items.append({'concept': active_cid, 'name': concept['name'], 'action': 'resume',
                      'kind': 'auto', 'reason': '继续未完成的题目，保留当前作答任务。',
                      'due_at': existing['due_at'] if existing else None,
                      'last_score': round(rows[-1]['score'] * 100) if rows else None,
                      'weak_points': _weak_points(rows[-1]) if rows else []})
    items.extend(entry[-1] for entry in reviews if entry[-1]['concept'] != active_cid)
    new_budget = max(0, daily_new_limit - new_started_today)
    if active_cid in known and not histories[active_cid]:
        new_budget = max(0, new_budget - 1)
    for concept in unseen:
        if new_budget <= 0 or len(items) >= plan_limit:
            break
        if concept['id'] == active_cid:
            continue
        items.append({'concept': concept['id'], 'name': concept['name'], 'action': 'learn',
                      'kind': 'diagnostic', 'reason': '尚无作答记录，先用三个要点了解当前掌握情况。',
                      'due_at': None, 'last_score': None, 'weak_points': []})
        new_budget -= 1
    return {'scope': f'脑神经示例章节 · {len(concepts)}个知识点',
            'method': '优先未完成任务、薄弱要点与到期复习；每天最多安排{}个新知识点。'
                      '复习间隔由 FSRS-lite 计算（目标保持率 {:.0%}）：只有独立完成的迁移题才推进稳定度，'
                      '答错立刻把复习拉回 1 天内，同日重复或借助提示的高分不推进；'
                      '到期项按可提取度从低到高排序。不是经验证的记忆模型。'
                      .format(daily_new_limit, target),
            'counts': {'due': len(reviews), 'weak': weak_count, 'new': len(unseen),
                       'practiced_today': practiced_today},
            'srs': {'model': 'FSRS-lite', 'target_retention': target,
                    'daily_new_limit': daily_new_limit, 'plan_limit': plan_limit},
            'next_due_at': min(upcoming) if upcoming else None,
            'items': items[:plan_limit]}