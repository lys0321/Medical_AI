/* 医学知识星图：把真实掌握度数据渲染成星座式可视化。
   数据来自 galaxy.build_galaxy()——确定性、可核验、不造假。
   tone 只表达学习状态，不代表医学质量；未测评不算薄弱。 */
const SVGNS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs, className) {
  const node = document.createElementNS(SVGNS, tag);
  if (className) node.setAttribute("class", className);
  Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, v));
  return node;
}

function renderGalaxy(mount, galaxy, handlers = {}) {
  const onOpen = typeof handlers.onOpen === "function" ? handlers.onOpen : () => {};
  mount.innerHTML = "";
  if (!galaxy || !Array.isArray(galaxy.nodes) || !galaxy.nodes.length) {
    const empty = document.createElement("p");
    empty.className = "galaxy-empty";
    empty.textContent = "还没有测评数据。完成第一次学习评估，知识星图就会亮起来——开始第一次测评 ›";
    mount.appendChild(empty);
    return null;
  }
  const summary = galaxy.summary || {};
  const vb = galaxy.viewBox || [0, 0, 680, 460];
  const cx = (galaxy.center || [340, 230])[0];
  const cy = (galaxy.center || [340, 230])[1];
  const svg = svgEl("svg", {
    viewBox: vb.join(" "), role: "img",
    "aria-label": "知识星图：" + summary.total + " 个知识点，已掌握 " + summary.mastered + " 个"
  }, "galaxy-svg");

  // 轨道环 + 星座连线
  (galaxy.clusters || []).forEach((cl) => {
    svg.appendChild(svgEl("circle", {
      cx: cx, cy: cy, r: cl.ring, fill: "none"
    }, "galaxy-orbit"));
  });
  const byCluster = {};
  galaxy.nodes.forEach((n) => {
    (byCluster[n.cluster] = byCluster[n.cluster] || []).push(n);
  });
  Object.values(byCluster).forEach((group) => {
    if (group.length < 2) return;
    const pts = group.slice().sort((a, b) => a.id.localeCompare(b.id));
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        svg.appendChild(svgEl("line", {
          x1: pts[i].x, y1: pts[i].y, x2: pts[j].x, y2: pts[j].y
        }, "galaxy-link"));
      }
    }
  });

  // 中心总览环：真实掌握数 / 总数
  const total = Math.max(1, summary.total || 0);
  const mastered = summary.mastered || 0;
  const circ = 2 * Math.PI * 30;
  const dash = Math.round(circ * mastered / total);
  svg.appendChild(svgEl("circle", { cx: cx, cy: cy, r: 30, fill: "none" }, "galaxy-core-track"));
  svg.appendChild(svgEl("circle", {
    cx: cx, cy: cy, r: 30, fill: "none",
    "stroke-dasharray": dash + " " + Math.max(0, circ - dash),
    transform: "rotate(-90 " + cx + " " + cy + ")"
  }, "galaxy-core-progress"));
  const coreNum = svgEl("text", { x: cx, y: cy - 2, "text-anchor": "middle" }, "galaxy-core-num");
  coreNum.textContent = mastered + "/" + (summary.total || 0);
  svg.appendChild(coreNum);
  const coreLbl = svgEl("text", { x: cx, y: cy + 15, "text-anchor": "middle" }, "galaxy-core-label");
  coreLbl.textContent = "已掌握";
  svg.appendChild(coreLbl);

  // 节点：大小=掌握度，颜色=状态，薄弱点带脉冲
  galaxy.nodes.forEach((n) => {
    const g = svgEl("g", {
      class: "galaxy-node tone-" + (n.tone || "untested"),
      "data-id": n.id, "data-status": n.status || "",
      "data-score": n.score == null ? "" : n.score,
      tabindex: "0", role: "button",
      "aria-label": n.name + "，" + n.status
    });
    if (n.is_weak) g.appendChild(svgEl("circle", { cx: n.x, cy: n.y, r: n.r + 9 }, "galaxy-pulse"));
    g.appendChild(svgEl("circle", { cx: n.x, cy: n.y, r: n.r + 4 }, "galaxy-halo"));
    g.appendChild(svgEl("circle", { cx: n.x, cy: n.y, r: n.r }, "galaxy-star"));
    const label = svgEl("text", { x: n.x, y: n.y - n.r - 7, "text-anchor": "middle" }, "galaxy-node-label");
    label.textContent = n.name || n.id;
    g.appendChild(label);
    const activate = () => onOpen(n.id);
    g.addEventListener("click", activate);
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") activate(); });
    svg.appendChild(g);
  });
  mount.appendChild(svg);

  // 图例与真实来源标注
  const foot = document.createElement("div");
  foot.className = "galaxy-foot";
  const legend = document.createElement("div");
  legend.className = "galaxy-legend";
  [["mastered", "已掌握"], ["progressing", "初步达标"], ["weak", "需巩固"], ["untested", "未测评"]].forEach(([tone, label]) => {
    const item = document.createElement("span");
    item.className = "galaxy-legend-item";
    const dot = document.createElement("i");
    dot.className = "legend-dot tone-" + tone;
    item.appendChild(dot);
    item.appendChild(document.createTextNode(label));
    legend.appendChild(item);
  });
  foot.appendChild(legend);
  if (summary.has_weak) {
    const weak = document.createElement("span");
    weak.className = "galaxy-weak-legend";
    weak.textContent = "闪烁的节点是反复出错的知识点，点击可直达补救";
    foot.appendChild(weak);
  }
  const src = document.createElement("span");
  src.className = "galaxy-source";
  src.textContent = "数据来源：" + (summary.source || "本地真实作答数据");
  foot.appendChild(src);
  mount.appendChild(foot);
  return svg;
}
