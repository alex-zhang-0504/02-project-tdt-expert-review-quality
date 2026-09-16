const FACT_METRICS = [
  ["attendance_rate", "出勤率", "attended", "expected", "实参场次÷应参场次×100％", "实参包含按原规则归属的代理参评。"],
  ["signoff_rate", "会签率", "signed", "expected", "已填会签场次÷应参场次×100％", "会签结果非空且不是横杠即计入，以项目经理填写为准。"],
  ["opinion_rate", "意见提出率", "opinions", "attended", "意见总条数÷实参场次×100％", "同场多条意见逐条累计，允许超过100％。"],
];
const PROXY_METRIC = ["proxy_rate", "代理情况", "proxy", "expected", "代理场次÷应参场次×100％", "跨全部阶段统计，代理事实归原评审人。"];
const FACT_COLUMNS = [
  ["expected", "应参场次", 72, "应参<br>场次"], ["attended", "实参场次", 72, "实参<br>场次"],
  ["attendance_rate", "出勤率", 80], ["signed", "已会签场次", 84, "已会签<br>场次"],
  ["signoff_rate", "会签率", 80], ["opinions", "意见条数", 72, "意见<br>条数"],
  ["opinion_rate", "意见提出率", 88, "意见<br>提出率"], ["solutions", "含对策意见条数", 100, "含对策<br>意见条数"],
];
function visibleFactGroups(value) {
  return value === "overall" ? ["全部阶段"] : ["TDR1", "TDR2", "TDR3"].includes(value) ? [value] : ["TDR1", "TDR2", "TDR3"];
}
function factCellText(stats, key) {
  if (stats.expected === 0) return "—";
  if (key === "proxy_rate") return stats.proxy + "/" + stats.expected;
  if (stats.unknown && ["attendance_rate", "opinion_rate"].includes(key)) return "待确认";
  if (key.endsWith("_rate")) return percent(stats[key]);
  if (key === "solutions" && stats.pending) return "待识别";
  return String(stats[key]);
}
function subtaskDisplayName(name) {
  const separator = name.indexOf("-");
  return separator < 0 ? name : name.slice(separator + 1).trim() || name;
}
let evidenceReturnFocus = null;
let evidenceExpertName = "";
let factsMutating = false;

function percent(value) {
  return value === null || value === undefined ? "—" : Number(value).toLocaleString("zh-CN", {maximumFractionDigits: 2}) + "％";
}

function renderAnalysis() {
  if (!state.analysis) return;
  elements.centralBatchField.classList.toggle("is-hidden", state.workflowMode !== "central");
  elements.exportDimensionOne.textContent = state.workflowMode === "manager" ? "导出个人提交表" : "导出统计结果";
  renderDimensionOneTable();
  syncServiceActions();
}

function renderDimensionOneTable() {
  if (!state.analysis) return;
  const query = normalizedReviewerSearch(elements.dimensionOneSearch.value);
  const experts = state.analysis.experts.filter(e => reviewerMatchesSearch(e, query));
  state.dimensionOneVisibleRows = experts;
  const groups = visibleFactGroups(elements.dimensionOneStage.value);
  elements.analysisSummary.textContent = experts.length + "位评审人 · 点击数字查看公式，详情查看项目与意见证据。";
  const pending = state.analysis.experts.reduce((n, e) => n + e.overall.pending, 0);
  const totalOpinions = state.analysis.experts.reduce((n, e) => n + e.overall.opinions, 0);
  const unresolvedCount = state.analysis.experts.reduce((n, e) => n + e.overall.suspected, 0);
  document.querySelector("#facts-ai-status").textContent = `已识别${totalOpinions - pending}／${totalOpinions}条 · 疑似待确认${unresolvedCount}条`;
  if (!experts.length) {
    elements.dimensionOneTableWrap.innerHTML = '<div class="dimension-one-empty">没有匹配的评审人。</div>';
    return;
  }
  const metricCell = (value, row, group, metric) => '<td class="numeric"><button type="button" class="fact-number" data-row="' + row
    + '" data-group="' + group + '" data-metric="' + metric[0] + '" aria-label="' + metric[1] + '计算方法">'
    + factCellText(value, metric[0]) + (metric[0] === 'solutions' && value.suspected ? '<span class="solution-alert" title="' + value.suspected + '条疑似待确认，尚未计入" aria-label="' + value.suspected + '条疑似待确认">!</span>' : '') + '</button>'
    + (metric[0] === 'attended' && value.unknown ? '<small class="fact-hint">' + value.unknown + '场待确认</small>' : '')
    + '</td>';
  elements.dimensionOneTableWrap.innerHTML = '<table class="dimension-one-table facts-table" style="--dimension-table-width:'
    + (408 + groups.length * FACT_COLUMNS.reduce((n, c) => n + c[2], 0)) + 'px"><colgroup><col style="width:120px">'
    + groups.map(() => FACT_COLUMNS.map(c => '<col style="width:' + c[2] + 'px">').join("")).join("")
    + '<col style="width:112px"><col style="width:88px"><col style="width:88px"></colgroup><thead><tr>'
    + '<th class="sticky-1" rowspan="2">评审人</th>'
    + groups.map(g => '<th colspan="8" scope="colgroup">' + g + '</th>').join("")
    + '<th rowspan="2">总参与<br>评审场次</th><th rowspan="2">代理情况</th><th class="evidence-sticky" rowspan="2">详情</th></tr><tr>'
    + groups.map(() => FACT_COLUMNS.map(m => '<th scope="col" aria-label="' + m[1] + '">' + (m[3] || m[1]) + '</th>').join("")).join("")
    + '</tr></thead><tbody>'
    + experts.map((e, row) => '<tr><td class="sticky-1">' + escapeHtml(e.expert_name) + '</td>'
      + groups.map(g => FACT_COLUMNS.map(m => metricCell(g === "全部阶段" ? e.overall : e.stages[g], row, g, m)).join("")).join("")
      + '<td class="numeric"><button type="button" class="fact-number" data-participation="' + row + '">'
      + (e.overall.unknown ? '待确认' : e.overall.attended + '场') + '</button></td>'
      + metricCell(e.overall, row, "全部阶段", PROXY_METRIC)
      + '<td class="evidence-sticky"><button class="row-evidence-button" type="button" data-details="' + row + '">详情查看</button></td></tr>').join("")
    + '</tbody></table>';
  makeTableScrollable(elements.dimensionOneTableWrap);
  elements.dimensionOneTableWrap.querySelectorAll("[data-metric]").forEach(button => button.addEventListener("click", () => {
    const expert = experts[Number(button.dataset.row)];
    const metric = [...FACT_METRICS, PROXY_METRIC].find(m => m[0] === button.dataset.metric);
    const stats = button.dataset.group === "全部阶段" ? expert.overall : expert.stages[button.dataset.group];
    if (metric) showFormula(expert.expert_name, button.dataset.group, metric, stats);
    else showFactCount(expert.expert_name, button.dataset.group, button.dataset.metric, stats);
  }));
  elements.dimensionOneTableWrap.querySelectorAll("[data-participation]").forEach(button => button.addEventListener("click", () => {
    const expert = experts[Number(button.dataset.participation)];
    document.querySelector("#formula-title").textContent = expert.expert_name + " · 评审参与度";
    document.querySelector("#formula-body").innerHTML = '<p>本批次全部阶段有效参评共' + expert.overall.attended
      + '场，出勤待确认' + expert.overall.unknown + '场。按项目编码＋阶段去重，代理归原评审人，单阶段筛选不改变此范围。</p><p>达到3场后，按完整批次前两个不同数量档计5／3分，其余0分，并列同分；分数在第四模块计算。</p>'
      + '<ul>' + expert.sessions.filter(s => s.attended === true).map(s => '<li>'
        + escapeHtml(s.project_name + '／' + s.project_code + '／' + s.stage) + '</li>').join('') + '</ul>';
    document.querySelector("#formula-dialog").showModal();
  }));
  elements.dimensionOneTableWrap.querySelectorAll("[data-details]").forEach(button => button.addEventListener("click", () => {
    evidenceReturnFocus = button;
    openDimensionOneEvidence(experts[Number(button.dataset.details)].expert_name);
  }));
}

function showFactCount(name, stage, key, stats) {
  const column = FACT_COLUMNS.find(c => c[0] === key);
  const notes = {
    expected: "本阶段报告评审人名单中，应参加的唯一评审场次数。",
    attended: "已确认实际参评场次，包含按原规则归属的代理参评；待确认出勤另行标示。",
    signed: "会签结果非空且不是横杠的场次，以项目经理填写为准。",
    opinions: "按原摘取、拆条、归属和去重规则累计意见条数，不按场次折为一条。",
    solutions: "纳入统计的含对策意见条数，疑似未确认不计入；识别未完成时不显示最终数量。",
  };
  document.querySelector("#formula-title").textContent = name + " · " + stage + " · " + column[1];
  document.querySelector("#formula-body").innerHTML = '<p class="formula-value">' + factCellText(stats, key)
    + '</p><p>' + notes[key] + '</p>'
    + (key === "solutions" ? '<p>当前已纳入' + stats.solutions + '条；待识别' + stats.pending + '条；疑似' + stats.suspected + '条。</p>' : '');
  document.querySelector("#formula-dialog").showModal();
}
function showFormula(name, stage, metric, stats) {
  const dialog = document.querySelector("#formula-dialog");
  document.querySelector("#formula-title").textContent = name + " · " + stage + " · " + metric[1];
  let note = metric[5];
  if (metric[0] === "proxy_rate") note = "主表" + stats.proxy + "/" + stats.expected
    + "表示代理" + stats.proxy + "场／应参" + stats.expected + "场。" + note;
  if (!stats[metric[3]]) note += " 分母为0，显示“—”。";
  if ((metric[0] === "attendance_rate" || metric[0] === "opinion_rate") && stats.unknown)
    note += " 有" + stats.unknown + "场出勤状态无法判断，暂不计算比率。";
  document.querySelector("#formula-body").innerHTML = '<p>' + escapeHtml(metric[4]) + '</p><p class="formula-value">'
    + stats[metric[2]] + ' ÷ ' + stats[metric[3]] + ' × 100％'
    + (stats[metric[0]] === null ? '；当前显示：—' : ' ＝ ' + percent(stats[metric[0]]))
    + '</p><p>' + escapeHtml(note) + '</p>';
  dialog.showModal();
}

function openDimensionOneEvidence(name) {
  const expert = state.analysis?.experts.find(e => e.expert_name === name);
  if (!expert) return;
  if (!elements.evidenceDrawer.open) evidenceReturnFocus = document.activeElement;
  evidenceExpertName = name;
  const projects = [...new Set(expert.sessions.map(s => s.project_code))];
  elements.evidenceDrawerTitle.textContent = name + " · 评审详情";
  elements.evidenceDrawerContent.innerHTML = projects.map((code, projectIndex) => {
    const sessions = expert.sessions.filter(s => s.project_code === code);
    return '<section class="review-project"><h3>' + (projectIndex + 1) + '　'
      + escapeHtml(subtaskDisplayName(sessions[0].project_name)) + '　｜　项目编码：' + escapeHtml(code) + '</h3>'
      + ['TDR1', 'TDR2', 'TDR3'].map(stage => {
        const stageSessions = sessions.filter(s => s.stage === stage);
        const imported = (state.analysis.sessions || []).some(s => s.project_code === code && s.stage === stage)
          || state.analysis.experts.some(e => e.sessions.some(s => s.project_code === code && s.stage === stage));
        return '<section class="review-stage" data-stage="' + stage + '">'
          + (stageSessions.length ? stageSessions.map(session => '<h4>' + stage + '　｜　参评：'
            + escapeHtml(session.attendance || (session.attended === true ? '已参加' : session.attended === false ? '未参加' : '待确认'))
            + (session.proxy_name ? '（代理：' + escapeHtml(session.proxy_name) + '）' : '')
            + '　｜　会签：' + escapeHtml(session.signoff || '未填写') + '</h4>'
            + (session.opinions.length ? session.opinions.map((o, i) => renderOpinion(o, session, i)).join('')
              : '<p>评审意见：无</p>')).join('')
            : '<h4>' + stage + '　｜　' + (imported ? '未列入本阶段评审名单' : '本批次未导入该阶段报告') + '</h4>')
          + '</section>';
      }).join('') + '</section>';
  }).join('');
  elements.evidenceDrawerContent.querySelectorAll("[data-opinion]").forEach(button => button.addEventListener("click", () =>
    selectSolution(button.dataset.opinion, button.dataset.include === "null" ? null : button.dataset.include === "true")));
  if (!elements.evidenceDrawer.open) elements.evidenceDrawer.showModal();

}

function makeTableScrollable(scroller) {
  let frame = scroller.parentElement;
  if (!frame.classList.contains('table-scroll-frame')) {
    frame = document.createElement('div');
    frame.className = 'table-scroll-frame';
    scroller.before(frame);
    frame.append(scroller);
    scroller.classList.add('table-scroll-content');
    const bar = document.createElement('div');
    bar.className = 'table-x-scroll';
    bar.tabIndex = 0;
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', '表格横向滚动条');
    bar.append(document.createElement('div'));
    frame.append(bar);
    bar.addEventListener('scroll', () => { scroller.scrollLeft = bar.scrollLeft; });
    scroller.addEventListener('scroll', () => { bar.scrollLeft = scroller.scrollLeft; });
  }
  const bar = frame.querySelector('.table-x-scroll');
  bar.hidden = scroller.scrollWidth <= scroller.clientWidth;
  bar.firstElementChild.style.width = (scroller.scrollWidth + bar.clientWidth - scroller.clientWidth) + 'px';
  bar.scrollLeft = scroller.scrollLeft;
}

window.addEventListener('resize', () => {
  document.querySelectorAll('.table-scroll-content').forEach(makeTableScrollable);
});
document.addEventListener('toggle', event => {
  if (event.target.open) event.target.querySelectorAll('.table-scroll-content').forEach(makeTableScrollable);
}, true);

function renderOpinion(o, session, index) {
  const labels = {pending: "待AI识别", yes: "包含", no: "不包含", suspected: "疑似"};
  const unresolved = o.ai_status === 'suspected' && o.included == null;
  const selection = unresolved ? null : (o.included ?? (o.ai_status === 'yes'));
  const excerpt = o.excerpt === o.text ? "见上述意见" : o.excerpt;
  let html = '<article class="opinion-record' + (unresolved ? ' needs-confirmation' : '') + '"><p class="opinion-text"><strong>意见' + (index + 1) + '：</strong>' + escapeHtml(o.text) + '</p>';
  html += '<p class="opinion-text"><strong>对策：</strong>' + labels[o.ai_status]
    + (excerpt ? '（' + escapeHtml(excerpt) + '）' : '')
    + (o.ai_status !== 'pending' ? ' · ' + (unresolved ? '待人工确认，暂未计入' : selection ? '计入统计' : '不计入统计') : '') + '</p>';
  if (o.reason) html += '<p>判定说明：' + escapeHtml(o.reason) + '</p>';
  if (o.ai_status !== "pending") html += '<div class="solution-actions" aria-label="是否计入对策统计">'
    + [true, false].map(include => '<button type="button" class="secondary-button" data-opinion="' + o.opinion_id
      + '" data-include="' + include + '" aria-pressed="' + (selection === include)
      + '">' + (include ? '计入统计' : '不计入统计') + '</button>').join("") + '</div>';
  if (o.audit.length) {
    const latest = o.audit[o.audit.length - 1];
    const date = new Date(latest.at);
    const time = Number.isNaN(date.getTime()) ? '时间不可用' : date.toLocaleString('zh-CN', {hour12: false});
    html += '<p class="muted">最近修改：' + escapeHtml(time) + '</p>';
  }
  if (o.rule_version) html += '<p class="muted">识别版本：' + escapeHtml(o.rule_version) + '</p>';
  return html + '</article>';
}

async function selectSolution(opinionId, included) {
  if (factsMutating || !await checkServiceHealth() || state.analysisStale) return;
  factsMutating = true;
  const scroll = elements.evidenceDrawerContent.scrollTop;
  const horizontal = elements.dimensionOneTableWrap.scrollLeft;
  elements.evidenceDrawerContent.querySelectorAll("button").forEach(b => b.disabled = true);
  try {
    state.analysis = await requestJson("/api/facts/solution-selection", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({analysis_id: state.analysis.analysis_id, opinion_id: opinionId, included}),
    });
    renderDimensionOneTable();
    if (state.activeStep === 3) {
      renderSubjectiveEditor();
      evidenceReturnFocus = document.querySelector("#subjective-facts");
    } else if (state.activeStep === 4) {
      await refreshScoreStatistics();
      evidenceReturnFocus = document.querySelector("#refresh-score-statistics");
    }
  } catch (error) { window.alert(error.message); }
  finally {
    factsMutating = false;
    if (!elements.evidenceDrawer.open) return;
    openDimensionOneEvidence(evidenceExpertName);
    elements.evidenceDrawerContent.scrollTop = scroll;
    elements.dimensionOneTableWrap.scrollLeft = horizontal;
    elements.evidenceDrawerContent.querySelector('[data-opinion="' + opinionId + '"][data-include="' + included + '"]')?.focus({preventScroll: true});
  }
}

function closeDimensionOneEvidence() {
  if (!elements.evidenceDrawer.open) return;
  elements.evidenceDrawer.close();
  if (evidenceReturnFocus?.isConnected) evidenceReturnFocus.focus();
  else elements.dimensionOneTableWrap.querySelector('[data-details]')?.focus();
}

function initializeFactsUI() {
elements.evidenceDrawer.addEventListener("cancel", event => {
  event.preventDefault();
  closeDimensionOneEvidence();
});
document.querySelector("#identify-solutions").addEventListener("click", async () => {
  if (!await checkServiceHealth() || state.analysisStale || !qualityGatePassed()) return;
  window.reviewAI.start();
});
document.querySelector("#close-formula").addEventListener("click", () => document.querySelector("#formula-dialog").close());

}
