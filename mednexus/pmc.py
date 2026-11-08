"""PMC 开放获取全文：PMID→PMCID、license 判定、JATS 段落抽取。

只用标准库（json / re / xml.etree）。网络访问由调用方注入 ``fetch(url) -> bytes``，
所以解析、license 判定和降级逻辑都能离线单测。

三条硬规则：
1. **license 不明确或不允许就拒绝展示正文**。宁可只给摘要，也不把版权不明的全文
   复制到本地或界面上。
2. **只做搬运，不做推断**：段落文字原样截取，标题按原文，编号只是位置，不代表
   重要性或质量。
3. **缺字段就说缺**：没有 body、没有 license、没有段落时返回明确的 reason，
   不补造段落、不猜 license。
"""
import json
import re
import xml.etree.ElementTree as ET


IDCONV_URL = ("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={pmid}"
              "&format=json&tool=MedNexusLearning")
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmcid}&retmode=xml"

# 允许展示正文的许可：可以再分发、可以摘录与解释。
# 刻意排除 ND（禁止演绎）变体——本地阅读卡会做摘录与解释，属于演绎使用。
ALLOWED_LICENSES = frozenset({
    'CC0', 'CC BY', 'CC BY-SA', 'CC BY-NC', 'CC BY-NC-SA', 'PUBLIC DOMAIN',
})
LICENSE_ALIASES = {
    'CC-BY': 'CC BY', 'CC BY 4.0': 'CC BY', 'CCBY': 'CC BY',
    'CC-BY-4.0': 'CC BY', 'CC BY 4 0': 'CC BY',
    'CC-BY-NC': 'CC BY-NC', 'CC BY-NC 4.0': 'CC BY-NC',
    'CC-BY-NC-SA': 'CC BY-NC-SA', 'CC-BY-SA': 'CC BY-SA',
    'CC0 1.0': 'CC0', 'CC0': 'CC0',
}
URL_LICENSES = (
    ('creativecommons.org/publicdomain/zero', 'CC0'),
    ('creativecommons.org/licenses/by-nc-sa', 'CC BY-NC-SA'),
    ('creativecommons.org/licenses/by-nc-nd', 'CC BY-NC-ND'),
    ('creativecommons.org/licenses/by-nc', 'CC BY-NC'),
    ('creativecommons.org/licenses/by-sa', 'CC BY-SA'),
    ('creativecommons.org/licenses/by-nd', 'CC BY-ND'),
    ('creativecommons.org/licenses/by', 'CC BY'),
)

SECTIONS = (('methods', '研究方法'), ('results', '研究结果'), ('discussion', '讨论与结论'))
SECTION_HINTS = {
    'methods': ('method', 'material', 'experimental', 'study design', '方法', '材料'),
    'results': ('result', 'finding', '结果'),
    'discussion': ('discussion', 'conclusion', 'limitation', '讨论', '结论', '局限'),
}
MAX_PARAGRAPHS = 40
MAX_PARAGRAPH_CHARS = 1200

NOTICE = ('以下是 PMC 开放获取正文的原文段落，按原文章节归类并顺序编号，未翻译、未改写。'
          '段落编号只表示位置，不代表重要性或证据质量；引用时请写 [PMID:段落号] 并回原文核对。')


def normalize_license(raw):
    """把 'CC BY 4.0'、许可链接等写法归一到统一名称；无法识别时返回原字符串。"""
    if not isinstance(raw, str):
        return ''
    text = re.sub(r'\s+', ' ', raw).strip()
    if not text:
        return ''
    key = text.upper().replace('_', ' ')
    key = re.sub(r'\s+', ' ', key).strip(' .')
    if key in LICENSE_ALIASES:
        return LICENSE_ALIASES[key]
    for token, name in URL_LICENSES:
        if token in text.lower():
            return name
    squashed = key.replace(' ', '').replace('-', '')
    for alias, name in LICENSE_ALIASES.items():
        if alias.replace(' ', '').replace('-', '') == squashed:
            return name
    return text


def license_allowed(license_name):
    return normalize_license(license_name).upper() in {item.upper() for item in ALLOWED_LICENSES}


def _text(node):
    return re.sub(r'\s+', ' ', ''.join(node.itertext())).strip() if node is not None else ''


def parse_idconv(payload):
    """解析 ID Converter 返回；找不到 PMCID 时给出明确原因。"""
    try:
        data = json.loads(payload.decode('utf-8') if isinstance(payload, bytes) else payload)
    except (ValueError, AttributeError):
        return {'pmcid': '', 'reason': 'ID 转换返回的不是合法 JSON'}
    records = data.get('records') if isinstance(data, dict) else None
    if not isinstance(records, list) or not records:
        return {'pmcid': '', 'reason': 'ID 转换没有返回记录'}
    record = records[0] if isinstance(records[0], dict) else {}
    pmcid = record.get('pmcid')
    if isinstance(pmcid, str) and re.fullmatch(r'PMC\d{1,9}', pmcid):
        return {'pmcid': pmcid, 'reason': ''}
    message = record.get('errmsg') or record.get('status') or '该文献不在 PMC 中'
    return {'pmcid': '', 'reason': str(message)[:200]}


def _license_of(root):
    """优先用 PMC 规范化字段 pmc-license-ref，其次 <license> 里的 URL/文字。"""
    for meta in root.iter('custom-meta'):
        name = _text(meta.find('meta-name'))
        if name == 'pmc-license-ref':
            value = _text(meta.find('meta-value'))
            if value:
                return normalize_license(value), value
    for license_node in root.iter('license'):
        for ref in license_node.iter():
            tag = ref.tag.split('}')[-1]
            href = ref.get('{http://www.w3.org/1999/xlink}href') or ref.get('href') or ''
            if tag == 'license_ref' and href:
                return normalize_license(href), href
            text = _text(ref)
            if tag == 'license_ref' and text:
                return normalize_license(text), text
        phrase = _text(license_node)
        if phrase:
            return normalize_license(phrase[:120]), phrase[:120]
    return '', ''


def _section_kind(sec):
    raw = (sec.get('sec-type') or '').lower()
    title = _text(sec.find('title')).lower()
    for kind, hints in SECTION_HINTS.items():
        if any(hint in raw for hint in hints) or any(hint in title for hint in hints):
            return kind
    return ''


def _paragraphs_of(sec):
    """只取直接子 p，避免父章节把子章节的段落重复计入。"""
    out = []
    for node in sec.findall('p'):
        text = _text(node)
        if text:
            out.append(text)
    return out


def extract(xml_bytes, pmid):
    """从 JATS XML 抽取方法/结果/讨论三段，并给出 license。

    返回 ``{'available': bool, 'reason': str, 'license': str, 'license_raw': str,
    'sections': [...], 'paragraph_count': int}``。没有正文时 available=False，
    sections 为空，reason 明确说明原因。
    """
    if not isinstance(xml_bytes, (bytes, bytearray)):
        return {'available': False, 'reason': '全文返回不是 XML 字节流', 'license': '', 'license_raw': '',
                'sections': [], 'paragraph_count': 0}
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return {'available': False, 'reason': '全文 XML 解析失败', 'license': '', 'license_raw': '',
                'sections': [], 'paragraph_count': 0}

    license_name, license_raw = _license_of(root)
    article = next(root.iter('article'), root)
    body = article.find('.//body')
    title = _text(article.find('.//article-title'))

    if body is None:
        return {'available': False, 'reason': 'PMC 记录没有可用的正文（可能仅摘要或非开放获取）',
                'license': license_name, 'license_raw': license_raw,
                'title': title, 'sections': [], 'paragraph_count': 0}

    buckets = {kind: [] for kind, _ in SECTIONS}
    for sec in body.iter('sec'):
        kind = _section_kind(sec)
        if not kind:
            continue
        for text in _paragraphs_of(sec):
            truncated = len(text) > MAX_PARAGRAPH_CHARS
            buckets[kind].append({'text': text[:MAX_PARAGRAPH_CHARS], 'truncated': truncated,
                                  'title': _text(sec.find('title'))})

    if not any(buckets.values()):
        return {'available': False, 'reason': '正文中没有识别到方法/结果/讨论段落',
                'license': license_name, 'license_raw': license_raw,
                'title': title, 'sections': [], 'paragraph_count': 0}

    sections, number = [], 0
    for kind, chinese in SECTIONS:
        entries = []
        for item in buckets[kind][:MAX_PARAGRAPHS]:
            if number >= MAX_PARAGRAPHS:
                break
            number += 1
            entries.append({'number': number, 'section': kind, 'text': item['text'],
                            'truncated': item['truncated'], 'title': item['title'],
                            'citation': '[PMID:%d]' % number})
        if entries:
            sections.append({'id': kind, 'title': chinese, 'paragraphs': entries})
    return {'available': True, 'reason': '', 'license': license_name, 'license_raw': license_raw,
            'title': title, 'sections': sections, 'paragraph_count': number}


def harvest(pmid, fetch):
    """按 PMID 取全文并做 license 闸门；``fetch(url) -> bytes`` 由调用方注入。"""
    try:
        converted = fetch(IDCONV_URL.format(pmid=pmid))
    except Exception as error:                      # 网络或 HTTP 失败
        return {'status': 'error', 'reason': 'PMC 编号查询失败：%s' % error, 'pmid': pmid}
    mapping = parse_idconv(converted)
    if not mapping['pmcid']:
        return {'status': 'no_pmcid', 'reason': mapping['reason'], 'pmid': pmid}

    pmcid = mapping['pmcid']
    try:
        xml_bytes = fetch(EFETCH_URL.format(pmcid=pmcid))
    except Exception as error:
        return {'status': 'error', 'reason': 'PMC 全文获取失败：%s' % error, 'pmid': pmid, 'pmcid': pmcid}

    document = extract(xml_bytes, pmid)
    base = {'status': 'no_fulltext', 'pmid': pmid, 'pmcid': pmcid,
            'license': document.get('license', ''), 'license_raw': document.get('license_raw', ''),
            'reason': document.get('reason', ''), 'title': document.get('title', '')}
    if not document['available']:
        return base
    if not license_allowed(document['license']):
        # 关键：正文一个字都不往下传，只报告许可与原因。
        return {**base, 'status': 'license_denied',
                'reason': '许可为 %s，不允许摘录或再分发正文' % (document['license'] or '未知'),
                'document': None}
    return {**base, 'status': 'ok', 'reason': '', 'document': document}


LAYER_MESSAGES = {
    'no_pmcid': '该文献没有 PMC 全文记录，只能阅读摘要。',
    'no_fulltext': 'PMC 记录没有可用的开放获取正文，只能阅读摘要。',
    'license_denied': '该文献的许可不允许摘录正文，只能阅读摘要。',
    'error': 'PMC 服务暂时不可用，本次只展示摘要，可稍后重试。',
    'not_requested': '未请求全文；可以展开开放获取全文。',
}


def layer_from_record(record, pmid):
    """把缓存记录整理成阅读卡的一层；不可用时只给原因，不给正文。"""
    if record.get('status') == 'ok' and record.get('sections'):
        return {'available': True, 'pmid': pmid, 'pmcid': record.get('pmcid', ''),
                'license': record.get('license', ''), 'license_raw': record.get('license_raw', ''),
                'sections': record['sections'], 'paragraph_count': record.get('paragraph_count', 0),
                'notice': NOTICE}
    status = record.get('status') or 'error'
    return {'available': False, 'pmid': pmid, 'pmcid': record.get('pmcid', ''),
            'license': record.get('license', ''), 'reason': status,
            'message': LAYER_MESSAGES.get(status, '没有可用的开放获取全文，只能阅读摘要。'),
            'detail': record.get('reason', ''), 'sections': [], 'paragraph_count': 0}


def reading_layer(result, pmid):
    """把 harvest 结果整理成阅读卡里的一层（不改变结论，只换形状）。"""
    document = result.get('document') or {}
    record = {'status': result.get('status'), 'pmcid': result.get('pmcid', ''),
              'license': result.get('license', ''), 'license_raw': result.get('license_raw', ''),
              'reason': result.get('reason', ''),
              'sections': document.get('sections', []),
              'paragraph_count': document.get('paragraph_count', 0)}
    return layer_from_record(record, pmid)


def evidence_citations(layer):
    """全文层里带引用的段落，供"每个结论必须挂 [PMID:段落号]"使用。"""
    if not layer.get('available'):
        return []
    return [{'citation': paragraph['citation'], 'section': section['id'],
             'text': paragraph['text']}
            for section in layer.get('sections', [])
            for paragraph in section.get('paragraphs', [])]