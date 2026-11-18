/* 循证研究画布：把 research_trace.build_trace() 的五步链路画成一条可读、
   可点击、可核验的路线。首页保持不变；这块只出现在文献漫游。
   纪律：没有检索结果时后三步显示“待完成”，不画假证据、不给质量评分。 */
function renderResearchTrace(mount, trace, opts) {
  if (!mount) return null;
  mount.innerHTML = "";
  if (!trace || !Array.isArray(trace.stages) || !trace.stages.length) return null;
  const h = opts || {};
  const onStage = typeof h.onStage === "function" ? h.onStage : () => {};

  const node = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  };
  const truncate = (text, max) => {
    const s = String(text || "").replace(/\s+/g, " ").trim();
    return s.length > max ? s.slice(0, max - 1) + "…" : s;
  };

  const wrap = node("div", "research-trace");
  wrap.setAttribute("role", "region");
  wrap.setAttribute("aria-label", "循证研究画布：" + (trace.headline || "从疑问到证据的留痕路线"));

  const head = node("div", "trace-head");
  const titleBox = node("div", "trace-title-box");
  titleBox.appendChild(node("span", "trace-kicker", "RESEARCH TRACE · 5 步留痕"));
  titleBox.appendChild(node("h3", null, trace.headline || "从疑问到证据，每一步都留痕"));
  head.appendChild(titleBox);
  const badge = node("span", "trace-badge", trace.question_label || "证据探索类问题");
  head.appendChild(badge);
  wrap.appendChild(head);

  const rail = node("div", "trace-rail");
  rail.setAttribute("aria-label", "研究链路步骤");
  (trace.stages || []).forEach((stage, i) => {
    const key = stage.key || "step-" + i;
    const ready = stage.state === "ready";
    const step = node("button", "trace-step " + (ready ? "is-ready" : "is-pending"));
    step.type = "button";
    step.setAttribute("data-key", key);
    step.setAttribute("aria-label", "第 " + (stage.index || i + 1) + " 步：" + (stage.label || key) +
      (ready ? "，已留痕，点击定位" : "，待完成"));
    step.appendChild(node("span", "trace-marker", String(stage.index || i + 1)));
    step.appendChild(node("span", "trace-step-label", stage.label || key));
    step.appendChild(node("span", "trace-value", truncate(stage.value, 92) || "—"));
    step.appendChild(node("span", "trace-detail", truncate(stage.detail, 130) || "—"));
    step.appendChild(node("span", "trace-state", ready ? "已留痕" : "待完成"));
    step.addEventListener("click", () => onStage(key, stage));
    rail.appendChild(step);
  });
  wrap.appendChild(rail);

  const checks = node("div", "trace-checkpoints");
  (trace.checkpoints || []).forEach((cp) => {
    const card = node("article", "trace-check trace-check--" + (cp.key || "note"));
    card.appendChild(node("span", "trace-check-label", cp.label || "核对点"));
    card.appendChild(node("p", null, cp.text || ""));
    checks.appendChild(card);
  });
  wrap.appendChild(checks);

  const audit = trace.audit || {};
  if (audit.total || audit.assessed) {
    const strip = node("div", "trace-audit");
    strip.appendChild(node("span", "trace-audit-title", "摘要可核对项"));
    const chips = [
      ["样本量", audit.sample_reported || 0],
      ["随机化", audit.randomization_mentioned || 0],
      ["盲法", audit.blinding_mentioned || 0],
    ];
    chips.forEach(([label, count]) => {
      const chip = node("span", "trace-audit-chip", label + " " + count + "/" + (audit.total || 0));
      strip.appendChild(chip);
    });
    strip.appendChild(node("span", "trace-audit-note", audit.notice || "未提到不等于原文没有报告。"));
    wrap.appendChild(strip);
  }

  wrap.appendChild(node("p", "trace-notice", trace.legal_note || "这是检索与阅读的留痕路线，不是医学结论。"));
  mount.appendChild(wrap);
  return wrap;
}
