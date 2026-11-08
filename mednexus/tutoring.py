"""Source-independent reasoning scaffolds; never disclose scoring keys as hints.

提示文案优先用课程包里的 hints 模板；课程包缺失或写坏时退回内置默认话术，
避免因为一个提示模板就让 /api/hint 直接 500。
"""
from knowledge import HINTS

FALLBACK = {
    'level1': '先单独分析“{label}”：列出题干给出的条件与限制，再比较选项。',
    'transfer': '先找出与原情境相同和变化的条件，只在题干给出的定位范围内推理，再说明排除其他选项的依据。',
    'diagnostic': '按“结构或通路 → 对应功能 → 可能表现”口述依据。遇到“所有、必然”等表述，检查题干是否支持这样的范围。',
}


def _template(key):
    value = HINTS.get(key) if isinstance(HINTS, dict) else None
    return value if isinstance(value, str) and value.strip() else FALLBACK[key]


def hint_text(question, index, level):
    point = question['points'][index]
    if level == 1:
        return _template('level1').format(label=point['label'])
    if question['kind'] == 'transfer':
        return _template('transfer')
    return _template('diagnostic')