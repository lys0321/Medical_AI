"""循证学习态势引擎（Evidence-grounded learning pulse）。

把学习者"怎么学"的诚实信号——而非"学得多好"的成绩——量化成四维态势：
  1. 循证提问：近 7 天带教材依据的提问占比（evidence）
  2. 掌握质量：已掌握 / 已测评（mastery，未测评不计入分母）
  3. 闭环补救：需巩固点中已被编排进今日计划的比例（loop）
  4. 学习节奏：连续天数与活跃天数（consistency）

设计纪律（与 evidence.py / galaxy.py 一致）：
  - 只描述本机真实行为，不评分能力、不评价医学水平。
  - 未测评一律返回 None（"未测量"），绝不当作 0 分惩罚。
  - 所有数值都来自 /api/overview 已有字段，不新增采集、不编造。
  - 纯函数：不改入参、不依赖时间以外的外部状态、同输入同输出。
"""

_WEIGHTS = {"evidence": 0.25, "mastery": 0.35, "loop": 0.25, "consistency": 0.15}

_LEVELS = [(85, "扎实"), (60, "积累"), (30, "起步"), (0, "萌芽")]


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _round(value):
    return int(round(value))


def _ratio(num, den):
    if not isinstance(num, (int, float)) or not isinstance(den, (int, float)):
        return None
    if den <= 0:
        return None
    return min(1.0, max(0.0, float(num) / float(den)))


def _dimension(key, label, value, detail, note):
    return {"key": key, "label": label, "value": value, "detail": detail, "note": note}


def _level_of(index):
    if index is None:
        return "尚未开始"
    for threshold, name in _LEVELS:
        if index >= threshold:
            return name
    return "萌芽"


def _headline(dimensions, index):
    measured = [d for d in dimensions if d["value"] is not None]
    if not measured:
        return "还没有学习记录。完成第一次测评和提问后，这里会显示你的循证学习态势。"
    strongest = max(measured, key=lambda d: d["value"])
    weakest = min(measured, key=lambda d: d["value"])
    if strongest["key"] == weakest["key"]:
        return "你的「" + strongest["label"] + "」已有记录，继续保持规律学习。"
    return "你的「" + strongest["label"] + "」表现稳定；「" + weakest["label"] \
        + "」还有提升空间。这是行为观察，不是成绩排名。"


def build_pulse(overview, *, now=None):
    """从 /api/overview 数据构造循证学习态势。

    参数 overview：dict，至少可含 questions / stats / learning_plan / learning_time。
    返回 JSON 可序列化字典；任何脏数据都降级为"未测量"，不抛异常。
    """
    ov = _safe_dict(overview)
    questions = _safe_dict(ov.get("questions"))
    stats = _safe_dict(ov.get("stats"))
    plan = _safe_dict(ov.get("learning_plan"))
    ltime = _safe_dict(ov.get("learning_time"))

    # 1) 循证提问：近 7 天带教材依据的提问占比
    ev = _ratio(questions.get("week_cited"), questions.get("week"))
    evidence = _dimension(
        "evidence", "循证提问",
        _round(ev * 100) if ev is not None else None,
        (str(questions.get("week_cited")) + "/" + str(questions.get("week")) + " 次提问带教材依据")
        if ev is not None else "近 7 天还没有提问",
        "看的是提问是否有出处，不是提问多少。",
    )

    # 2) 掌握质量：已掌握 / 已测评（未测评不算分母）
    ma = _ratio(stats.get("mastered"), stats.get("assessed"))
    mastery = _dimension(
        "mastery", "掌握质量",
        _round(ma * 100) if ma is not None else None,
        (str(stats.get("mastered")) + "/" + str(stats.get("assessed")) + " 个已测评知识点达标")
        if ma is not None else "还没有知识点完成测评",
        "只看测评过的知识点，未测评不扣分。",
    )

    # 3) 闭环补救：需巩固点中被编排进今日计划的比例
    weak = stats.get("weak") if isinstance(stats.get("weak"), int) else 0
    assessed = stats.get("assessed") if isinstance(stats.get("assessed"), int) else 0
    remediated = 0
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    for item in items:
        if isinstance(item, dict) and "orchestration" in str(item.get("origin", "")):
            remediated += 1
    if assessed <= 0:
        lo_value, lo_detail = None, "还没有测评，谈不上补救闭环"
    elif weak <= 0:
        lo_value, lo_detail = 100, "当前没有需要巩固的知识点"
    else:
        coverage = min(1.0, remediated / float(weak))
        lo_value = _round(coverage * 100)
        lo_detail = str(weak) + " 个需巩固点，" + str(remediated) + " 个已排入今日补救"
    loop = _dimension("loop", "闭环补救", lo_value, lo_detail,
                      "衡量薄弱点是否被接住，不代表已经掌握。")

    # 4) 学习节奏：连续天数 / 7（活跃天数作佐证）
    streak = ltime.get("streak_days") if isinstance(ltime.get("streak_days"), int) else 0
    active_days = ltime.get("active_days") if isinstance(ltime.get("active_days"), int) else 0
    if active_days <= 0:
        co_value, co_detail = None, "还没有学习时长记录"
    else:
        co_value = _round(min(1.0, streak / 7.0) * 100)
        co_detail = "连续 " + str(streak) + " 天 · 累计活跃 " + str(active_days) + " 天"
    consistency = _dimension("consistency", "学习节奏", co_value, co_detail,
                             "只看本机前台学习计时，翻页不算。")

    dimensions = [evidence, mastery, loop, consistency]

    # 综合指数：只对已测量维度加权平均（权重重新归一），全未测量则为 None。
    total_w = sum(_WEIGHTS[d["key"]] for d in dimensions if d["value"] is not None)
    if total_w > 0:
        weighted = sum(_WEIGHTS[d["key"]] * d["value"] for d in dimensions
                       if d["value"] is not None)
        index = _round(weighted / total_w)
    else:
        index = None

    return {
        "index": index,
        "level": _level_of(index),
        "dimensions": dimensions,
        "headline": _headline(dimensions, index),
        "disclaimer": "这是本机学习行为的诚实观察，不是能力评分，也不代表医学水平。",
        "source": "本地真实作答与提问数据",
    }
