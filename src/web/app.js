const SERVICE_HEALTH_INTERVAL_MS = 5000;
const EXPECTED_PROJECT_ID = "tdt-expert-review-quality";
const EXPECTED_BUILD_ID = new URLSearchParams(window.location.search).get("build") || "";
const SERVICE_DISCONNECTED_MESSAGE = "无法连接本地统计服务。请重新双击 start.cmd，并使用新打开的页面重新导入评审表";
const SERVICE_RESTARTED_MESSAGE = "本地统计服务已重新启动，原评审分析已失效。请返回读取评审表并重新导入后再统计";
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
  ["fact_bounds", "检查统计事实"],
];

const state = {
  activeStep: 0,
  workflowMode: null,
  currentBatchId: "",
  analysis: null,
  droppedFiles: [],
  droppedSubmissionFiles: [],
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
  dimensionOneVisibleRows: [],
};

const elements = {
  mainContent: document.querySelector(".main-content"),
  status: document.querySelector("#service-status"),
  notice: document.querySelector("#notice"),
  modePanel: document.querySelector("#mode-panel"),
  mergePanel: document.querySelector("#merge-panel"),
  mergeNotice: document.querySelector("#merge-notice"),
  submissionFiles: document.querySelector("#submission-files"),
  submissionUploadBox: document.querySelector("#submission-upload-box"),
  submissionFileName: document.querySelector("#submission-file-name"),
  expectedManagerCount: document.querySelector("#expected-manager-count"),
  expectedProjectCount: document.querySelector("#expected-project-count"),
  mergeSubmissions: document.querySelector("#merge-submissions"),
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
  importModeLabel: document.querySelector("#import-mode-label"),
  managerMeta: document.querySelector("#manager-meta"),
  managerBatchId: document.querySelector("#manager-batch-id"),
  managerId: document.querySelector("#manager-id"),
  managerName: document.querySelector("#manager-name"),
  managerRevision: document.querySelector("#manager-revision"),
  analysisPanel: document.querySelector("#analysis-panel"),
  analysisSummary: document.querySelector("#analysis-summary"),
  dimensionOneSearch: document.querySelector("#dimension-one-search"),
  dimensionOneStage: document.querySelector("#dimension-one-stage"),
  dimensionOneTableWrap: document.querySelector("#dimension-one-table-wrap"),
  centralBatchField: document.querySelector(".central-batch-field"),
  centralBatchId: document.querySelector("#central-batch-id"),
  exportDimensionOne: document.querySelector("#export-dimension-one"),
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
  evidenceDrawer: document.querySelector("#evidence-drawer"),
  evidenceDrawerTitle: document.querySelector("#evidence-drawer-title"),
  evidenceDrawerContent: document.querySelector("#evidence-drawer-content"),
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
    const authorizationMissing = button === elements.importFeishu && !state.feishuAuthReady;
    const analysisMissing = (button === elements.exportDimensionOne || button.id === "identify-solutions")
      && (!state.analysis || !qualityGatePassed());
    const submissionsMissing = button === elements.mergeSubmissions
      && !selectedSubmissionFiles().length;
    button.disabled = button.dataset.busy === "true"
      || !state.serviceAvailable
      || state.analysisStale
      || authorizationMissing
      || analysisMissing
      || submissionsMissing;
  });
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
    return "当前页面与本地统计服务版本不一致。请关闭此页面，重新双击 start.cmd，并使用新打开的页面";
  }
  if (!health.service_instance_id) {
    return "当前本地统计服务版本过旧。请关闭此页面，重新双击 start.cmd，并使用新打开的页面";
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
    setServiceStatus(`试用版 ${health.version}`, "本地统计服务运行正常", true);
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
  elements.mainContent.classList.toggle("is-wide", step === 0 || step === 2 || step === 3 || step === 4);
  document.querySelectorAll(".module-tab").forEach((item) => {
    const itemStep = Number(item.dataset.step);
    item.classList.toggle("is-active", itemStep === step);
    item.disabled = !canNavigate(itemStep);
    if (itemStep === step) item.setAttribute("aria-current", "step");
    else item.removeAttribute("aria-current");
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
  if (!state.workflowMode) return false;
  if (step === 1) return state.workflowMode !== "merge";
  return (step === 2 || step === 3 || step === 4) && qualityGatePassed();
}

function showPanel(panel) {
  hideSubjectiveTooltip();
  [elements.modePanel, elements.mergePanel, elements.importPanel, elements.analysisPanel, document.querySelector("#subjective-panel"), document.querySelector("#score-statistics-panel")]
    .forEach((item) => item.classList.add("is-hidden"));
  panel.classList.remove("is-hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function selectWorkflow(mode) {
  state.workflowMode = mode;
  state.currentBatchId = "";
  if (mode === "merge") {
    showPanel(elements.mergePanel);
    activateStep(0);
    syncServiceActions();
    return;
  }
  elements.importModeLabel.textContent = mode === "manager"
    ? "方案 2 · 项目经理提交 · 步骤 1"
    : "方案 1 · 集中统计 · 步骤 1";
  elements.managerMeta.classList.toggle("is-hidden", mode !== "manager");
  showPanel(elements.importPanel);
  activateStep(1);
  syncServiceActions();
}

function returnToMode() {
  if (state.analysis && !window.confirm("返回方案选择会清空当前页面中的分析结果，是否继续？")) return;
  clearAnalysisState();
  state.workflowMode = null;
  state.currentBatchId = "";
  showPanel(elements.modePanel);
  activateStep(0);
}

function managerMetadata() {
  const metadata = {
    batch_id: elements.managerBatchId.value.trim(),
    manager_id: elements.managerId.value.trim(),
    manager_name: elements.managerName.value.trim(),
    revision: Number(elements.managerRevision.value),
  };
  if (!metadata.batch_id || !metadata.manager_id || !metadata.manager_name) {
    throw new Error("请先填写年度批次编号、项目经理编号和项目经理姓名");
  }
  if (!Number.isInteger(metadata.revision) || metadata.revision < 1) {
    throw new Error("修订号必须是大于等于1的整数");
  }
  return metadata;
}

function validateWorkflowMetadata() {
  if (state.workflowMode === "manager") managerMetadata();
}

async function importLocal() {
  const button = elements.importLocal;
  clearNotice();
  setBusy(button, true, "正在读取与检查…");
  try {
    validateWorkflowMetadata();
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
    validateWorkflowMetadata();
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
  state.selectedReportIndex = 0;
  state.warningsAcknowledged = false;
  if (state.workflowMode === "manager") {
    state.currentBatchId = elements.managerBatchId.value.trim();
  }
  elements.warningAcknowledged.checked = false;
  const reportCount = analysis.reports?.length || 1;
  const candidateCount = analysis.batch_summary?.candidate_count ?? reportCount;
  elements.projectSummary.textContent = `${candidateCount}份候选报告 · ${analysis.sessions.length}场 · ${analysis.experts.length}位评审人`;
  renderBatchSummary();
  renderReportList();
  if (analysis.reports?.length) selectReport(0);
  else renderIssues(analysis.issues, analysis.source_name);
  activateStep(1);
  syncServiceActions();
}

function startProgressDisplay(sourceNames = []) {
  stopProgressPlayback();
  state.analysis = null;
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
      <span class="report-progress-name"><strong class="inline-name-expand">${escapeHtml(report.source_name)}</strong><small class="report-progress-status">${escapeHtml(summaryText)}</small></span>
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

function renderIssues(issues, reportName = "") {
  const batchIssues = (state.analysis?.issues || []).filter((issue) => (
    issue.requires_confirmation
    || (state.analysis?.batch_summary && issue.code.startsWith("feishu_folder_"))
  ));
  const visibleIssues = issues.filter((issue) => issue.severity !== "info");
  batchIssues.forEach((issue) => {
    const alreadyVisible = visibleIssues.some((visibleIssue) => (
      visibleIssue === issue
      || (issue.confirmation_key && visibleIssue.confirmation_key === issue.confirmation_key)
    ));
    if (issue.severity !== "info" && !alreadyVisible) visibleIssues.push(issue);
  });
  const errors = visibleIssues.filter((issue) => issue.severity === "error").length;
  const warnings = visibleIssues.filter((issue) => issue.severity === "warning").length;
  const aggregate = validationCounts();
  const label = reportName ? `“${reportName}”` : "评审报告";
  if (!visibleIssues.length) {
    elements.checkTitle.textContent = `${label}检查完成`;
    elements.checkState.textContent = "检查通过";
    elements.checkState.className = "check-state is-ok";
    elements.issueSummary.innerHTML = `<p><strong>未发现格式错误或检查提醒。</strong>可以继续进入统计。</p>`;
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
          : issue.source_name || "工作簿";
        const expert = issue.expert_name ? `；专家：${issue.expert_name}` : "";
        const severityLabel = issue.severity === "error" ? "错误" : "提醒";
        const relatedLocations = issue.related_locations?.length
          ? `<small class="issue-related-locations"><strong>表格位置：</strong>${issue.related_locations.map((location, index) => `<span>${index + 1}．${escapeHtml(location)}</span>`).join("")}</small>`
          : "";
        const confirmation = issue.code === "reviewer_name_similarity" && issue.confirmation_key
          ? `<button class="secondary-button issue-confirm-button" type="button" data-confirm-reviewer-names="${escapeHtml(issue.confirmation_key)}">确认均为不同人员</button>`
          : "";
        return `<li class="issue-item ${issue.severity}"><span class="severity">${severityLabel}</span><span class="issue-location">${escapeHtml(location)}</span><span class="issue-content">${escapeHtml(issue.message + expert)}${relatedLocations}${confirmation}</span></li>`;
      }).join("")}</ul>`;
  }
  elements.issueSummary.querySelectorAll("[data-confirm-reviewer-names]").forEach((button) => {
    button.addEventListener("click", () => confirmReviewerNamesDistinct(button));
  });
  elements.warningConfirm.classList.toggle("is-hidden", aggregate.errors > 0 || aggregate.warnings === 0);
  elements.continueAnalysis.disabled = !qualityGatePassed();
  activateStep(1);
}

async function confirmReviewerNamesDistinct(button) {
  const confirmationKey = button.dataset.confirmReviewerNames;
  if (!state.analysis || !confirmationKey) return;
  button.disabled = true;
  button.textContent = "正在确认…";
  try {
    const analysis = await requestJson("/api/analysis/confirm-reviewer-names-distinct", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        analysis_id: state.analysis.analysis_id,
        confirmation_key: confirmationKey,
      }),
    });
    state.analysis = analysis;
    state.warningsAcknowledged = false;
    elements.warningAcknowledged.checked = false;
    renderBatchSummary();
    renderReportList();
    if (analysis.reports?.length) selectReport(state.selectedReportIndex);
    else renderIssues(analysis.issues, analysis.source_name);
    syncServiceActions();
  } catch (error) {
    button.disabled = false;
    button.textContent = "确认均为不同人员";
    setNotice(error.message, "error");
  }
}

function normalizedReviewerSearch(value) {
  return value.toLocaleLowerCase("zh-CN").replace(/\s+/g, "");
}

function isSearchSubsequence(search, target) {
  let searchIndex = 0;
  for (const character of target) {
    if (character === search[searchIndex]) searchIndex += 1;
    if (searchIndex === search.length) return true;
  }
  return search.length === 0;
}

function reviewerMatchesSearch(expert, search) {
  if (!search) return true;
  return [expert.expert_name, expert.expert_name_pinyin, expert.expert_name_initials]
    .filter(Boolean)
    .some((candidate) => isSearchSubsequence(search, normalizedReviewerSearch(candidate)));
}

async function downloadDimensionOne() {
  if (!state.analysis || !qualityGatePassed()) return;
  let metadata;
  let packageKind;
  if (state.workflowMode === "manager") {
    metadata = managerMetadata();
    packageKind = "manager_submission";
  } else {
    const batchId = state.workflowMode === "merge"
      ? state.currentBatchId
      : elements.centralBatchId.value.trim();
    if (!batchId) {
      window.alert("请填写年度批次编号");
      return;
    }
    metadata = { batch_id: batchId, manager_id: "", manager_name: "", revision: 1 };
    packageKind = "annual_result";
  }
  setBusy(elements.exportDimensionOne, true, "正在生成Excel…");
  try {
    const response = await fetch("/api/export/dimension-one", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        analysis_id: state.analysis.analysis_id,
        package_kind: packageKind,
        ...metadata,
      }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `导出失败（${response.status}）`);
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    const filename = encodedName ? decodeURIComponent(encodedName) : "维度1年度结果.xlsx";
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    window.alert(error.message);
  } finally {
    setBusy(elements.exportDimensionOne, false);
  }
}

function selectedSubmissionFiles() {
  return state.droppedSubmissionFiles.length
    ? state.droppedSubmissionFiles
    : [...(elements.submissionFiles?.files || [])];
}

function setMergeNotice(message, type = "info") {
  elements.mergeNotice.textContent = message;
  elements.mergeNotice.className = `notice notice-${type}`;
}

function useSubmissionFiles(fileList) {
  const files = [...fileList];
  if (!files.length || files.some((file) => !file.name.toLowerCase().endsWith(".xlsx"))) {
    state.droppedSubmissionFiles = [];
    elements.submissionFileName.textContent = "只接受由本系统生成的“四维事实提交”Excel";
    setMergeNotice("请选择系统导出的.xlsx维度1提交表", "error");
    syncServiceActions();
    return;
  }
  state.droppedSubmissionFiles = files;
  const preview = files.slice(0, 3).map((file) => file.name).join("、");
  elements.submissionFileName.textContent = files.length > 3
    ? `已选择${files.length}份：${preview}等`
    : `已选择${files.length}份：${preview}`;
  elements.mergeNotice.className = "notice is-hidden";
  syncServiceActions();
}

async function mergeDimensionOneSubmissions() {
  const files = selectedSubmissionFiles();
  if (!files.length) return;
  const expectedManagers = Number(elements.expectedManagerCount.value);
  const projectText = elements.expectedProjectCount.value.trim();
  const expectedProjects = projectText ? Number(projectText) : null;
  if (!Number.isInteger(expectedManagers) || expectedManagers < 1) {
    setMergeNotice("预计项目经理人数必须是大于等于1的整数", "error");
    return;
  }
  if (expectedProjects !== null && (!Number.isInteger(expectedProjects) || expectedProjects < 1)) {
    setMergeNotice("预计项目数必须是大于等于1的整数", "error");
    return;
  }
  setBusy(elements.mergeSubmissions, true, "正在校验与汇总…");
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file, file.name));
  formData.append("expected_manager_count", String(expectedManagers));
  if (expectedProjects !== null) formData.append("expected_project_count", String(expectedProjects));
  try {
    const analysis = await requestJson("/api/import/dimension-one-submissions", {
      method: "POST",
      body: formData,
    });
    await receiveAnalysis(analysis);
    const errors = analysis.issues.filter((issue) => issue.severity === "error");
    if (errors.length) {
      setMergeNotice(errors.map((issue) => issue.message).join("；"), "error");
      showPanel(elements.mergePanel);
      activateStep(0);
      return;
    }
    state.warningsAcknowledged = true;
    state.currentBatchId = analysis.source_name.split(" · ")[0];
    renderAnalysis();
    showPanel(elements.analysisPanel);
    activateStep(2);
  } catch (error) {
    setMergeNotice(error.message, "error");
  } finally {
    setBusy(elements.mergeSubmissions, false);
  }
}

function clearAnalysisState() {
  state.analysis = null;
  state.analysisServiceInstanceId = null;
  state.analysisStale = false;
  state.droppedFiles = [];
  state.selectedReportIndex = 0;
  state.warningsAcknowledged = false;
  state.importJobId = null;
  state.importProgressReports = [];
  state.dimensionOneVisibleRows = [];
  elements.file.value = "";
  elements.fileName.textContent = "支持一次上传多个项目，不修改、不覆盖原始评审表";
  elements.projectSummary.textContent = "尚未读取评审表";
  elements.checkCard.classList.add("is-hidden");
  elements.reportList.innerHTML = "";
  closeDimensionOneEvidence();
  clearNotice();
}

function reset() {
  clearAnalysisState();
  if (state.workflowMode === "merge") {
    showPanel(elements.mergePanel);
    activateStep(0);
  } else {
    showPanel(elements.importPanel);
    activateStep(1);
  }
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
    openSubjective();
  } else if (step === 4) {
    openScoreStatistics();
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

document.querySelector("#choose-central").addEventListener("click", () => selectWorkflow("central"));
document.querySelector("#choose-manager").addEventListener("click", () => selectWorkflow("manager"));
document.querySelector("#choose-merge").addEventListener("click", () => selectWorkflow("merge"));
document.querySelectorAll(".back-to-mode").forEach((button) => {
  button.addEventListener("click", returnToMode);
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
elements.submissionFiles.addEventListener("change", () => {
  useSubmissionFiles(elements.submissionFiles.files);
});
elements.submissionUploadBox.addEventListener("dragenter", (event) => {
  event.preventDefault();
  elements.submissionUploadBox.classList.add("is-dragging");
});
elements.submissionUploadBox.addEventListener("dragover", (event) => {
  event.preventDefault();
  elements.submissionUploadBox.classList.add("is-dragging");
});
elements.submissionUploadBox.addEventListener("dragleave", (event) => {
  if (!elements.submissionUploadBox.contains(event.relatedTarget)) {
    elements.submissionUploadBox.classList.remove("is-dragging");
  }
});
elements.submissionUploadBox.addEventListener("drop", (event) => {
  event.preventDefault();
  elements.submissionUploadBox.classList.remove("is-dragging");
  useSubmissionFiles(event.dataTransfer.files);
  elements.submissionFiles.value = "";
});
document.querySelectorAll(".module-tab").forEach((step) => {
  step.addEventListener("click", () => navigateStep(Number(step.dataset.step)));
});
elements.importLocal.addEventListener("click", importLocal);
elements.importFeishu.addEventListener("click", importFeishu);
elements.authorizeFeishu.addEventListener("click", startFeishuAuthorization);
elements.completeFeishuAuth.addEventListener("click", completeFeishuAuthorization);
elements.warningAcknowledged.addEventListener("change", () => {
  state.warningsAcknowledged = elements.warningAcknowledged.checked;
  elements.continueAnalysis.disabled = !qualityGatePassed();
  activateStep(1);
  syncServiceActions();
});
elements.continueAnalysis.addEventListener("click", () => navigateStep(2));
document.querySelector("#restart").addEventListener("click", reset);
elements.mergeSubmissions.addEventListener("click", mergeDimensionOneSubmissions);
elements.exportDimensionOne.addEventListener("click", downloadDimensionOne);
[elements.dimensionOneSearch, elements.dimensionOneStage]
  .forEach((control) => control.addEventListener(control.tagName === "INPUT" && control.type === "search" ? "input" : "change", renderDimensionOneTable));
document.querySelector("#close-evidence").addEventListener("click", closeDimensionOneEvidence);

initializeFactsUI();
initializeSubjectiveUI();
initializeScoreStatisticsUI();
requestJson("/api/health").then((health) => {
  if (!applyServiceHealth(health)) return;
  showPanel(elements.modePanel);
  activateStep(0);
  checkFeishuAuthorization();
}).catch((error) => {
  markServiceUnavailable(error.message || SERVICE_DISCONNECTED_MESSAGE);
});

window.setInterval(checkServiceHealth, SERVICE_HEALTH_INTERVAL_MS);
