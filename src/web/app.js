const SERVICE_HEALTH_INTERVAL_MS = 5000;
const EXPECTED_PROJECT_ID = "tdt-expert-review-quality";
const EXPECTED_BUILD_ID = new URLSearchParams(window.location.search).get("build") || "";
const SERVICE_DISCONNECTED_MESSAGE = "无法连接本地评分服务。请重新双击 start.cmd，并使用新打开的页面重新导入评审表";
const SERVICE_RESTARTED_MESSAGE = "本地评分服务已重新启动，原评审分析已失效。请返回读取评审表并重新导入后再评分";
const IMPORT_PROGRESS_STEP_MS = 120;
const IMPORT_CHECKPOINTS = [
  ["report_acquisition", "获取报告"],
  ["xlsx_acquisition", "获取XLSX"],
  ["workbook_parse", "解析工作簿"],
  ["template_structure", "检查模板结构"],
  ["session_identity", "检查场次身份"],
  ["reviewer_roster", "检查评审名单"],
  ["attendance_signoff", "检查出勤与会签"],
  ["opinions_problems", "检查意见与问题"],
  ["session_uniqueness", "检查场次唯一性"],
  ["score_bounds", "检查评分边界"],
];

const state = {
  activeStep: 1,
  analysis: null,
  selectedExpert: null,
  questions: [],
  answers: {},
  questionnaireDrafts: {},
  professionalReasonTags: [],
  professionalReasonNote: "",
  outstandingContributionReason: "",
  auditDrafts: {},
  lastResult: null,
  droppedFiles: [],
  selectedReportIndex: 0,
  warningsAcknowledged: false,
  serviceAvailable: false,
  serviceInstanceId: null,
  serviceVersion: "",
  analysisServiceInstanceId: null,
  analysisStale: false,
  feishuAuthReady: false,
  importJobId: null,
  importJobStatus: "queued",
  importProgressReports: [],
  displayProgressReports: [],
  progressPlaybackTimer: null,
};

const elements = {
  status: document.querySelector("#service-status"),
  notice: document.querySelector("#notice"),
  importLocal: document.querySelector("#import-local"),
  importFeishu: document.querySelector("#import-feishu"),
  file: document.querySelector("#workbook-file"),
  fileName: document.querySelector("#file-name"),
  uploadBox: document.querySelector("#upload-box"),
  feishuUrl: document.querySelector("#feishu-url"),
  feishuAuthStatus: document.querySelector("#feishu-auth-status"),
  authorizeFeishu: document.querySelector("#authorize-feishu"),
  completeFeishuAuth: document.querySelector("#complete-feishu-auth"),
  importPanel: document.querySelector("#import-panel"),
  analysisPanel: document.querySelector("#analysis-panel"),
  questionnairePanel: document.querySelector("#questionnaire-panel"),
  resultPanel: document.querySelector("#result-panel"),
  analysisSummary: document.querySelector("#analysis-summary"),
  projectSummary: document.querySelector("#project-summary"),
  checkCard: document.querySelector("#check-card"),
  checkTitle: document.querySelector("#check-title"),
  checkState: document.querySelector("#check-state"),
  reportList: document.querySelector("#report-list"),
  batchSummary: document.querySelector("#batch-summary"),
  warningConfirm: document.querySelector("#warning-confirm"),
  warningAcknowledged: document.querySelector("#warning-acknowledged"),
  continueAnalysis: document.querySelector("#continue-analysis"),
  issueSummary: document.querySelector("#issue-summary"),
  expertList: document.querySelector("#expert-list"),
  expertDetail: document.querySelector("#expert-detail"),
  selectedExpertLabel: document.querySelector("#selected-expert"),
  evidenceStrip: document.querySelector("#evidence-strip"),
  questionnaire: document.querySelector("#questionnaire"),
  standaloneIdentity: document.querySelector("#standalone-identity"),
  standaloneProjectCode: document.querySelector("#standalone-project-code"),
  standaloneProjectName: document.querySelector("#standalone-project-name"),
  standaloneExpertName: document.querySelector("#standalone-expert-name"),
  calculate: document.querySelector("#calculate-total"),
  result: document.querySelector("#score-result"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setNotice(message, type = "info") {
  elements.notice.textContent = message;
  elements.notice.className = `notice notice-${type}`;
}

function clearNotice() {
  elements.notice.textContent = "";
  elements.notice.className = "notice is-hidden";
}

function setBusy(button, busy, label) {
  button.dataset.busy = String(busy);
  button.disabled = busy;
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.textContent = label;
  } else {
    button.textContent = button.dataset.originalLabel || button.textContent;
  }
  if (button.dataset.serviceAction === "true") syncServiceActions();
}

function setServiceStatus(label, message, ready) {
  elements.status.textContent = label;
  elements.status.title = message;
  elements.status.className = `status-pill ${ready ? "is-ready" : "is-error"}`;
}

function syncServiceActions() {
  document.querySelectorAll('[data-service-action="true"]').forEach((button) => {
    if (button === elements.calculate) return;
    const authorizationMissing = button === elements.importFeishu && !state.feishuAuthReady;
    button.disabled = button.dataset.busy === "true" || !state.serviceAvailable || authorizationMissing;
  });
  updateSubmitAvailability();
}

function markServiceUnavailable(message, label = "服务已断开") {
  state.serviceAvailable = false;
  setServiceStatus(label, message, false);
  syncServiceActions();
}

function serviceIdentityError(health) {
  if (health.project_id !== EXPECTED_PROJECT_ID) {
    return "当前页面连接到了其他项目的本地服务。请关闭此页面，重新双击本项目的 start.cmd";
  }
  if (EXPECTED_BUILD_ID && health.build_id !== EXPECTED_BUILD_ID) {
    return "当前页面与本地评分服务版本不一致。请关闭此页面，重新双击 start.cmd，并使用新打开的页面";
  }
  if (!health.service_instance_id) {
    return "当前本地评分服务版本过旧。请关闭此页面，重新双击 start.cmd，并使用新打开的页面";
  }
  return "";
}

function applyServiceHealth(health) {
  const identityError = serviceIdentityError(health);
  if (identityError) {
    markServiceUnavailable(identityError, "服务版本不匹配");
    return false;
  }

  state.serviceAvailable = true;
  state.serviceInstanceId = health.service_instance_id;
  state.serviceVersion = health.version;
  if (state.analysis && state.analysisServiceInstanceId
      && health.service_instance_id !== state.analysisServiceInstanceId) {
    state.analysisStale = true;
  }

  if (state.analysisStale) {
    setServiceStatus("服务已重新启动", SERVICE_RESTARTED_MESSAGE, false);
  } else {
    setServiceStatus(`试用版 ${health.version}`, "本地评分服务运行正常", true);
  }
  syncServiceActions();
  return true;
}

async function checkServiceHealth() {
  try {
    const response = await fetch(`/api/health?ts=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`健康检查失败（${response.status}）`);
    return applyServiceHealth(await response.json());
  } catch (error) {
    markServiceUnavailable(SERVICE_DISCONNECTED_MESSAGE);
    return false;
  }
}

async function requestJson(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    if (window.location.protocol === "file:") {
      throw new Error("请通过启动脚本打开系统，不能直接双击index.html使用");
    }
    markServiceUnavailable(SERVICE_DISCONNECTED_MESSAGE);
    throw new Error(SERVICE_DISCONNECTED_MESSAGE);
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `请求失败（${response.status}）`);
  }
  return payload;
}

function activateStep(step) {
  state.activeStep = step;
  document.querySelectorAll(".module-tab").forEach((item) => {
    const itemStep = Number(item.dataset.step);
    item.classList.toggle("is-active", itemStep === step);
    item.disabled = !canNavigate(itemStep);
    if (itemStep === step) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
  });
  syncExpertNavigationState();
}

function expertSelectionEnabled() {
  return state.activeStep === 2 || state.activeStep === 3;
}

function syncExpertNavigationState() {
  const enabled = expertSelectionEnabled();
  const selectedKey = state.selectedExpert ? expertKey(state.selectedExpert) : "";
  elements.expertList.querySelectorAll(".expert-chip").forEach((button) => {
    const expert = state.analysis?.experts[Number(button.dataset.index)];
    button.disabled = !enabled;
    button.classList.toggle("is-active", enabled && expertKey(expert) === selectedKey);
  });
}

function validationCounts() {
  const issues = state.analysis?.issues || [];
  const errors = issues.filter((issue) => issue.severity === "error").length;
  const warnings = issues.filter((issue) => issue.severity === "warning").length;
  return { errors, warnings };
}

function qualityGatePassed() {
  if (!state.analysis) return false;
  const { errors, warnings } = validationCounts();
  return errors === 0 && (warnings === 0 || state.warningsAcknowledged);
}

function canNavigate(step) {
  if (step === 1) return true;
  if (!state.analysis) return step === 3 || step === 4;
  return qualityGatePassed();
}

function showPanel(panel) {
  [elements.importPanel, elements.analysisPanel, elements.questionnairePanel, elements.resultPanel]
    .forEach((item) => item.classList.add("is-hidden"));
  panel.classList.remove("is-hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function importLocal() {
  const button = elements.importLocal;
  clearNotice();
  setBusy(button, true, "正在读取与检查…");
  try {
    const selectedFiles = state.droppedFiles.length
      ? state.droppedFiles
      : [...elements.file.files];
    if (!selectedFiles.length) throw new Error("请选择或拖入.xlsx格式的TDRX评审报告");
    startProgressDisplay(selectedFiles.map((file) => file.name));
    const formData = new FormData();
    selectedFiles.forEach((file) => formData.append("files", file, file.name));
    const job = await requestJson("/api/import/local-batch/start", {
      method: "POST",
      body: formData,
    });
    const analysis = await pollImportJob(job.job_id);
    await receiveAnalysis(analysis);
  } catch (error) {
    finishCheckWithRequestError(error.message);
    setNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function importFeishu() {
  const button = elements.importFeishu;
  clearNotice();
  startProgressDisplay([]);
  setBusy(button, true, "正在枚举并检查飞书报告…");
  try {
    const url = elements.feishuUrl.value.trim();
    if (!url) throw new Error("请输入飞书归档文件夹URL");
    const job = await requestJson("/api/import/feishu/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const analysis = await pollImportJob(job.job_id);
    await receiveAnalysis(analysis);
  } catch (error) {
    finishCheckWithRequestError(error.message);
    setNotice(error.message, "error");
  } finally {
    setBusy(button, false);
  }
}

async function receiveAnalysis(analysis) {
  state.analysis = analysis;
  state.analysisServiceInstanceId = state.serviceInstanceId;
  state.analysisStale = false;
  state.selectedExpert = analysis.experts[0] || null;
  state.answers = {};
  state.questionnaireDrafts = {};
  state.professionalReasonTags = [];
  state.professionalReasonNote = "";
  state.outstandingContributionReason = "";
  state.auditDrafts = {};
  state.lastResult = null;
  state.selectedReportIndex = 0;
  state.warningsAcknowledged = false;
  elements.warningAcknowledged.checked = false;
  const reportCount = analysis.reports?.length || 1;
  const candidateCount = analysis.batch_summary?.candidate_count ?? reportCount;
  elements.projectSummary.textContent = `${candidateCount}份候选报告 · ${analysis.sessions.length}场 · ${analysis.experts.length}位专家`;
  renderBatchSummary();
  renderExpertNavigation();
  renderReportList();
  if (analysis.reports?.length) selectReport(0);
  else renderIssues(analysis.issues, analysis.source_name);
  activateStep(1);
}

function startProgressDisplay(sourceNames = []) {
  stopProgressPlayback();
  state.analysis = null;
  state.selectedExpert = null;
  state.selectedReportIndex = 0;
  state.importJobId = null;
  state.importJobStatus = "queued";
  state.importProgressReports = sourceNames.map((sourceName) => ({
    source_name: sourceName,
    status: "queued",
    progress_percent: 0,
    current_checkpoint_label: "等待检查",
    message: "",
  }));
  state.displayProgressReports = state.importProgressReports.map((report) => ({
    ...report,
    target_percent: 0,
    display_percent: 0,
    display_checkpoint_label: "等待检查",
  }));
  state.warningsAcknowledged = false;
  elements.projectSummary.textContent = "正在检查评审表";
  renderExpertNavigation();
  activateStep(1);
  elements.checkCard.classList.remove("is-hidden");
  elements.checkTitle.textContent = "正在检查评审报告";
  elements.checkState.textContent = "检查中";
  elements.checkState.className = "check-state";
  elements.issueSummary.innerHTML = "";
  elements.batchSummary.className = "batch-summary usage-note is-hidden";
  elements.batchSummary.innerHTML = "";
  elements.warningConfirm.classList.add("is-hidden");
  elements.continueAnalysis.disabled = true;
  renderReportList();
}

async function pollImportJob(jobId) {
  state.importJobId = jobId;
  while (true) {
    const job = await requestJson(`/api/import/jobs/${encodeURIComponent(jobId)}?ts=${Date.now()}`, {
      cache: "no-store",
    });
    state.importJobStatus = job.status;
    syncProgressTargets(job.reports || []);
    if (job.status === "completed") {
      await waitForProgressPlayback();
      return job.result;
    }
    if (job.status === "error") throw new Error(job.error || "评审报告批量读取失败");
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

function stopProgressPlayback() {
  if (state.progressPlaybackTimer !== null) {
    window.clearTimeout(state.progressPlaybackTimer);
    state.progressPlaybackTimer = null;
  }
}

function syncProgressTargets(reports) {
  const previous = state.displayProgressReports;
  state.importProgressReports = reports;
  state.displayProgressReports = reports.map((report, index) => {
    const target = Math.max(0, Math.min(100, Number(report.progress_percent) || 0));
    const existing = previous[index];
    const canReuse = existing?.source_name === report.source_name;
    const displayPercent = canReuse
      ? Math.min(Number(existing.display_percent) || 0, target)
      : 0;
    return {
      ...report,
      target_percent: target,
      display_percent: displayPercent,
      display_checkpoint_label: canReuse
        ? existing.display_checkpoint_label
        : "等待检查",
    };
  });
  renderReportList();
  updateProgressHeader();
  scheduleProgressPlayback();
}

function nextProgressReport() {
  const reports = state.displayProgressReports;
  const preparing = reports.find((report) => (
    report.display_percent < Math.min(20, report.target_percent)
  ));
  if (preparing) return preparing;
  const allPrepared = reports.length > 0 && reports.every((report) => (
    report.target_percent >= 20 || report.status === "error"
  ));
  if (!allPrepared) return null;
  return reports.find((report) => report.display_percent < report.target_percent) || null;
}

function advanceProgressPlayback() {
  const report = nextProgressReport();
  if (!report) return false;
  report.display_percent = Math.min(report.target_percent, report.display_percent + 10);
  const checkpointIndex = Math.max(0, Math.ceil(report.display_percent / 10) - 1);
  report.display_checkpoint_label = IMPORT_CHECKPOINTS[checkpointIndex]?.[1] || "等待检查";
  renderReportList();
  updateProgressHeader();
  return true;
}

function scheduleProgressPlayback() {
  if (state.progressPlaybackTimer !== null || !nextProgressReport()) return;
  state.progressPlaybackTimer = window.setTimeout(() => {
    state.progressPlaybackTimer = null;
    if (advanceProgressPlayback()) scheduleProgressPlayback();
  }, IMPORT_PROGRESS_STEP_MS);
}

async function waitForProgressPlayback() {
  scheduleProgressPlayback();
  while (nextProgressReport() || state.progressPlaybackTimer !== null) {
    await new Promise((resolve) => setTimeout(resolve, 40));
  }
}

function updateProgressHeader() {
  const reports = state.displayProgressReports;
  if (!reports.length) {
    elements.checkTitle.textContent = "正在枚举飞书归档文件夹";
    elements.checkState.textContent = "检查中";
    return;
  }
  const completed = reports.filter((report) => (
    report.status === "completed" && report.display_percent >= report.target_percent
  )).length;
  const failed = reports.filter((report) => report.status === "error").length;
  const playbackComplete = reports.every((report) => (
    report.display_percent >= report.target_percent
  ));
  elements.checkTitle.textContent = state.importJobStatus === "completed" && playbackComplete
    ? "评审报告检查完成"
    : `正在逐份检查${reports.length}份评审报告`;
  elements.checkState.textContent = `${completed}完成${failed ? ` · ${failed}失败` : ""}`;
}

function selectedReport() {
  return state.analysis?.reports?.[state.selectedReportIndex] || null;
}

function renderReportList() {
  const reports = state.analysis
    ? state.analysis.reports.map((report, index) => {
      const live = state.displayProgressReports[index];
      const errors = report.issues.filter((issue) => issue.severity === "error").length;
      const warnings = report.issues.filter((issue) => issue.severity === "warning").length;
      return {
        ...(live || {}),
        source_name: report.source_name,
        status: errors ? "error" : warnings ? "warning" : "completed",
        display_percent: live?.display_percent ?? (errors ? 0 : 100),
        target_percent: live?.target_percent ?? (errors ? 0 : 100),
        display_checkpoint_label: live?.display_checkpoint_label
          || IMPORT_CHECKPOINTS.at(-1)[1],
        message: errors ? `${errors}项错误` : warnings ? `${warnings}项提醒` : "检查通过",
      };
    })
    : state.displayProgressReports;
  elements.reportList.innerHTML = reports.map((report, index) => {
    const percent = Math.max(0, Math.min(100, Number(report.display_percent) || 0));
    const targetPercent = Math.max(percent, Math.min(100, Number(report.target_percent) || 0));
    const completedSegments = Math.floor(percent / 10);
    const currentCheckpointIndex = IMPORT_CHECKPOINTS.findIndex(
      ([checkpointId]) => checkpointId === report.current_checkpoint
    );
    const actualCheckpointIsNext = targetPercent === percent
      && report.status === "running"
      && currentCheckpointIndex === completedSegments;
    const playbackCheckpointIndex = targetPercent > percent ? completedSegments : -1;
    const activeCheckpointIndex = playbackCheckpointIndex >= 0
      ? playbackCheckpointIndex
      : actualCheckpointIsNext ? currentCheckpointIndex : -1;
    const checkpointLabel = playbackCheckpointIndex >= 0
      ? IMPORT_CHECKPOINTS[playbackCheckpointIndex]?.[1]
      : targetPercent === percent && actualCheckpointIsNext
        ? report.current_checkpoint_label
        : report.display_checkpoint_label || "等待检查";
    const playbackPending = targetPercent > percent;
    const statusClass = report.status === "error"
      ? "is-error"
      : playbackPending
        ? "is-pending"
        : report.status === "warning"
          ? "is-warning"
          : report.status === "completed" ? "is-ok" : "is-pending";
    const summaryText = report.status === "error"
      ? report.message || "检查失败"
      : !playbackPending && (report.status === "completed" || report.status === "warning")
        ? report.message || "检查完成"
        : `已完成${completedSegments}／${IMPORT_CHECKPOINTS.length}项`;
    const segments = IMPORT_CHECKPOINTS.map((_, segmentIndex) => {
      const classes = ["report-progress-segment"];
      if (segmentIndex < completedSegments) classes.push("is-complete");
      if (segmentIndex === activeCheckpointIndex) classes.push("is-current");
      return `<span class="${classes.join(" ")}"></span>`;
    }).join("");
    const tag = state.analysis ? "button" : "div";
    return `<${tag} class="report-progress-row ${statusClass} ${index === state.selectedReportIndex && state.analysis ? "is-active" : ""}" ${state.analysis ? `type="button" data-index="${index}"` : ""}>
      <span class="report-progress-name" data-full-name="${escapeHtml(report.source_name)}"><strong>${escapeHtml(report.source_name)}</strong><small class="report-progress-status">${escapeHtml(summaryText)}</small></span>
      <span class="report-progress-reader ${activeCheckpointIndex >= 0 ? "is-reading" : ""}"><small>当前检查</small><strong>${escapeHtml(checkpointLabel)}</strong></span>
      <span class="report-progress-meter">
        <span class="report-progress-segments" role="progressbar" aria-label="${escapeHtml(report.source_name)}检查进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}">${segments}</span>
        <span class="report-progress-value">${percent}%</span>
      </span>
    </${tag}>`;
  }).join("");
  elements.reportList.querySelectorAll("button.report-progress-row").forEach((button) => {
    button.addEventListener("click", () => selectReport(Number(button.dataset.index)));
  });
}

function renderBatchSummary() {
  const summary = state.analysis?.batch_summary;
  if (!summary) {
    elements.batchSummary.className = "batch-summary usage-note is-hidden";
    elements.batchSummary.innerHTML = "";
    return;
  }
  elements.batchSummary.className = `batch-summary usage-note ${summary.complete ? "" : "is-error"}`;
  const excluded = summary.excluded_names?.length
    ? `；排除资源：${summary.excluded_names.map(escapeHtml).join("、")}`
    : "";
  elements.batchSummary.innerHTML = `
    <strong>${summary.complete ? "飞书批次完整" : "飞书批次不完整，禁止生成完整年度结果"}</strong>
    <p>发现${summary.discovered_count}项 · 候选${summary.candidate_count}份 · 成功${summary.succeeded_count}份 · 失败${summary.failed_count}份 · 排除${summary.excluded_count}项${excluded}</p>`;
}

function renderSelectedReportChecks() {
  const report = selectedReport();
  if (!report) return;
  renderIssues(report.issues, report.source_name);
}

function selectReport(index) {
  if (!state.analysis?.reports?.[index]) return;
  state.selectedReportIndex = index;
  renderReportList();
  renderSelectedReportChecks();
}

function finishCheckWithRequestError(message) {
  elements.checkTitle.textContent = "评审报告读取失败";
  elements.checkState.textContent = "未通过";
  elements.checkState.className = "check-state is-error";
  elements.issueSummary.innerHTML = `<div class="issue-item error"><span class="severity">错误</span><span class="issue-location">读取阶段</span><span>${escapeHtml(message)}</span></div>`;
}

function renderAnalysis() {
  const { analysis } = state;
  if (!analysis) {
    elements.analysisSummary.textContent = "尚未读取评审表";
    elements.expertDetail.innerHTML = `
      <div class="empty-detail">
        <strong>评审过程表现需要TDRX评审表</strong>
        <p>请先在“读取评审表”模块导入并通过文档质量检查。</p>
        <button class="secondary-button" id="go-import" type="button">前往读取评审表</button>
      </div>`;
    document.querySelector("#go-import").addEventListener("click", () => navigateStep(1));
    return;
  }
  elements.analysisSummary.textContent = `${analysis.source_name} · 仅纳入已完成TDR3的项目 · ${analysis.experts.length}位专家`;
  renderExpertDetail();
}

function renderIssues(issues, reportName = "") {
  const batchIssues = state.analysis?.batch_summary
    ? state.analysis.issues.filter((issue) => issue.code.startsWith("feishu_folder_"))
    : [];
  const visibleIssues = issues.filter((issue) => issue.severity !== "info");
  batchIssues.forEach((issue) => {
    if (issue.severity !== "info" && !visibleIssues.includes(issue)) visibleIssues.push(issue);
  });
  const errors = visibleIssues.filter((issue) => issue.severity === "error").length;
  const warnings = visibleIssues.filter((issue) => issue.severity === "warning").length;
  const aggregate = validationCounts();
  const label = reportName ? `“${reportName}”` : "评审报告";
  if (!visibleIssues.length) {
    elements.checkTitle.textContent = `${label}检查完成`;
    elements.checkState.textContent = "检查通过";
    elements.checkState.className = "check-state is-ok";
    elements.issueSummary.innerHTML = `<p><strong>未发现错误或提醒。</strong>评审报告可以进入后续评分。</p>`;
  } else {
    elements.checkTitle.textContent = errors
      ? `${label}存在错误`
      : warnings ? `${label}存在提醒` : `${label}检查完成`;
    elements.checkState.textContent = errors
      ? `${errors}项错误`
      : warnings ? `${warnings}项提醒` : "检查通过";
    elements.checkState.className = `check-state ${errors ? "is-error" : warnings ? "is-warning" : "is-ok"}`;
    elements.issueSummary.innerHTML = `
      <strong>${errors}项错误，${warnings}项提醒</strong>
      <ul>${visibleIssues.map((issue) => {
        const location = issue.sheet_name
          ? `${issue.sheet_name}${issue.cell_reference ? `!${issue.cell_reference}` : ""}`
          : "工作簿";
        const expert = issue.expert_name ? `；专家：${issue.expert_name}` : "";
        const severityLabel = issue.severity === "error" ? "错误" : "提醒";
        return `<li class="issue-item ${issue.severity}"><span class="severity">${severityLabel}</span><span class="issue-location">${escapeHtml(location)}</span><span>${escapeHtml(issue.message + expert)}</span></li>`;
      }).join("")}</ul>`;
  }
  elements.warningConfirm.classList.toggle("is-hidden", aggregate.warnings === 0 || aggregate.errors > 0);
  elements.continueAnalysis.disabled = aggregate.errors > 0 || (aggregate.warnings > 0 && !state.warningsAcknowledged);
  activateStep(1);
}

function selectExpert(index) {
  if (!expertSelectionEnabled()) return;
  if (!state.analysis?.experts[index]) return;
  state.selectedExpert = state.analysis.experts[index];
  const key = expertKey(state.selectedExpert);
  state.answers = { ...(state.questionnaireDrafts[key] || {}) };
  const audit = state.auditDrafts[key] || state.selectedExpert;
  state.professionalReasonTags = [...(audit.professional_reason_tags || [])];
  state.professionalReasonNote = audit.professional_reason_note || "";
  state.outstandingContributionReason = audit.outstanding_contribution_reason || "";
  state.lastResult = state.selectedExpert.status === "已完成" ? state.selectedExpert : null;
  document.querySelectorAll(".expert-chip").forEach((button, buttonIndex) => {
    button.classList.toggle("is-active", buttonIndex === index);
  });
  if (state.activeStep === 2) renderExpertDetail();
  else if (state.activeStep === 3) openQuestionnaire();
  else if (state.activeStep === 4) openResultPanel();
}

function renderExpertNavigation() {
  const experts = state.analysis?.experts || [];
  if (!experts.length) {
    elements.expertList.innerHTML = `<span class="expert-placeholder">读取评审表后显示评审人</span>`;
    return;
  }
  const selectedKey = state.selectedExpert ? expertKey(state.selectedExpert) : "";
  const enabled = expertSelectionEnabled();
  elements.expertList.innerHTML = experts.map((expert, index) => `
    <button class="expert-chip ${enabled && (expertKey(expert) === selectedKey || (!selectedKey && index === 0)) ? "is-active" : ""} ${expert.status === "已完成" ? "is-complete" : ""}" data-index="${index}" title="${escapeHtml(expert.expert_name)}" ${enabled ? "" : "disabled"}>${escapeHtml(expert.expert_name)}</button>
  `).join("");
  elements.expertList.querySelectorAll(".expert-chip").forEach((button) => {
    button.addEventListener("click", () => selectExpert(Number(button.dataset.index)));
  });
}

function renderExpertDetail() {
  const expert = state.selectedExpert;
  if (!expert) {
    elements.expertDetail.innerHTML = `<div class="empty-detail">当前报告中没有已完成TDR3、可进入年度考核的专家记录。</div>`;
    return;
  }
  elements.expertDetail.innerHTML = `
    <div class="detail-heading">
      <div><p>当前专家</p><h3>${escapeHtml(expert.expert_name)}</h3></div>
      <div class="average-score"><span>${expert.objective_score}</span><small>客观分数／60</small></div>
    </div>
    <div class="fact-score-grid">
      <article><span>${expert.process_average}／50</span><small>评审过程表现</small></article>
      <article><span>${expert.participation_score}／6</span><small>评审参与度 · ${expert.participation_project_count}个项目</small></article>
      <article><span>${expert.problem_score}／4</span><small>问题贡献度 · ${expert.problem_project_count}个项目</small></article>
    </div>
    <div class="formula-note">客观分数＝评审过程表现 ${expert.process_average}＋年度服务贡献 ${expert.annual_service_score}＝<strong>${expert.objective_score}</strong>。有效参评项目：${escapeHtml(expert.participation_project_codes.join("、") || "无")}；问题贡献项目：${escapeHtml(expert.problem_project_codes.join("、") || "无")}。年度代理事实：被代理 ${expert.proxy_session_count}／${expert.expected_session_count} 场，代理率 ${expert.proxy_rate}％（仅展示，不参与计分）。</div>
    <details class="fact-details">
      <summary>查看逐场计分依据</summary>
      <div class="session-grid">
        ${expert.sessions.map((session) => `
          <article class="session-card">
            <div class="session-title"><strong>${escapeHtml(session.project_code)} · ${escapeHtml(session.stage)}</strong><span>${session.total}／50</span></div>
            <dl>
              <div><dt>出勤表现</dt><dd>${session.attendance.score}</dd></div>
              <div><dt>结果会签</dt><dd>${session.signoff.score}</dd></div>
              <div><dt>评审意见</dt><dd>${session.opinion.score}</dd></div>
            </dl>
            <p>${escapeHtml(session.opinion.reason)}</p>
            <div class="opinion-evidence">
              <span>技术对象：${escapeHtml(session.opinion_evidence.technical_object || "未识别")}</span>
              <span>专业动作：${escapeHtml(session.opinion_evidence.professional_action || "未识别")}</span>
              <span>具体细节：${escapeHtml(session.opinion_evidence.specific_detail || "未识别")}</span>
            </div>
            <p class="opinion-source">${(session.opinion_evidence.source_cells || []).length
              ? `${escapeHtml(session.sheet_name)}!${escapeHtml(session.opinion_evidence.source_cells.join("、"))} · ${escapeHtml((session.opinion_evidence.source_texts || []).join(" ｜ "))}`
              : `${session.opinion_evidence.source_cell ? `${escapeHtml(session.sheet_name)}!${escapeHtml(session.opinion_evidence.source_cell)} · ` : ""}${escapeHtml(session.opinion_evidence.source_text || "未填写评审意见")}`}</p>
          </article>`).join("")}
      </div>
    </details>
    <button class="primary-button" id="start-questionnaire">为该专家作答主观分数</button>`;
  document.querySelector("#start-questionnaire").addEventListener("click", openQuestionnaire);
}

function expertProblems() {
  if (!state.analysis) return [];
  const name = state.selectedExpert?.expert_name;
  return state.analysis.sessions.flatMap((session) =>
    session.problems
      .filter((problem) => problem.reviewers.includes(name))
      .map((problem) => ({ ...problem, project_code: session.project_code, stage: session.stage })),
  );
}

function openQuestionnaire() {
  const expert = state.selectedExpert;
  showPanel(elements.questionnairePanel);
  activateStep(3);
  if (!expert) {
    elements.standaloneIdentity.classList.remove("is-hidden");
    elements.selectedExpertLabel.innerHTML = "";
    elements.evidenceStrip.classList.add("is-hidden");
    elements.questionnaire.innerHTML = "";
    elements.calculate.classList.add("is-hidden");
    return;
  }
  const key = expertKey(expert);
  state.answers = { ...(state.questionnaireDrafts[key] || {}) };
  const audit = state.auditDrafts[key] || expert;
  state.professionalReasonTags = [...(audit.professional_reason_tags || [])];
  state.professionalReasonNote = audit.professional_reason_note || "";
  state.outstandingContributionReason = audit.outstanding_contribution_reason || "";
  elements.standaloneIdentity.classList.add("is-hidden");
  elements.evidenceStrip.classList.toggle("is-hidden", !state.analysis);
  elements.calculate.classList.remove("is-hidden");
  elements.selectedExpertLabel.innerHTML = `<strong>${escapeHtml(expert.expert_name)}</strong><span>${escapeHtml(expert.project_name)}</span>`;
  const problems = expertProblems();
  elements.evidenceStrip.innerHTML = state.analysis ? `
    <strong>考核事实</strong>
    <p>评审过程 ${expert.process_average}／50；有效参评 ${expert.participation_project_count}个项目；提出有效问题 ${expert.problem_project_count}个项目。</p>
    ${problems.length
      ? `<div>${problems.map((problem) => `<span>${escapeHtml(problem.project_code)} · ${escapeHtml(problem.stage)} · ${escapeHtml(problem.number)} · ${escapeHtml(problem.description)}</span>`).join("")}</div>`
      : `<p>评审表中没有该专家名下的问题记录。</p>`}` : "";
  renderQuestionnaire();
}

function expertKey(expert) {
  return `${expert.project_code}::${expert.expert_name}`;
}

function professionalAuditRequired() {
  return state.answers.professional_judgement_guidance === "low";
}

function outstandingReasonRequired() {
  return state.answers.outstanding_contribution === "high";
}

function questionnaireReady() {
  const allAnswered = Object.keys(state.answers).length === state.questions.length;
  const professionalAuditValid = !professionalAuditRequired()
    || (state.professionalReasonTags.length > 0
      && state.professionalReasonNote.trim().length > 0
      && state.professionalReasonNote.length <= 100);
  const outstandingReasonValid = !outstandingReasonRequired()
    || (state.outstandingContributionReason.trim().length > 0
      && state.outstandingContributionReason.length <= 100);
  return allAnswered && professionalAuditValid && outstandingReasonValid;
}

function saveQuestionnaireDraft() {
  if (!state.selectedExpert) return;
  const key = expertKey(state.selectedExpert);
  state.questionnaireDrafts[key] = { ...state.answers };
  state.auditDrafts[key] = {
    professional_reason_tags: [...state.professionalReasonTags],
    professional_reason_note: state.professionalReasonNote,
    outstanding_contribution_reason: state.outstandingContributionReason,
  };
}

function syncAuditFields() {
  const professionalField = document.querySelector("#professional-audit-field");
  const outstandingField = document.querySelector("#outstanding-reason-field");
  if (professionalField) professionalField.classList.toggle("is-hidden", !professionalAuditRequired());
  if (outstandingField) outstandingField.classList.toggle("is-hidden", !outstandingReasonRequired());
}

function updateSubmitAvailability() {
  const busy = elements.calculate.dataset.busy === "true";
  elements.calculate.disabled = busy || !state.serviceAvailable || state.analysisStale || !questionnaireReady();
}

function renderQuestionnaire() {
  elements.questionnaire.innerHTML = state.questions.map((question, questionIndex) => `
    <fieldset class="question-card" data-option-count="${question.options.length}">
      <legend><span>${questionIndex + 1}</span><div><strong>${escapeHtml(question.title)}</strong><small>${escapeHtml(question.prompt)}</small></div></legend>
      <div class="option-grid">
        ${question.options.map((option) => `
          <label class="answer-option ${state.answers[question.id] === option.level ? "is-selected" : ""}">
            <input type="radio" name="${escapeHtml(question.id)}" value="${escapeHtml(option.level)}" ${state.answers[question.id] === option.level ? "checked" : ""} />
            <span class="radio-mark"></span>
            <span class="answer-copy"><strong>${escapeHtml(option.label)}</strong><small>${escapeHtml(option.description)}</small></span>
            ${option.reference ? `<span class="option-reference" tabindex="0" aria-label="查看典型情形">i<span class="option-reference-popover"><strong>典型情形参考</strong><ol>${option.reference.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol></span></span>` : ""}
          </label>`).join("")}
      </div>
      ${question.id === "professional_judgement_guidance" ? `
        <div class="audit-field ${professionalAuditRequired() ? "" : "is-hidden"}" id="professional-audit-field">
          <strong>请选择主要原因（至少1项，可多选）</strong>
          <div class="reason-tags">
            ${["严重技术误判", "重大风险遗漏", "竞争力误判", "其他"].map((tag) => `
              <label class="reason-tag"><input type="checkbox" name="professional-reason-tag" value="${tag}" ${state.professionalReasonTags.includes(tag) ? "checked" : ""} /><span>${tag}</span></label>`).join("")}
          </div>
          <label for="professional-reason-note"><strong>0分原因和导致影响</strong><span>请说明具体误判或遗漏、对应评审阶段，以及实际造成的影响。</span></label>
          <textarea id="professional-reason-note" maxlength="100" rows="3" placeholder="例如：TDR2对可控风险作出失衡判断，项目因此延期并错失技术窗口。">${escapeHtml(state.professionalReasonNote)}</textarea>
          <div class="contribution-case-meta"><span>必填，100字以内。</span><span id="professional-reason-count">${state.professionalReasonNote.length}/100</span></div>
        </div>` : ""}
      ${question.id === "outstanding_contribution" ? `
        <div class="audit-field ${outstandingReasonRequired() ? "" : "is-hidden"}" id="outstanding-reason-field">
          <label for="outstanding-contribution-reason"><strong>突出贡献加分原因</strong><span>请说明具体贡献、产生的项目价值，以及对应的评审阶段或问题编号。</span></label>
          <textarea id="outstanding-contribution-reason" maxlength="100" rows="3" placeholder="例如：在TDR2识别关键风险，推动补充验证并避免量产返工。">${escapeHtml(state.outstandingContributionReason)}</textarea>
          <div class="contribution-case-meta"><span>必填，100字以内。</span><span id="outstanding-reason-count">${state.outstandingContributionReason.length}/100</span></div>
        </div>` : ""}
    </fieldset>`).join("");
  elements.questionnaire.querySelectorAll("input[type=radio]").forEach((input) => {
    input.addEventListener("change", () => {
      state.answers[input.name] = input.value;
      saveQuestionnaireDraft();
      input.closest(".option-grid").querySelectorAll(".answer-option").forEach((option) => option.classList.remove("is-selected"));
      input.closest(".answer-option").classList.add("is-selected");
      syncAuditFields();
      updateSubmitAvailability();
    });
  });
  elements.questionnaire.querySelectorAll('input[name="professional-reason-tag"]').forEach((input) => {
    input.addEventListener("change", () => {
      state.professionalReasonTags = [...elements.questionnaire.querySelectorAll('input[name="professional-reason-tag"]:checked')]
        .map((item) => item.value);
      saveQuestionnaireDraft();
      updateSubmitAvailability();
    });
  });
  const professionalReasonNote = document.querySelector("#professional-reason-note");
  if (professionalReasonNote) {
    professionalReasonNote.addEventListener("input", () => {
      state.professionalReasonNote = professionalReasonNote.value;
      document.querySelector("#professional-reason-count").textContent = `${state.professionalReasonNote.length}/100`;
      saveQuestionnaireDraft();
      updateSubmitAvailability();
    });
  }
  const outstandingReason = document.querySelector("#outstanding-contribution-reason");
  if (outstandingReason) {
    outstandingReason.addEventListener("input", () => {
      state.outstandingContributionReason = outstandingReason.value;
      document.querySelector("#outstanding-reason-count").textContent = `${state.outstandingContributionReason.length}/100`;
      saveQuestionnaireDraft();
      updateSubmitAvailability();
    });
  }
  syncAuditFields();
  updateSubmitAvailability();
  elements.calculate.textContent = "提交";
}

async function submitQuestionnaire(event) {
  event.preventDefault();
  if (!await checkServiceHealth()) {
    window.alert(elements.status.title || SERVICE_DISCONNECTED_MESSAGE);
    return;
  }
  if (state.analysisStale) {
    window.alert(SERVICE_RESTARTED_MESSAGE);
    return;
  }
  setBusy(elements.calculate, true, "提交中…");
  try {
    const hasProcessScore = state.analysis && state.selectedExpert.process_average !== null;
    let result;
    if (hasProcessScore) {
      result = await requestJson("/api/score/finalize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          analysis_id: state.analysis.analysis_id,
          project_code: state.selectedExpert.project_code,
          expert_name: state.selectedExpert.expert_name,
          answers: state.answers,
          professional_reason_tags: state.professionalReasonTags,
          professional_reason_note: state.professionalReasonNote,
          outstanding_contribution_reason: state.outstandingContributionReason,
        }),
      });
      if (Array.isArray(result.experts)) {
        state.analysis.experts = result.experts;
      } else {
        const index = state.analysis.experts.findIndex((expert) =>
          expert.project_code === result.project_code && expert.expert_name === result.expert_name,
        );
        state.analysis.experts[index] = result;
      }
      state.selectedExpert = state.analysis.experts.find((expert) =>
        expert.project_code === result.project_code && expert.expert_name === result.expert_name,
      );
      result = state.selectedExpert;
    } else {
      const contribution = await requestJson("/api/score/contribution", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          answers: state.answers,
          professional_reason_tags: state.professionalReasonTags,
          professional_reason_note: state.professionalReasonNote,
          outstanding_contribution_reason: state.outstandingContributionReason,
        }),
      });
      result = {
        ...state.selectedExpert,
        contribution_score: contribution.contribution_score,
        professional_reason_tags: contribution.professional_reason_tags,
        professional_reason_note: contribution.professional_reason_note,
        outstanding_contribution_reason: contribution.outstanding_contribution_reason,
        total_score: null,
        grade: null,
      };
    }
    state.lastResult = result;
    renderExpertNavigation();
    renderResults();
    showPanel(elements.resultPanel);
    activateStep(4);
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(elements.calculate, false);
  }
}

function renderResults() {
  if (!state.analysis) {
    const result = state.lastResult;
    if (!result) {
      elements.result.innerHTML = `<div class="empty-detail"><strong>还没有评分结果</strong><p>导入评审表后，这里会汇总全部评审人的完成状态。</p></div>`;
      return;
    }
    elements.result.innerHTML = `
      <div class="result-identity"><span>${escapeHtml(result.project_code)}</span><h3>${escapeHtml(result.expert_name)}</h3></div>
      <div class="result-equation">
        <div class="total"><span>${result.contribution_score}</span><small>主观分数／40</small></div>
      </div>
      <p class="result-note">本次为独立主观分数评分。尚无客观分数，因此不计算年度总分和等级。</p>`;
    return;
  }
  const experts = state.analysis.experts;
  const rankingPending = experts.some((expert) => expert.status === "已完成" && expert.grade === "待排名");
  elements.result.innerHTML = `
    ${rankingPending ? '<p class="result-note">年度等级将在本批次全体专家的客观分数和主观分数均完成后统一生成。</p>' : ""}
    <table class="results-table">
      <thead><tr><th>评审人</th><th class="numeric">客观分数／60</th><th class="numeric">主观分数／40</th><th class="numeric">年度总分／100</th><th>等级</th><th>状态</th></tr></thead>
      <tbody>${experts.map((expert) => {
        const complete = expert.status === "已完成";
        return `<tr>
          <td>${escapeHtml(expert.expert_name)}</td>
          <td class="numeric">${expert.objective_score}</td>
          <td class="numeric">${complete ? expert.contribution_score : "—"}</td>
          <td class="numeric">${complete ? expert.total_score : "—"}</td>
          <td>${complete ? escapeHtml(expert.grade) : "—"}</td>
          <td class="${complete ? "status-complete" : "status-pending"}">${complete ? "已完成" : "待完成"}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
}

function reset() {
  state.analysis = null;
  state.analysisServiceInstanceId = null;
  state.analysisStale = false;
  state.selectedExpert = null;
  state.answers = {};
  state.questionnaireDrafts = {};
  state.professionalReasonTags = [];
  state.professionalReasonNote = "";
  state.outstandingContributionReason = "";
  state.auditDrafts = {};
  state.lastResult = null;
  state.droppedFiles = [];
  state.selectedReportIndex = 0;
  state.warningsAcknowledged = false;
  state.importJobId = null;
  state.importProgressReports = [];
  elements.file.value = "";
  elements.fileName.textContent = "支持一次上传多个项目，不修改、不覆盖原始评审表";
  elements.projectSummary.textContent = "尚未读取评审表";
  elements.checkCard.classList.add("is-hidden");
  elements.reportList.innerHTML = "";
  renderExpertNavigation();
  clearNotice();
  showPanel(elements.importPanel);
  activateStep(1);
}

function openResultPanel() {
  renderResults();
  showPanel(elements.resultPanel);
  activateStep(4);
}

function navigateStep(step) {
  if (!canNavigate(step)) return;
  if (step === 1) {
    showPanel(elements.importPanel);
    activateStep(1);
  } else if (step === 2) {
    renderAnalysis();
    showPanel(elements.analysisPanel);
    activateStep(2);
  } else if (step === 3) {
    openQuestionnaire();
  } else if (step === 4) {
    openResultPanel();
  }
}

async function checkFeishuAuthorization() {
  try {
    const status = await requestJson("/api/feishu/auth/status");
    state.feishuAuthReady = status.ready === true;
    elements.feishuAuthStatus.textContent = status.ready
      ? `已授权：${status.user_name || "当前飞书用户"}`
      : "首次使用需要完成飞书只读授权";
    elements.authorizeFeishu.classList.toggle("is-hidden", status.ready);
    elements.completeFeishuAuth.classList.add("is-hidden");
    syncServiceActions();
  } catch (error) {
    state.feishuAuthReady = false;
    elements.feishuAuthStatus.textContent = error.message;
    syncServiceActions();
  }
}

async function startFeishuAuthorization() {
  setBusy(elements.authorizeFeishu, true, "正在发起授权…");
  try {
    const authorization = await requestJson("/api/feishu/auth/start", { method: "POST" });
    window.open(authorization.verification_url, "_blank", "noopener");
    state.feishuAuthReady = false;
    elements.feishuAuthStatus.textContent = "请在新窗口完成授权，然后点击右侧按钮";
    elements.completeFeishuAuth.classList.remove("is-hidden");
  } catch (error) {
    setNotice(error.message, "error");
  } finally {
    setBusy(elements.authorizeFeishu, false);
  }
}

async function completeFeishuAuthorization() {
  setBusy(elements.completeFeishuAuth, true, "正在确认授权…");
  try {
    const status = await requestJson("/api/feishu/auth/complete", { method: "POST" });
    state.feishuAuthReady = status.ready === true;
    elements.feishuAuthStatus.textContent = `已授权：${status.user_name || "当前飞书用户"}`;
    elements.authorizeFeishu.classList.add("is-hidden");
    elements.completeFeishuAuth.classList.add("is-hidden");
    clearNotice();
    syncServiceActions();
  } catch (error) {
    setNotice(error.message, "error");
  } finally {
    setBusy(elements.completeFeishuAuth, false);
  }
}

function useDroppedFiles(fileList) {
  const files = [...fileList];
  if (!files.length || files.some((file) => !file.name.toLowerCase().endsWith(".xlsx"))) {
    state.droppedFiles = [];
    elements.fileName.textContent = "支持一次上传多个项目，不修改、不覆盖原始评审表";
    setNotice("请选择或拖入.xlsx格式的TDRX评审报告", "error");
    return;
  }
  state.droppedFiles = files;
  const preview = files.slice(0, 3).map((file) => file.name).join("、");
  elements.fileName.textContent = files.length > 3
    ? `已选择${files.length}份：${preview}等`
    : `已选择${files.length}份：${preview}`;
  clearNotice();
}

document.querySelectorAll(".source-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".source-tab").forEach((item) => item.classList.remove("is-active"));
    tab.classList.add("is-active");
    document.querySelector("#local-pane").classList.toggle("is-hidden", tab.dataset.source !== "local");
    document.querySelector("#feishu-pane").classList.toggle("is-hidden", tab.dataset.source !== "feishu");
    clearNotice();
  });
});

elements.file.addEventListener("change", () => {
  useDroppedFiles(elements.file.files);
});
document.addEventListener("dragover", (event) => event.preventDefault());
document.addEventListener("drop", (event) => event.preventDefault());
elements.uploadBox.addEventListener("dragenter", (event) => {
  event.preventDefault();
  elements.uploadBox.classList.add("is-dragging");
});
elements.uploadBox.addEventListener("dragover", (event) => {
  event.preventDefault();
  elements.uploadBox.classList.add("is-dragging");
});
elements.uploadBox.addEventListener("dragleave", (event) => {
  if (!elements.uploadBox.contains(event.relatedTarget)) elements.uploadBox.classList.remove("is-dragging");
});
elements.uploadBox.addEventListener("drop", (event) => {
  event.preventDefault();
  elements.uploadBox.classList.remove("is-dragging");
  useDroppedFiles(event.dataTransfer.files);
  elements.file.value = "";
});
document.querySelectorAll(".module-tab").forEach((step) => {
  step.addEventListener("click", () => navigateStep(Number(step.dataset.step)));
});
document.querySelector("#start-standalone-questionnaire").addEventListener("click", () => {
  const projectCode = elements.standaloneProjectCode.value.trim();
  const expertName = elements.standaloneExpertName.value.trim();
  if (!projectCode || !expertName) {
    window.alert("请填写项目编码和专家姓名");
    return;
  }
  state.selectedExpert = {
    project_code: projectCode,
    project_name: elements.standaloneProjectName.value.trim(),
    expert_name: expertName,
    process_average: null,
    effective_session_count: 0,
    sessions: [],
  };
  state.professionalReasonTags = [];
  state.professionalReasonNote = "";
  state.outstandingContributionReason = "";
  openQuestionnaire();
});
elements.importLocal.addEventListener("click", importLocal);
elements.importFeishu.addEventListener("click", importFeishu);
elements.authorizeFeishu.addEventListener("click", startFeishuAuthorization);
elements.completeFeishuAuth.addEventListener("click", completeFeishuAuthorization);
elements.warningAcknowledged.addEventListener("change", () => {
  state.warningsAcknowledged = elements.warningAcknowledged.checked;
  elements.continueAnalysis.disabled = !qualityGatePassed();
  activateStep(1);
});
elements.continueAnalysis.addEventListener("click", () => navigateStep(2));
document.querySelector("#restart").addEventListener("click", reset);
elements.calculate.addEventListener("click", submitQuestionnaire);

Promise.all([
  requestJson("/api/health"),
  requestJson("/api/questionnaire"),
]).then(([health, questionnaire]) => {
  if (!applyServiceHealth(health)) return;
  state.questions = questionnaire.questions;
  activateStep(1);
  checkFeishuAuthorization();
}).catch((error) => {
  markServiceUnavailable(error.message || SERVICE_DISCONNECTED_MESSAGE);
});

window.setInterval(checkServiceHealth, SERVICE_HEALTH_INTERVAL_MS);
