/*
 * ADCChat v1.4 一体版 F12 脚本
 * 自动识别测试/生产环境；仅在对应环境的同源页面运行，各自重新捕获会话。
 * 一次安装 ask、自动捕获会话与页面头、动态 CSRF、SSE 正文解析。
 * 安装后直接 await ask("问题")；首次通过网页输入框发送该问题，无需手动预问。
 * 首次发送需要当前页面有唯一可见且为空的聊天输入框；已有草稿时保留草稿并报错。
 * 后续默认直接请求；可用 await ask("问题", {viaPage:true}) 再走网页原有发送流程。
 * 初始化后可 await ADCChat.newSession() 新建会话，再 await ask("问题")。
 * newSession 需要捕获当前环境的 session-init 路由；未捕获时传 {url, serviceName}。
 * 页面校验头仍沿用已捕获值，其长期有效性未验证；不推测签名算法。
 * 不需要先安装其它脚本；不包含任何人的固定 token 或会话值。
 * 本地模拟测试已通过，测试/生产网站中的实际接口仍需分别验证。
 */
(() => {
  "use strict";
  const ENVIRONMENTS = Object.freeze({
    "https://netcareclaw-beta.icta138.huawei.com": "测试环境",
    "https://netcareclaw.gde.huawei.com": "生产环境"
  });
  const ORIGIN = location.origin;
  const ENVIRONMENT = ENVIRONMENTS[ORIGIN];
  if (!Object.hasOwn(ENVIRONMENTS, ORIGIN)) {
    throw new Error("请在测试或生产网站的同源页面运行脚本；不支持当前域名：" + ORIGIN);
  }
  if (window.ADCChat?.busy) throw new Error("请等待当前请求结束再重新安装。");
  window.ADCAutoCapture?.stop();
  window.ADCChat?.stopCapture?.();
  const PATH = "/adc-agent/web/rest/v1/deepagent/stream/" +
    "OperationsDigitalHuman/OperationsDigitalHuman/agent_OperationsDigitalHuman";
  const INIT_PATH = "/adc-agent/web/rest/v1/deepagent/session-init";
  const USER_INFO_PATH = "/adc-system/web/rest/v1/uiconfig/info";
  const SOURCE_PAGE = "/adc-agent/static/deepagent-sandbox/index.html";
  const REFERRER = ORIGIN + SOURCE_PAGE +
    "?project_name=OperationsDigitalHuman&module_name=OperationsDigitalHuman" +
    "&deepAgent_name=agent_OperationsDigitalHuman";
  const PAGE_KEYS = ["x-adc-page-timestamp", "x-adc-page-token",
    "x-gde-src-page", "x-gde-target-app"];
  // 只保存当前浏览器标签页的配置；页面刷新后重新初始化。
  let config = null, controller = null, lastAnswer = "", captureState = null;
  let runtimeRoute = null, routeCapture = null, pageAsk = null;
  const fetchRequest = window.fetch.bind(window);

  function checkOrigin() {
    if (location.origin !== ORIGIN) {
      throw new Error("请在目标网站同源页面运行；localhost 不能复用该站的 localStorage。");
    }
  }

  // 每次提问前重新读取。多个不同 token 时拒绝猜测第一个。
  function readStoredCsrf() {
    let value;
    try { value = JSON.parse(localStorage.getItem("csrfTokens") || "null"); }
    catch { throw new Error("无法读取 csrfTokens JSON，请检查当前登录及存储状态。"); }
    const records = Array.isArray(value) ? value : [value];
    const tokens = [...new Set(records.map(x => x?.csrfToken)
      .filter(x => typeof x === "string" && x.trim()))];
    if (tokens.length !== 1) {
      throw new Error("csrfTokens 中没有唯一 token；需按应用选择或提供 csrfProvider。");
    }
    return tokens[0];
  }

  // 不记录、输出或持久化接口返回的用户信息和 token。
  async function readUiConfigCsrf() {
    checkOrigin();
    const response = await fetchRequest(ORIGIN + USER_INFO_PATH, {
      method: "GET", credentials: "include", redirect: "error",
      headers: { accept: "application/json" }, signal: AbortSignal.timeout(15000)
    });
    if (!response.ok) throw new Error("用户信息接口 HTTP " + response.status);
    const data = await response.json();
    if (typeof data.csrf_token !== "string" || !data.csrf_token.trim()) {
      throw new Error("用户信息接口未返回有效 csrf_token；请检查登录和接口鉴权。");
    }
    return data.csrf_token;
  }

  async function readCurrentCsrf() {
    try { return readStoredCsrf(); }
    catch { return readUiConfigCsrf(); }
  }

  function validateRoute(url, serviceName) {
    const target = new URL(url, ORIGIN);
    if (target.origin !== ORIGIN || target.search || target.hash ||
        target.username || target.password || !/^\/ars-[A-Za-z0-9_-]+\/$/.test(target.pathname)) {
      throw new Error("url 必须是当前环境实际返回的 /ars-…/ 相对路由。");
    }
    if (typeof serviceName !== "string" || !serviceName.trim()) {
      throw new Error("缺少当前环境的 serviceName。");
    }
    return { url: target.pathname, service_name: serviceName.trim() };
  }

  // 不重试创建会话：网络中断时不能假定服务端没有创建。
  // 页面校验头沿用当前捕获值；若接口拒绝，请重新捕获，不能伪造刷新。
  async function newSession(options = {}) {
    checkOrigin();
    if (controller || pageAsk) throw new Error("请等待当前请求结束。");
    if (!config) throw new Error("请先捕获或 configure 当前环境的页面头和模型配置。");
    await routeCapture;
    if (controller) throw new Error("请等待当前请求结束。");
    if (!(options.url ?? runtimeRoute?.url)) {
      throw new Error("未捕获 session-init 路由；请新建会话并重新捕获，或传入 {url, serviceName}。");
    }
    const route = validateRoute(options.url ?? runtimeRoute?.url,
      options.serviceName ?? runtimeRoute?.service_name);
    const current = config;
    const active = controller = new AbortController();
    const timer = setTimeout(() => active.abort(), 30000);
    try {
      const token = await Promise.race([
        Promise.resolve().then(() => current.csrfProvider()),
        new Promise((_, reject) => active.signal.addEventListener("abort",
          () => reject(new Error("创建会话已停止或等待凭证超时。")), { once: true }))
      ]);
      if (active.signal.aborted) throw new Error("创建会话已停止。");
      if (typeof token !== "string" || !token.trim()) throw new Error("CSRF token 为空。");
      const headers = new Headers(current.pageHeaders);
      headers.set("accept", "application/json");
      headers.set("content-type", "application/json;charset=utf-8");
      headers.set("x-gde-csrf-token", token);
      const response = await fetchRequest(ORIGIN + INIT_PATH, {
        method: "POST", credentials: "include", redirect: "error",
        headers, referrer: current.referrer, signal: active.signal,
        body: JSON.stringify({ ...route, agent_name: "agent_OperationsDigitalHuman" })
      });
      if (!response.ok) throw new Error("创建会话 HTTP " + response.status);
      const result = await response.json();
      if (result.success !== true || typeof result.session_id !== "string" ||
          !result.session_id.trim()) throw new Error("创建会话未返回成功状态及 session_id。");
      config = { ...current, sessionId: result.session_id };
      runtimeRoute = route;
      lastAnswer = "";
      return result.session_id;
    } finally {
      clearTimeout(timer);
      controller = null;
    }
  }

  function configure(options) {
    checkOrigin();
    if (controller) throw new Error("请求执行中，不能修改配置。");
    const sessionId = options?.sessionId;
    const pageHeaders = new Headers(options?.pageHeaders || {});
    if (typeof sessionId !== "string" || !sessionId.trim()) {
      throw new Error("请传入当前用户自己的有效 sessionId。");
    }
    for (const key of PAGE_KEYS.slice(0, 2)) {
      if (!pageHeaders.get(key)?.trim()) throw new Error("缺少页面校验头 " + key);
    }
    const referrer = new URL(options.referrer || REFERRER, ORIGIN);
    if (referrer.origin !== ORIGIN) throw new Error("referrer 必须与接口同源。");
    const defaultModel = ENVIRONMENT === "生产环境"
      ? { provider_id: "DeepSeek", model_id: "DeepSeek-V4-Flash-RTAC" }
      : { provider_id: "Qwen", model_id: "Qwen3.8-27B" };
    const model = { ...(options.model || defaultModel) };
    if (!model.provider_id || !model.model_id) throw new Error("model 缺少必要字段。");
    config = {
      sessionId: sessionId.trim(), agent: options.agent || "build", model,
      pageHeaders: Object.fromEntries(PAGE_KEYS.map(k => [k,
        pageHeaders.get(k) ?? (k === "x-gde-src-page" ? SOURCE_PAGE : "")])),
      referrer: referrer.href,
      // 正式接入可注入平台 SDK 提供的实时 CSRF 获取函数。
      csrfProvider: options.csrfProvider || readCurrentCsrf
    };
    stopCapture();
    console.info("[ADCChat] 配置完成，未发送请求。");
  }

  // 在回调内粘贴 DevTools 的 Copy as fetch 内容。
  // 参数 fetch 是本地捕获函数，因此这一步不真正调用接口。
  async function importRequest(copiedFetch) {
    checkOrigin();
    if (controller) throw new Error("请先等待当前请求结束。");
    if (typeof copiedFetch !== "function") throw new Error("需要一个接收 fetch 参数的函数。");
    let captured, count = 0;
    await copiedFetch((input, init) => {
      count += 1;
      captured = new Request(input, init);
      return Promise.resolve(null);
    });
    if (count !== 1) throw new Error("请只粘贴一条原始成功 POST 的 fetch。");
    const url = new URL(captured.url);
    if (url.origin !== ORIGIN || url.pathname !== PATH || url.search ||
        captured.method !== "POST") {
      throw new Error("需要无重定向参数的原始 POST，不能使用登录后的 GET。");
    }
    const body = JSON.parse(await captured.text());
    const expected = captured.headers.get("x-gde-csrf-token");
    if (!expected) throw new Error("成功请求中缺少 x-gde-csrf-token。");
    // 确认默认存储来源与成功请求一致，不把其它应用的 token 当成本接口 token。
    if (await readCurrentCsrf() !== expected) {
      throw new Error("存储 token 与成功请求不一致；请重新复制当前请求或接入平台 SDK。");
    }
    configure({ sessionId: body.session_id, agent: body.agent, model: body.model,
      pageHeaders: Object.fromEntries(PAGE_KEYS.map(k => [k, captured.headers.get(k) ??
        (k === "x-gde-src-page" ? SOURCE_PAGE : "")])),
      referrer: captured.referrer && captured.referrer !== "about:client"
        ? captured.referrer : REFERRER });
  }

  function validateResponseUrl(response, expectedPath) {
    if (!response.url) return; // 本地 Response 测试桩没有 URL。
    const url = new URL(response.url);
    if (url.origin !== ORIGIN || url.pathname !== expectedPath) {
      throw new Error("响应未回到当前环境的目标接口，请检查登录状态。");
    }
  }

  function findComposer() {
    const candidates = [], seen = new Set();
    function scan(w) {
      if (seen.has(w)) return;
      seen.add(w);
      try {
        if (w.location.origin !== ORIGIN) return;
        for (const el of w.document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"]')) {
          const style = w.getComputedStyle(el);
          if (el.disabled || el.readOnly || el.getAttribute("aria-disabled") === "true" ||
              !el.getClientRects().length || style.display === "none" ||
              style.visibility === "hidden" || el.closest('[aria-hidden="true"]')) continue;
          candidates.push({ w, el });
        }
        for (let i = 0; i < (w.frames?.length || 0); i++) scan(w.frames[i]);
      } catch { /* 不读取跨源 iframe。 */ }
    }
    scan(window);
    const hinted = candidates.filter(({el}) => /提问|请输入|发送消息|输入问题|输入消息|message|ask|prompt/i
      .test([el.getAttribute("placeholder"), el.getAttribute("aria-label"),
        el.getAttribute("data-placeholder")].filter(Boolean).join(" ")));
    const selected = hinted.length ? hinted : candidates;
    if (selected.length !== 1) {
      throw new Error("无法唯一识别聊天输入框（候选 " + selected.length +
        " 个）；请打开聊天页并关闭其它编辑窗口，或提供输入框 HTML 以适配。");
    }
    const item = selected[0];
    if (String("value" in item.el ? item.el.value : item.el.textContent || "").trim()) {
      throw new Error("输入框已有未发送草稿，请先自行保存或清空，再运行 ask；脚本没有覆盖草稿。");
    }
    return item;
  }

  // 仅首次借用网页的真实发送流程。只发送用户当前的问题，不额外发送初始化问题。
  async function askViaPage(question, options) {
    const {w: owner, el} = findComposer();
    stopCapture();
    const active = new AbortController();
    pageAsk = active;
    const hooks = new Map();
    let settled = false, resolveResponse, rejectResponse;
    const responseReady = new Promise((resolve, reject) => {
      resolveResponse = resolve; rejectResponse = reject;
    });
    void responseReady.catch(() => {}); // 提交前被停止时也处理 Promise 拒绝。
    const timer = setTimeout(() => active.abort(), options.timeoutMs ?? 180000);
    function restore() {
      for (const [w, hook] of hooks) {
        try { if (w.fetch === hook.wrapped) w.fetch = hook.previous; } catch {}
      }
    }
    function fail(error) {
      if (settled) return;
      settled = true;
      restore();
      rejectResponse(error);
    }
    active.signal.addEventListener("abort", () => fail(new Error(
      "网页发送已停止或超时；不会自动重发。请检查页面提示和登录状态；服务端任务可能仍在运行。")), {once:true});
    function hook(w, seen) {
      if (seen.has(w)) return;
      seen.add(w);
      try {
        if (w.location.origin !== ORIGIN) return;
        const previous = w.fetch;
        const wrapped = function(...args) {
          let request;
          try {
            const input = args[0];
            const url = new URL(typeof input === "string" ? input : input?.url || String(input), w.location.href);
            const method = String(args[1]?.method || input?.method || "GET").toUpperCase();
            if (method === "POST" && url.origin === ORIGIN && !url.search &&
                (url.pathname === PATH || url.pathname === INIT_PATH)) {
              request = new w.Request(input instanceof w.Request ? input.clone() : input, args[1]);
            }
          } catch {}
          const result = previous.apply(this, args);
          if (request && !settled) {
            // 在原网页读取响应前克隆；不消耗页面自己的响应体，不重发请求。
            const copiedResponse = result.then(r => r.clone());
            void Promise.all([request.text(), copiedResponse]).then(async ([text, response]) => {
              if (settled) { void response.body?.cancel().catch(() => {}); return; }
              const body = JSON.parse(text);
              if (new URL(request.url).pathname === INIT_PATH) {
                const data = await response.json();
                if (data.success && body.agent_name === "agent_OperationsDigitalHuman") {
                  runtimeRoute = validateRoute(body.url, body.service_name);
                }
                return;
              }
              if (body.message !== question) { void response.body?.cancel().catch(() => {}); return; }
              validateResponseUrl(response, PATH);
              if (!response.ok || !/text\/event-stream/i.test(response.headers.get("content-type") || "")) {
                throw new Error("网页提问没有返回 SSE（HTTP " + response.status + "），请检查页面错误或登录状态。");
              }
              configure({ sessionId: body.session_id, agent: body.agent, model: body.model,
                pageHeaders: Object.fromEntries(PAGE_KEYS.map(k => [k, request.headers.get(k) ??
                  (k === "x-gde-src-page" ? SOURCE_PAGE : "")])),
                referrer: request.referrer && request.referrer !== "about:client" ? request.referrer : REFERRER });
              settled = true;
              restore();
              resolveResponse(response);
            }).catch(fail);
          }
          return result;
        };
        w.fetch = wrapped;
        hooks.set(w, {previous, wrapped});
        for (let i = 0; i < (w.frames?.length || 0); i++) hook(w.frames[i], seen);
      } catch {}
    }
    try {
      hook(window, new Set());
      if (!hooks.size) throw new Error("无法监听当前聊天页的 fetch。");
      console.info("[自动首次发送] 正在通过原网页发送当前问题，无需预先手动提问。");
      if ("value" in el) {
        const proto = el.tagName === "TEXTAREA" ? owner.HTMLTextAreaElement.prototype : owner.HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
        if (!setter) throw new Error("无法设置当前输入框，请提供输入框 HTML。");
        setter.call(el, question);
      } else {
        el.textContent = question;
      }
      el.dispatchEvent(new owner.Event("input", {bubbles:true, composed:true}));
      el.dispatchEvent(new owner.Event("change", {bubbles:true}));
      await Promise.resolve(); // 等待 Vue 响应式输入状态更新。
      if (active.signal.aborted) throw new Error("网页发送已停止。");
      el.focus();
      const submit = el.closest("form")?.querySelector('button[type="submit"], input[type="submit"]');
      if (submit && !submit.disabled) submit.click();
      else el.dispatchEvent(new owner.KeyboardEvent("keydown", {
        key:"Enter", code:"Enter", keyCode:13, which:13, bubbles:true, cancelable:true, composed:true
      }));
      // 只触发一次提交。即使没有立即出现请求，也不再点击，避免重复提问。
      const response = await responseReady;
      clearTimeout(timer);
      pageAsk = null;
      return await runAsk(question, options, response);
    } finally {
      settled = true;
      restore();
      clearTimeout(timer);
      if (pageAsk === active) pageAsk = null;
    }
  }

  async function ask(question, options = {}) {
    checkOrigin();
    if (controller || pageAsk) throw new Error("当前标签页已有提问，请等待结束。");
    if (typeof question !== "string" || !question.trim()) throw new Error("问题不能为空。");
    const timeoutMs = options.timeoutMs ?? 300000;
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error("timeoutMs 必须大于零。");
    return !config || options.viaPage ? askViaPage(question, options) : runAsk(question, options);
  }

  async function runAsk(question, options = {}, observedResponse = null) {
    checkOrigin();
    if (!config) throw new Error("ask 已安装，但尚未捕获配置。请先在原网页正常发送一次消息，等网页回答结束后再用 ask。");
    if (controller) throw new Error("当前标签页已有提问，请等待结束。");
    if (typeof question !== "string" || !question.trim()) throw new Error("问题不能为空。");
    // timeoutMs 语义改为“空闲窗口”：流式有数据（含心跳）就续期，长回答不会按总时长被切断；
    // 仅当连续无数据超过该窗口才判卡死。另设 30 分钟绝对上限作安全兜底。
    const idleMs = options.timeoutMs ?? 300000;   // 空闲窗口默认 5 分钟
    if (!Number.isFinite(idleMs) || idleMs <= 0) throw new Error("timeoutMs 必须大于零。");
    const totalMs = 30 * 60 * 1000;               // 绝对上限 30 分钟
    const current = config;
    const active = controller = new AbortController();
    const startedAt = Date.now();
    let timer = setTimeout(() => active.abort(), idleMs);
    function armIdle() {
      clearTimeout(timer);
      const remain = Math.max(1000, totalMs - (Date.now() - startedAt));
      timer = setTimeout(() => active.abort(), Math.min(idleMs, remain));
    }
    const roles = new Map(), parts = new Map(), seen = new Set();
    let reader, buffer = "", finished = false, sawAssistant = false;
    lastAnswer = "";

    // 规整正文：统一换行、去行尾空白、把连续多个空行合并为单个换行，避免大量留白。
    function compactText(s) {
      return String(s || "")
        .replace(/\r\n?/g, "\n")
        .replace(/[ \t]+\n/g, "\n")
        .replace(/\n{2,}/g, "\n")
        .trim();
    }
    function answerText() {
      return compactText([...parts.values()].filter(p => p.type === "text" &&
        roles.get(p.message_id) === "assistant")
        .map(p => p.text || "").join("\n"));
    }
    function publish() {
      const text = answerText();
      if (text !== lastAnswer) {
        lastAnswer = text;
        if (text) console.info("[回答更新]", text);
        options.onUpdate?.(text); // 页面可用 textContent 展示当前累计正文。
      }
    }
    function handle(block) {
      // SSE 使用空行分帧；同一帧可以有多条 data 行。
      const data = block.split(/\r\n|\n|\r/).filter(x => x.startsWith("data:"))
        .map(x => x.slice(5).replace(/^ /, "")).join("\n");
      if (!data) return; // 忽略心跳注释及空帧。
      if (data.trim() === "[DONE]") { finished = true; return; }
      const raw = JSON.parse(data), event = raw.payload || raw;
      const p = event.properties || {};
      if (p.session_id && p.session_id !== current.sessionId) return;
      if (event.id && seen.has(event.id)) return;
      if (event.id) seen.add(event.id); // 防止相同增量事件重复拼接。
      if (event.type === "session.error" || event.type === "error") {
        const error = p.error || p;
        throw new Error(error.message || error.data?.message || "服务端返回错误事件。");
      }
      if (event.type === "message.updated" && p.info) {
        roles.set(p.info.id, p.info.role);
        if (p.info.role === "assistant") {
          sawAssistant = true;
          if (p.info.error) throw new Error(p.info.error.message || "助手生成失败。");
        }
      }
      if (event.type === "message.part.updated" && p.part) {
        // updated 是完整快照：覆盖旧 text，不能再追加一次。
        parts.set(p.part.id, { ...parts.get(p.part.id), ...p.part });
      }
      if (event.type === "message.part.delta" && p.field === "text") {
        const part = parts.get(p.part_id) || { message_id: p.message_id };
        parts.set(p.part_id, { ...part, text: (part.text || "") + (p.delta || "") });
      }
      publish(); // 只发布 assistant 的 text，排除用户回显与 reasoning。
      if (sawAssistant && (event.type === "session.idle" ||
          (event.type === "session.status" && p.status?.type === "idle"))) {
        finished = true;
      }
    }

    try {
      let response = observedResponse;
      if (!response) {
        const token = await Promise.race([
          Promise.resolve().then(() => current.csrfProvider()),
          new Promise((_, reject) => active.signal.addEventListener("abort",
            () => reject(new Error("凭证读取已停止。")), { once: true }))
        ]);
        if (active.signal.aborted) throw new Error("请求已停止或等待凭证超时。");
        if (typeof token !== "string" || !token.trim()) throw new Error("CSRF token 为空。");
        const headers = new Headers(current.pageHeaders);
        headers.set("accept", "text/event-stream");
        headers.set("content-type", "application/json;charset=utf-8");
        headers.set("x-gde-csrf-token", token);
        // 已确认成功的叠加请求同时携带这两个头，整理版暂保留兼容行为。
        // 单独移除 csrftoken 的真实接口验证尚未完成。
        headers.set("csrftoken", token);
        console.info("[开始提问]", question);
        response = await fetchRequest(ORIGIN + PATH, {
          method: "POST", headers, credentials: "include", redirect: "follow",
          referrer: current.referrer, signal: active.signal,
          body: JSON.stringify({ message: question, session_id: current.sessionId,
            agent: current.agent, model: current.model })
        });
      }
      validateResponseUrl(response, PATH);
      console.info("[HTTP 状态]", response.status);
      const type = response.headers.get("content-type") || "";
      if (!response.ok || /application\/json/i.test(type)) {
        let detail = "";
        try { const e = await response.json(); detail = [e.code, e.message].filter(Boolean).join(" "); }
        catch { /* 非 JSON 错误体只报告 HTTP 状态，避免输出登录页面内容。 */ }
        throw new Error("HTTP " + response.status + (detail ? " " + detail : " 未返回 SSE"));
      }
      if (/text\/html/i.test(type)) throw new Error("返回 HTML 页面，请检查登录状态。");
      if (!response.body) throw new Error("响应体为空。");
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      while (!finished) {
        const { done, value } = await reader.read();
        if (value) armIdle(); // 收到数据（含心跳）即续期空闲计时器
        buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
        let separator;
        while (!finished && (separator = /\r\n\r\n|\n\n|\r\r/.exec(buffer))) {
          const block = buffer.slice(0, separator.index);
          buffer = buffer.slice(separator.index + separator[0].length);
          handle(block);
        }
        if (done) {
          if (!finished && buffer.trim()) handle(buffer);
          break;
        }
      }
      if (!finished) throw new Error("流提前结束，当前正文仅为部分结果，不能判定完成。");
      if (!lastAnswer) throw new Error("会话已结束但没有助手正文，请检查工具调用或错误事件。");
      console.info("[最终回答]", lastAnswer);
      return lastAnswer;
    } catch (error) {
      if (active.signal.aborted) throw new Error("已停止读取或超过超时限制；不代表服务端任务已取消。");
      throw error;
    } finally {
      clearTimeout(timer);
      if (reader) void reader.cancel().catch(() => {});
      controller = null;
    }
  }


  // 临时监听当前页及同源 iframe；捕获成功或超时后恢复原 fetch。
  function stopCapture() {
    if (!captureState) return;
    const state = captureState;
    state.stopped = true;
    clearInterval(state.interval);
    clearTimeout(state.timeout);
    for (const [w, hook] of state.hooks) {
      try { if (w.fetch === hook.wrapped) w.fetch = hook.previous; } catch {}
    }
    captureState = null;
  }

  function autoCapture() {
    checkOrigin();
    if (controller) throw new Error("请等待当前问题结束后再捕获。");
    stopCapture();
    const state = { stopped: false, hooks: new Map(), interval: null, timeout: null };
    captureState = state;

    async function capture(request, responsePromise) {
      try {
        const isInit = new URL(request.url).pathname === INIT_PATH;
        // 响应一到就克隆初始化 JSON，避免原网页先读完；SSE 不克隆、不消费。
        const responseCopy = responsePromise.then(r => isInit ? r.clone() : r);
        const [text, response] = await Promise.all([request.text(), responseCopy]);
        if (!response.ok) return;
        validateResponseUrl(response, isInit ? INIT_PATH : PATH);
        if (!isInit && !/text\/event-stream/i.test(response.headers.get("content-type") || "")) return;
        const body = JSON.parse(text), headers = request.headers;
        if (new URL(request.url).pathname === INIT_PATH) {
          const result = await response.json();
          if (result.success === true && result.session_id &&
              body.agent_name === "agent_OperationsDigitalHuman") {
            runtimeRoute = validateRoute(body.url, body.service_name);
          }
          return;
        }
        if (state.stopped || typeof body.message !== "string" || !body.session_id) return;
        for (const name of [...PAGE_KEYS.slice(0, 2), "x-gde-csrf-token"]) {
          if (!headers.get(name)) {
            console.warn("[自动捕获] 请求可见，但缺少 SDK 请求头 " + name);
            return;
          }
        }
        if (await readCurrentCsrf() !== headers.get("x-gde-csrf-token")) {
          throw new Error("存储 token 与请求头不一致，需要确认该应用的 CSRF 来源。");
        }
        configure({ sessionId: body.session_id, agent: body.agent, model: body.model,
          pageHeaders: Object.fromEntries(PAGE_KEYS.map(k => [k, headers.get(k) ??
            (k === "x-gde-src-page" ? SOURCE_PAGE : "")])),
          referrer: request.referrer && request.referrer !== "about:client"
            ? request.referrer : REFERRER });
        console.info("[自动捕获成功] 等原网页本次回答结束后，即可运行 await ask('你好')。");
      } catch (error) {
        if (!state.stopped) console.warn("[自动捕获提示]", error.message);
      }
    }

    function scan(w, seen) {
      if (seen.has(w) || state.stopped) return;
      seen.add(w);
      try {
        if (w.location.origin !== ORIGIN) return;
        const hook = state.hooks.get(w);
        // iframe 重新加载后 fetch 可能已变化，下一轮重新挂载监听。
        if (!hook || w.fetch !== hook.wrapped) {
          const previous = w.fetch;
          const wrapped = function (...args) {
            let request;
            try {
              const input = args[0];
              const rawUrl = typeof input === "string" ? input : input?.url || String(input);
              const url = new URL(rawUrl, w.location.href || ORIGIN);
              const method = String(args[1]?.method || input?.method || "GET").toUpperCase();
              if (method === "POST" && url.origin === ORIGIN &&
                  (url.pathname === PATH || url.pathname === INIT_PATH) && !url.search) {
                // 克隆 Request 输入，避免消耗原页面待发送的 body。
                const copied = input instanceof w.Request ? input.clone() : input;
                request = new w.Request(copied, args[1]);
              }
            } catch {}
            const result = previous.apply(this, args);
            if (request) {
              const pending = capture(request, result);
              if (new URL(request.url).pathname === INIT_PATH) routeCapture = pending;
            }
            return result;
          };
          w.fetch = wrapped;
          state.hooks.set(w, { previous, wrapped });
        }
        for (let i = 0; i < (w.frames?.length || 0); i++) scan(w.frames[i], seen);
      } catch { /* 跨源或禁止访问的 iframe 不处理。 */ }
    }
    scan(window, new Set());
    state.interval = setInterval(() => scan(window, new Set()), 1000);
    state.timeout = setTimeout(() => {
      if (state.stopped) return;
      stopCapture();
      console.warn("[自动捕获] 10 分钟内未完成初始化，可运行 ADCChat.autoCapture() 再试。");
    }, 600000);
    console.info("[等待初始化] 请在原网页输入框正常发送一次 1+2。已监听同源页面数：", state.hooks.size);
  }

  checkOrigin();
  window.ADCChat = Object.freeze({ version: "1.4", environment: ENVIRONMENT, origin: ORIGIN, configure, importRequest, ask,
    autoCapture, stopCapture, newSession, readUiConfigCsrf,
    get capturing() { return Boolean(captureState); },
    stop: () => { pageAsk?.abort(); controller?.abort(); },
    get lastAnswer() { return lastAnswer; },
    get busy() { return Boolean(controller || pageAsk); },
    get configured() { return Boolean(config); }
  });
  // ask 使用安装时保存的 fetch，不会把自身请求当作网页初始化请求捕获。
  window.ask = (question, options) => window.ADCChat.ask(question, options);
  console.info("[安装完成] " + ENVIRONMENT + "，接口：" + ORIGIN + PATH);
  console.info('现在直接运行 await ask("你的问题")；首次会自动通过网页输入框发送，无需手动预问。');
})();
