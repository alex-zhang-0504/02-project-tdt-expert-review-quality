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
  activeStep: 0,
  workflowMode: null,
  currentBatchId: "",
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
  questionnairePanel: document.querySelector("#questionnaire-panel"),
  resultPanel: document.querySelector("#result-panel"),
  analysisSummary: document.querySelector("#analysis-summary"),
  dimensionOneSearch: document.querySelector("#dimension-one-search"),
  dimensionOneProject: document.querySelector("#dimension-one-project"),
  dimensionOneStage: document.querySelector("#dimension-one-stage"),
  dimensionOneExceptionOnly: document.querySelector("#dimension-one-exception-only"),
  dimensionOneSummary: document.querySelector("#dimension-one-summary"),
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
  evidenceBackdrop: document.querySelector("#evidence-backdrop"),
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
    if (button === elements.calculate) return;
    const authorizationMissing = button === elements.importFeishu && !state.feishuAuthReady;
    const analysisMissing = button === elements.exportDimensionOne
      && (!state.analysis || !qualityGatePassed());
    const submissionsMissing = button === elements.mergeSubmissions
      && !selectedSubmissionFiles().length;
    button.disabled = button.dataset.busy === "true"
      || !state.serviceAvailable
      || authorizationMissing
      || analysisMissing
      || submissionsMissing;
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
  elements.mainContent.classList.toggle("is-wide", step === 0 || step === 2);
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
  return state.activeStep === 3;
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
  if (!state.workflowMode) return false;
  if (step === 1) return state.workflowMode !== "merge";
  if ((state.workflowMode === "manager" || state.workflowMode === "merge") && step >= 3) {
    return false;
  }
  if (!state.analysis) return step === 3 || step === 4;
  return qualityGatePassed();
}

function showPanel(panel) {
  [elements.modePanel, elements.mergePanel, elements.importPanel, elements.analysisPanel, elements.questionnairePanel, elements.resultPanel]
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
    : "方案 1 · 集中评分 · 步骤 1";
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
  if (state.workflowMode === "manager") {
    state.currentBatchId = elements.managerBatchId.value.trim();
  }
  elements.warningAcknowledged.checked = false;
  const reportCount = analysis.reports?.length || 1;
  const candidateCount = analysis.batch_summary?.candidate_count ?? reportCount;
  elements.projectSummary.textContent = `${candidateCount}份候选报告 · ${analysis.sessions.length}场 · ${analysis.experts.length}位评审人`;
  renderBatchSummary();
  renderExpertNavigation();
  renderReportList();
  if (analysis.reports?.length) selectReport(0);
  else renderIssues(analysis.issues, analysis.source_name);
  activateStep(1);
  syncServiceActions();
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
  elements.analysisSummary.textContent = `${analysis.source_name} · 仅纳入已完成TDR3的项目 · ${analysis.experts.length}位评审人`;
  renderDimensionOneControls();
  renderDimensionOneTable();
}

function dimensionOneRows() {
  if (!state.analysis) return [];
  return state.analysis.experts.flatMap((expert) =>
    expert.project_process_scores.map((project) => ({
      expert,
      project,
      sessions: expert.sessions.filter((session) => session.project_code === project.project_code),
    })),
  );
}

function renderDimensionOneControls() {
  const projects = [...new Map(
    dimensionOneRows().map((row) => [row.project.project_code, row.project.project_name]),
  ).entries()].sort(([left], [right]) => left.localeCompare(right, "zh-CN"));
  const selected = elements.dimensionOneProject.value;
  elements.dimensionOneProject.innerHTML = `<option value="">全部项目</option>${projects.map(([code, name]) => (
    `<option value="${escapeHtml(code)}">${escapeHtml(code)} · ${escapeHtml(name)}</option>`
  )).join("")}`;
  if (projects.some(([code]) => code === selected)) elements.dimensionOneProject.value = selected;
  const centralMode = state.workflowMode === "central";
  elements.centralBatchField.classList.toggle("is-hidden", !centralMode);
  elements.exportDimensionOne.textContent = state.workflowMode === "manager"
    ? "导出个人维度一提交表"
    : state.workflowMode === "merge" ? "导出汇总后的维度一结果" : "导出维度一结果";
  syncServiceActions();
}

function filteredDimensionOneRows() {
  const search = elements.dimensionOneSearch.value.trim().toLocaleLowerCase("zh-CN");
  const projectCode = elements.dimensionOneProject.value;
  const stage = elements.dimensionOneStage.value;
  const exceptionOnly = elements.dimensionOneExceptionOnly.checked;
  return dimensionOneRows().filter((row) => {
    if (search && !row.expert.expert_name.toLocaleLowerCase("zh-CN").includes(search)) return false;
    if (projectCode && row.project.project_code !== projectCode) return false;
    if (stage && !row.sessions.some((session) => session.stage === stage)) return false;
    if (exceptionOnly && row.sessions.every((session) => session.total === 50)) return false;
    return true;
  }).sort((left, right) => (
    left.expert.expert_name.localeCompare(right.expert.expert_name, "zh-CN")
      || left.project.project_code.localeCompare(right.project.project_code, "zh-CN")
  ));
}

function dimensionOneScoreCell(session, metric, rowIndex) {
  if (!session) return "<td></td>";
  const value = metric === "total" ? session.total : session[metric].score;
  const label = metric === "attendance" ? "出勤表现"
    : metric === "signoff" ? "结果会签"
      : metric === "opinion" ? "评审意见" : "阶段小计";
  return `<td class="numeric"><button class="score-detail-button" type="button" data-row-index="${rowIndex}" data-stage="${escapeHtml(session.stage)}" data-metric="${metric}" aria-label="查看${escapeHtml(label)}计分依据">${value}</button></td>`;
}

function renderDimensionOneTable() {
  if (!state.analysis) return;
  const rows = filteredDimensionOneRows();
  state.dimensionOneVisibleRows = rows;
  const visibleStages = elements.dimensionOneStage.value
    ? [elements.dimensionOneStage.value]
    : ["TDR1", "TDR2", "TDR3"];
  const projectCount = new Set(rows.map((row) => row.project.project_code)).size;
  const reviewerCount = new Set(rows.map((row) => row.expert.expert_name)).size;
  elements.dimensionOneSummary.innerHTML = `<strong>${reviewerCount}位评审人 · ${projectCount}个项目 · ${rows.length}行</strong>；单击任一分数可查看原文与单元格证据。年度服务贡献基于当前完整批次统一重算。`;
  if (!rows.length) {
    elements.dimensionOneTableWrap.innerHTML = `<div class="dimension-one-empty">当前筛选条件下没有维度一记录。</div>`;
    return;
  }
  const stageHeaders = visibleStages.map((stage) => `<th colspan="4">${stage}</th>`).join("");
  const subHeaders = visibleStages.map(() => (
    '<th>出勤／15</th><th>会签／25</th><th>意见／10</th><th>小计／50</th>'
  )).join("");
  elements.dimensionOneTableWrap.innerHTML = `
    <table class="dimension-one-table">
      <thead>
        <tr>
          <th class="sticky-1" rowspan="2">评审人</th>
          <th class="sticky-2" rowspan="2">项目编码</th>
          <th class="sticky-3" rowspan="2">子任务名称</th>
          ${stageHeaders}
          <th colspan="2">项目汇总</th>
          <th colspan="5">年度服务贡献</th>
          <th colspan="3">年度汇总</th>
          <th class="evidence-sticky" rowspan="2">证据</th>
        </tr>
        <tr>${subHeaders}<th>有效场次</th><th>项目均分／50</th><th>参与项目</th><th>参与分／6</th><th>问题项目</th><th>问题分／4</th><th>服务／10</th><th>过程均分／50</th><th>代理场次</th><th class="objective-sticky">客观分／60</th></tr>
      </thead>
      <tbody>${rows.map((row, rowIndex) => {
        const stageMap = new Map(row.sessions.map((session) => [session.stage, session]));
        const stageCells = visibleStages.map((stage) => {
          const session = stageMap.get(stage);
          return ["attendance", "signoff", "opinion", "total"]
            .map((metric) => dimensionOneScoreCell(session, metric, rowIndex)).join("");
        }).join("");
        return `<tr>
          <td class="sticky-1">${escapeHtml(row.expert.expert_name)}</td>
          <td class="sticky-2">${escapeHtml(row.project.project_code)}</td>
          <td class="sticky-3 project-name-cell"><span class="project-name-tooltip" data-full-name="${escapeHtml(row.project.project_name)}">${escapeHtml(row.project.project_name)}</span></td>
          ${stageCells}
          <td class="numeric">${row.project.session_count}</td>
          <td class="numeric">${row.project.process_average}</td>
          <td class="numeric">${row.expert.participation_project_count}</td>
          <td class="numeric">${row.expert.participation_score}</td>
          <td class="numeric">${row.expert.problem_project_count}</td>
          <td class="numeric">${row.expert.problem_score}</td>
          <td class="numeric">${row.expert.annual_service_score}</td>
          <td class="numeric">${row.expert.process_average}</td>
          <td class="numeric">${row.expert.proxy_session_count}／${row.expert.expected_session_count}</td>
          <td class="numeric objective-sticky">${row.expert.objective_score}</td>
          <td class="evidence-sticky"><button class="row-evidence-button" type="button" data-row-index="${rowIndex}">查看</button></td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
  elements.dimensionOneTableWrap.querySelectorAll(".score-detail-button").forEach((button) => {
    button.addEventListener("click", () => openDimensionOneEvidence(
      Number(button.dataset.rowIndex),
      button.dataset.stage,
      button.dataset.metric,
    ));
  });
  elements.dimensionOneTableWrap.querySelectorAll(".row-evidence-button").forEach((button) => {
    button.addEventListener("click", () => openDimensionOneEvidence(Number(button.dataset.rowIndex)));
  });
}

function openDimensionOneEvidence(rowIndex, stage = "", metric = "") {
  const row = state.dimensionOneVisibleRows[rowIndex];
  if (!row) return;
  const sessions = stage ? row.sessions.filter((session) => session.stage === stage) : row.sessions;
  const metricLabels = {
    attendance: "出勤表现",
    signoff: "结果会签",
    opinion: "评审意见",
    total: "阶段小计",
  };
  elements.evidenceDrawerTitle.textContent = `${row.expert.expert_name} · ${row.project.project_code}`;
  elements.evidenceDrawerContent.innerHTML = sessions.map((session) => {
    const evidence = session.opinion_evidence;
    const scoreDetails = metric && metric !== "total"
      ? `<div><dt>${metricLabels[metric]}</dt><dd>${session[metric].score}分 · ${escapeHtml(session[metric].reason)}</dd></div>`
      : `<div><dt>出勤表现</dt><dd>${session.attendance.score}分 · ${escapeHtml(session.attendance.reason)}</dd></div>
         <div><dt>结果会签</dt><dd>${session.signoff.score}分 · ${escapeHtml(session.signoff.reason)}</dd></div>
         <div><dt>评审意见</dt><dd>${session.opinion.score}分 · ${escapeHtml(session.opinion.reason)}</dd></div>`;
    const sourceCells = evidence.source_cells?.length ? evidence.source_cells : evidence.source_cell ? [evidence.source_cell] : [];
    const sourceTexts = evidence.source_texts?.length ? evidence.source_texts : evidence.source_text ? [evidence.source_text] : [];
    return `<section class="evidence-block"><h4>${escapeHtml(session.stage)} · ${session.total}／50</h4><dl>
      ${scoreDetails}
      <div><dt>技术对象</dt><dd>${escapeHtml(evidence.technical_object || "未识别")}</dd></div>
      <div><dt>专业动作</dt><dd>${escapeHtml(evidence.professional_action || "未识别")}</dd></div>
      <div><dt>具体细节</dt><dd>${escapeHtml(evidence.specific_detail || "未识别")}</dd></div>
      <div><dt>证据位置</dt><dd>${escapeHtml(sourceCells.map((cell) => `${session.sheet_name}!${cell}`).join("、") || "无")}</dd></div>
      <div><dt>原始文本</dt><dd>${escapeHtml(sourceTexts.join(" ｜ ") || "未填写评审意见")}</dd></div>
    </dl></section>`;
  }).join("");
  elements.evidenceBackdrop.classList.remove("is-hidden");
  elements.evidenceDrawer.classList.remove("is-hidden");
}

function closeDimensionOneEvidence() {
  elements.evidenceBackdrop.classList.add("is-hidden");
  elements.evidenceDrawer.classList.add("is-hidden");
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
    elements.submissionFileName.textContent = "只接受由本系统生成的“年度评分提交”Excel";
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
  state.dimensionOneVisibleRows = [];
  elements.file.value = "";
  elements.fileName.textContent = "支持一次上传多个项目，不修改、不覆盖原始评审表";
  elements.projectSummary.textContent = "尚未读取评审表";
  elements.checkCard.classList.add("is-hidden");
  elements.reportList.innerHTML = "";
  closeDimensionOneEvidence();
  renderExpertNavigation();
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
  syncServiceActions();
});
elements.continueAnalysis.addEventListener("click", () => navigateStep(2));
document.querySelector("#restart").addEventListener("click", reset);
elements.calculate.addEventListener("click", submitQuestionnaire);
elements.mergeSubmissions.addEventListener("click", mergeDimensionOneSubmissions);
elements.exportDimensionOne.addEventListener("click", downloadDimensionOne);
[elements.dimensionOneSearch, elements.dimensionOneProject, elements.dimensionOneStage, elements.dimensionOneExceptionOnly]
  .forEach((control) => control.addEventListener(control.tagName === "INPUT" && control.type === "search" ? "input" : "change", renderDimensionOneTable));
document.querySelector("#close-evidence").addEventListener("click", closeDimensionOneEvidence);
elements.evidenceBackdrop.addEventListener("click", closeDimensionOneEvidence);

Promise.all([
  requestJson("/api/health"),
  requestJson("/api/questionnaire"),
]).then(([health, questionnaire]) => {
  if (!applyServiceHealth(health)) return;
  state.questions = questionnaire.questions;
  showPanel(elements.modePanel);
  activateStep(0);
  checkFeishuAuthorization();
}).catch((error) => {
  markServiceUnavailable(error.message || SERVICE_DISCONNECTED_MESSAGE);
});

window.setInterval(checkServiceHealth, SERVICE_HEALTH_INTERVAL_MS);
