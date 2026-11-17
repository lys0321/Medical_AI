"""Practice hints.

两套提示并存，由调用方决定用哪一套：

1. `hint_text()` —— 原来的「分析思路」模板（先列条件、再比较选项），文案优先取
   课程包里的 hints 模板，课程包缺失或写坏时退回内置默认话术，避免因为一个提示
   模板就让 /api/hint 直接 500。
2. `page_hint_text()` —— 现在学习评估默认用这一套。学生反馈「分析思路」对以记忆
   为主的知识点没有帮助，所以改成给教材出处：书名、印刷页码、那一页讲的是什么，
   再附一句原文片段，方便合上书之前先回书核对。

两套提示都不透露正确答案；看过提示的要点照样计为「辅助练习」，不能作为独立掌握
证据（判定逻辑在 server.request_hint）。
"""
from knowledge import HINTS

FALLBACK = {
    'level1': '先单独分析“{label}”：列出题干给出的条件与限制，再比较选项。',
    'transfer': '先找出与原情境相同和变化的条件，只在题干给出的定位范围内推理，再说明排除其他选项的依据。',
    'diagnostic': '按“结构或通路 → 对应功能 → 可能表现”口述依据。遇到“所有、必然”等表述，检查题干是否支持这样的范围。',
}

NO_PAGE = ('这三本教材（局部解剖学 / 生理学 / 生物化学）没有直接讲到“%s”这一处；'
           '本题的判断依据来自公开神经科资料，可在“文献漫游”里查原始出处。')
NO_PAGE_STEP2 = ('本地教材索引里暂时没有“%s”这一处的页码。先按结构或通路 → 功能 → 表现的顺序'
                 '自己把依据说一遍，再到“文献漫游”核对公开资料；教材页码可在导入扫描件后补充。')
NO_MORE = ('教材里与“%s”直接相关的就上面这些页了；再看下去要看机制或病理生理，'
           '建议回看知识卡，或直接在“我的学习”里提问。')


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


def page_hint_text(concept, question, index, level, lookup):
    """level 1 给首要出处，level 2 给同一知识点的另一处出处。

    lookup(concept, question, index) -> [{'book', 'page', 'label', 'snippet'}, ...]
    由调用方注入，避免本模块依赖教材索引。
    """
    hits = lookup(concept, question, index) or []
    if not hits:
        # 没有教材索引时两级提示也要给出不同、且诚实的话术：
        # 第一级说明没有页码，第二级给出可操作的复习路径，避免两步一模一样。
        return (NO_PAGE if level == 1 else NO_PAGE_STEP2) % concept['name']
    if level > len(hits):
        return NO_MORE % concept['name']
    hit = hits[level - 1]
    where = '《%s》P%s' % (hit['book'], hit['page'])
    if hit.get('label'):
        where += '｜' + hit['label']
    snippet = hit.get('snippet') or ''
    if snippet:
        return '%s —— 原文：“%s”' % (where, snippet)
    return where