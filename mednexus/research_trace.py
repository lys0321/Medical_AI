"""循证研究链路：把一次真实检索转成可核验的五步路线图。

这不是"自动写综述"，也不产生医学结论。它只把已经发生的确定性事实按固定
顺序摆出来：研究疑问 → 检索式 → 证据类型构成 → 逐篇核对项 → 结论边界。
每一步都能回到用户输入的原文、PubMed PMID 或 PubMed 官方文献类型；
没有检索结果时后几步明确显示"待完成"，不补造摘要、结论或质量评分。
"""
import re

import evidence

SCHEMA_VERSION = 1

# 问题类型只用于选择"应该核对什么"的提示，不用于推断答案。
_QUESTION_PATTERNS = (
    ('intervention', '干预 / 效果类问题',
     re.compile(r'治疗|干预|疗效|效果|药物|手术|康复|预防|剂量|联合|treatment|therap|intervention|drug|surgery|rehabilit|prevent|dose', re.I)),
    ('diagnosis', '诊断 / 准确性类问题',
     re.compile(r'诊断|准确率|敏感度|特异度|筛查|误诊|漏诊|预测值|diagnos|sensitiv|specific|screen|false positive|false negative', re.I)),
    ('mechanism', '机制 / 差异类问题',
     re.compile(r'机制|原因|病因|风险|关联|差异|为什么|影响|通路|mechanism|etiolog|risk|associat|differ|why|pathway|factor', re.I)),
    ('prognosis', '预后 / 随访类问题',
     re.compile(r'预后|恢复|随访|复发|生存|进展|结局|prognos|recover|follow[- ]?up|relapse|surviv|progress|outcome', re.I)),
    ('measurement', '测量 / 指标类问题',
     re.compile(r'指标|测量|定量|评分|量表|检测|评估方法|measure|quantit|score|scale|assay|detect|evaluat', re.I)),
)

_FOCUS_HINT = {
    'intervention': '这类问题需要核对研究对象、干预、对照与结局是否可比；摘要里没有对照不等于研究没有对照。',
    'diagnosis': '这类问题需要核对参考标准、敏感度与特异度；单项检查结果不能脱离研究背景解释。',
    'mechanism': '这类问题要区分关联与因果，并检查是否报告了混杂因素；机制解释通常要回到基础教材。',
    'prognosis': '这类问题需要核对人群、随访时长与结局定义；短期恢复不等于长期预后。',
    'measurement': '这类问题需要核对信度、效度与测量条件；相关性不等于一致性。',
    'explore': '这是开放探索问题；先把比较对象、条件与结局说清楚，再判断检索结果是否回答了它。',
}

_CANNOT_HINT = {
    'intervention': '不能仅凭"随机"字样或文献类型判断疗效；效应大小、置信区间与偏倚风险要读原文。',
    'diagnosis': '不能仅凭摘要里的敏感度或特异度下诊断结论；研究人群与参考标准会改变数值含义。',
    'mechanism': '不能把相关性当成因果，也不能用一篇机制研究解释全部病例。',
    'prognosis': '不能把某个人群的恢复比例直接套用到另一个人群；需核对基线与随访差异。',
    'measurement': '不能把一个指标的统计相关性当成临床可替代性；需核对一致性与测量条件。',
    'explore': '不能把检索结果直接当作对原疑问的回答；要逐篇判断是否真的回答了同一个问题。',
}

NOTICE = ('这是检索与阅读的留痕路线，不是医学结论，也不是证据质量评级。'
          'PubMed 只返回本次取到的条目，不代表全部已发表证据；请通过 PMID 核对原文。')


def _clip(value, limit=150):
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


def question_type(question):
    """返回 (key, 中文标签)。仅决定核对清单，不决定任何医学结论。"""
    text = str(question or '')
    for key, label, pattern in _QUESTION_PATTERNS:
        if pattern.search(text):
            return key, label
    return 'explore', '证据探索类问题'


def _audit(papers):
    """从摘要原文抽取"还有哪些字段需要人工核对"的计数，不评分。"""
    total = len(papers)
    assessed = sample = random = blind = 0
    for paper in papers:
        try:
            fields = evidence.assess(paper)['fields']
        except (TypeError, ValueError):
            continue
        assessed += 1
        if fields['sample_size']['status'] == 'reported':
            sample += 1
        if fields['randomization']['status'] == 'reported':
            random += 1
        if fields['blinding']['status'] == 'reported':
            blind += 1
    return {
        'total': total,
        'assessed': assessed,
        'sample_reported': sample,
        'randomization_mentioned': random,
        'blinding_mentioned': blind,
        'summary': '本次 %d 篇中，摘要可核对：样本量 %d 篇、随机化 %d 篇、盲法 %d 篇。' % (
            total, sample, random, blind),
        'notice': '未提到不等于原文没有报告；字段只提示该去原文核对什么，不参与评分。',
    }


def build_trace(question, query, mapping='', papers=None, mix=None):
    """构造五步研究链路。纯函数：同输入必得同输出，不修改入参。"""
    question = _clip(question, 300)
    query = _clip(query, 1500)
    mapping = _clip(mapping, 240)
    papers = papers if isinstance(papers, list) else []
    mix = mix if isinstance(mix, dict) else evidence.evidence_mix(papers)
    qkey, qlabel = question_type(question)
    audit = _audit(papers)
    has_results = bool(papers)
    pmids = [str(p.get('pmid')) for p in papers
             if isinstance(p, dict) and p.get('pmid')]

    checkpoints = [
        {
            'key': 'can', 'label': '现在能核对什么',
            'text': ('已取回 %d 篇真实 PubMed 记录（PMID 可点开），摘要字段与文献类型构成列在上方；'
                     '可以逐篇核对研究设计、人群与结果。' % len(papers)) if has_results
                    else '还没有检索结果。先确认检索式；在检索完成前，不填写任何研究发现。',
        },
        {
            'key': 'cannot', 'label': '现在不能推断什么',
            'text': _CANNOT_HINT[qkey] + ' 文献类型与摘要字段都不是证据质量评级。',
        },
        {
            'key': 'next', 'label': '下一步动作',
            'text': ('先读 1 篇最相关摘要，记下人群 / 干预或暴露 / 结局 / 限制；'
                     '再判断是否需要调整检索式，或回到教材补基础。') if has_results
                    else '确认英文检索式后主动查询；若检索式没有通过核对，先改成更具体的研究性问法。',
        },
    ]

    stages = [
        {'key': 'question', 'index': 1, 'label': '研究疑问', 'value': question,
         'detail': qlabel + ' · ' + _FOCUS_HINT[qkey],
         'state': 'ready' if question else 'pending', 'action': 'focus-question'},
        {'key': 'query', 'index': 2, 'label': '检索式', 'value': query,
         'detail': mapping or '尚未确认英文检索式；请核对后主动检索。',
         'state': 'ready' if query else 'pending', 'action': 'focus-query'},
        {'key': 'evidence', 'index': 3, 'label': '证据构成',
         'value': mix.get('summary') or '本次没有文献可统计。',
         'detail': mix.get('notice') or NOTICE,
         'state': 'ready' if has_results else 'pending', 'action': 'show-evidence'},
        {'key': 'reading', 'index': 4, 'label': '逐篇核对',
         'value': ('已取回 %d 篇：%s' % (len(pmids), '、'.join('PMID ' + p for p in pmids[:5]))
                   if pmids else '尚未取回文献'),
         'detail': audit['summary'],
         'state': 'ready' if has_results else 'pending', 'action': 'read-paper'},
        {'key': 'boundary', 'index': 5, 'label': '结论边界',
         'value': ('可核对 %d 篇，不产生医学结论' % len(papers)) if has_results else '待检索后生成',
         'detail': checkpoints[1]['text'],
         'state': 'ready' if has_results else 'pending', 'action': 'show-boundary'},
    ]

    return {
        'schema_version': SCHEMA_VERSION,
        'question_type': qkey,
        'question_label': qlabel,
        'headline': '从疑问到证据，每一步都留痕',
        'stages': stages,
        'checkpoints': checkpoints,
        'audit': audit,
        'legal_note': NOTICE,
    }
