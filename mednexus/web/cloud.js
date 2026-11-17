/* 医枢 · 可选云同步层
   设计边界：本机仍是唯一真相源；云只做「登录身份 + 学习摘要跨设备同步 + 免密钥模型兜底」。
   - 不上传教材原文 / 作答原文 / 提问原文 / 浏览器身份标识 / 任何令牌。
   - 同步载荷是显式白名单摘要；未登录或云不可用时全部功能照常用本机。
   - 只有用户主动点「上传到云」才写云端；「从云恢复」需二次确认才覆盖本机。 */
(function () {
  "use strict";

  var CFG = window.MEDNEXUS_CLOUD || null;
  var cloud = null;
  var sdkReady = false;
  var session = null;

  // 与后端 /api/report 的摘要字段对齐：只保留进度与统计类，不含 history/events 原文。
  var ALLOWED_SUMMARY_KEYS = ["course", "concepts", "stats", "recommendation", "errors", "time", "method"];
  var ALLOWED_CONCEPT_KEYS = ["id", "name", "unit", "mastered", "status", "score", "ema", "attempts", "last_score", "due_at"];

  function available() {
    return !!(CFG && window.WorkBuddyCloud && typeof window.WorkBuddyCloud.createWorkBuddyCloud === "function");
  }

  function init() {
    if (!available() || sdkReady) return sdkReady;
    try {
      cloud = window.WorkBuddyCloud.createWorkBuddyCloud({
        endpoint: CFG.endpoint,
        oauthRelayBaseUrl: CFG.oauthRelayBaseUrl,
        publishableKey: CFG.publishableKey
      });
      sdkReady = true;
    } catch (e) {
      cloud = null;
    }
    return sdkReady;
  }

  // 回调统一在首页根目录处理，遵循 OAuth relay 的站点根路径约束。
  async function handleCallback() {
    if (!init()) return { signedIn: false };
    var url = new URL(location.href);
    if (!url.searchParams.has("code") && !url.searchParams.has("error")) {
      return { signedIn: false };
    }
    var provider = url.searchParams.get("provider");
    if (provider !== "workbuddy" && provider !== "wechat") {
      return { signedIn: false, error: "授权回调缺少有效的登录方式" };
    }
    var handler = provider === "workbuddy"
      ? (cloud.auth.handleWorkBuddyCallback && cloud.auth.handleWorkBuddyCallback.bind(cloud.auth))
      : (cloud.auth.handleWechatWebCallback && cloud.auth.handleWechatWebCallback.bind(cloud.auth));
    if (!handler) return { signedIn: false, error: "当前 SDK 暂不支持该登录方式" };
    try {
      var result = await handler();
      // SDK 约定返回 { data: session, error }；部分旧版本直接返回 session。
      var authed = result && result.data ? result.data : (result && result.session ? result.session : null);
      if (authed) {
        ["code", "state", "provider"].forEach(function (k) { url.searchParams.delete(k); });
        history.replaceState(null, "", url.pathname + url.search + url.hash);
        session = authed;
        return { signedIn: true, user: session.user };
      }
      return { signedIn: false, error: result && result.error && result.error.message };
    } catch (e) {
      return { signedIn: false, error: "登录处理失败，请重试" };
    }
  }

  async function restore() {
    if (!init()) return null;
    try {
      var res = await cloud.auth.getSession();
      session = (res && res.data) || null;
      return session ? (session.user || {}) : null;
    } catch (e) {
      return null;
    }
  }

  async function signIn() {
    if (!init()) return { ok: false, error: "云服务不可用" };
    try {
      var back = new URL(location.href);
      back.pathname = "/";
      ["code", "state", "provider"].forEach(function (k) { back.searchParams.delete(k); });
      var res = await cloud.auth.signInWithOAuth({ provider: "workbuddy", redirectTo: back.toString() });
      if (res && res.error) return { ok: false, error: res.error.message };
      if (res && res.data && res.data.url) {
        location.assign(res.data.url); // 必须同标签页，PKCE 证明在 sessionStorage。
        return { ok: true, redirecting: true };
      }
      return { ok: false, error: "未获得登录地址" };
    } catch (e) {
      return { ok: false, error: "登录发起失败" };
    }
  }

  async function signOut() {
    if (!cloud) return;
    try { await cloud.auth.signOut(); } catch (e) { /* 静默 */ }
    session = null;
  }

  // 白名单裁剪：无论 report() 返回什么，只保留学习进度与统计，杜绝原文外泄。
  function sanitize(report) {
    if (!report || typeof report !== "object") return null;
    var out = {};
    ALLOWED_SUMMARY_KEYS.forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(report, key)) out[key] = report[key];
    });
    if (Array.isArray(out.concepts)) {
      out.concepts = out.concepts.map(function (c) {
        var item = {};
        ALLOWED_CONCEPT_KEYS.forEach(function (k) {
          if (c && Object.prototype.hasOwnProperty.call(c, k)) item[k] = c[k];
        });
        return item;
      });
    }
    out.schema_version = 1;
    out.synced_at = Date.now();
    // 明确声明不含的内容，便于审计。
    out.excluded = ["作答原文", "提问原文", "教学对话", "教材索引与原文", "浏览器身份标识", "访问令牌"];
    return out;
  }

  async function upload(report) {
    if (!init()) return { ok: false, error: "云服务不可用" };
    if (!session) return { ok: false, error: "请先登录" };
    var payload = sanitize(report);
    if (!payload) return { ok: false, error: "没有可同步的学习摘要" };
    try {
      var res = await cloud.database.from("mednexus_snapshots").upsert(
        { slot: "main", payload: payload, schema_version: 1, updated_at: new Date().toISOString() },
        { onConflict: "owner_id,slot" }
      );
      if (res && res.error) return { ok: false, error: res.error.message };
      return { ok: true, synced_at: payload.synced_at };
    } catch (e) {
      return { ok: false, error: "同步失败：" + (e && e.message ? e.message : "网络不可用") };
    }
  }

  async function download() {
    if (!init()) return { ok: false, error: "云服务不可用" };
    if (!session) return { ok: false, error: "请先登录" };
    try {
      var res = await cloud.database.from("mednexus_snapshots")
        .select("payload,updated_at").eq("slot", "main").maybeSingle();
      if (res && res.error) return { ok: false, error: res.error.message };
      if (!res || !res.data) return { ok: false, error: "云端还没有同步记录" };
      return { ok: true, report: res.data.payload, updated_at: res.data.updated_at };
    } catch (e) {
      return { ok: false, error: "读取失败：" + (e && e.message ? e.message : "网络不可用") };
    }
  }

  // 免密钥模型兜底：仅做"组织语言"，不改判分与证据校验；仍要求 system 首条 + 流式。
  async function askModel(systemPrompt, userText, onToken, signal) {
    if (!init()) throw new Error("云服务不可用");
    var models = await cloud.llm.models.list();
    var modelsList = Array.isArray(models) ? models : (models && models.data) || [];
    var model = modelsList.find(function (m) { return m && m.id === "hy4flash-free" && m.disabled !== true && m.enabled !== false; })
      || modelsList.find(function (m) { return m && m.disabled !== true && m.enabled !== false && !m.onlyReasoning; })
      || modelsList.find(function (m) { return m && m.disabled !== true && m.enabled !== false; });
    if (!model) throw new Error("当前没有可用的模型");
    var answer = "";
    try {
      for await (var chunk of cloud.llm.chat.completions.create({
        model: model.id,
        messages: [
          { role: "system", content: systemPrompt || "你是医学基础课程辅导员。只依据给定材料作答，不编造事实，不给个人诊疗建议。" },
          { role: "user", content: String(userText || "") }
        ],
        stream: true,
        temperature: 0.3,
        signal: signal
      })) {
        var delta = chunk && chunk.choices && chunk.choices[0] && chunk.choices[0].delta;
        var text = delta && delta.content;
        if (text) { answer += text; if (typeof onToken === "function") onToken(text); }
      }
    } catch (e) {
      if (e && e.name === "AbortError") throw e;
      if (answer) return answer; // 流中断时保留已生成内容。
      throw e;
    }
    return answer;
  }

  window.MedNexusCloud = {
    available: available,
    init: init,
    handleCallback: handleCallback,
    restore: restore,
    signIn: signIn,
    signOut: signOut,
    currentUser: function () { return session ? session.user : null; },
    sanitize: sanitize,
    upload: upload,
    download: download,
    askModel: askModel
  };
})();
