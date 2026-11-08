/* 组胚识图练习：标注来自本机 OCR，全部标记“待教师审核”，只考页面主题。 */
let imageQuizBusy = false;

async function mountImageQuiz(container) {
  if (!container) return;
  container.textContent = '';
  const reviewNotice = el('p', 'study-source',
    '标注待教师审核：由 OCR 机械抽取，未经医学教师核对；本练习只考查能否认出资料页的小标题，' +
    '不代表能辨认切片结构或染色结果。');
  const status = el('p', 'study-source', '正在读取识图练习记录…');
  const body = el('div', 'image-quiz-body');
  const actions = el('div', 'quicknote-actions');
  const next = el('button', 'btn', '出题');
  next.type = 'button';
  actions.appendChild(next);
  container.append(reviewNotice, status, body, actions);

  function showStats(stats) {
    if (!stats) return;
    const rate = stats.accuracy == null ? '' : '（正确率 ' + Math.round(stats.accuracy * 100) + '%）';
    status.textContent = '识图练习：已答 ' + stats.attempts + ' 题，正确 ' + stats.correct + rate +
      ' · 单独统计，不计入三要点评分或掌握度';
  }

  async function submit(question, choice, buttons) {
    if (imageQuizBusy) return;
    imageQuizBusy = true;
    buttons.forEach(button => { button.disabled = true; });
    try {
      const out = await api('/api/image-quiz', { action: 'answer', token: question.token, choice });
      showStats(out.stats);
      const verdict = el('p', 'study-source',
        (out.correct ? '答对了：' : '答错了，正确的小标题是：') + out.answer);
      body.appendChild(verdict);
      const result = out.result || {};
      if (result.tissue || (result.stains || []).length) {
        const tags = [result.tissue, (result.stains || []).join('、')].filter(Boolean).join(' · ');
        body.appendChild(el('p', 'study-source', '该页自动标注（待教师审核）：' + tags));
      }
    } catch (error) {
      body.appendChild(el('p', 'study-source', '提交失败：' + error.message));
      buttons.forEach(button => { button.disabled = false; });
    } finally {
      imageQuizBusy = false;
    }
  }

  async function ask() {
    if (imageQuizBusy) return;
    imageQuizBusy = true;
    next.disabled = true;
    body.textContent = '正在出题…';
    try {
      const out = await api('/api/image-quiz', { action: 'next' });
      showStats(out.stats);
      if (!out.available) {
        body.textContent = out.message || '本机还没有可用的识图标注。';
        next.textContent = '重试';
        return;
      }
      const question = out.question;
      body.textContent = '';
      const image = el('img', 'image-quiz-image');
      image.src = question.image_url;
      image.alt = '第 ' + question.image_number + ' 页组胚复习资料（标注待教师审核）';
      body.appendChild(image);
      body.appendChild(el('p', 'answer', question.prompt));
      body.appendChild(el('p', 'study-source', question.notice || ''));
      const row = el('div', 'chips');
      const buttons = question.options.map(option => {
        const button = el('button', 'chip', option);
        button.type = 'button';
        button.addEventListener('click', () => submit(question, option, buttons));
        row.appendChild(button);
        return button;
      });
      body.appendChild(row);
      if (out.assist_available) {
        const assist = el('button', 'btn', '让本机视觉模型描述这页（仅辅助）');
        assist.type = 'button';
        assist.addEventListener('click', async () => {
          assist.disabled = true;
          try {
            const reply = await api('/api/image-quiz', { action: 'assist' });
            body.appendChild(el('p', 'study-source', reply.available
              ? '模型描述（未核验，不能作为答案依据）：' + (reply.assist?.text || '')
              : (reply.message || '模型描述不可用。')));
          } catch (error) {
            body.appendChild(el('p', 'study-source', '描述失败：' + error.message));
          } finally {
            assist.disabled = false;
          }
        });
        body.appendChild(assist);
      }
      next.textContent = '换一题';
    } catch (error) {
      body.textContent = '出题失败：' + error.message;
      next.textContent = '重试';
    } finally {
      next.disabled = false;
      imageQuizBusy = false;
    }
  }

  next.addEventListener('click', ask);
  await ask();
}