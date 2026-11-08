/* Display source-labelled excerpts, never manufacture a study summary. */
function mountPaperReading(container, data) {
  container.textContent = '';
  const paper = data.paper || {};
  container.append(el('h4', 'reading-title', paper.title || '标题未提供'),
    el('p', 'study-label', '围绕问题：' + data.question));
  const meta = [paper.journal, paper.year].filter(Boolean).join(' · ');
  if (meta) container.appendChild(el('p', 'study-source', meta));
  if (/^\d{1,12}$/.test(String(paper.pmid || ''))) {
    const source = el('a', 'reading-original', '核对 PubMed 原始记录 · PMID ' + paper.pmid + ' ↗');
    source.href = 'https://pubmed.ncbi.nlm.nih.gov/' + paper.pmid + '/';
    source.target = '_blank'; source.rel = 'noopener noreferrer'; container.appendChild(source);
  }
  container.appendChild(el('p', 'reading-notice', data.notice ||
    '以下仅为摘要原文节选，不是中文翻译、全文解读或研究质量评价。'));
  const sections = Array.isArray(data.sections) ? data.sections : [{
    id:'results', title:'结果或结论节选', excerpts:(data.evidence || []),
    missing_notice:'摘要未提供可直接提取的结果或结论段落。'
  }];
  const grid = el('div', 'paper-reading-grid');
  const missing = el('details', 'reading-missing');
  missing.appendChild(el('summary', null, '核对摘要中未识别或未展示的环节'));
  let displayed = 0, absent = 0;
  sections.forEach(section => {
    const excerpts = (Array.isArray(section.excerpts) ? section.excerpts : []).filter(part => typeof part?.text === 'string' && part.text);
    if (!excerpts.length) {
      absent++;
      missing.appendChild(el('p', 'study-source', (section.title || '未标注环节') + '：' +
        (section.missing_notice || '未识别到对应摘要标签，请打开原文核对。')));
      return;
    }
    displayed++;
    const block = el('section', 'reading-section');
    block.appendChild(el('h5', null, section.title || '摘要节选'));
    excerpts.forEach(part => {
      if (part.label || part.category) block.appendChild(el('p', 'reading-origin-label',
        '原摘要标签：' + (part.label || '未标注') + (part.category ? ' · NLM ' + part.category : '')));
      block.appendChild(el('blockquote', 'reading-excerpt', part.text));
      if (part.truncated) block.appendChild(el('small', 'study-source', '本段仅显示开头节选，请在 PubMed 核对完整摘要。'));
    });
    if (Number.isInteger(section.omitted_count) && section.omitted_count > 0) {
      block.appendChild(el('p', 'study-source', '本环节另有 ' + section.omitted_count + ' 段未展示，请打开 PubMed 核对。'));
    }
    grid.appendChild(block);
  });
  if (displayed) container.appendChild(grid);
  else container.appendChild(el('p', 'study-source', '未取得可展示的摘要节选，请打开 PubMed 核对是否提供摘要。'));
  if (absent) container.appendChild(missing);
  if (data.excerpt_limits?.truncated) container.appendChild(el('p', 'study-source',
    '本卡受节选长度和段数限制，未展示完整摘要；未展示不等于原文没有报告。'));
  if (data.limitations) container.appendChild(el('p', 'study-source', data.limitations));
  if (data.relationship) container.appendChild(el('p', 'study-source', data.relationship));
  if (data.ai_guide) {
    const guide = el('details', 'reading-ai');
    guide.appendChild(el('summary', null, 'AI 辅助摘要解读（需对照原摘要核验）'));
    [['question', '问题'], ['evidence', '证据'], ['limitations', '局限'], ['relationship', '与课程知识的关系']].forEach(([key, label]) => {
      guide.appendChild(el('p', 'study-source', label + '：' + (data.ai_guide[key] || '摘要未报告')));
    });
    container.appendChild(guide);
  }
  /* ---------- 开放获取全文（可选，独立一层） ---------- */
  const fulltext = data.fulltext;
  if (fulltext && typeof fulltext === 'object') {
    if (fulltext.available && Array.isArray(fulltext.sections) && fulltext.sections.length) {
      const layer = el('section', 'reading-fulltext');
      layer.appendChild(el('h4', null, '开放获取全文'));
      const meta = ['许可：' + (fulltext.license || '未标注'), fulltext.pmcid || ''].filter(Boolean).join(' · ');
      layer.appendChild(el('p', 'study-source', meta));
      layer.appendChild(el('p', 'reading-notice', fulltext.notice || '原文段落，未翻译或改写。'));
      fulltext.sections.forEach(section => {
        const block = el('div', 'reading-section');
        block.appendChild(el('h5', null, section.title || '全文段落'));
        (Array.isArray(section.paragraphs) ? section.paragraphs : []).forEach(part => {
          if (typeof part?.text !== 'string' || !part.text) return;
          const quote = el('blockquote', 'reading-excerpt', part.text);
          quote.appendChild(el('small', 'reading-cite', ' ' + (part.citation || ('[PMID:' + part.number + ']'))));
          block.appendChild(quote);
          if (part.truncated) block.appendChild(el('small', 'study-source', '本段仅显示开头，请回原文核对。'));
        });
        layer.appendChild(block);
      });
      container.appendChild(layer);
    } else if (fulltext.reason === 'not_requested') {
      container.appendChild(el('p', 'study-source', fulltext.message || '未请求全文。'));
      const load = el('button', 'btn', '加载开放获取全文');
      load.type = 'button';
      load.addEventListener('click', async () => {
        if (typeof api !== 'function') return;
        load.disabled = true;
        load.textContent = '正在获取全文…';
        try {
          const next = await api('/api/read-paper', {
            pmid: paper.pmid, concept: data.concept || null,
            question: data.question, include_fulltext: true
          });
          mountPaperReading(container, next);
        } catch (error) {
          load.disabled = false;
          load.textContent = '重试加载开放获取全文';
          container.appendChild(el('p', 'study-source', '全文获取失败：' + error.message));
        }
      });
      container.appendChild(load);
    } else {
      container.appendChild(el('p', 'study-source',
        (fulltext.message || '没有可用的开放获取全文，只能阅读摘要。') +
        (fulltext.license ? '（许可：' + fulltext.license + '）' : '')));
    }
  }

  /* ---------- 证据字段提示（不是质量评级） ---------- */
  const grade = data.evidence_grade;
  if (grade && grade.fields) {
    const box = el('details', 'reading-evidence');
    box.appendChild(el('summary', null, '证据字段提示（不是质量评级）'));
    [['study_type', '研究类型'], ['sample_size', '样本量'],
     ['randomization', '随机化'], ['blinding', '盲法']].forEach(([key, label]) => {
      const field = grade.fields[key] || {};
      const shown = field.status === 'reported'
        ? String(field.value == null ? '' : field.value)
        : (field.status === 'not_reported' ? '摘要未报告' : '未获取');
      box.appendChild(el('p', 'study-source', label + '：' + shown + (field.source ? '（' + field.source + '）' : '')));
    });
    (Array.isArray(grade.hints) ? grade.hints : []).forEach(hint => {
      box.appendChild(el('p', 'study-source', '· ' + hint));
    });
    box.appendChild(el('p', 'study-source', grade.notice || grade.reminder || ''));
    container.appendChild(box);
  }

  /* ---------- 引文导出（BibTeX / RIS） ---------- */
  if (/^\d{1,12}$/.test(String(paper.pmid || '')) && typeof api === 'function') {
    const row = el('div', 'reading-export');
    [['bibtex', '复制 BibTeX'], ['ris', '复制 RIS']].forEach(([format, label]) => {
      const button = el('button', 'btn', label);
      button.type = 'button';
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          const out = await api('/api/export-citations', { pmids: [paper.pmid], format });
          container.appendChild(el('pre', 'reading-citation', out.content || ''));
          if (typeof navigator !== 'undefined' && navigator.clipboard) {
            try { await navigator.clipboard.writeText(out.content || ''); } catch (_) {}
          }
        } catch (error) {
          container.appendChild(el('p', 'study-source', '引文导出失败：' + error.message));
        } finally {
          button.disabled = false;
        }
      });
      row.appendChild(button);
    });
    container.appendChild(row);
  }

  if (data.warning) container.appendChild(el('p', 'study-source', data.warning));
}
