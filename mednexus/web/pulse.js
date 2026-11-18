/* 循证学习罗盘：把 pulse.build_pulse() 的真实态势渲染成浅色仪表盘。
   与整体浅色主题协调——不搞深色星空，靠"证据纪律"这个独有维度取胜。
   value=null（未测量）画空弧，绝不当作 0 分；颜色只表示状态，不是成绩。 */
function renderPulse(mount, pulse, opts) {
  const h = opts || (typeof handlers !== "undefined" ? handlers : {});
  const onInspect = typeof h.onInspect === "function" ? h.onInspect : () => {};
  const NS = "http://www.w3.org/2000/svg";
  const svgEl = (tag, attrs, cls) => {
    const n = document.createElementNS(NS, tag);
    if (cls) n.setAttribute("class", cls);
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
    return n;
  };
  const FALLBACK = [
    { key: "evidence", label: "循证提问" },
    { key: "mastery", label: "掌握质量" },
    { key: "loop", label: "闭环补救" },
    { key: "consistency", label: "学习节奏" },
  ];
  const data = pulse && Array.isArray(pulse.dimensions) && pulse.dimensions.length
    ? pulse
    : { index: null, level: "尚未开始", dimensions: FALLBACK.map((d) => ({ ...d, value: null, detail: "还没有记录" })),
        headline: "还没有学习记录。完成第一次测评和提问后，这里会显示你的循证学习态势。",
        disclaimer: "这是本机学习行为的诚实观察，不是能力评分，也不代表医学水平。",
        source: "本地真实作答与提问数据" };

  mount.innerHTML = "";
  const dims = data.dimensions.slice(0, 4);
  const cx = 100, cy = 100;
  const radii = [78, 62, 46, 30];

  const svg = svgEl("svg", { viewBox: "0 0 200 200", role: "img",
    "aria-label": "循证学习罗盘：循证学习态势" }, "pulse-svg");

  // 背景轨道（淡色整圈）
  radii.forEach((r) => svg.appendChild(svgEl("circle", {
    cx: cx, cy: cy, r: r, fill: "none"
  }, "pulse-track")));

  // 数据弧：长度由真实 value 决定，未测量则长度为 0
  dims.forEach((d, i) => {
    const r = radii[i] || 30;
    const circ = 2 * Math.PI * r;
    const measured = typeof d.value === "number" && isFinite(d.value);
    const dash = measured ? Math.max(0, Math.min(1, d.value / 100)) * circ : 0;
    const arc = svgEl("circle", {
      cx: cx, cy: cy, r: r, fill: "none",
      "stroke-dasharray": dash + " " + circ,
      "data-key": d.key || "",
      "data-value": measured ? String(d.value) : "null",
      transform: "rotate(-90 " + cx + " " + cy + ")"
    }, "pulse-arc pulse-arc--" + (d.key || "x") + (measured ? "" : " is-unmeasured"));
    svg.appendChild(arc);
  });

  const idx = svgEl("text", { x: cx, y: cy + 2, "text-anchor": "middle" }, "pulse-index");
  idx.textContent = typeof data.index === "number" && isFinite(data.index) ? String(data.index) : "—";
  svg.appendChild(idx);
  const lvl = svgEl("text", { x: cx, y: cy + 20, "text-anchor": "middle" }, "pulse-level");
  lvl.textContent = data.level || "";
  svg.appendChild(lvl);
  mount.appendChild(svg);

  // 右侧：四个维度的可读明细，每行可点击下钻
  const list = document.createElement("div");
  list.className = "pulse-dims";
  dims.forEach((d) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "pulse-dim pulse-dim--" + (d.key || "x");
    const top = document.createElement("span");
    top.className = "pulse-dim-top";
    const label = document.createElement("b");
    label.textContent = d.label || d.key || "";
    top.appendChild(label);
    const val = document.createElement("em");
    val.textContent = (typeof d.value === "number" && isFinite(d.value)) ? (d.value + " / 100") : "未测量";
    top.appendChild(val);
    row.appendChild(top);
    const detail = document.createElement("span");
    detail.className = "pulse-dim-detail";
    detail.textContent = d.detail || "";
    row.appendChild(detail);
    const bar = document.createElement("span");
    bar.className = "pulse-dim-bar";
    const fill = document.createElement("i");
    fill.style.width = (typeof d.value === "number" && isFinite(d.value))
      ? Math.max(0, Math.min(100, d.value)) + "%" : "0%";
    bar.appendChild(fill);
    row.appendChild(bar);
    row.addEventListener("click", () => onInspect(d.key));
    list.appendChild(row);
  });
  mount.appendChild(list);

  // 底部：一句诚实观察 + 来源 + 免责声明
  const foot = document.createElement("div");
  foot.className = "pulse-foot";
  const head = document.createElement("p");
  head.className = "pulse-headline";
  head.textContent = data.headline || "";
  foot.appendChild(head);
  const note = document.createElement("p");
  note.className = "pulse-disclaimer";
  note.textContent = (data.disclaimer || "") + " 数据来源：" + (data.source || "本地记录") + "。";
  foot.appendChild(note);
  mount.appendChild(foot);

  return svg;
}
