/* 医枢 MedNexus · 医学学习工作台 —— 前端逻辑
   视图切换 / 提问三卡 / 科研探索 / 我的学习 / 知识库 / 状态
*/
const $ = (id) => document.getElementById(id);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

let busy = false;
let overviewData = null;
let wanderOriginConcept = null;
let selectedCourseConcept = null;
let selectedCourseMode = "test";
let activeRequests = 0;
let dataResetting = false;
let pmRequestId = 0;
let readingRequestId = 0;
let researchContext = null;
let askOriginConcept = null;
let answerOriginConcept = null;
let learningPlanLoading = false;
let reportRequestId = 0;
let syllabusRefsRequest = 0;

/* ---------- 基础工具 ---------- */
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function icon(id, cls) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  if (cls) svg.setAttribute("class", cls);
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", "#" + id);
  svg.appendChild(use);
  return svg;
}

function toast(msg, ms = 2600) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove("show"), ms);
}

/* 每位浏览器一个学习身份，存在本地；同一台电脑换浏览器视为不同人 */
function learnerId() {
  const KEY = "mednexus-learner";
  let v = localStorage.getItem(KEY);
  if (!v || !/^[a-f0-9]{48}$/.test(v)) {
    const buf = new Uint8Array(24);
    crypto.getRandomValues(buf);
    v = Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
    localStorage.setItem(KEY, v);
  }
  return v;
}

async function api(path, payload) {
  if (dataResetting && path !== "/api/reset") throw new Error("正在清理数据，请稍后再试");
  const headers = { "X-Learner-ID": learnerId() };
  if (payload) headers["Content-Type"] = "application/json";
  const opt = payload
    ? { method: "POST", headers, body: JSON.stringify(payload) }
    : { method: "GET", headers };
  activeRequests++;
  try {
    const res = await fetch(path, opt);
    const data = await res.json();
    if (!res.ok) {
      const error = new Error(data.error || "请求失败");
      if (data.url) error.url = data.url;
      throw error;
    }
    return data;
  } finally {
    activeRequests--;
  }
}

/* ---------- 视图切换 ---------- */
const VIEWS = ["home", "learn", "quiz", "ask", "quicknotes", "books", "materials", "research", "me"];

function showView(name, { restoreTask = true } = {}) {
  if (!VIEWS.includes(name)) name = "home";
  VIEWS.forEach((v) => {
    const sec = $("view-" + v);
    if (sec) sec.classList.toggle("is-active", v === name);
  });
  $$(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === name));
  $("rail").classList.toggle("is-hidden", name !== "home");
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (name === "learn" && overviewData) renderLearn(overviewData);
  if (name === "quiz") {
    renderQuiz(overviewData);
    loadLearningReport();
    applyQuizMode();
    if (restoreTask && quizPhase === "empty") resumeActiveTask();
  }
  if (name === "quicknotes") loadQuicknotes();
  if (name === "materials") {
    const quizPanel = $("imageQuizPanel");
    if (quizPanel) quizPanel.hidden = false;
    if (typeof mountImageQuiz === "function") mountImageQuiz($("imageQuiz"));
    if (typeof loadCourseMaterials === "function") loadCourseMaterials();
  }
  if (name === "books" && overviewData) renderBooks(overviewData);
  if (name === "me" && overviewData) renderMe(overviewData);
  const nextHash = name === "home" ? "" : "#" + name;
  if (location.hash !== nextHash) history.pushState(null, "", location.pathname + location.search + nextHash);
}

window.addEventListener("popstate", () => showView(location.hash.slice(1) || "home"));
window.addEventListener("hashchange", () => showView(location.hash.slice(1) || "home"));

$$(".nav-item").forEach((b) => {
  b.setAttribute("aria-label", b.textContent.trim());
  b.title = b.textContent.trim();
});
$$(".nav-item").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.view === "home") setAskContext(null);
  showView(b.dataset.view);
}));
$$("[data-view]").forEach((b) => {
  if (b.classList.contains("nav-item")) return;
  b.addEventListener("click", () => showView(b.dataset.view));
});

/* ---------- 首页渲染 ---------- */
function renderRecent(list) {
  const box = $("recent");
  box.innerHTML = "";
  if (!list.length) {
    box.appendChild(el("p", "empty-line", "还没有提问记录。从上面的输入框开始，或者点一个示例问题。"));
    return;
  }
  list.forEach((it) => {
    const btn = el("button", "recent-item");
    btn.type = "button";
    const ic = el("span", "recent-icon");
    ic.appendChild(icon("i-learn"));
    const body = el("span", "recent-body");
    body.appendChild(el("strong", null, it.query));
    body.appendChild(el("span", null,
      (it.book ? it.book + " · P" + it.page : "未命中教材")));
    const time = el("span", "recent-time", it.time);
    const pill = el("span", "pill" + (it.cited_ok ? "" : " warn"), it.cited_ok ? "已引用" : "未引用");
    btn.append(ic, body, time, pill);
    btn.addEventListener("click", () => {
      $("q").value = it.query;
      ask(it.query);
    });
    box.appendChild(btn);
  });
}

function renderChecklist(data) {
  const ul = $("checklist");
  ul.innerHTML = "";
  const plan = data.learning_plan;
  if (plan && Array.isArray(plan.items)) {
    const tasks = plan.items.filter((item) => item && typeof item.concept === "string" && item.concept &&
      ["resume", "review", "learn"].includes(item.action)).slice(0, 3);
    tasks.forEach((item) => {
      const li = el("li");
      const box = el("span", "box"); box.appendChild(icon("i-check"));
      const prefix = item.action === "resume" ? "继续：" : item.kind === "transfer" ? "迁移验证：" : item.action === "review" ? "复习：" : "初测：";
      const action = el("button", "plan-action learning-plan-task", prefix + (item.name || item.concept));
      action.type = "button"; action.disabled = learningPlanLoading;
      action.title = item.reason || "根据本机作答记录安排";
      action.addEventListener("click", () => startLearningPlanTask(item, action));
      li.append(box, action); ul.appendChild(li);
    });
    if (!tasks.length) {
      const li = el("li");
      const body = el("div");
      const next = formatLearningPlanDate(plan.next_due_at);
      body.appendChild(el("p", "study-source", next ? "下次建议复习：" + next + "（北京时间）" : "当前没有到期任务。"));
      const open = el("button", "plan-action", "查看课程与学习路径"); open.type = "button";
      open.addEventListener("click", () => showView("learn"));
      body.appendChild(open); li.appendChild(body); ul.appendChild(li);
    }
  } else {
    const items = [];
    if (data.weak && data.weak.length) {
      data.weak.slice(0, 2).forEach((w) => {
        items.push({ text: "复习《" + shortBook(w.book) + "》P" + w.page + " 附近", done: false });
      });
    }
    items.push({ text: "完成 1 次有书页引用的提问", done: (data.questions?.day_cited || 0) > 0, view: "home" });
    items.push({ text: "检索 1 次 PubMed 文献", done: (data.literature?.day || 0) > 0, view: "research" });
    items.push({ text: "查看课程与推荐任务", done: false, view: "learn" });
    items.slice(0, 4).forEach((it) => {
      const li = el("li", it.done ? "done" : "");
      const box = el("span", "box"); box.appendChild(icon("i-check"));
      const action = el("button", "plan-action", it.text); action.type = "button";
      action.addEventListener("click", () => {
        if (it.view === "research") resetResearchContext();
        showView(it.view || "learn");
      });
      li.append(box, action); ul.appendChild(li);
    });
  }

  const day = /^\d{4}-\d{2}-\d{2}$/.test(data.day_date || "") ? new Date(data.day_date + "T12:00:00+08:00") : new Date();
  $("planDate").textContent = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", weekday: "short"
  }).format(Number.isNaN(day.getTime()) ? new Date() : day);
}

function formatLearningPlanDate(timestamp) {
  if (!Number.isFinite(timestamp) || timestamp <= 0) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", month: "numeric", day: "numeric",
    hour: "2-digit", minute: "2-digit", hour12: false
  }).format(new Date(timestamp * 1000));
}

function renderLearningPlan(plan, errorMessage = "") {
  const panel = $("learningPlan");
  if (!panel) return;
  panel.innerHTML = "";
  const heading = el("div", "learning-plan-heading");
  const headingText = el("div");
  const title = el("h2", null, "今天从这里开始"); title.id = "learningPlanTitle";
  headingText.append(el("p", "study-label", "根据你的作答安排下一步"), title);
  const refresh = el("button", "link", "刷新计划"); refresh.type = "button";
  refresh.addEventListener("click", async () => {
    if (learningPlanLoading) return;
    refresh.disabled = true;
    try { await refreshOverview(); } finally { refresh.disabled = false; }
  });
  heading.append(headingText, refresh); panel.appendChild(heading);
  const status = el("p", "study-source learning-plan-status");
  status.id = "learningPlanStatus"; status.setAttribute("role", "status");
  if (errorMessage) status.textContent = "计划刷新失败，" + (plan ? "当前保留上一次结果。" : "请重试读取。") + " " + errorMessage;
  panel.appendChild(status);
  if (!plan || !Array.isArray(plan.items)) {
    panel.appendChild(el("p", "empty-line", "暂未读取到学习计划。你仍可从“我的学习”选择知识点；这里不会显示预设成绩或虚构任务。"));
    const open = el("button", "btn", "选择知识点"); open.type = "button";
    open.addEventListener("click", () => showView("learn")); panel.appendChild(open);
    return;
  }
  panel.appendChild(el("p", "study-source learning-plan-scope", plan.scope || "根据本机学习记录推荐"));
  const counts = plan.counts || {};
  const metrics = el("div", "learning-plan-metrics");
  [["今日已练", counts.practiced_today], ["到期待练", counts.due], ["尚未测评", counts.new]].forEach(([label, count]) => {
    const metric = el("div");
    metric.append(el("strong", null, Number.isFinite(count) && count >= 0 ? String(count) : "—"), el("span", null, label));
    metrics.appendChild(metric);
  });
  panel.appendChild(metrics);
  const list = el("div", "learning-plan-list");
  const items = plan.items.filter((item) => item && typeof item.concept === "string" && item.concept &&
    ["resume", "review", "learn"].includes(item.action)).slice(0, 5);
  const more = items.length > 2 ? el("details", "learning-plan-more") : null;
  if (more) more.appendChild(el("summary", null, "还有 " + (items.length - 2) + " 项学习建议"));
  items.forEach((item, index) => {
    const orchestrated = item.origin === "orchestration";
    const row = el("article", "learning-plan-item" + (index === 0 ? " is-next" : "")
      + (orchestrated ? " is-remediation" : ""));
    const content = el("div", "learning-plan-content");
    const nameRow = el("div", "learning-plan-name");
    const label = orchestrated ? "诊断后补救"
      : item.action === "resume" ? "继续未完成" : item.action === "review" ? "复习巩固" : "新知识";
    nameRow.append(el("span", "pill" + (orchestrated ? " warn" : ""), label),
      el("h3", null, item.name || item.concept));
    content.append(nameRow, el("p", "learning-plan-reason", item.reason || "根据本机作答记录安排。"));
    if (Array.isArray(item.weak_points) && item.weak_points.length) {
      content.appendChild(el("p", "learning-plan-weak", "重点补齐：" + item.weak_points.slice(0, 3).join("、")));
    }
    const detail = [];
    if (Number.isFinite(item.last_score)) detail.push("最近作答 " + item.last_score + " 分");
    if (Number.isFinite(item.due_at)) detail.push("建议复习时间 " + formatLearningPlanDate(item.due_at));
    if (detail.length) content.appendChild(el("p", "study-source learning-plan-detail", detail.join(" · ")));
    const start = el("button", "btn" + (index === 0 ? " btn-primary" : "") + " learning-plan-task",
      item.action === "resume" ? "继续作答 →" : item.kind === "transfer" ? "做迁移题 →" : item.action === "review" ? "开始复习 →" : "先测一测 →");
    start.type = "button"; start.disabled = learningPlanLoading;
    start.addEventListener("click", () => startLearningPlanTask(item, start));
    row.append(content, start); (index < 2 ? list : more).appendChild(row);
  });
  if (more) list.appendChild(more);
  if (!items.length) {
    const next = formatLearningPlanDate(plan.next_due_at);
    list.appendChild(el("p", "empty-line", "当前没有到期的建议任务。" + (next ? "下次建议复习时间：" + next + "（北京时间）。" : "") + "你也可以从“我的学习”主动选择知识点。"));
    const open = el("button", "btn", "查看我的学习"); open.type = "button";
    open.addEventListener("click", () => showView("learn")); list.appendChild(open);
  }
  panel.appendChild(list);
  const method = el("details", "learning-plan-method");
  method.append(el("summary", null, "为什么这样安排？"), el("p", "study-source",
    (plan.method || "推荐依据是本机作答记录。") + " 练习次数与最近得分不等于医学知识已审定或长期掌握。"));
  panel.appendChild(method);
}

async function startLearningPlanTask(item, button) {
  if (learningPlanLoading || quizLoading || quizSubmitting || (typeof quizHintLoading !== "undefined" && quizHintLoading)) {
    toast("当前学习任务正在处理，请稍后继续"); return;
  }
  learningPlanLoading = true;
  const label = button.textContent;
  button.textContent = "正在载入…"; button.disabled = true;
  $$(".learning-plan-task").forEach((control) => { control.disabled = true; });
  const status = $("learningPlanStatus"); if (status) status.textContent = "正在打开：" + (item.name || item.concept);
  let taskLoaded = false;
  try {
    showView("quiz", { restoreTask: false });
    const kind = item.action === "resume" ? "auto" : ["diagnostic", "transfer"].includes(item.kind) ? item.kind : "auto";
    await loadTask(item.concept, kind);
    if (quizPhase !== "task" || quizTask?.concept !== item.concept) throw new Error("任务未能载入，请重试。");
    taskLoaded = true;
    if (status) status.textContent = "任务已载入，完成作答后会更新计划。";
    await refreshOverview();
  } catch (error) {
    if (taskLoaded) {
      const currentStatus = $("learningPlanStatus") || status;
      if (currentStatus) currentStatus.textContent = "题目已载入，可继续作答；学习计划刷新失败：" + error.message;
      toast("题目可继续作答，学习计划稍后可刷新");
    } else {
      if (status) status.textContent = error.message;
      const area = $("quizArea"); area.innerHTML = "";
      area.appendChild(el("p", "study-source", "学习任务读取失败：" + error.message));
      const retry = el("button", "btn btn-primary", "重试本次学习任务"); retry.type = "button";
      retry.addEventListener("click", () => startLearningPlanTask(item, button)); area.appendChild(retry);
      toast("任务读取失败，可点击重试");
    }
  } finally {
    learningPlanLoading = false;
    button.textContent = label; button.disabled = false;
    $$(".learning-plan-task").forEach((control) => { control.disabled = false; });
  }
}

function shortBook(name) {
  return (name || "").replace(/（.*?）/g, "").replace(/\(.*?\)/g, "");
}

/* ---------- 我的学习 ---------- */
function renderLearn(data) {
  renderCourse(data);
  const q = data.questions || {};
  const m = $("metrics");
  m.innerHTML = "";
  [
    ["累计提问", q.total || 0],
    ["近 7 天提问", q.week || 0],
    ["近 7 天有引用", q.week_cited || 0],
    ["常问页段", (data.weak || []).length],
  ].forEach(([label, val]) => {
    const d = el("div", "metric");
    d.appendChild(el("strong", null, String(val)));
    d.appendChild(el("span", null, label));
    m.appendChild(d);
  });

  const weak = $("weakList");
  weak.innerHTML = "";
  if (!(data.weak || []).length) {
    weak.appendChild(el("p", "empty-line", "还没有反复提问的页段。多问几次同一主题，这里会自动浮现。"));
  } else {
    data.weak.forEach((w) => {
      const b = el("button", "weak-item");
      b.type = "button";
      b.appendChild(el("b", null, "P" + w.page));
      b.appendChild(el("span", null, "《" + shortBook(w.book) + "》"));
      b.appendChild(el("span", "count", w.count + " 次"));
      b.addEventListener("click", () => {
        showView("home");
        $("q").value = "《" + shortBook(w.book) + "》P" + w.page + " 这一节的重点是什么";
        $("q").focus();
      });
      weak.appendChild(b);
    });
  }

  const hist = $("historyList");
  hist.innerHTML = "";
  const list = (data.recent || []).concat([]);
  if (!list.length) {
    hist.appendChild(el("p", "empty-line", "暂无提问记录。"));
  } else {
    list.forEach((it) => {
      const b = el("button", "history-item");
      b.type = "button";
      b.appendChild(el("time", null, it.time));
      b.appendChild(el("span", null, it.query));
      b.addEventListener("click", () => {
        showView("home");
        $("q").value = it.query;
        ask(it.query);
      });
      hist.appendChild(b);
    });
  }
}

function renderCourse(data) {
  const renderRequest = ++syllabusRefsRequest;
  if (typeof mountCourseCatalog === "function") mountCourseCatalog($("courseCatalog"), {
    onAsk: (text) => { setAskContext(null); showView("home"); $("q").value = text; $("q").focus(); },
    onStart: async () => { showView("quiz", { restoreTask: false }); await loadTask(data.recommendation?.id || "oculomotor", "auto"); }
  });
  const box = $("coursePanel");
  box.innerHTML = "";
  const course = data.course;
  const concepts = data.concepts || [];
  if (!course || !concepts.length) {
    box.appendChild(el("p", "empty-line", "课程暂未载入，请确认本地服务已更新并刷新页面。"));
    return;
  }
  if (!concepts.some((c) => c.id === selectedCourseConcept)) {
    selectedCourseConcept = data.active?.concept || data.recommendation?.id || concepts[0].id;
  }
  const selected = concepts.find((c) => c.id === selectedCourseConcept);
  const heading = el("div", "course-heading");
  const names = el("div");
  names.append(el("p", "study-label", "我的课程 / " + course.name),
    el("h2", null, course.chapter + " · 示例章节"),
    el("p", "study-source", "本区提供 10 个脑神经知识点的诊断、补学与迁移练习。上方目录展示已导入大纲；评分目标仍待教师逐项审核。"));
  const stats = data.stats || {};
  heading.append(names, el("span", "pill", (stats.mastered || 0) + " / " + concepts.length + " 个已掌握"));
  box.appendChild(heading);
  if (typeof summarizeLevels === "function") {
    const levelRows = summarizeLevels(concepts);
    if (levelRows.length) {
      const summary = el("div", "course-level-summary");
      levelRows.forEach((row) => summary.appendChild(el("p", "study-source",
        "「" + row.level + "」级 " + row.total + " 个：已测评 " + row.assessed + "，已掌握 " + row.mastered)));
      summary.appendChild(el("p", "study-source", "层级为示例教学目标，待教师审核。"));
      box.appendChild(summary);
    }
  }
  const layout = el("div", "course-layout");
  const directory = el("div", "course-directory");
  [...new Set(concepts.map((c) => c.unit))].forEach((unit) => {
    directory.appendChild(el("h3", "course-unit", unit));
    concepts.filter((c) => c.unit === unit).forEach((c) => {
      const button = el("button", "course-topic" + (c.id === selected.id ? " is-active" : ""));
      button.type = "button";
      button.setAttribute("aria-pressed", String(c.id === selected.id));
      button.append(el("span", null, c.name), el("small", null, c.status));
      button.addEventListener("click", () => { selectedCourseConcept = c.id; renderCourse(data); });
      directory.appendChild(button);
    });
  });
  const entry = el("div", "course-entry");
  entry.append(el("p", "study-label", selected.id === data.recommendation?.id ? "根据当前作答记录推荐" : "你选择的知识点"),
    el("h3", null, selected.name),
    el("p", "study-source", "示例目标：" + selected.level + " · " + selected.status +
      "。阅读只记录接触情况，掌握需通过不同题目的测评。"));
  if (Array.isArray(selected.syllabus_refs) && selected.syllabus_refs.length) {
    const refsLine = el("p", "study-source", "对应大纲要求：" + selected.syllabus_refs.join("；"));
    entry.appendChild(refsLine);
    if (typeof loadCourseMaterials === "function") {
      Promise.resolve(loadCourseMaterials()).then((materials) => {
        if (renderRequest !== syllabusRefsRequest) return;
        const items = materials?.syllabus?.items || [];
        refsLine.textContent = "对应大纲要求：" + selected.syllabus_refs.map((ref) => {
          const item = items.find((i) => i.id === ref);
          if (!item) return ref;
          const requirement = String(item.text || "");
          return (item.chapter || "") + "·" + (requirement.length > 30 ? requirement.slice(0, 30) + "…" : requirement);
        }).join("；");
      }).catch(() => {});
    }
  }
  const modes = el("fieldset", "course-modes");
  modes.appendChild(el("legend", null, "这次想怎样开始？"));
  [["test", "先测一测，检查掌握情况"], ["study", "先复习学习卡，再做题"],
    ["ask", "我有具体问题，查询教材依据"], ["research", "从这个主题探索文献"]].forEach(([value, label]) => {
      const row = el("label");
      const radio = el("input");
      radio.type = "radio"; radio.name = "courseMode"; radio.value = value;
      radio.checked = selectedCourseMode === value;
      radio.addEventListener("change", () => { selectedCourseMode = value; });
      row.append(radio, el("span", null, label)); modes.appendChild(row);
    });
  const start = el("button", "btn btn-primary", "开始学习 →");
  start.type = "button";
  start.addEventListener("click", () => {
    if (selectedCourseMode === "test" || selectedCourseMode === "study") {
      showView("quiz", { restoreTask: false });
      if (selectedCourseMode === "study") showStudyForResult({ concept: selected.id, score: 0, rubric: [] });
      else loadTask(selected.id, "auto");
    } else if (selectedCourseMode === "ask") {
      openConceptQuestion(selected.id, selected.name);
    } else {
      openResearch(selected.name, selected.id);
    }
  });
  entry.append(modes, start);
  if (data.active) {
    const resume = el("button", "link course-resume", "继续尚未提交的测评 ›");
    resume.type = "button";
    resume.addEventListener("click", () => {
      showView("quiz", { restoreTask: false }); loadTask(data.active.concept, "auto");
    });
    entry.appendChild(resume);
  }
  layout.append(directory, entry); box.appendChild(layout);
}

/* ---------- 知识库 ---------- */
function renderBooks(data) {
  const grid = $("bookGrid");
  grid.innerHTML = "";
  if (!(data.books || []).length) {
    grid.appendChild(el("p", "empty-line", "尚未导入可核对的教材书页。准备好教材索引后，这里会显示书名与页码范围。"));
    return;
  }
  const max = Math.max(1, ...(data.books || []).map((b) => b.chunks));
  (data.books || []).forEach((b) => {
    const card = el("div", "book-card");
    const ic = el("div", "book-icon");
    ic.appendChild(icon("i-books"));
    card.appendChild(ic);
    card.appendChild(el("h3", null, shortBook(b.book)));
    const ver = (b.book.match(/（(.*?)）/) || [])[1] || "版本未注明";
    card.appendChild(el("div", "meta", ver + " · " + b.chunks + " 条索引"));
    card.appendChild(el("div", "meta", "索引页码 P" + b.min + " – P" + b.max + "（待对照原书）"));
    const bar = el("div", "bar");
    const i = el("i");
    i.style.width = Math.round((b.chunks / max) * 100) + "%";
    bar.appendChild(i);
    card.appendChild(bar);
    grid.appendChild(card);
  });
}

$("downloadIndexTemplate").addEventListener("click", () => {
  const template = [{ book: "请填写教材名称和版本", chapter: "请填写章节", page: null,
    keywords: ["请填写检索词"], text: "可选：你有权在本机使用的教材段落" }];
  const blob = new Blob([JSON.stringify(template, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = el("a");
  a.href = url;
  a.download = "教材页码索引模板.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

$("importIndex").addEventListener("click", async () => {
  const file = $("indexFile").files?.[0];
  const status = $("importStatus");
  if (!file) { status.textContent = "请先选择 JSON 或 JSONL 文件。"; return; }
  if (!$("importAuthorized").checked) { status.textContent = "请先确认使用权和隐私要求。"; return; }
  if (file.size > 1_800_000) { status.textContent = "文件过大；请拆成不超过 1.8 MB 的批次。"; return; }
  try {
    const raw = await file.text();
    let records;
    if (file.name.toLowerCase().endsWith(".jsonl")) {
      records = raw.split(/\r?\n/).filter((line) => line.trim()).map((line) => JSON.parse(line));
    } else {
      const parsed = JSON.parse(raw);
      records = Array.isArray(parsed) ? parsed : (Array.isArray(parsed.records) ? parsed.records : [parsed]);
    }
    if (!records.length || records.length > 1000) throw new Error("每次只能导入 1–1000 条记录");
    status.textContent = "正在导入 " + records.length + " 条索引…";
    const result = await api("/api/import", { records, authorized: true });
    status.textContent = result.message || "已导入 " + result.count + " 条索引；页码仍需对照原书核验。";
    await refreshOverview();
  } catch (e) {
    status.textContent = "导入失败：" + e.message;
  }
});

/* ---------- 个人中心 ---------- */
function renderStatus(data) {
  const box = $("statusPanel");
  box.innerHTML = "";
  const st = data.status || {};
  const rows = [
    ["教材数量", (data.books || []).length + " 本"],
    ["索引记录", (data.chunks || 0).toLocaleString() + " 条"],
    ["累计提问", String((data.questions || {}).total || 0)],
    ["回答方式", st.llm ? "已接入大模型（" + st.model + "）" : "离线抽取模式（未配置 API Key）"],
    ["文献来源", "PubMed E-utilities（公开接口）"],
    ["拒答阈值", "覆盖率 < " + st.coverage_threshold],
    ["数据存储", "服务所在电脑的 SQLite；联网发送范围见本页说明"],
  ];
  rows.forEach(([k, v]) => {
    const r = el("div", "status-row");
    const left = el("span", null, k);
    const right = el("b", null, v);
    if (k === "回答方式") {
      const dot = el("i", "dot" + (st.llm ? "" : " off"));
      right.prepend(dot);
    }
    r.append(left, right);
    box.appendChild(r);
  });
}

function downloadLearningJson(data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = el("a"); link.href = url;
  link.download = "MedNexus-学习报告-" + new Date().toLocaleDateString("sv-SE") + ".json";
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$("exportLearning").addEventListener("click", async () => {
  const button = $("exportLearning"); button.disabled = true;
  try {
    const data = await api("/api/export");
    const local = {};
    Object.entries(quicknoteProgress).forEach(([key, value]) => {
      if (/^\d+$/.test(key) && ["known", "review"].includes(value)) local[key] = value;
    });
    data.quicknote_self_review = local;
    data.excluded = (data.excluded || []).filter((label) => label !== "浏览器速记记录");
    downloadLearningJson(data);
    $("dataStatus").textContent = "学习报告摘要已生成。文件不包含教材原文与提问原文；不支持导入还原学习历史。";
  } catch (error) { $("dataStatus").textContent = "导出失败：" + error.message; }
  finally { button.disabled = false; }
});
$("clearConfirmed").addEventListener("change", () => { $("clearLearning").disabled = !$("clearConfirmed").checked; });
$("clearScope").addEventListener("change", () => { $("clearConfirmed").checked = false; $("clearLearning").disabled = true; });
$("clearLearning").addEventListener("click", async () => {
  if (!$("clearConfirmed").checked || dataResetting) return;
  if (activeRequests) { $("dataStatus").textContent = "仍有请求正在处理，请完成后再清理。"; return; }
  dataResetting = true; $("clearLearning").disabled = true;
  const scope = $("clearScope").value;
  try {
    await api("/api/reset", { scope, confirmation: scope === "all" ? "CLEAR_MY_DATA" : "CLEAR_MY_LEARNING" });
    clearTutorChatState();
    try { clearTaskDraft(sessionStorage, learnerId()); } catch (_) {}
    reportRequestId++;
    localStorage.removeItem(quicknoteKey());
    localStorage.removeItem("mednexus-materials-" + learnerId());
    quicknoteProgress = {}; quizTask = null; quizConcept = null; quizPhase = "empty";
    selectedCourseConcept = null; resetResearchContext(); setAskContext(null); answerOriginConcept = null;
    $("result").hidden = true; $("q").value = "";
    $("dataStatus").textContent = scope === "all" ? "已清理学习记录和当前身份导入的索引。" : "已清理学习记录，导入索引已保留。";
    $("clearConfirmed").checked = false;
  } catch (error) { $("dataStatus").textContent = "清理未完成：" + error.message; }
  finally {
    dataResetting = false; $("clearLearning").disabled = !$("clearConfirmed").checked;
    await refreshOverview();
  }
});

/* ---------- 提问 ---------- */
const MODE_TEXT = { "教材摘录": "教材原文要点", "拒答": "暂无教材依据", llm: "模型生成", extractive: "离线抽取", extractive_fallback: "离线兜底", refuse: "已拒答" };

function renderBadges(data) {
  const box = $("badges");
  box.innerHTML = "";
  const ok = (data.citations || []).filter((c) => c.ok).length;
  const total = (data.citations || []).length;
  box.appendChild(el("span", "tag " + (data.refused ? "bad" : "good"),
    data.refused ? "查不到依据 · 已拒答" : `引用 ${ok}/${total} 通过`));
  if ((data.expanded || []).length) {
    box.appendChild(el("span", "tag ghost", "扩展：" + data.expanded.join("、")));
  }
}

function renderCites(data) {
  const box = $("cites");
  box.innerHTML = "";
  const list = data.citations || [];
  if (!list.length) {
    box.appendChild(el("div", "cite no", "本次回答未使用教材引用"));
    return;
  }
  list.forEach((c) => {
    const row = el("div", "cite " + (c.ok ? "ok" : "no"));
    row.appendChild(icon(c.ok ? "i-check" : "i-x"));
    const body = el("div");
    const head = el("div");
    head.appendChild(el("b", null, "《" + c.book + "》" + (c.page ? "第 " + c.page + " 页" : "（无页码）")));
    if (c.chapter) head.appendChild(el("span", "reason", " · " + c.chapter));
    head.appendChild(document.createTextNode(" "));
    head.appendChild(el("span", "reason", c.reason || ""));
    body.appendChild(head);
    if (c.snippet) body.appendChild(el("div", "reason", "「" + c.snippet + "」"));
    row.appendChild(body);
    box.appendChild(row);
  });
}

function paperCard(p) {
  const card = el("div", "paper");
  const top = el("div", "paper-top");
  top.appendChild(el("span", "ev", p.evidence || "文献"));
  const meta = [p.journal, p.year].filter(Boolean).join(" · ");
  if (meta) top.appendChild(el("span", "src", meta));
  card.appendChild(top);
  card.appendChild(el("h4", null, p.title || "(无标题)"));
  if (p.authors?.length) card.appendChild(el("p", "paper-authors", p.authors.slice(0, 3).join("、")));
  if (p.abstract && p.abstract.length) {
    const raw = Array.isArray(p.abstract)
      ? p.abstract.map((part) => part.text || "").filter(Boolean).join(" ")
      : String(p.abstract);
    const t = raw.slice(0, 300);
    card.appendChild(el("p", null, t + (raw.length > 300 ? "…" : "")));
  }
  if (p.pmid) {
    const a = el("a", null, "PubMed · PMID " + p.pmid + " ↗");
    a.href = "https://pubmed.ncbi.nlm.nih.gov/" + p.pmid + "/";
    a.target = "_blank";
    a.rel = "noopener";
    card.appendChild(a);
    if (researchContext?.question) {
      const read = el("button", "link paper-read", "阅读摘要与证据 →");
      read.type = "button";
      read.addEventListener("click", () => loadPaperReading(p));
      card.appendChild(read);
    }
  }
  return card;
}

function renderPapers(container, papers, note, tagEl) {
  container.innerHTML = "";
  if (tagEl) {
    tagEl.textContent = note ? String(note).replace(/^cache:/, "") : "";
    tagEl.title = tagEl.textContent;
  }
  if (!papers || !papers.length) {
    const empty = el("div", "paper");
    empty.appendChild(el("p", null, note || "未获取文献"));
    container.appendChild(empty);
    return;
  }
  papers.forEach((p) => container.appendChild(paperCard(p)));
}

function setAskContext(concept) {
  askOriginConcept = concept;
  const banner = $("askContext");
  banner.hidden = !concept;
  banner.innerHTML = "";
  if (!concept) return;
  const name = overviewData?.concepts?.find((c) => c.id === concept)?.name || concept;
  banner.appendChild(el("span", null, "当前学习：系统解剖学 / 脑神经 / " + name));
  const back = el("button", "link", "返回知识点学习 ›");
  back.type = "button";
  back.addEventListener("click", () => { showView("quiz", { restoreTask: false }); loadTask(concept, "auto"); });
  const clear = el("button", "link", "切换为独立提问");
  clear.type = "button"; clear.addEventListener("click", () => setAskContext(null));
  banner.append(back, clear);
}

function openConceptQuestion(concept, question) {
  setAskContext(concept); showView("home"); $("q").value = question; $("q").focus();
}

async function ask(question, originConcept = null) {
  if (busy) return;
  const q = (question || "").trim();
  if (!q) { toast("先输入一个问题"); $("q").focus(); return; }

  busy = true;
  setAskContext(originConcept);
  answerOriginConcept = null;
  $("wanderBtn").disabled = true;
  $("sendBtn").disabled = true;
  const result = $("result");
  result.hidden = false;
  $("resultTitle").textContent = "正在检索「" + q + "」";
  $("answerText").textContent = "正在教材里找依据，并回查页码…";
  $("answerText").classList.remove("is-refused");
  $("cites").innerHTML = "";
  $("tips").innerHTML = "";
  $("badges").innerHTML = "";
  result.scrollIntoView({ behavior: "smooth", block: "start" });

  try {
    const data = await api("/api/ask", { question: q });
    answerOriginConcept = originConcept;
    $("resultTitle").textContent = "关于「" + data.question + "」";
    renderBadges(data);
    const ans = $("answerText");
    ans.textContent = data.answer || "（无内容）";
    ans.classList.toggle("is-refused", !!data.refused);
    $("modeTag").textContent = MODE_TEXT[data.mode] || data.mode || "—";
    renderCites(data);
    if (typeof showLocalMaterialMatches === "function") showLocalMaterialMatches(q);
    const tips = $("tips");
    tips.innerHTML = "";
    (data.tips || []).forEach((t) => tips.appendChild(el("li", null, t)));
    $("statCoverage").textContent = (data.coverage ?? 0).toFixed(2);
    const ok = (data.citations || []).filter((c) => c.ok).length;
    $("statCites").textContent = ok + "/" + (data.citations || []).length;
    $("statMs").textContent = data._ms ?? "—";
    $("wanderPrompt").textContent = data.wander?.prompt || "要不要深入了解？进入文献漫游查找前沿研究。";
    $("wanderBtn").dataset.question = data.question || q;
    $("wanderBtn").disabled = false;
    if (data.refused) toast("教材中没有找到可核对的依据，已拒答");
    refreshOverview();
  } catch (e) {
    $("answerText").textContent = "请求失败：" + e.message;
    toast("请求失败：" + e.message);
  } finally {
    busy = false;
    $("sendBtn").disabled = false;
  }
}

/* ---------- 科研探索 ---------- */
function resetResearchContext() {
  wanderOriginConcept = null; researchContext = null;
  pmRequestId++; readingRequestId++;
  $("pmResults").innerHTML = ""; $("pmStatus").textContent = "";
  $("paperReading").hidden = true; $("researchReturn").hidden = true;
  $("researchQueryEditor").hidden = true; $("pmQuery").value = "";
  $("researchContextLabel").textContent = "";
  $("pmQ").value = "";
  if (typeof clearResearchQueryPlan === 'function') clearResearchQueryPlan($("researchQueryPlan"));
  try { if (typeof clearResearchDraft === "function") clearResearchDraft(sessionStorage, learnerId()); } catch (_) {}
}

function rememberResearchWorkspace() {
  if (typeof saveResearchDraft !== "function") return;
  try {
    saveResearchDraft(sessionStorage, learnerId(), {concept:wanderOriginConcept, question:$("pmQ").value,
      query:$("pmQuery").value, ready:!$("researchQueryEditor").hidden}, (overviewData?.concepts || []).map(c => c.id));
  } catch (_) {}
}

function restoreResearchWorkspace() {
  if (typeof readResearchDraft !== "function") return;
  let draft;
  try { draft = readResearchDraft(sessionStorage, learnerId(), (overviewData?.concepts || []).map(c => c.id)); } catch (_) { return; }
  if (!draft) return;
  wanderOriginConcept = draft.concept;
  researchContext = {concept:draft.concept, question:draft.question};
  $("pmQ").value = draft.question; $("pmQuery").value = draft.query;
  $("researchQueryEditor").hidden = !(draft.concept && draft.ready && draft.query && draft.question.trim());
  $("researchReturn").hidden = !draft.concept;
  if (typeof clearResearchQueryPlan === 'function') {
    clearResearchQueryPlan($("researchQueryPlan"));
    $("researchQueryPlan").textContent = '已恢复编辑草稿；词语对照未恢复，可重新判断疑问取得建议。';
  }
  if (draft.concept) {
    const name = overviewData.concepts.find(c => c.id === draft.concept).name;
    $("researchContextLabel").textContent = "来自：系统解剖学 / 脑神经 / " + name;
  }
  $("pmStatus").textContent = "已恢复本窗口的疑问与检索式草稿。文献结果未自动重查，请确认内容后主动检索。";
}

function openResearch(question, concept = null) {
  resetResearchContext();
  wanderOriginConcept = concept;
  researchContext = { question, concept };
  $("pmQ").value = question;
  showView("research"); $("pmQ").focus();
  if (concept) {
    const name = overviewData?.concepts?.find((c) => c.id === concept)?.name || concept;
    $("researchContextLabel").textContent = "来自：系统解剖学 / 脑神经 / " + name;
    $("researchReturn").hidden = false;
    $("pmStatus").textContent = "请写下这个知识点的具体机制、差异或证据疑问。先判断问题并确认英文检索式，再查询文献。";
  }
  rememberResearchWorkspace();
}

async function pmSearch(q, originConcept = null, editedQuery = null) {
  const query = (q || "").trim();
  if (!query) { toast("先输入一个疑问"); return; }
  const request = ++pmRequestId;
  readingRequestId++;
  wanderOriginConcept = originConcept;
  researchContext = { question: query, concept: originConcept };
  $("pmStatus").textContent = originConcept && editedQuery === null ? "正在判断疑问与当前知识点的关联…" : "正在检索 PubMed 真实文献…";
  $("pmResults").innerHTML = "";
  $("paperReading").hidden = true;
  $("researchReturn").hidden = !originConcept;
  $("researchQueryEditor").hidden = true;
  rememberResearchWorkspace();
  try {
    if (originConcept && editedQuery === null) {
      if (typeof clearResearchQueryPlan === 'function') clearResearchQueryPlan($("researchQueryPlan"));
      const gate = await api("/api/research", { concept: originConcept, question: query });
      if (request !== pmRequestId) return;
      $("pmStatus").textContent = gate.reason + (gate.eligible ? "\n" + gate.mapping : "\n建议先补学，再明确要比较的条件或证据。");
      if (gate.eligible) {
        $("pmQuery").value = gate.query;
        $("researchQueryEditor").hidden = false;
        if (typeof mountResearchQueryPlan === 'function') mountResearchQueryPlan($("researchQueryPlan"), gate.query_plan, value => {
          if ($("pmQ").value.trim() !== query || wanderOriginConcept !== originConcept) return;
          $("pmQuery").value = value; researchQueryChanged();
        });
      }
      rememberResearchWorkspace();
      return;
    }
    const payload = { question: query, retmax: 6 };
    if (originConcept) { payload.concept = originConcept; payload.query = editedQuery; }
    const data = await api("/api/pubmed", payload);
    if (request !== pmRequestId) return;
    $("pmStatus").textContent = data.note
      ? (data.mapping || "") + "\n检索式：" + data.note +
        "\nPubMed 共 " + data.count + " 条匹配；下方按发表日期显示本次获取的文献。摘要为原文节选，具体结论请打开原文核对。"
      : "";
    renderPapers($("pmResults"), data.papers, data.note);
    if (originConcept) { $("pmQuery").value = data.note; $("researchQueryEditor").hidden = false; }
    if (typeof updateResearchQueryPlan === 'function') updateResearchQueryPlan($("researchQueryPlan"), $("pmQuery").value);
    rememberResearchWorkspace();
    $("researchReturn").hidden = !wanderOriginConcept;
    if (!data.papers || !data.papers.length) {
      $("pmStatus").textContent = "没有取到文献：" + (data.note || "检索式为空");
    }
  } catch (e) {
    if (request !== pmRequestId) return;
    $("pmStatus").textContent = "检索失败：" + e.message;
    if (originConcept && editedQuery !== null) $("researchQueryEditor").hidden = false;
    rememberResearchWorkspace();
    if (e.url) {
      const a = el("a", null, "在 PubMed 打开检索式 ↗");
      a.href = e.url;
      a.target = "_blank";
      a.rel = "noopener";
      $("pmStatus").appendChild(a);
    }
  }
}

async function loadPaperReading(paper) {
  const context = researchContext;
  if (!context?.question) return;
  const request = ++readingRequestId;
  const panel = $("paperReading");
  const body = $("paperReadingBody");
  panel.hidden = false;
  body.textContent = "正在读取 PubMed 摘要…";
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const result = await api("/api/read-paper", {
      concept: context.concept || null, pmid: paper.pmid, question: context.question
    });
    if (request !== readingRequestId) return;
    mountPaperReading(body, result);
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    if (request !== readingRequestId) return;
    body.textContent = "摘要读取失败：" + e.message;
    const retry = el('button', 'btn', '重试读取这篇摘要'); retry.type = 'button';
    retry.addEventListener('click', () => { if (researchContext === context) loadPaperReading(paper); });
    body.appendChild(retry);
  }
}

/* ---------- 数据加载 ---------- */
async function refreshOverview() {
  try {
    overviewData = await api("/api/overview");
    renderRecent(overviewData.recent || []);
    renderChecklist(overviewData);
    renderLearningPlan(overviewData.learning_plan);
    if (document.querySelector("#view-learn.is-active")) renderLearn(overviewData);
    if (document.querySelector("#view-quiz.is-active")) renderQuiz(overviewData);
    if (document.querySelector("#view-books.is-active")) renderBooks(overviewData);
    if (document.querySelector("#view-me.is-active")) renderMe(overviewData);
  } catch (e) {
    console.warn("overview failed", e);
    renderLearningPlan(overviewData?.learning_plan, e.message);
    showDataNotice(e.message);
  }
}

/* ---------- 事件绑定 ---------- */
$("askForm").addEventListener("submit", (e) => {
  e.preventDefault();
  ask($("q").value, askOriginConcept);
});

$("wanderBtn").addEventListener("click", () => {
  const topic = $("wanderBtn").dataset.question || $("q").value.trim();
  if (!topic) return;
  openResearch(topic, answerOriginConcept);
  pmSearch(topic, answerOriginConcept);
});

$("returnTransfer").addEventListener("click", () => {
  if (!wanderOriginConcept) return;
  const cid = wanderOriginConcept;
  showView("quiz", { restoreTask: false });
  loadTask(cid, "transfer");
});

$$(".chip", $("chips")).forEach((c) => {
  c.addEventListener("click", () => {
    const text = c.textContent.trim();
    if (text === "我有个问题想问…") { $("q").focus(); return; }
    $("q").value = text;
    setAskContext(null);
    ask(text);
  });
});

const askGuides = $("askGuides");
if (askGuides) {
  $$(".chip", askGuides).forEach((c) => {
    c.addEventListener("click", () => {
      $("q").value = c.textContent.trim();
      setAskContext(null);
      $("q").focus();
      ask($("q").value);
    });
  });
}

$("pmForm").addEventListener("submit", (e) => {
  e.preventDefault();
  pmSearch($("pmQ").value, wanderOriginConcept);
});
$("runResearchQuery").addEventListener("click", () => pmSearch($("pmQ").value, wanderOriginConcept, $("pmQuery").value));
$("pmQuery").addEventListener("input", () => researchQueryChanged());
function researchQueryChanged() {
  pmRequestId++; readingRequestId++;
  $("pmResults").innerHTML = ""; $("paperReading").hidden = true;
  $("pmStatus").textContent = "检索式已修改，请确认后主动重新检索。";
  if (typeof updateResearchQueryPlan === 'function') updateResearchQueryPlan($("researchQueryPlan"), $("pmQuery").value);
  rememberResearchWorkspace();
}
const researchScopeButtons = { researchScopeBasic: "basic", researchScopeFrontier: "frontier", researchScopeNone: "none" };
Object.keys(researchScopeButtons).forEach((id) => {
  $(id).addEventListener("click", () => {
    if (typeof applyResearchScope !== "function") return;
    const mode = researchScopeButtons[id];
    $("pmQuery").value = applyResearchScope($("pmQuery").value, mode, new Date().getFullYear());
    researchQueryChanged();
    $("pmStatus").textContent = mode === "basic" ? "已限定综述类文献；仅调整检索式，不保证结果更基础，请核对后主动检索。" :
      mode === "frontier" ? "已限定近四个自然年；仅调整检索式，不保证结果更前沿，请核对后主动检索。" :
      "已去掉检索限定；请核对后主动检索。";
  });
});
$("newResearch").addEventListener("click", () => {
  resetResearchContext(); $("pmQ").focus();
  $("pmStatus").textContent = "已开启独立检索。可输入医学主题或英文 PubMed 检索式。";
});
$("pmQ").addEventListener("input", () => {
  pmRequestId++; readingRequestId++;
  $("researchQueryEditor").hidden = true; $("paperReading").hidden = true;
  $("pmResults").innerHTML = "";
  $("pmStatus").textContent = "疑问已修改，请重新提交。";
  if (typeof clearResearchQueryPlan === 'function') clearResearchQueryPlan($("researchQueryPlan"));
  rememberResearchWorkspace();
});

$$(".pm-chip").forEach((c) => {
  c.addEventListener("click", () => {
    resetResearchContext();
    $("pmQ").value = c.textContent.trim();
    pmSearch($("pmQ").value);
  });
});

$$(".quick-card").forEach((card) => {
  card.addEventListener("click", () => {
    const act = card.dataset.act;
    if (act === "research") { resetResearchContext(); showView("research"); $("pmQ").focus(); return; }
    if (act === "learn") {
      // 开始学习 = 先选章节再出题；章节选择在「学习评估」页第一步
      showView("quiz", { restoreTask: false });
      const chapterPanel = $("quizChapterPanel");
      if (chapterPanel) chapterPanel.scrollIntoView({ block: "start", behavior: "smooth" });
      return;
    }
    if (act === "quiz") { showView("quiz"); return; }
    if (act === "ask") { showView("ask"); $("q").focus(); return; }
  });
});

/* ---------- 学习评估（诊断 → 三要点评分 → 掌握度） ---------- */
let quizConcept = null;
let quizTask = null;
let quizPhase = "empty";
let quizSubmitting = false;
let quizLoading = false;
let quizHintLoading = false;
let quizUnit = null;

async function resumeActiveTask() {
  if (quizLoading || quizSubmitting || quizHintLoading) return;
  quizLoading = true;
  try {
    const data = await api("/api/bootstrap");
    if (quizPhase !== "empty") return;
    if (data.active) {
      quizConcept = data.active.concept;
      quizTask = data.active;
      quizPhase = "task";
      renderTaskCard(data.active);
    } else if (data.last_result) {
      quizConcept = data.last_result.concept;
      quizTask = null;
      quizPhase = "result";
      $("quizKind").textContent = data.last_result.kind === "transfer" ? "上次迁移题结果" : "上次诊断题结果";
      renderQuizResult(data.last_result);
    }
    renderQuiz(overviewData);
  } catch (e) {
    if (quizPhase === "empty") {
      const box = $("quizArea");
      box.textContent = "上次学习状态读取失败：" + e.message;
      const retry = el("button", "btn", "重新读取上次学习");
      retry.type = "button"; retry.addEventListener("click", resumeActiveTask); box.appendChild(retry);
    }
  } finally { quizLoading = false; }
}

function renderQuiz(data) {
  const box = $("quizConcepts");
  const report = $("quizReport");
  if (!data) return;

  // 指标
  const m = $("quizMetrics");
  if (m) {
    const st = data.stats || {};
    m.innerHTML = "";
    [["已测评知识点", (st.assessed || 0) + " / " + (st.total || 0)],
     ["已掌握", st.mastered || 0],
     ["需巩固", st.weak || 0],
     ["累计作答", st.attempts || 0]].forEach(([label, val]) => {
      const d = el("div", "metric");
      d.appendChild(el("strong", null, String(val)));
      d.appendChild(el("span", null, label));
      m.appendChild(d);
    });
  }

  // 第一步：章节（课程单元）。章节只决定可选知识点，不自动出题。
  const units = quizUnits(data);
  if (quizUnit && !units.some((u) => u.name === quizUnit)) quizUnit = null;
  const unitBox = $("quizUnits");
  if (unitBox) {
    unitBox.innerHTML = "";
    units.forEach((u) => {
      const b = el("button", "chip", u.name);
      b.type = "button";
      const done = u.completed ? " · 已完成" : " · " + u.assessed + "/" + u.total + " 已测评";
      b.title = u.name + done;
      b.classList.toggle("is-active", u.name === quizUnit);
      b.addEventListener("click", () => {
        quizUnit = quizUnit === u.name ? null : u.name;
        renderQuiz(overviewData);
      });
      unitBox.appendChild(b);
    });
    if (!units.length) unitBox.appendChild(el("p", "study-source", "没有读到章节数据（页面构建 " + (PAGE_BUILD || "未知") + "）。请确认服务是最新版本：关闭窗口后重新双击「医枢 MedNexus」，再按 Ctrl+F5 刷新。"));
  }
  const chapterHint = $("quizChapterHint");
  if (chapterHint) {
    const current = units.find((u) => u.name === quizUnit);
    chapterHint.textContent = current ? current.name + " · " + current.total + " 个知识点" : "还没有选章节";
  }
  const unitNote = $("quizUnitNote");
  if (unitNote) {
    const current = units.find((u) => u.name === quizUnit);
    unitNote.textContent = current
      ? "本章已测评 " + current.assessed + " / " + current.total + " 个知识点" + (current.completed ? "，可以继续巩固或换章。" : "；本章全部测评完才算完成。")
      : "章节来自本机课程单元划分；先选一章，再在右侧挑知识点出题。";
  }

  // 第二步：知识点（按章节过滤）
  const conceptHint = $("quizConceptHint");
  if (conceptHint) conceptHint.textContent = quizUnit ? "本章可选" : "先选章节";
  if (box) {
    box.innerHTML = "";
    const pool = (data.concepts || []).filter((c) => !quizUnit || c.unit === quizUnit);
    if (!quizUnit) {
      box.appendChild(el("p", "study-source", "先在上面选一个章节，这里会列出该章的知识点。"));
    } else if (!pool.length) {
      box.appendChild(el("p", "study-source", "本章还没有可测评的知识点。"));
    }
    pool.forEach((c) => {
      const b = el("button", "chip", c.name);
      b.type = "button";
      b.dataset.cid = c.id;
      b.title = c.status + (c.attempts ? " · " + c.attempts + " 题" : "");
      b.classList.toggle("is-active", c.id === quizConcept);
      b.addEventListener("click", () => {
        loadTask(c.id, "auto");
      });
      box.appendChild(b);
    });
  }

  // 掌握概览：仍然给出全部知识点，便于对照
  if (report) {
    report.innerHTML = "";
    (data.concepts || []).forEach((c) => {
      const row = el("button", "weak-item");
      row.type = "button";
      row.appendChild(el("b", null, c.status || "未测评"));
      row.appendChild(el("span", null, c.name));
      row.appendChild(el("span", "count", (c.attempts || 0) + " 题"));
      row.addEventListener("click", () => {
        quizUnit = c.unit || quizUnit;
        loadTask(c.id, "auto");
      });
      report.appendChild(row);
    });
  }

  if (quizPhase === "empty") {
    const area = $("quizArea");
    area.innerHTML = "";
    if (!quizUnit) {
      area.appendChild(el("p", null, "先在「第一步」选一个章节，再选知识点出题；也可以直接按推荐来一道。"));
    } else {
      const chapter = units.find((u) => u.name === quizUnit);
      area.appendChild(el("p", null, "已选章节：" + quizUnit + (chapter ? "（已测评 " + chapter.assessed + " / " + chapter.total + "）" : "") + "。在右侧点一个知识点开始出题。"));
    }
    const start = el("button", "btn btn-primary", quizUnit ? "按推荐在本章来一道题" : "按推荐直接来一道题");
    start.type = "button";
    start.addEventListener("click", () => loadTask(nextConceptId(), "auto"));
    area.appendChild(start);
    area.appendChild(quizToolbar({ refresh: false }));
  }
  renderQuizAsk(data);
}

function quizUnits(data) {
  if (Array.isArray(data.units) && data.units.length) return data.units;
  const names = [];
  (data.concepts || []).forEach((c) => {
    if (c.unit && !names.includes(c.unit)) names.push(c.unit);
  });
  return names.map((name) => {
    const rows = (data.concepts || []).filter((c) => c.unit === name);
    const assessed = rows.filter((c) => c.attempts > 0).length;
    return { name, total: rows.length, assessed, mastered: rows.filter((c) => c.status === "已掌握").length,
      progress: rows.length ? Math.round(assessed / rows.length * 100) : 0,
      completed: rows.length > 0 && assessed === rows.length };
  });
}

async function loadTask(cid, kind = "auto") {
  if (quizLoading || quizSubmitting || quizHintLoading) { toast("当前任务正在处理，请稍后切换"); return null; }
  quizLoading = true;
  quizConcept = cid;
  quizPhase = "loading";
  $("quizArea").textContent = "正在出题…";
  try {
    const t = await api("/api/task", { concept: cid, kind });
    quizTask = t;
    quizPhase = "task";
    renderTaskCard(t);
    return t;
  } catch (e) {
    quizPhase = "error";
    $("quizArea").textContent = "出题失败：" + e.message;
    const retry = el('button', 'btn', '重试出题');
    retry.addEventListener('click', () => loadTask(cid, kind));
    $("quizArea").appendChild(retry);
    return null;
  } finally { quizLoading = false; renderQuiz(overviewData); }
}

function nextConceptId() {
  const pool = (overviewData?.concepts || []).filter((c) => !quizUnit || c.unit === quizUnit);
  const list = pool.map((c) => c.id).filter(Boolean);
  if (!list.length) return quizConcept;
  const recommend = overviewData?.recommendation?.id;
  if (recommend && list.includes(recommend) && recommend !== quizConcept) return recommend;
  const i = list.indexOf(quizConcept);
  return list[(i + 1) % list.length] || quizConcept;
}

/* 每次出题/看结果/补学都带同一组「换一题、换个知识点」按钮，
   学生不会被卡在某一题或某段对话里出不来。 */
function quizToolbar({ refresh = true, refreshLabel = "换一题" } = {}) {
  const bar = el("div", "quiz-actions");
  bar.style.cssText = "display:flex;gap:10px;flex-wrap:wrap;margin-top:14px";
  if (refresh) {
    const again = el("button", "btn", refreshLabel);
    again.type = "button";
    again.title = "放弃当前这道题，换同一知识点的另一道题（不计分）";
    again.addEventListener("click", () => {
      if (!quizConcept) { toast("先选一个知识点"); return; }
      loadTask(quizConcept, "refresh");
    });
    bar.appendChild(again);
  }
  const jump = el("button", "btn", "换个知识点");
  jump.type = "button";
  jump.addEventListener("click", () => loadTask(nextConceptId(), "auto"));
  bar.appendChild(jump);
  return bar;
}

function renderTaskCard(t) {
  $("quizKind").textContent = t.kind === "transfer" ? "迁移题 · 不同情境" : "诊断题";
  const area = $("quizArea");
  area.innerHTML = "";
  area.appendChild(el("p", "answer", t.prompt));

  let restored = null;
  try { restored = readTaskDraft(sessionStorage, learnerId(), t); } catch (_) {}
  const draft = {answers: restored?.answers.slice() || t.points.map(() => null),
    confidence:restored?.confidence || '未填写', reasoning:restored?.reasoning || ''};
  const form = el("div");
  const answers = draft.answers;
  const draftStatus = el('p', 'study-source task-draft-status', restored ?
    '已恢复本窗口未提交的选择与补充记录；尚未计分。' :
    '选择会作为草稿保留在本窗口，刷新可恢复；提交后才计分。');
  draftStatus.setAttribute('role', 'status');
  const remember = () => {
    if (quizTask?.token !== t.token || quizPhase !== 'task') return;
    let status = 'unavailable';
    try { status = saveTaskDraft(sessionStorage, learnerId(), t, draft); } catch (_) {}
    draftStatus.textContent = status === 'saved' ? '本窗口草稿已保存，尚未提交或计分。' : status === 'private' ?
      '补充推理疑似含个人信息，草稿未保存。请改为匿名教学说明。' :
      '浏览器暂不能保存草稿；可继续作答，刷新后可能丢失未提交内容。';
  };
  const optionButtons = [];
  (t.points || []).forEach((p, i) => {
    const wrap = el("div", "cite");
    wrap.style.flexDirection = "column";
    wrap.style.alignItems = "stretch";
    wrap.appendChild(el("b", null, (i + 1) + ". " + p.label));
    const row = el("div", "chips");
    row.style.marginTop = "8px";
    p.options.forEach((opt) => {
      const b = el("button", "chip", opt);
      b.type = "button";
      b.classList.toggle('is-active', answers[i] === opt);
      b.setAttribute('aria-pressed', String(answers[i] === opt));
      b.addEventListener("click", () => {
        if (quizSubmitting || quizLoading || quizTask?.token !== t.token || quizPhase !== 'task') return;
        answers[i] = opt;
        $$(".chip", row).forEach((x) => {
          x.classList.toggle("is-active", x === b); x.setAttribute('aria-pressed', String(x === b));
        });
        remember();
      });
      optionButtons.push(b);
      row.appendChild(b);
    });
    wrap.appendChild(row);
    const hints = el('div', 'task-hints');
    const previousHints = p.hints || [];
    previousHints.forEach((text, step) => hints.appendChild(el('p', 'study-source task-hint-item', '教材出处' + (step + 1) + '：' + text)));
    const hintButton = el('button', 'btn task-hint-button', previousHints.length ? '再看另一处出处' : '这题在教材哪一页');
    hintButton.type = 'button';
    hintButton.dataset.level = previousHints.length;
    if (previousHints.length >= 2) { hintButton.disabled = true; hintButton.textContent = '两处出处已显示'; }
    hintButton.addEventListener('click', () => requestTaskHint(t, i, hintButton, hints));
    wrap.append(hints, hintButton);
    form.appendChild(wrap);
  });
  area.appendChild(form);

  const reflection = el('div', 'task-reflection');
  const confidenceLabel = el('label', 'task-confidence-label', '这次作答有多大把握？');
  const confidence = el('select'); confidence.setAttribute('aria-label', '本次作答信心');
  [['未填写','暂不记录信心'],['不确定','不确定'],['一般','一般'],['很有把握','很有把握']].forEach(([value, text]) => {
    const option = el('option', null, text); option.value = value; confidence.appendChild(option);
  });
  confidence.value = draft.confidence;
  confidence.addEventListener('change', () => { draft.confidence = confidence.value; remember(); });
  confidenceLabel.appendChild(confidence); reflection.appendChild(confidenceLabel);
  const reasoningDetails = el('details', 'task-reasoning');
  reasoningDetails.appendChild(el('summary', null, '记录我的推理（可选）'));
  const reasoningLabel = el('label', null, '说明你如何连接结构、功能与表现');
  const reasoning = el('textarea'); reasoning.rows = 3; reasoning.maxLength = 3000;
  reasoning.setAttribute('aria-label', '补充推理'); reasoning.value = draft.reasoning;
  reasoning.placeholder = '仅写匿名教学分析，请勿输入个人或患者资料。';
  reasoning.addEventListener('input', () => { draft.reasoning = reasoning.value; remember(); });
  reasoningLabel.appendChild(reasoning);
  reasoningDetails.append(reasoningLabel, el('p', 'study-source', '推理仅记录供回顾，不自动评分，也不会自动发给教学模型。'));
  if (draft.reasoning) reasoningDetails.open = true;
  reflection.appendChild(reasoningDetails); area.append(reflection, draftStatus);

  const submit = el("button", "btn btn-primary", "提交作答");
  submit.type = 'button';
  submit.style.marginTop = "16px";
  submit.addEventListener("click", async () => {
    if (quizSubmitting || quizLoading || quizHintLoading || quizTask?.token !== t.token || quizPhase !== 'task') return;
    const controls = [...optionButtons, confidence, reasoning, submit];
    controls.forEach(control => { control.disabled = true; });
    submit.textContent = '正在提交…';
    try { await submitAnswer(t, answers.slice(), {confidence:draft.confidence, reasoning:draft.reasoning}); }
    finally { controls.forEach(control => { control.disabled = false; }); submit.textContent = '提交作答'; }
  });
  area.appendChild(submit);
  area.appendChild(quizToolbar());
  area.appendChild(el('p', 'study-source', '可先独立作答；卡住时点“这题在教材哪一页”，会给出书名、印刷页码和原文片段，方便回书核对。使用提示的作答会标为辅助练习，不作为独立掌握证据。'));
  const tutorBox = el('section'); area.appendChild(tutorBox);
  mountTutorChat(tutorBox, t.token);
}

async function requestTaskHint(t, point, button, container) {
  if (quizLoading || quizSubmitting || quizHintLoading || quizTask?.token !== t.token) return;
  const level = Number(button.dataset.level || 0) + 1;
  if (level > 2) return;
  quizHintLoading = true; button.disabled = true;
  const oldLabel = button.textContent; button.textContent = '正在检索教材…';
  try {
    const data = await api('/api/hint', {token:t.token, point, level});
    if (quizTask?.token !== t.token || quizPhase !== 'task') return;
    container.appendChild(el('p', 'study-source task-hint-item', '教材出处' + data.level + '：' + data.text));
    button.dataset.level = data.level;
    button.textContent = data.level >= 2 ? '两处出处已显示' : '再看另一处出处';
    button.disabled = data.level >= 2;
  } catch (error) {
    button.textContent = oldLabel; button.disabled = false;
    toast('教材出处暂不可用：' + error.message + '，可继续作答或重试，结果页会说明是否使用过提示');
  } finally { quizHintLoading = false; }
}

async function submitAnswer(t, answers, reflection = {}) {
  if (quizSubmitting || quizLoading || quizHintLoading) return;
  if (quizTask?.token !== t.token || quizPhase !== 'task') return;
  if (answers.filter(Boolean).length !== (t.points || []).length) {
    toast("三个要点都要选（不会可选「暂时不确定」）");
    return;
  }
  quizSubmitting = true;
  try {
    const r = await api("/api/answer", { token: t.token, answers: answers,
      confidence: reflection.confidence || '未填写', reasoning: reflection.reasoning || '' });
    try { clearTaskDraft(sessionStorage, learnerId(), t.token); } catch (_) {}
    quizTask = null;
    quizPhase = "result";
    renderQuizResult(r);
    await refreshOverview();
    await loadLearningReport();
  } catch (e) {
    toast("提交失败：" + e.message);
  } finally {
    quizSubmitting = false;
  }
}

function renderQuizResult(r) {
  const area = $("quizArea");
  area.innerHTML = "";
  const head = el("p", "answer");
  head.innerHTML = "<b>得分 " + r.score + " / 100</b>　" + r.label;
  area.appendChild(head);
  area.appendChild(el("p", "page-sub", r.why));
  if (r.assisted) area.appendChild(el('p', 'pill', '辅助练习 · 使用过提示或教学对话，需再独立复测'));
  renderAnswerReflection(area, r);

  (r.rubric || []).forEach((p) => {
    const row = el("div", "cite " + (p.correct ? "ok" : "no"));
    row.appendChild(icon(p.correct ? "i-check" : "i-x"));
    const body = el("div");
    body.appendChild(el("b", null, p.label + "：" + (p.correct ? "正确" : "错在「" + p.selected + "」")));
    body.appendChild(el("div", "reason", p.reason + "　正确要点：" + p.expected));
    row.appendChild(body);
    area.appendChild(row);
  });

  const next = el("button", "btn btn-primary",
    r.action === "transfer" ? "做迁移题" :
    r.action === "next" ? "查看下一学习任务" : "查看针对性补学");
  next.style.marginTop = "16px";
  next.addEventListener("click", async () => {
    if (r.action === "transfer") return loadTask(r.concept, "transfer");
    if (r.action === "next") {
      await refreshOverview();
      const cid = overviewData?.recommendation?.id || r.concept;
      return loadTask(cid, "auto");
    }
    return showStudyForResult(r);
  });
  area.appendChild(next);

  const toReport = el("button", "link", "查看学习报告 ›");
  toReport.style.marginLeft = "12px";
  toReport.addEventListener("click", () => $("learningReport").scrollIntoView({ behavior: "smooth" }));
  area.appendChild(toReport);

  // 结果页必须能随时离开：不等推荐按钮，直接再来一道或换知识点。
  area.appendChild(quizToolbar({ refresh: Boolean(r.concept), refreshLabel: "再来一题" }));

  if (r.tutor_token) {
    const tutorBox = el('section'); area.appendChild(tutorBox);
    mountTutorChat(tutorBox, r.tutor_token);
  }

  mountResearchBridge(area, r.concept);
}

function renderAnswerReflection(container, result) {
  const confidence = result.confidence_source === 'self_reported' &&
    ['不确定', '一般', '很有把握'].includes(result.confidence) ? result.confidence : null;
  const reasoning = typeof result.reasoning === 'string' ? result.reasoning : '';
  if (!confidence && !reasoning) return;
  const details = el('details', 'task-reflection task-saved-reflection');
  details.appendChild(el('summary', null, '回看本次信心与推理记录'));
  if (confidence) details.appendChild(el('p', null, '提交时的信心：' + confidence));
  if (confidence && typeof result.calibration === 'string' && result.calibration) details.appendChild(el('p', 'task-calibration', result.calibration));
  if (reasoning) details.append(el('p', 'task-saved-reasoning', reasoning),
    el('p', 'study-source', '以上为你提交时的推理记录，未参与自动评分。'));
  container.appendChild(details);
}

function mountResearchBridge(container, concept) {
  const research = el("div", "research-bridge");
  research.appendChild(el("b", null, "这个知识点还有值得深挖的问题吗？"));
  const question = el("input");
  question.type = "text";
  question.maxLength = 300;
  question.placeholder = "写下具体的机制、差异或证据疑问";
  question.setAttribute("aria-label", "待判断的研究疑问");
  research.appendChild(question);
  const judge = el("button", "btn", "判断能否进入文献漫游");
  const status = el("p", "study-source");
  judge.addEventListener("click", async () => {
    const q = question.value.trim();
    if (!q) { toast("先写一个具体疑问"); question.focus(); return; }
    status.textContent = "正在判断…";
    judge.disabled = true;
    const old = research.querySelector(".research-enter");
    if (old) old.remove();
    try {
      const gate = await api("/api/research", { concept, question: q });
      if (q !== question.value.trim()) return;
      status.textContent = gate.reason;
      if (gate.eligible) {
        const enter = el("button", "btn btn-primary research-enter", "核对英文检索式 →");
        enter.addEventListener("click", () => {
          openResearch(q, concept);
          pmSearch(q, concept);
        });
        research.appendChild(enter);
      }
    } catch (e) {
      status.textContent = "判断失败：" + e.message;
    } finally { judge.disabled = false; }
  });
  question.addEventListener("input", () => {
    const old = research.querySelector(".research-enter");
    if (old) old.remove();
    status.textContent = "";
  });
  research.append(judge, status);
  container.appendChild(research);
}

async function showStudyForResult(result) {
  if (quizLoading || quizSubmitting || quizHintLoading) { toast("当前任务正在处理，请稍后再试"); return; }
  quizLoading = true;
  const area = $("quizArea");
  quizPhase = "loading";
  area.textContent = "正在整理补学内容…";
  try {
    const data = await api("/api/study", { concept: result.concept });
    quizPhase = "study";
    quizConcept = data.concept; quizTask = null;
    $("quizKind").textContent = data.study_mode === "targeted" ? "针对性补学" : "学习准备";
    renderQuiz(overviewData);
    area.innerHTML = "";
    area.appendChild(el("h3", null, (data.study_mode === "targeted" ? "针对性补学 · " : "学习准备 · ") + data.name));
    area.appendChild(el("p", "study-source", data.study_mode === "targeted" ?
      "根据本知识点最近一次作答，只整理仍未掌握的要点。" : "尚无需要补齐的错点记录。先阅读学习卡，再通过独立作答检查掌握情况。"));
    (data.focus || []).forEach((point) => {
      const row = el("div", "cite no");
      row.appendChild(el("div", null, point.label + "：" + point.reason + " 正确要点：" + point.expected));
      (point.evidence || []).forEach((source) => row.appendChild(studyEvidence(source)));
      if (!point.evidence?.length) row.appendChild(el("p", "study-source", "该要点尚无匹配的教材书页。下面的自编学习卡仅作教学示例。"));
      area.appendChild(row);
    });
    area.appendChild(el("p", "study-label", "自编学习卡（教学示例，待教师审核）"));
    area.appendChild(el("p", "answer", data.note));
    if (data.study_mode !== "targeted") (data.local_sources || []).forEach((source) => area.appendChild(studyEvidence(source)));
    if (!(data.local_sources || []).length) {
      area.appendChild(el("p", "study-source", "本知识点尚无可核对的教材页码；请结合课程教材核对学习卡。"));
    }
    if (/^https:\/\//.test(data.source?.url || "")) {
      const reference = el("a", "study-source", "公开参考：" + data.source.title + " ↗（请核对原文，不是课程教材页码）");
      reference.href = data.source.url; reference.target = "_blank"; reference.rel = "noopener";
      area.appendChild(reference);
    }
    const actions = el("div", "quicknote-actions");
    const retestKind = data.retest_kind === "transfer" ? "transfer" : "diagnostic";
    const retest = el("button", "btn btn-primary", retestKind === "diagnostic" ? "补完再测基础题" : "补完做迁移题");
    retest.addEventListener("click", () => loadTask(data.concept, retestKind));
    const askMore = el("button", "btn", "围绕这个知识点查询教材");
    askMore.addEventListener("click", () => openConceptQuestion(data.concept, data.name));
    actions.append(retest, askMore); area.appendChild(actions);
    area.appendChild(quizToolbar({ refresh: true, refreshLabel: "直接换一道题" }));
    mountResearchBridge(area, data.concept);
  } catch (e) {
    quizPhase = "result";
    area.textContent = "补学内容读取失败：" + e.message;
    const retry = el("button", "btn", "重试补学");
    retry.addEventListener("click", () => showStudyForResult(result));
    area.appendChild(retry);
  } finally { quizLoading = false; }
}

function studyEvidence(source) {
  const box = el("div", "study-evidence");
  const locator = "《" + source.book + "》" + (source.chapter ? " · " + source.chapter : "") +
    (source.page ? " · 第 " + source.page + " 页" : " · 暂无教材页码");
  box.appendChild(el("p", "study-source", locator + "（请对照原书核验）"));
  if (source.evidence_type === "text" && source.excerpt) box.appendChild(el("p", "answer", "原文节选：" + source.excerpt));
  box.appendChild(el("p", "study-source", source.evidence_notice || "导入来源尚需核对。"));
  return box;
}

async function loadLearningReport() {
  const box = $("learningReportBody");
  const request = ++reportRequestId;
  box.textContent = "正在读取实际作答记录…";
  try {
    const data = await api("/api/report");
    if (request !== reportRequestId) return;
    mountLearningReport(box, data, {
      onReview: async row => {
        if (!row.can_study_current) return;
        if (quizLoading || quizSubmitting || quizHintLoading) { toast("当前任务正在处理，请稍后切换"); return; }
        showView("quiz", {restoreTask:false});
        await showStudyForResult({concept:row.concept});
        $("quizArea").scrollIntoView({behavior:"smooth",block:"start"});
      },
      onRetest: async row => {
        if (quizLoading || quizSubmitting || quizHintLoading) { toast("当前任务正在处理，请稍后切换"); return; }
        if (!["diagnostic", "transfer"].includes(row.kind)) return;
        showView("quiz", {restoreTask:false});
        await loadTask(row.concept, row.kind);
        $("quizArea").scrollIntoView({behavior:"smooth",block:"start"});
      }
    });
  } catch (e) {
    if (request !== reportRequestId) return;
    box.textContent = "学习报告读取失败：" + e.message;
    const retry = el("button", "btn", "重新读取学习报告");
    retry.type = "button"; retry.addEventListener("click", loadLearningReport);
    box.appendChild(retry);
  }
}

/* ---------- 本机 PDF 速记自测（翻卡核对，不自动评分） ---------- */
let quicknoteData = null;
let quicknoteVisible = [];
let quicknoteIndex = 0;
let quicknoteRevealed = false;
let quicknoteProgress = {};

function quicknoteKey() {
  return "mednexus-quicknotes-" + (quicknoteData?.source_sha256 || "local");
}

function saveQuicknoteProgress() {
  localStorage.setItem(quicknoteKey(), JSON.stringify(quicknoteProgress));
}

async function loadQuicknotes() {
  if (quicknoteData) return;
  try {
    quicknoteData = await api("/api/quick-notes");
    if (!quicknoteData.available || !quicknoteData.items?.length) {
      $("quicknoteCard").textContent = quicknoteData.message || "本机尚未导入速记资料。";
      return;
    }
    try { quicknoteProgress = JSON.parse(localStorage.getItem(quicknoteKey()) || "{}"); }
    catch (_) { quicknoteProgress = {}; }
    const select = $("quicknoteSection");
    [...new Set(quicknoteData.items.map((item) => item.chapter).filter(Boolean))].forEach((chapter) => {
      const option = el("option", null, chapter);
      option.value = chapter;
      select.appendChild(option);
    });
    filterQuicknotes();
  } catch (error) {
    $("quicknoteCard").textContent = "速记资料加载失败：" + error.message;
  }
}

function renderQuicknoteMetrics() {
  const items = quicknoteData?.items || [];
  const known = items.filter((item) => quicknoteProgress[item.number] === "known").length;
  const review = items.filter((item) => quicknoteProgress[item.number] === "review").length;
  const metrics = $("quicknoteMetrics");
  metrics.innerHTML = "";
  [["考点总数", items.length], ["已记住", known], ["待复习", review], ["当前筛选", quicknoteVisible.length]].forEach(([label, value]) => {
    const node = el("div", "metric");
    node.append(el("strong", null, String(value)), el("span", null, label));
    metrics.appendChild(node);
  });
}

function filterQuicknotes() {
  if (!quicknoteData?.items) return;
  const chapter = $("quicknoteSection").value;
  const state = $("quicknoteStatus").value;
  const query = $("quicknoteSearch").value.trim().toLowerCase();
  quicknoteVisible = quicknoteData.items.filter((item) => {
    const progress = quicknoteProgress[item.number] || "unseen";
    return (!chapter || item.chapter === chapter)
      && (!state || progress === state)
      && (!query || [String(item.number), item.text, item.cue, item.chapter, item.section]
        .some((value) => String(value || "").toLowerCase().includes(query)));
  });
  quicknoteIndex = 0;
  quicknoteRevealed = false;
  renderQuicknoteMetrics();
  renderQuicknoteCard();
}

function renderQuicknoteCard() {
  const card = $("quicknoteCard");
  card.innerHTML = "";
  const item = quicknoteVisible[quicknoteIndex];
  const hasItem = !!item;
  ["quicknotePrev", "quicknoteNext", "quicknoteRandom", "quicknoteReveal", "quicknoteReview", "quicknoteKnown"]
    .forEach((id) => { $(id).disabled = !hasItem; });
  if (!item) {
    card.appendChild(el("p", "empty-line", "没有符合筛选条件的考点，请调整章节、状态或搜索词。"));
    return;
  }
  const position = el("p", "quicknote-position",
    "第 " + (quicknoteIndex + 1) + " / " + quicknoteVisible.length + " 条 · 编号 " + item.number);
  const section = el("p", "quicknote-section", [item.chapter, item.section].filter(Boolean).join(" · "));
  const cue = el("h2", "quicknote-cue", item.cue || "请回忆这条考点的完整内容");
  const status = quicknoteProgress[item.number] || "unseen";
  const badge = el("span", "quicknote-badge", status === "known" ? "已记住" : status === "review" ? "待复习" : "未练习");
  card.append(position, section, cue, badge);
  if (quicknoteRevealed) {
    card.appendChild(el("p", "quicknote-answer", item.text));
    const source = el("a", "quicknote-source", "查看 PDF 原页（第 " + item.page + " 页） ↗");
    source.href = "/api/quick-notes/source.pdf#page=" + Math.max(1, Number(item.page) || 1);
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    card.appendChild(source);
    card.appendChild(el("p", "quicknote-caution", "本卡由扫描件 OCR 提取，尚未逐条校对；以原页为准。"));
  }
  $("quicknoteReveal").textContent = quicknoteRevealed ? "收起答案" : "查看答案";
}

function moveQuicknote(offset) {
  if (!quicknoteVisible.length) return;
  quicknoteIndex = (quicknoteIndex + offset + quicknoteVisible.length) % quicknoteVisible.length;
  quicknoteRevealed = false;
  renderQuicknoteCard();
}

$("quicknoteSection").addEventListener("change", filterQuicknotes);
$("quicknoteStatus").addEventListener("change", filterQuicknotes);
$("quicknoteSearch").addEventListener("input", filterQuicknotes);
$("quicknotePrev").addEventListener("click", () => moveQuicknote(-1));
$("quicknoteNext").addEventListener("click", () => moveQuicknote(1));
$("quicknoteRandom").addEventListener("click", () => {
  if (!quicknoteVisible.length) return;
  quicknoteIndex = Math.floor(Math.random() * quicknoteVisible.length);
  quicknoteRevealed = false;
  renderQuicknoteCard();
});
$("quicknoteReveal").addEventListener("click", () => {
  quicknoteRevealed = !quicknoteRevealed;
  renderQuicknoteCard();
});
[["quicknoteReview", "review"], ["quicknoteKnown", "known"]].forEach(([id, state]) => {
  $(id).addEventListener("click", () => {
    const item = quicknoteVisible[quicknoteIndex];
    if (!item) return;
    quicknoteProgress[item.number] = state;
    saveQuicknoteProgress();
    if ($("quicknoteStatus").value) filterQuicknotes();
    else { renderQuicknoteMetrics(); renderQuicknoteCard(); }
  });
});

/* ---------- 学习评估内的教材答疑 ---------- */
let quizAskBusy = false;

function quizAskExamples(data) {
  const list = [];
  const concept = (data?.concepts || []).find((c) => c.id === quizConcept);
  const task = quizTask && quizTask.concept === quizConcept ? quizTask : null;
  // 优先用当前这道题的三个要点做示例，问句短、能直接命中原文
  (task?.points || []).slice(0, 2).forEach((p) => {
    if (p.label) list.push(p.label + "怎么解释？");
  });
  if (concept) list.push(shortBook(concept.name) + "在教材哪一页？");
  if (!list.length && quizUnit) list.push(quizUnit + "这一章最常考什么？");
  return list.slice(0, 4);
}

function renderQuizAsk(data) {
  const chips = $("quizAskChips");
  if (!chips) return;
  chips.innerHTML = "";
  quizAskExamples(data).forEach((text) => {
    const b = el("button", "chip", text);
    b.type = "button";
    b.addEventListener("click", () => {
      $("quizAskInput").value = text;
      quizAskSubmit();
    });
    chips.appendChild(b);
  });
  const input = $("quizAskInput");
  const concept = (data?.concepts || []).find((c) => c.id === quizConcept);
  if (input && concept) input.placeholder = "例如：" + concept.name + "为什么会出现这些表现？";
}

async function quizAskSubmit() {
  if (quizAskBusy) return;
  const input = $("quizAskInput");
  const q = (input?.value || "").trim();
  if (!q) { toast("先写下你的问题"); input?.focus(); return; }
  quizAskBusy = true;
  const status = $("quizAskStatus");
  const box = $("quizAskResult");
  status.textContent = "正在教材里找依据，并回查页码…";
  box.hidden = true;
  box.innerHTML = "";
  try {
    const data = await api("/api/ask", { question: q, concept: quizConcept || null });
    status.textContent = "";
    box.hidden = false;
    const head = el("div", "quiz-ask-head");
    head.appendChild(el("span", "tag", MODE_TEXT[data.mode] || data.mode || "—"));
    const ok = (data.citations || []).filter((c) => c.ok).length;
    head.appendChild(el("span", "tag ghost", "引用 " + ok + "/" + (data.citations || []).length));
    head.appendChild(el("span", "tag ghost", "覆盖率 " + (data.coverage ?? 0).toFixed(2)));
    box.appendChild(head);
    const ans = el("p", "quiz-ask-answer", data.answer || "（无内容）");
    if (data.refused) ans.classList.add("is-refused");
    box.appendChild(ans);
    const cites = el("div", "quiz-ask-cites");
    (data.citations || []).forEach((c) => {
      const row = el("div", "cite " + (c.ok ? "ok" : "no"));
      row.appendChild(icon(c.ok ? "i-check" : "i-x"));
      const body = el("div");
      body.appendChild(el("b", null, "《" + c.book + "》" + (c.page ? "第 " + c.page + " 页" : "（无页码）")));
      if (c.snippet) body.appendChild(el("div", "reason", "「" + c.snippet + "」"));
      row.appendChild(body);
      cites.appendChild(row);
    });
    if (!(data.citations || []).length) cites.appendChild(el("div", "cite no", "本次回答未使用教材引用"));
    box.appendChild(cites);
    // 拒答不等于没救：教材用的是术语，学生用的是自己的说法；给出可点的术语检索建议。
    if ((data.suggested || []).length) {
      const row = el("div", "quiz-ask-suggest");
      row.appendChild(el("span", "quiz-ask-suggest-label", "教材里用的是这些词，点一下再问："));
      (data.suggested || []).slice(0, 2).forEach((text) => {
        const chip = el("button", "chip", text);
        chip.type = "button";
        chip.addEventListener("click", () => {
          $("quizAskInput").value = text;
          quizAskSubmit();
        });
        row.appendChild(chip);
      });
      box.appendChild(row);
    }
    if (data.refused) toast("教材里没找到可核对的依据，已拒答");
  } catch (e) {
    status.textContent = "提问失败：" + e.message;
  } finally {
    quizAskBusy = false;
  }
}

const quizAskForm = $("quizAskForm");
if (quizAskForm) {
  quizAskForm.addEventListener("submit", (e) => {
    e.preventDefault();
    quizAskSubmit();
  });
}

/* ---------- 个人中心：学习数据 ---------- */
function renderMe(data) {
  if (!data) return;
  renderProfileCard(data);
  renderMeStats(data);
  renderMeProgress(data);
  renderMeWeek(data);
  renderMeBadges(data);
  renderStatus(data);
}

function renderProfileCard(data) {
  const box = $("profileCard");
  if (!box) return;
  box.innerHTML = "";
  const avatar = el("div", "profile-avatar");
  avatar.appendChild(icon("i-user"));
  box.appendChild(avatar);
  const main = el("div", "profile-main");
  const nameRow = el("div", "profile-name-row");
  nameRow.appendChild(el("h2", null, "同学"));
  const edit = el("button", "btn btn-ghost small", "修改信息");
  edit.type = "button";
  edit.addEventListener("click", () => toast("学习身份由本浏览器匿名生成，不上传姓名与学号；换浏览器即视为另一位同学。"));
  nameRow.appendChild(edit);
  main.appendChild(nameRow);
  main.appendChild(el("p", "profile-school", "郑州大学 · 临床医学 · 大二"));
  main.appendChild(el("p", "profile-motto", "慢慢来，会变好的。"));
  const tags = el("div", "profile-tags");
  ["临床医学", "教材可溯源", "学习记录在本机"].forEach((t) => tags.appendChild(el("span", "tag ghost", t)));
  main.appendChild(tags);
  box.appendChild(main);
  const mark = el("div", "profile-watermark", "Better me · Better future");
  box.appendChild(mark);
}

function renderMeStats(data) {
  const box = $("meStats");
  if (!box) return;
  const lt = data.learning_time || {};
  const st = data.stats || {};
  const units = data.units || [];
  const doneUnits = units.filter((u) => u.completed).length;
  const totalMinutes = lt.total_minutes || 0;
  const hours = (totalMinutes / 60).toFixed(1);
  const weekMinutes = lt.week_minutes || 0;
  const cards = [
    { icon: "i-clock", label: "累计学习时长", value: hours, unit: "小时",
      note: "本周 " + weekMinutes + " 分钟" + (lt.today_minutes ? " · 今日 " + lt.today_minutes + " 分钟" : " · 今日还没计时") },
    { icon: "i-learn", label: "已学知识点", value: (st.assessed || 0) + " / " + (st.total || 0), unit: "",
      note: "已掌握 " + (st.mastered || 0) + " 个 · 需巩固 " + (st.weak || 0) + " 个" },
    { icon: "i-books", label: "已完成章节", value: doneUnits + " / " + units.length, unit: "",
      note: units.length ? "按测评过的知识点计算" : "暂无章节数据", progress: units.length ? Math.round(doneUnits / units.length * 100) : 0 },
    { icon: "i-flask", label: "连续学习天数", value: lt.streak_days || 0, unit: "天",
      note: "累计有记录 " + (lt.active_days ?? 0) + " 天" },
  ];
  box.innerHTML = "";
  cards.forEach((c) => {
    const card = el("article", "me-stat");
    const top = el("div", "me-stat-top");
    top.appendChild(el("span", "me-stat-icon", null)).appendChild(icon(c.icon));
    top.appendChild(el("span", "me-stat-label", c.label));
    card.appendChild(top);
    const val = el("div", "me-stat-value");
    val.appendChild(el("strong", null, String(c.value)));
    if (c.unit) val.appendChild(el("span", null, c.unit));
    card.appendChild(val);
    if (typeof c.progress === "number") {
      const bar = el("div", "me-stat-bar");
      const fill = el("i");
      fill.style.width = Math.min(100, Math.max(0, c.progress)) + "%";
      bar.appendChild(fill);
      card.appendChild(bar);
    }
    card.appendChild(el("p", "me-stat-note", c.note));
    box.appendChild(card);
  });
}

function renderMeProgress(data) {
  const box = $("meProgressBody");
  if (!box) return;
  box.innerHTML = "";
  const units = data.units || [];
  if (!units.length) {
    box.appendChild(el("p", "study-source", "还没有章节数据。"));
    return;
  }
  const total = units.reduce((s, u) => s + u.total, 0);
  const assessed = units.reduce((s, u) => s + u.assessed, 0);
  const pct = total ? Math.round(assessed / total * 100) : 0;
  const ring = el("div", "ring");
  ring.style.setProperty("--pct", pct + "%");
  const inner = el("div", "ring-inner");
  inner.appendChild(el("strong", null, pct + "%"));
  inner.appendChild(el("span", null, "总体完成度"));
  ring.appendChild(inner);
  box.appendChild(ring);
  const list = el("div", "unit-list");
  units.forEach((u) => {
    const row = el("div", "unit-row");
    const head = el("div", "unit-row-head");
    head.appendChild(el("b", null, u.name));
    head.appendChild(el("span", "count", u.assessed + " / " + u.total + (u.completed ? " · 已完成" : "")));
    row.appendChild(head);
    const bar = el("div", "unit-bar");
    const fill = el("i");
    fill.style.width = Math.min(100, Math.max(0, u.progress || 0)) + "%";
    bar.appendChild(fill);
    row.appendChild(bar);
    list.appendChild(row);
  });
  box.appendChild(list);
}

function renderMeWeek(data) {
  const box = $("meWeekChart");
  if (!box) return;
  const lt = data.learning_time || {};
  const series = lt.series || [];
  const label = $("meWeekTotal");
  if (label) label.textContent = "本周 " + (lt.week_minutes || 0) + " 分钟";
  box.innerHTML = "";
  if (!series.length) {
    box.appendChild(el("p", "study-source", "还没有学习时长记录。"));
    return;
  }
  const max = Math.max(1, ...series.map((s) => s.minutes || 0));
  series.forEach((s) => {
    const col = el("div", "week-col");
    const mins = s.minutes || 0;
    const barWrap = el("div", "week-bar-wrap");
    const bar = el("div", "week-bar");
    bar.style.height = Math.max(mins ? 6 : 2, Math.round(mins / max * 100)) + "%";
    if (mins) bar.title = s.date + " · " + mins + " 分钟";
    barWrap.appendChild(bar);
    col.appendChild(barWrap);
    col.appendChild(el("span", "week-val", mins ? String(mins) : ""));
    col.appendChild(el("span", "week-day", (s.date || "").slice(5)));
    box.appendChild(col);
  });
}

function renderMeBadges(data) {
  const box = $("meAchievements");
  if (!box) return;
  const lt = data.learning_time || {};
  const st = data.stats || {};
  const units = data.units || [];
  const badges = [
    { name: "初次测评", desc: "完成第一道诊断题", on: (st.attempts || 0) > 0 },
    { name: "学习半小时", desc: "累计学习时长满 30 分钟", on: (lt.total_minutes || 0) >= 30 },
    { name: "连续三天", desc: "连续 3 天有学习记录", on: (lt.streak_days || 0) >= 3 },
    { name: "掌握一个", desc: "至少 1 个知识点评为已掌握", on: (st.mastered || 0) >= 1 },
    { name: "完成一章", desc: "某一章的知识点全部测评过", on: units.some((u) => u.completed) },
    { name: "全章通关", desc: "所有章节的测评都完成", on: units.length > 0 && units.every((u) => u.completed) },
  ];
  box.innerHTML = "";
  badges.forEach((b) => {
    const card = el("div", "badge" + (b.on ? " is-on" : ""));
    card.appendChild(el("div", "badge-icon", null)).appendChild(icon(b.on ? "i-spark" : "i-bell"));
    const text = el("div", "badge-text");
    text.appendChild(el("b", null, b.name));
    text.appendChild(el("span", null, b.desc));
    card.appendChild(text);
    box.appendChild(card);
  });
}

/* ---------- 学习时长心跳：只在页面可见时计时 ---------- */
const HEARTBEAT_SECONDS = 60;
let heartbeatTimer = null;
let pendingSeconds = 0;

async function flushHeartbeat() {
  const seconds = Math.round(pendingSeconds);
  if (seconds < 1) return;
  pendingSeconds = 0;
  try {
    const data = await api("/api/heartbeat", { seconds: Math.min(600, seconds) });
    if (overviewData && data?.learning_time) {
      overviewData.learning_time = data.learning_time;
      if (document.querySelector("#view-me.is-active")) renderMe(overviewData);
    }
  } catch (_) {
    /* 计时失败不影响学习，静默丢弃这一段 */
  }
}

function startHeartbeat() {
  if (heartbeatTimer) clearInterval(heartbeatTimer);
  heartbeatTimer = setInterval(() => {
    if (document.visibilityState !== "visible") return;
    pendingSeconds += HEARTBEAT_SECONDS;
    flushHeartbeat();
  }, HEARTBEAT_SECONDS * 1000);
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flushHeartbeat();
});

/* ---------- 旧页面自检：服务端更新了而窗口还是旧版时，提示刷新 ---------- */
const PAGE_BUILD = (document.querySelector('meta[name="app-build"]') || {}).content || "";

function showStaleNotice(serverBuild) {
  if (document.getElementById("staleNotice")) return;
  const bar = el("div", "stale-notice");
  bar.id = "staleNotice";
  bar.appendChild(el("span", null, "这个窗口是旧版页面（本页 " + (PAGE_BUILD || "未知") + "，服务端 " + serverBuild + "），新功能可能看不到。"));
  const btn = el("button", "btn btn-primary small", "刷新到最新版");
  btn.type = "button";
  btn.addEventListener("click", () => location.reload());
  bar.appendChild(btn);
  document.body.appendChild(bar);
}

function showDataNotice(message) {
  let bar = document.getElementById("dataNotice");
  if (!bar) {
    bar = el("div", "stale-notice data-notice");
    bar.id = "dataNotice";
    document.body.appendChild(bar);
  }
  bar.textContent = "";
  bar.appendChild(el("span", null, "学习数据没读到：" + (message || "服务没有返回数据") +
    "（页面构建 " + (PAGE_BUILD || "未知") + "）。可以先关闭本窗口，重新双击「医枢 MedNexus」，再按 Ctrl+F5 刷新。"));
  const retry = el("button", "btn btn-primary small", "重试");
  retry.type = "button";
  retry.addEventListener("click", async () => {
    retry.disabled = true;
    await refreshOverview();
    retry.disabled = false;
  });
  bar.appendChild(retry);
}

async function checkBuild() {
  if (!PAGE_BUILD) return;
  try {
    const res = await fetch("/api/version", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    if (data && data.build && data.build !== PAGE_BUILD) showStaleNotice(data.build);
  } catch (err) {
    /* 版本检查失败不影响正常使用 */
  }
}

/* ---------- 启动 ---------- */
/* ---------- 学习评估的两种练法：精选题库 / 教材章节 ---------- */
let quizMode = localStorage.getItem("mednexus-quiz-mode") || "concept";

function applyQuizMode() {
  const bar = $("quizModeBar");
  if (!bar) return;
  [...bar.querySelectorAll(".chip")].forEach((chip) => {
    chip.classList.toggle("is-active", chip.dataset.mode === quizMode);
  });
  const concept = $("quizConceptMode");
  const book = $("quizBookMode");
  if (concept) concept.hidden = quizMode !== "concept";
  if (book) book.hidden = quizMode !== "book";
  if (quizMode === "book") loadDrill();
}

(function bindQuizMode() {
  const bar = $("quizModeBar");
  if (!bar) return;
  bar.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip || !chip.dataset.mode || chip.dataset.mode === quizMode) return;
    quizMode = chip.dataset.mode;
    localStorage.setItem("mednexus-quiz-mode", quizMode);
    applyQuizMode();
  });
})();

/* ---------- 教材精练：按教材章节出原文题（单选速练 / 三要点自测） ---------- */
let drillData = null;
let drillBook = null;
let drillChapter = null;
let drillTask = null;
let drillResult = null;
let drillBusy = false;
let drillDone = 0;
let drillRight = 0;
let drillMode = "single";          // single | triple
let drillModeBound = false;
let tripleCatalog = null;          // { books: { 书名: { eligible, chapters } } }
let tripleTask = null;
let tripleResult = null;
let tripleSelections = [null, null, null];
let tripleBusy = false;
let tripleDone = 0;
let tripleRight = 0;

async function loadDrill() {
  if (drillData && tripleCatalog !== null) {
    renderDrill();
    return;
  }
  const box = $("drillBooks");
  box.textContent = "正在读取教材目录…";
  try {
    // 三要点目录单独吞掉异常：它不可用只隐藏该模式，不影响原有单选速练。
    const [single, triple] = await Promise.all([
      drillData ? Promise.resolve(drillData) : api("/api/kaodian"),
      tripleCatalog !== null ? Promise.resolve(tripleCatalog)
        : api("/api/kaodian/triple-catalog").catch(() => ({ available: false, books: {} })),
    ]);
    drillData = single;
    tripleCatalog = triple;
  } catch (error) {
    box.textContent = "教材目录读取失败：" + error.message;
    return;
  }
  if (!drillData.available) {
    box.textContent = drillData.message || "本机还没有考点题库。";
    return;
  }
  const books = drillData.books || [];
  drillBook = drillBook || (books[0] && books[0].book) || null;
  renderDrill();
}

function bindDrillModeSwitch() {
  if (drillModeBound) return;
  const box = $("drillModeSwitch");
  if (!box) return;
  drillModeBound = true;
  box.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-mode]");
    if (!btn || btn.dataset.mode === drillMode) return;
    drillMode = btn.dataset.mode;
    // 切换模式时清掉另一种模式的中间状态，避免看到上一模式的残留题。
    drillTask = null; drillResult = null;
    tripleTask = null; tripleResult = null; tripleSelections = [null, null, null];
    renderDrill();
  });
}

function tripleEligibleNos() {
  const stats = tripleCatalog?.books?.[drillBook];
  return new Set((stats?.chapters || []).filter((c) => (c.eligible || 0) > 0).map((c) => c.no));
}

function drillBookEntry() {
  return (drillData?.books || []).find((b) => b.book === drillBook) || null;
}

function renderDrill() {
  bindDrillModeSwitch();
  const switchBox = $("drillModeSwitch");
  if (switchBox) switchBox.querySelectorAll("button[data-mode]").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.mode === drillMode);
  });
  const entry = drillBookEntry();
  const bookBox = $("drillBooks");
  bookBox.innerHTML = "";
  (drillData.books || []).forEach((item) => {
    const chip = el("button", "chip" + (item.book === drillBook ? " is-active" : ""), item.book);
    chip.type = "button";
    chip.addEventListener("click", () => {
      if (drillBook === item.book) return;
      drillBook = item.book;
      drillChapter = null;
      drillTask = null;
      drillResult = null;
      renderDrill();
    });
    bookBox.appendChild(chip);
  });

  const chapters = entry ? entry.chapters : [];
  // 单选：一章不到 4 条凑不出选项；三要点：只列能转成合格三要点题的章。
  const eligible = drillMode === "triple" ? tripleEligibleNos() : null;
  const usable = chapters.filter((c) => drillMode === "triple"
    ? eligible.has(c.no)
    : (c.count || 0) >= 4);
  const skipped = chapters.length - usable.length;
  // 切换模式后原选中章节可能不再可用，自动清空避免停在空题状态。
  if (drillChapter != null && !usable.some((c) => c.no === drillChapter)) {
    drillChapter = null; drillTask = null; drillResult = null;
    tripleTask = null; tripleResult = null; tripleSelections = [null, null, null];
  }
  const chapterBox = $("drillChapters");
  chapterBox.innerHTML = "";
  if (!entry) {
    chapterBox.appendChild(el("p", "empty-line", "暂无可用教材。"));
  } else {
    usable.forEach((c) => {
      const stat = tripleCatalog?.books?.[drillBook]?.chapters?.find((x) => x.no === c.no);
      const countText = drillMode === "triple"
        ? (stat?.eligible || 0) + " 题"
        : c.count + " 条";
      const chip = el("button", "chip" + (c.no === drillChapter ? " is-active" : ""),
        (c.title || "第" + c.no + "章") + " · " + countText);
      chip.type = "button";
      chip.addEventListener("click", () => {
        drillChapter = c.no;
        drillTask = null; drillResult = null;
        tripleTask = null; tripleResult = null; tripleSelections = [null, null, null];
        renderDrill();
      });
      chapterBox.appendChild(chip);
    });
  }

  const chapter = usable.find((c) => c.no === drillChapter) || null;
  const skipNote = drillMode === "triple"
    ? "（另有 " + skipped + " 章凑不出合格三要点题）"
    : "（另有 " + skipped + " 章考点太少，暂不出题）";
  $("drillBookHint").textContent = entry
    ? entry.book + " · 可练 " + usable.length + " 章" + (skipped ? skipNote : "")
    : "还没有选教材";
  const chapStat = chapter && tripleCatalog?.books?.[drillBook]?.chapters?.find((x) => x.no === chapter.no);
  $("drillChapterHint").textContent = chapter
    ? chapter.title + (drillMode === "triple"
        ? " · " + (chapStat?.eligible || 0) + " 题可自测"
        : " · " + chapter.count + " 条考点")
    : (entry ? "还没有选章节" : "先选教材");
  $("drillChapterNote").textContent = chapter
    ? (drillMode === "triple"
        ? "从本章考点原文抽出三个要点，逐点选解释；选项与答案均可回书核对，自测不计入掌握度。"
        : "本章共 " + chapter.count + " 条考点；其中术语与完整解释齐全的会用来出题，其余在「速记自测」里逐条背诵。")
    : "选好章节后点「开始这一章」，会从本章原文里抽一条考点出题。";

  const sectionBox = $("drillSections");
  sectionBox.innerHTML = "";
  if (chapter) {
    $("drillSectionHint").textContent = (chapter.sections || []).length + " 个小节";
    (chapter.sections || []).forEach((s) => {
      const row = el("div", "unit-row");
      row.appendChild(el("span", "unit-name", s.name || "未分节"));
      row.appendChild(el("span", "unit-count", s.count + " 条"));
      sectionBox.appendChild(row);
    });
    if (!(chapter.sections || []).length) sectionBox.appendChild(el("p", "empty-line", "这一章没有小节信息。"));
  } else {
    $("drillSectionHint").textContent = "选章节后显示";
    sectionBox.appendChild(el("p", "empty-line", "先选好教材与章节。"));
  }

  $("drillKind").textContent = drillMode === "triple"
    ? (tripleDone ? "已自测 " + tripleDone + " 道 · 要点对 " + tripleRight + "/" + (tripleDone * 3) : "尚未开始")
    : (drillDone ? "已练 " + drillDone + " 道 · 对 " + drillRight + " 道" : "尚未开始");
  renderDrillArea(chapter);
}

function renderDrillArea(chapter) {
  if (drillMode === "triple") { renderTripleArea(chapter); return; }
  const box = $("drillArea");
  box.innerHTML = "";
  if (!chapter) {
    box.appendChild(el("p", "empty-line", "先在上面选教材与章节，再开始出题。"));
    return;
  }
  if (drillResult) {
    renderDrillResult(box);
    return;
  }
  if (!drillTask) {
    const start = el("button", "btn btn-primary", "开始这一章");
    start.type = "button";
    start.addEventListener("click", () => startDrill());
    box.appendChild(el("p", "study-source",
      "从「" + (chapter.title || "") + "」的 " + chapter.count + " 条考点里随机抽一条：可能是给术语选原文解释，也可能把术语挖空让你选。"));
    box.appendChild(start);
    return;
  }
  const kindText = drillTask.kind === "define" ? "原文挖空 · 选术语" : "术语 · 选原文解释";
  const head = el("p", "study-source", kindText + " · 第 " + drillTask.chapter + " 章");
  const prompt = el("p", "drill-prompt", drillTask.prompt);
  const options = el("div", "drill-options");
  drillTask.options.forEach((option) => {
    const btn = el("button", "drill-option", option);
    btn.type = "button";
    btn.addEventListener("click", () => answerDrill(option));
    options.appendChild(btn);
  });
  box.append(head, prompt, options);
  const skip = el("button", "btn", "换一道");
  skip.type = "button";
  skip.addEventListener("click", () => startDrill());
  box.appendChild(skip);
}

function renderDrillResult(box) {
  const result = drillResult;
  const card = el("div", "drill-result" + (result.correct ? " is-right" : " is-wrong"));
  card.appendChild(el("p", "drill-verdict", result.correct ? "✓ 答对了" : "✗ 答错了，正确答案在下面对比"));
  card.appendChild(el("p", "drill-prompt", result.prompt));
  result.options.forEach((option) => {
    const cls = "drill-option";
    const row = el("p", cls + (option === result.answer ? " is-correct" : "") + (option === result.choice && !result.correct ? " is-wrong" : ""), option);
    card.appendChild(row);
  });
  const source = el("p", "drill-source",
    "原文出处：第 " + result.source.no + " 条" + (result.source.section ? "（" + result.source.section + "）" : "") + " —— " + result.source.text);
  card.appendChild(source);
  card.appendChild(el("p", "study-source", result.notice));
  const again = el("button", "btn btn-primary", "再来一道");
  again.type = "button";
  again.addEventListener("click", () => startDrill());
  card.appendChild(again);
  box.appendChild(card);
}

async function startDrill() {
  if (drillBusy || !drillBook || drillChapter == null) return;
  drillBusy = true;
  drillResult = null;
  $("drillArea").textContent = "正在从这一章的原文里抽题…";
  try {
    drillTask = await api("/api/kaodian/task", { book: drillBook, chapter: drillChapter });
  } catch (error) {
    drillBusy = false;
    $("drillArea").textContent = "抽题失败：" + error.message;
    return;
  }
  // 先解除忙碌状态再渲染：否则按钮会带着 disabled 生成，之后不再重绘，点了没反应。
  drillBusy = false;
  renderDrillArea(drillBookEntry()?.chapters.find((c) => c.no === drillChapter) || null);
}

async function answerDrill(choice) {
  if (drillBusy || !drillTask) return;
  drillBusy = true;
  try {
    drillResult = await api("/api/kaodian/answer", { token: drillTask.token, choice });
    drillTask = null;
    drillDone += 1;
    if (drillResult.correct) drillRight += 1;
    $("drillKind").textContent = "已练 " + drillDone + " 道 · 对 " + drillRight + " 道";
  } catch (error) {
    toast("判分失败：" + error.message);
  } finally {
    drillBusy = false;
    renderDrillArea(drillBookEntry()?.chapters.find((c) => c.no === drillChapter) || null);
  }
}

/* ---- 三要点原文自测：逐点选解释，对照原文；不计入掌握度 ---- */
function renderTripleArea(chapter) {
  const box = $("drillArea");
  box.innerHTML = "";
  if (!chapter) {
    box.appendChild(el("p", "empty-line", "先在上面选教材与章节，再开始三要点自测。"));
    return;
  }
  if (tripleResult) { renderTripleResult(box); return; }
  if (!tripleTask) {
    const start = el("button", "btn btn-primary", "开始三要点自测");
    start.type = "button";
    start.addEventListener("click", () => startTriple());
    box.appendChild(el("p", "study-source",
      "把一条考点原文拆成三个要点，逐点选出正确解释。所有选项都来自原文，可回书核对；自测成绩不计入掌握度。"));
    box.appendChild(start);
    return;
  }
  box.appendChild(el("p", "study-source",
    "第 " + tripleTask.chapter + " 章 · 请为下面每个要点各选一个解释"));
  box.appendChild(el("p", "drill-prompt", tripleTask.prompt));
  tripleTask.points.forEach((point, idx) => {
    box.appendChild(el("p", "triple-point-label", "要点 " + (idx + 1) + "：" + point.label));
    const opts = el("div", "drill-options");
    (tripleTask.options[idx] || []).forEach((option) => {
      const btn = el("button", "drill-option" + (tripleSelections[idx] === option ? " is-active" : ""), option);
      btn.type = "button";
      btn.addEventListener("click", () => {
        tripleSelections[idx] = option;
        renderTripleArea(chapter);
      });
      opts.appendChild(btn);
    });
    box.appendChild(opts);
  });
  const submit = el("button", "btn btn-primary", "提交自测");
  submit.type = "button";
  submit.disabled = tripleBusy || tripleSelections.some((s) => !s);
  submit.addEventListener("click", () => answerTriple());
  box.appendChild(submit);
  const skip = el("button", "btn", "换一道");
  skip.type = "button";
  skip.addEventListener("click", () => startTriple());
  box.appendChild(skip);
}

function renderTripleResult(box) {
  const result = tripleResult;
  const card = el("div", "drill-result" + (result.score === 100 ? " is-right" : " is-wrong"));
  card.appendChild(el("p", "drill-verdict",
    "自测 " + result.score + " 分 · 答对 " + result.correct + "/3 要点"));
  (result.rubric || []).forEach((row, idx) => {
    card.appendChild(el("p", "triple-point-label", "要点 " + (idx + 1) + "：" + row.label));
    card.appendChild(el("p", "drill-option" + (row.correct ? " is-correct" : " is-wrong"),
      (row.correct ? "✓ " : "✗ ") + row.selected));
    if (!row.correct) {
      card.appendChild(el("p", "study-source", "原文应为：" + row.expected + (row.reason ? " · " + row.reason : "")));
    }
  });
  const source = result.source || {};
  card.appendChild(el("p", "drill-source",
    "原文出处：第 " + result.chapter + " 章" + (source.term ? " · " + source.term : "")
    + (source.explanation ? " —— " + source.explanation : "")));
  card.appendChild(el("p", "study-source", result.notice));
  const again = el("button", "btn btn-primary", "再来一道");
  again.type = "button";
  again.addEventListener("click", () => startTriple());
  card.appendChild(again);
  box.appendChild(card);
}

async function startTriple() {
  if (tripleBusy || !drillBook || drillChapter == null) return;
  tripleBusy = true;
  tripleResult = null;
  tripleSelections = [null, null, null];
  $("drillArea").textContent = "正在从这一章的原文里抽题…";
  try {
    tripleTask = await api("/api/kaodian/triple-task", { book: drillBook, chapter: drillChapter });
  } catch (error) {
    tripleBusy = false;
    $("drillArea").textContent = "抽题失败：" + error.message;
    return;
  }
  tripleBusy = false;
  renderTripleArea(drillBookEntry()?.chapters.find((c) => c.no === drillChapter) || null);
}

async function answerTriple() {
  if (tripleBusy || !tripleTask) return;
  if (tripleSelections.some((s) => !s)) { toast("请先为三个要点各选一个解释"); return; }
  tripleBusy = true;
  try {
    tripleResult = await api("/api/kaodian/triple-answer", { token: tripleTask.token, answers: tripleSelections });
    tripleTask = null;
    tripleDone += 1;
    tripleRight += tripleResult.correct || 0;
    $("drillKind").textContent = "已自测 " + tripleDone + " 道 · 要点对 "
      + tripleRight + "/" + (tripleDone * 3);
  } catch (error) {
    toast("判分失败：" + error.message);
  } finally {
    tripleBusy = false;
    renderTripleArea(drillBookEntry()?.chapters.find((c) => c.no === drillChapter) || null);
  }
}

/* ---------- 可选云同步（本机优先，未登录/不可用时零影响） ---------- */
async function initCloudSync() {
  const C = window.MedNexusCloud;
  const panel = $("cloudPanel");
  if (!C || !C.available() || !panel) return;   // SDK 未加载则整块隐藏
  panel.hidden = false;
  const status = $("cloudStatus"), hint = $("cloudHint");
  const btnIn = $("cloudSignIn"), btnUp = $("cloudUpload"), btnDown = $("cloudDownload"), btnOut = $("cloudSignOut");

  function paint(user) {
    const on = !!user;
    btnIn.hidden = on; btnOut.hidden = !on;
    btnUp.disabled = !on; btnDown.disabled = !on;
    hint.textContent = on
      ? "已登录" + (user.name ? "（" + user.name + "）" : "") + "。上传只发送学习摘要；从云恢复会覆盖当前浏览器的进度与统计，请先确认。"
      : "登录后可在不同设备间同步学习进度与统计。只上传学习摘要，不含教材原文、作答/提问原文或身份标识。";
  }

  try {
    const cb = await C.handleCallback();          // 先处理 OAuth 回调，早于任何路由守卫
    if (cb.error) status.textContent = cb.error;
    const user = cb.signedIn ? cb.user : await C.restore();
    paint(user);
  } catch (e) {
    paint(null);
  }

  btnIn.addEventListener("click", async () => {
    status.textContent = "正在跳转登录…";
    const r = await C.signIn();
    if (!r.ok) status.textContent = r.error || "登录失败";
  });
  btnOut.addEventListener("click", async () => {
    await C.signOut(); paint(null); status.textContent = "已退出登录，本机数据保持不变。";
  });
  btnUp.addEventListener("click", async () => {
    btnUp.disabled = true; status.textContent = "正在上传学习摘要…";
    try {
      const report = await api("/api/report");
      const r = await C.upload(report);
      status.textContent = r.ok ? "已上传到云（" + new Date(r.synced_at).toLocaleString("zh-CN") + "）。" : r.error;
    } catch (e) {
      status.textContent = "上传失败：" + e.message;
    } finally { btnUp.disabled = false; }
  });
  btnDown.addEventListener("click", async () => {
    btnDown.disabled = true; status.textContent = "正在读取云端…";
    try {
      const r = await C.download();
      if (!r.ok) { status.textContent = r.error; return; }
      const s = r.report || {};
      const c = Array.isArray(s.concepts) ? s.concepts : [];
      const mastered = c.filter(x => x && x.mastered).length;
      const stats = s.stats || {};
      status.textContent = "云端摘要读取成功：" + c.length + " 个知识点，已掌握 " + mastered +
        "，作答 " + (stats.attempts || stats.total || 0) + " 次。" +
        "本机为唯一真相源，请在核对后决定如何据此继续学习（不自动覆盖本机记录）。";
    } catch (e) {
      status.textContent = "恢复失败：" + e.message;
    } finally { btnDown.disabled = false; }
  });
}

(async function init() {
  await refreshOverview();
  restoreResearchWorkspace();
  initCloudSync();             // 云同步独立初始化，失败不影响主流程
  const preset = new URLSearchParams(location.search).get("q");
  const hash = location.hash.replace("#", "");
  if (hash && VIEWS.includes(hash)) showView(hash);
  if (preset) {
    $("q").value = preset;
    showView("ask");
    ask(preset);
  }
  startHeartbeat();
  checkBuild();
})();
