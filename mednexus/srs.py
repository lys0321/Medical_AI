"""FSRS-lite：可配置的间隔重复模型（纯函数，无 IO）。

设计取舍
--------
真正的 FSRS 有十几个权重，需要在大量复习记录上拟合。这里只保留它最关键的三个
概念，参数少到可以被人工审核：

  · stability   稳定度，单位为“天”。数值上等于“复习后经过多少天，记得的概率降到
                目标保持率”。所以 interval_days(S) 在默认参数下恰好等于 S。
  · difficulty  难度 1–10，初始 5。答对降一点、答错升一点，用来调节稳定度的增长
                速度（难题涨得慢），不直接决定间隔。
  · last_review 上一次**有效证据**的时间。只有它才重置遗忘曲线。

遗忘曲线用 FSRS 的形式：R(t) = (1 + t / (9S))^(-1)；反解出“什么时候该复习”：

    interval_days(S) = 9S · (1/target − 1)        target 默认 0.9 → 等于 S

稳定度更新（只在“独立完成迁移题”时发生）：

    R  = 复习时刻的可提取度
    S' = S · clamp(1 + (15 − 1.2·D)·(1 − R), 1.1, 3.0)

答错（任何得分低于 0.8 的作答）视为遗忘：

    S' = clamp(S · 0.35, 0.3, 1.0)      → 间隔最长 1 天，复习立刻回到近期
    D' = D + 1.2

刻意**不**推进稳定度的情况（与项目原有证据纪律一致）：
  · 借助提示、教学对话或自由文本判分完成的作答（``assisted``）；
  · 同一天内重复的成功作答（只有当天第一次成功计数）；
  · 只做了诊断题、还没做迁移题。

状态不写数据库：每次由作答历史重放得到（``derive_state``），所以没有迁移成本，
也不会出现“状态与记录不一致”。这是工程近似，不是经过验证的记忆模型。
"""
from datetime import datetime, timedelta, timezone

DAY = 86400
SHANGHAI = timezone(timedelta(hours=8))

PASS_SCORE = 0.8
TARGET_RETENTION = 0.9
DECAY = 9.0

INITIAL_STABILITY = 1.0
MIN_STABILITY = 0.3
MAX_STABILITY = 365.0

DEFAULT_DIFFICULTY = 5.0
MIN_DIFFICULTY = 1.0
MAX_DIFFICULTY = 10.0
SUCCESS_DIFFICULTY_DELTA = -0.4
FAILURE_DIFFICULTY_DELTA = 1.2

LAPSE_FACTOR = 0.35
LAPSE_MAX_STABILITY = 1.0

GROWTH_BASE = 15.0
GROWTH_DIFFICULTY_WEIGHT = 1.2
MIN_GROWTH = 1.1
MAX_GROWTH = 3.0


def _clamp(value, low, high):
    return max(low, min(value, high))


def day_of(timestamp):
    """按上海时区取"学习日"，与计划的其它部分保持一致。"""
    return datetime.fromtimestamp(timestamp, SHANGHAI).date()


def new_state():
    return {'difficulty': DEFAULT_DIFFICULTY, 'stability': 0.0, 'last_review': None,
            'last_success_day': None, 'reps': 0, 'lapses': 0}


def retrievability(stability, elapsed_days):
    """经过 elapsed_days 天后还记得的概率；时间倒流按 0 处理。"""
    if stability <= 0:
        return 1.0
    elapsed = max(0.0, float(elapsed_days))
    return (1.0 + elapsed / (DECAY * stability)) ** -1.0


def interval_days(stability, target=TARGET_RETENTION):
    """从当前稳定度反解出建议间隔（天）。"""
    if stability <= 0:
        return 0.0
    if not 0 < target < 1:
        raise ValueError('目标保持率必须在 0 与 1 之间')
    return DECAY * stability * (1.0 / target - 1.0)


def due_at(state, target=TARGET_RETENTION):
    """到期时间戳；还没有任何有效证据时返回 None。"""
    if state['last_review'] is None or state['stability'] <= 0:
        return None
    return state['last_review'] + interval_days(state['stability'], target) * DAY


def retrievability_now(state, now, target=TARGET_RETENTION):
    """当前可提取度；没有有效证据时返回 None。"""
    if state['last_review'] is None or state['stability'] <= 0:
        return None
    return retrievability(state['stability'], (now - state['last_review']) / DAY)


def growth(difficulty, r):
    return _clamp(1.0 + (GROWTH_BASE - GROWTH_DIFFICULTY_WEIGHT * difficulty) * (1.0 - r),
                  MIN_GROWTH, MAX_GROWTH)


def review(state, event, target=TARGET_RETENTION):
    """把一次作答结算进状态，返回新状态（不修改入参）。

    ``event`` 需要 ``created`` / ``score``，可选 ``kind`` 与 ``assisted``。
    """
    created = event.get('created')
    score = event.get('score')
    if not isinstance(created, (int, float)) or not isinstance(score, (int, float)):
        return dict(state)

    if score < PASS_SCORE:
        stability = state['stability']
        stability = _clamp(stability * LAPSE_FACTOR if stability > 0 else MIN_STABILITY,
                           MIN_STABILITY, LAPSE_MAX_STABILITY)
        return {**state,
                'difficulty': _clamp(state['difficulty'] + FAILURE_DIFFICULTY_DELTA,
                                     MIN_DIFFICULTY, MAX_DIFFICULTY),
                'stability': stability,
                'last_review': created,
                'lapses': state['lapses'] + 1}

    # 只有"独立完成的迁移题"才算推进证据；提示、对话、同日重复都不算。
    if event.get('kind') != 'transfer' or event.get('assisted') is True:
        return dict(state)

    day = day_of(created)
    if state['last_success_day'] == day:
        return dict(state)

    previous = state['last_review']
    elapsed = 0.0 if previous is None else max(0.0, (created - previous) / DAY)
    if state['stability'] <= 0:
        stability = INITIAL_STABILITY
    else:
        r = retrievability(state['stability'], elapsed)
        stability = min(state['stability'] * growth(state['difficulty'], r), MAX_STABILITY)

    return {**state,
            'difficulty': _clamp(state['difficulty'] + SUCCESS_DIFFICULTY_DELTA,
                                 MIN_DIFFICULTY, MAX_DIFFICULTY),
            'stability': stability,
            'last_review': created,
            'last_success_day': day,
            'reps': state['reps'] + 1}


def derive_state(events, target=TARGET_RETENTION):
    """按时间顺序重放作答历史，得到当前状态；乱序输入会先排序。"""
    state = new_state()
    for event in sorted(events, key=lambda item: item['created']):
        state = review(state, event, target)
    return state


def describe(state, now, target=TARGET_RETENTION):
    """给计划条目用的可读数字（不含结论，只报告模型当前认为的量）。"""
    return {'difficulty': round(state['difficulty'], 2),
            'stability_days': round(state['stability'], 2) if state['stability'] else 0.0,
            'interval_days': round(interval_days(state['stability'], target), 2),
            'retrievability': (round(retrievability_now(state, now, target), 3)
                               if state['stability'] else None),
            'lapses': state['lapses']}