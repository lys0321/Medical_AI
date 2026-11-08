"""引文导出：BibTeX 与 RIS。

只用检索缓存里的真实字段，缺什么就留空，不补造作者、卷期或页码。
作者原始写法是 PubMed 的 "Last Initials"，RIS 里转成 "Last, Initials"；
BibTeX 输出 UTF-8 原文，现代 bib 引擎可直接读取。
"""
import re

BIB_SPECIAL = re.compile(r'([{}\\&%$#_^~])')


def _clean(value, limit=400):
    if not isinstance(value, str):
        return ''
    return re.sub(r'\s+', ' ', value).strip()[:limit]


def _bib_escape(value):
    return BIB_SPECIAL.sub(r'\\\1', _clean(value, 1000))


def _doi(paper):
    raw = _clean(paper.get('doi'), 300)
    for prefix in ('https://doi.org/', 'http://doi.org/', 'doi:'):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
    return raw


def _authors(paper, limit=8):
    authors = paper.get('authors')
    if not isinstance(authors, list):
        return []
    return [_clean(item, 200) for item in authors[:limit] if isinstance(item, str) and item.strip()]


def _ris_author(name):
    match = re.fullmatch(r'(.+?)\s+([A-Z]{1,4})', name)
    return '%s, %s' % (match.group(1), match.group(2)) if match else name


def bibtex(papers):
    """返回多条 BibTeX；键名用 pmid，缺 id 的记录跳过。"""
    entries = []
    for paper in papers:
        pmid = _clean(paper.get('pmid'), 20)
        if not re.fullmatch(r'\d{1,12}', pmid):
            continue
        fields = [
            ('title', _bib_escape(paper.get('title'))),
            ('author', ' and '.join(_bib_escape(name) for name in _authors(paper))),
            ('journal', _bib_escape(paper.get('journal'))),
            ('year', _clean(paper.get('year'), 20)),
            ('doi', _bib_escape(_doi(paper))),
            ('pmid', pmid),
            ('url', _clean(paper.get('url'), 300)),
        ]
        body = ',\n'.join('  %s = {%s}' % (key, value) for key, value in fields if value)
        entries.append('@article{pmid%s,\n%s\n}' % (pmid, body))
    return '\n\n'.join(entries)


def ris(papers):
    """返回多条 RIS；每条以 ER  - 结束。"""
    entries = []
    for paper in papers:
        pmid = _clean(paper.get('pmid'), 20)
        if not re.fullmatch(r'\d{1,12}', pmid):
            continue
        lines = ['TY  - JOUR']
        for name in _authors(paper):
            lines.append('AU  - ' + _ris_author(name))
        for tag, key in (('TI', 'title'), ('JO', 'journal')):
            value = _clean(paper.get(key), 500)
            if value:
                lines.append('%s  - %s' % (tag, value))
        year = _clean(paper.get('year'), 20)
        if year:
            lines.append('PY  - ' + year)
        doi = _doi(paper)
        if doi:
            lines.append('DO  - ' + doi)
        url = _clean(paper.get('url'), 300)
        if url:
            lines.append('L1  - ' + url)
        lines.append('AN  - ' + pmid)
        lines.append('ER  - ')
        entries.append('\n'.join(lines))
    return '\n\n'.join(entries)


def export(papers, fmt):
    if fmt == 'bibtex':
        return bibtex(papers)
    if fmt == 'ris':
        return ris(papers)
    raise ValueError('只支持 bibtex 或 ris')