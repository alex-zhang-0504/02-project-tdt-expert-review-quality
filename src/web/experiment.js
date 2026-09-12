(() => {
  const dialog = document.querySelector("#experiment-dialog");
  const key = document.querySelector("#experiment-key");
  const status = document.querySelector("#experiment-status");
  const results = document.querySelector("#experiment-results");
  const consent = document.querySelector("#experiment-confirmed");
  let token = "", busy = false, previewId = "", expiresAt = 0;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "ghost-button";
  button.textContent = "个人实验设置";
  button.id = "open-experiment";
  document.querySelector(".topbar").append(button);
  const controls = ["save", "test", "disable", "preview", "run"];
  function sync() {
    const enabled = Boolean(token) && Date.now() < expiresAt;
    for (const name of controls) {
      document.querySelector("#" + name + "-experiment").disabled =
        busy || (name !== "save" && !enabled) || (name === "run" && (!consent.checked || !previewId));
    }
    document.querySelector("#experiment-model").disabled = busy;
    key.disabled = busy;
  }
  async function request(path, body = {}) {
    const response = await fetch("/api/experiment/" + path, {
      method: "POST", cache: "no-store",
      headers: {"Content-Type": "application/json", "X-Experiment-Request": "1", "X-Experiment-Session": token},
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "实验请求失败。");
    return data;
  }
  async function action(fn) {
    if (busy) return;
    busy = true; sync(); results.textContent = ""; status.textContent = "处理中，请稍候…";
    try { await fn(); }
    catch (error) { status.textContent = error.message || "请求失败，请检查本地服务。"; }
    finally { busy = false; sync(); }
  }
  function clearPreview() {
    previewId = ""; consent.checked = false;
    document.querySelector("#experiment-preview").textContent = "";
    document.querySelector("#experiment-consent").classList.add("is-hidden");
    document.querySelector("#run-experiment").classList.add("is-hidden");
    results.textContent = "";
  }
  function showResults(data) {
    const labels = {yes: "包含对策", no: "不包含对策", suspected: "疑似待确认"};
    results.innerHTML = "<h4>个人实验结果 · " + escapeHtml(data.model) + "</h4><p>仅供比较，不写回统计。</p>"
      + data.results.map(o => '<article class="opinion-record"><p class="opinion-text">' + escapeHtml(o.text)
        + '</p><strong>' + labels[o.status] + '</strong><p>原文片段：' + escapeHtml(o.excerpt || "无")
        + '</p><p>判定理由：' + escapeHtml(o.reason) + '</p></article>').join("");
  }
  button.addEventListener("click", () => { sync(); dialog.showModal(); });
  document.querySelector("#close-experiment").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => { key.value = ""; });
  document.querySelector("#save-experiment").addEventListener("click", () => action(async () => {
    const secret = key.value; key.value = "";
    const data = await request("settings", {api_key: secret, model: document.querySelector("#experiment-model").value});
    token = data.session; expiresAt = Date.now() + data.expires_in * 1000;
    clearPreview(); status.textContent = "本次实验已开启，密钥不回显。请先用虚拟文本测试连接。";
  }));
  document.querySelector("#test-experiment").addEventListener("click", () => action(async () => {
    const data = await request("test");
    showResults(data); status.textContent = "连接及结果格式验证通过，仅发送了虚拟文本。";
  }));
  document.querySelector("#disable-experiment").addEventListener("click", () => action(async () => {
    const data = await request("disable"); token = ""; expiresAt = 0;
    key.value = ""; clearPreview(); status.textContent = data.message;
  }));
  document.querySelector("#preview-experiment").addEventListener("click", () => {
    clearPreview();
    if (!state.analysis || state.analysisStale || !qualityGatePassed()) {
      status.textContent = "请先读取报告并处理检查问题。"; sync(); return;
    }
    const opinions = state.analysis.experts.flatMap(e => e.sessions.flatMap(s => s.opinions)).slice(0, 10);
    if (!opinions.length || opinions.reduce((n, o) => n + o.text.length, 0) > 12000) {
      status.textContent = "本批次没有意见或前10条超过12000字，请使用较小批次。"; sync(); return;
    }
    previewId = state.analysis.analysis_id;
    document.querySelector("#experiment-preview").innerHTML = "<h4>即将发送的文本（" + opinions.length + "条）</h4><ol>"
      + opinions.map(o => '<li class="opinion-text">' + escapeHtml(o.text) + "</li>").join("") + "</ol>";
    document.querySelector("#experiment-consent").classList.remove("is-hidden");
    document.querySelector("#run-experiment").classList.remove("is-hidden");
    status.textContent = "尚未发送。只发送上方意见文字和不含姓名的内部标识，不发送整份报告。";
    sync();
  });
  consent.addEventListener("change", sync);
  document.querySelector("#run-experiment").addEventListener("click", () => action(async () => {
    if (!consent.checked || previewId !== state.analysis?.analysis_id || state.analysisStale)
      throw new Error("报告已变化，请重新预览并确认。");
    const data = await request("preview", {analysis_id: previewId, confirmed: true});
    showResults(data); status.textContent = data.notice; consent.checked = false;
  }));
  window.setInterval(() => {
    if (token && Date.now() >= expiresAt && !busy) {
      token = ""; clearPreview(); status.textContent = "实验已过期，请重新配置。"; sync();
    }
  }, 5000);
})();
