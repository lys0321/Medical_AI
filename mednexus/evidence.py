"""证据字段提示：只报告摘要里能核验的四项，不给质量结论。

这里刻意不做的事情：
  · 不给"高/中/低质量"评分，也不给推荐等级；
  · 不从标题或文献类型推断研究设计；
  · 摘要没写的字段就写"未报告"，不猜、不补。
"""
import re

MAX_QUOTE = 160

STUDY_TYPE_HINTS = (
    ('Meta-Analysis', '荟萃分析'),
    ('Systematic Review', '系统综述'),
    ('Randomized Controlled Trial', '随机对照试验'),
    ('Clinical Trial', '临床试验'),
    ('Observational Study', '观察性研究'),
    ('Review', '综述'),
    ('Case Reports', '病例报告'),
)

RANDOM = re.compile(r'随机|randomi[sz]ed|randomi[sz]ation', re.I)
BLIND = re.compile(r'双盲|单盲|盲法|三盲|double[- ]blind|single[- ]blind|triple[- ]blind|\bblinded\b|\bblinding\b', re.I)
SAMPLE_PATTERNS = (
    re.compile(r'\bn\s*=\s*(\d{1,7})\b', re.I),
    re.compile(r'(\d{1,6})\s*(?:名|例)\s*(?:患者|受试者|儿童|成人|病人|病例)'),
    re.compile(r'(\d{1,6})\s*(?:patients|participants|subjects|children|adults|women|men)\b', re.I),
    re.compile(r'(?:总计|共|纳入|招募|enrolled|included|recruited)\s*(\d{1,6})\s*(?:名|例|patients|participants)?', re.I),
)

NOTICE = ('以上四项只是从 PubMed 文献类型与摘要原文中抽出的可核验字段，用于提示你应该核对什么，'
          '不是质量评级。文献类型不能判定证据质量，也不能替代偏倚风险评估；'
          '摘要未报告的字段不等于原文没有报告。')


def _abstract_text(paper):
    parts = paper.get('abstract') if isinstance(paper.get('abstract'), list) else []
    return ' '.join(part.get('text', '') for part in parts
                    if isinstance(part, dict) and isinstance(part.get('text'), str))


def _quote(text, match):
    start = max(0, match.start() - 60)
    end = min(len(text), match.end() + 60)
    snippet = re.sub(r'\s+', ' ', text[start:end]).strip()
    return snippet[:MAX_QUOTE]


def _study_type(paper):
    types = [item for item in paper.get('types', []) if isinstance(item, str)] if isinstance(paper.get('types'), list) else []
    for key, label in STUDY_TYPE_HINTS:
        if key in types:
            return {'status': 'reported', 'value': label, 'source': 'PubMed 文献类型', 'quote': key}
    if types:
        return {'status': 'reported', 'value': '其他类型（未映射）', 'source': 'PubMed 文献类型',
                'quote': '；'.join(types[:3])}
    return {'status': 'not_reported', 'value': '', 'source': 'PubMed 文献类型', 'quote': ''}


def _sample_size(text):
    found = []
    for pattern in SAMPLE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                found.append((int(match.group(1)), match))
            except (TypeError, ValueError):
                continue
    if not found:
        return {'status': 'not_reported', 'value': '', 'source': '摘要原文', 'quote': ''}
    found.sort(key=lambda item: item[0], reverse=True)
    value, match = found[0]
    return {'status': 'reported', 'value': value, 'source': '摘要原文', 'quote': _quote(text, match),
            'distinct_values': sorted({item[0] for item in found})}


def _mention(text, pattern, positive, negative):
    match = pattern.search(text)
    if match:
        return {'status': 'reported', 'value': positive, 'source': '摘要原文', 'quote': _quote(text, match)}
    return {'status': 'not_reported', 'value': '', 'source': '摘要原文', 'quote': '', 'note': negative}


def assess(paper):
    """返回四项可核验字段 + 中性提示。``paper`` 是 PubMed 检索缓存里的原始记录。"""
    if not isinstance(paper, dict):
        raise ValueError('需要真实的 PubMed 记录')
    text = _abstract_text(paper)
    fields = {
        'study_type': _study_type(paper),
        'sample_size': _sample_size(text),
        'randomization': _mention(text, RANDOM, '摘要提到随机化', '摘要未提到随机化'),
        'blinding': _mention(text, BLIND, '摘要提到盲法', '摘要未提到盲法'),
    }
    hints = []
    study = fields['study_type']['value']
    if study in ('荟萃分析', '系统综述'):
        hints.append('结论取决于纳入研究的质量与异质性，请核对纳入标准、检索范围与合并方法。')
    elif study == '病例报告':
        hints.append('病例报告通常只能提示可能性，不能用来估计效应大小或发生率。')
    elif study == '其他类型（未映射）':
        hints.append('文献类型未映射到常见设计，请打开 PubMed 核对 Publication Type。')
    elif fields['study_type']['status'] == 'not_reported':
        hints.append('文献类型未映射，请打开 PubMed 核对 Publication Type。')

    if fields['randomization']['status'] == 'not_reported':
        hints.append('摘要未提到随机化：非随机设计的组间差异可能来自混杂，不能直接当作干预效果。')
    if fields['blinding']['status'] == 'not_reported':
        hints.append('摘要未提到盲法：开放标签研究里，主观结局的效应估计更容易偏高。')
    if fields['sample_size']['status'] == 'reported' and isinstance(fields['sample_size']['value'], int):
        if fields['sample_size']['value'] < 50:
            hints.append('摘要报告的样本量较小，置信区间可能很宽，外推到其他人群要谨慎。')
        if len(fields['sample_size'].get('distinct_values', [])) > 1:
            hints.append('摘要里出现了多个样本量，请确认哪个对应主分析。')
    elif fields['sample_size']['status'] == 'not_reported':
        hints.append('摘要没有报告样本量，无法判断估计精度。')

    return {'fields': fields, 'hints': hints, 'notice': NOTICE,
            'reminder': '不能凭文献类型判定质量；以下字段仅用于定位需要人工核对的地方。'}