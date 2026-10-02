const FACT_METRICS = [
  ["attendance_rate", "出勤率", "attended", "expected", "实参场次÷应参场次×100％", "实参包含按原规则归属的代理参评。"],
  ["signoff_rate", "会签率", "signed", "expected", "已填会签场次÷应参场次×100％", "会签结果非空且不是横杠即计入，以技术项目经理填写为准。"],
  ["opinion_average", "意见提出平均数", "opinions", "attended", "意见总条数÷实参场次", "同场多条意见逐条累计，每场可超过1条。"],
];
const PROXY_METRIC = ["proxy_rate", "代理情况", "proxy", "expected", "代理场次÷应参场次×100％", "跨全部阶段统计，代理事实归原评审人。"];
const FACT_COLUMNS = [
  ["expected", "应参场次", 72, "应参<br>场次"], ["attended", "实参场次", 72, "实参<br>场次"],
  ["attendance_rate", "出勤率", 80], ["signed", "已会签场次", 84, "已会签<br>场次"],
  ["signoff_rate", "会签率", 80], ["opinions", "意见条数", 72, "意见<br>条数"],
  ["opinion_average", "意见提出平均数", 88, "意见提出<br>平均数"], ["solutions", "含对策意见条数", 100, "含对策<br>意见条数"],
];
function visibleFactGroups(value) {
  return value === "overall" ? ["全部阶段"] : ["TDR1", "TDR2", "TDR3"].includes(value) ? [value] : ["TDR1", "TDR2", "TDR3"];
}
function factCellText(stats, key) {
  if (stats.expected === 0) return "—";
  if (key === "proxy_rate") return stats.proxy + "/" + stats.expected;
  if (stats.unknown && ["attendance_rate", "opinion_average"].includes(key)) return "待确认";
  if (key === "opinion_average") return stats[key] == null ? "—" : Number(stats[key]).toFixed(1);
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
  document.querySelector('#personal-scope').hidden=!state.analysis.assessment?.personal_scope;
  elements.exportDimensionOne.textContent = "导出评价结果";
  renderDimensionOneTable();
  syncServiceActions();
}

function renderDimensionOneTable() {
  if (!state.analysis) return;
  const experts = objectiveReviewers().filter(e => objectiveReviewerVisible(e.expert_name));
  state.dimensionOneVisibleRows = experts;
  const groups = visibleFactGroups(elements.dimensionOneStage.value);
  elements.analysisSummary.textContent = experts.length + "位评审人";
  window.reviewAI?.refresh();
  const metricCell = (value, row, group, metric) => '<td class="numeric">'
    + (metric[0] === 'proxy_rate' ? '<button type="button" class="fact-number" data-proxy="' + row + '" aria-label="代理情况代理人清单">' : '<span>')
    + factCellText(value, metric[0]) + (metric[0] === 'solutions' && value.suspected ? '<span class="solution-alert" title="' + value.suspected + '条疑似待确认，尚未计入" aria-label="' + value.suspected + '条疑似待确认">!</span>' : '')
    + (metric[0] === 'proxy_rate' ? '</button>' : '</span>')
    + (metric[0] === 'attended' && value.unknown ? '<small class="fact-hint">' + value.unknown + '场待确认</small>' : '') + '</td>';
  elements.dimensionOneTableWrap.innerHTML = '<table class="dimension-one-table facts-table" style="--dimension-table-width:'
    + (408 + groups.length * FACT_COLUMNS.reduce((n, c) => n + c[2], 0)) + 'px"><colgroup><col style="width:120px">'
    + groups.map(() => FACT_COLUMNS.map(c => '<col style="width:' + c[2] + 'px">').join("")).join("")
    + '<col style="width:112px"><col style="width:88px"><col style="width:88px"></colgroup><thead><tr>'
    + '<th class="sticky-1" rowspan="2">' + objectiveReviewerHeader() + '</th>'
    + groups.map(g => '<th colspan="8" scope="colgroup">' + g + '</th>').join("")
    + '<th rowspan="2">总参与<br>评审场次</th><th rowspan="2">代理情况</th><th class="evidence-sticky" rowspan="2">详情</th></tr><tr>'
    + groups.map(() => FACT_COLUMNS.map(m => '<th scope="col" aria-label="' + m[1] + '">' + '<button type="button" class="fact-header-formula" data-formula="' + m[0] + '" aria-label="' + m[1] + '公式">' + (m[3] || m[1]) + '</button></th>').join("")).join("")
    + '</tr></thead><tbody>'
    + experts.map((e, row) => '<tr><td class="sticky-1">' + escapeHtml(e.expert_name) + '</td>'
      + groups.map(g => FACT_COLUMNS.map(m => metricCell(g === "全部阶段" ? e.overall : e.stages[g], row, g, m)).join("")).join("")
      + '<td class="numeric"><button type="button" class="fact-number" data-participation="' + row + '">'
      + (e.overall.unknown ? '待确认' : e.overall.attended + '场') + '</button></td>'
      + metricCell(e.overall, row, "全部阶段", PROXY_METRIC)
      + '<td class="evidence-sticky"><button class="row-evidence-button" type="button" data-details="' + row + '">详情查看</button></td></tr>').join("")
    + (experts.length ? '' : '<tr><td colspan="' + (4 + groups.length * 8) + '">没有匹配的评审人，请修改筛选。</td></tr>') + '</tbody></table>';
  makeTableScrollable(elements.dimensionOneTableWrap);
  elements.dimensionOneTableWrap.querySelectorAll('[data-proxy]').forEach(button => button.addEventListener('click', () => showProxyDetails(experts[Number(button.dataset.proxy)])));
  elements.dimensionOneTableWrap.querySelectorAll('[data-formula]').forEach(button => button.addEventListener('click', () => showHeaderFormula(button.dataset.formula)));
  elements.dimensionOneTableWrap.querySelectorAll("[data-participation]").forEach(button => button.addEventListener("click", () => {
    const expert = experts[Number(button.dataset.participation)];
    document.querySelector("#formula-title").textContent = expert.expert_name + " · 评审参与度";
    document.querySelector("#formula-body").innerHTML = '<p>本批次全部阶段有效参评共' + expert.overall.attended
      + '场，出勤待确认' + expert.overall.unknown + '场。按项目编码＋阶段去重，代理归原评审人，单阶段筛选不改变此范围。</p><p>按本期完整名单实参场次降序，以人数的10％／30％向上取整为分界取高／中／低档分；并列占位、跨界取高档。未达任务最低场次取低档分，各档分值读取任务参数；页面筛选不改变计分范围。</p>'
      + '<ul>' + expert.sessions.filter(s => s.attended === true).map(s => '<li>'
        + escapeHtml(s.project_name + '／' + s.project_code + '／' + s.stage) + '</li>').join('') + '</ul>';
    if(state.analysis.assessment?.personal_scope)document.querySelector('#formula-body').innerHTML='<p>本人项目范围内参评'+expert.overall.attended+'场。此视图仅呈现本人报告事实，全量参与度计分范围不变。</p><ul>'+expert.sessions.filter(s=>s.attended===true).map(s=>'<li>'+escapeHtml(s.project_name+'／'+s.stage)+'</li>').join('')+'</ul>';
    document.querySelector("#formula-dialog").showModal();
  }));
  elements.dimensionOneTableWrap.querySelectorAll("[data-details]").forEach(button => button.addEventListener("click", () => {
    evidenceReturnFocus = button;
    openDimensionOneEvidence(experts[Number(button.dataset.details)].expert_name);
  }));
}

function showHeaderFormula(key) {
  const column = FACT_COLUMNS.find(c => c[0] === key);
  const metric = FACT_METRICS.find(m => m[0] === key);
  const counts = {
    expected: '应参场次＝所选阶段内列入评审人名单的去重场次数',
    attended: '实参场次＝所选阶段内确认实际参评的去重场次数（含归属本人的代理参评）',
    signed: '已会签场次＝所选阶段内会签结果非空且非横杠的场次数',
    opinions: '意见条数＝所选阶段内按拆条、归属及去重规则计入的意见条数之和',
    solutions: '含对策意见条数＝所选阶段内已确认计入的含有效对策意见条数之和',
  };
  document.querySelector('#formula-title').textContent = column[1];
  document.querySelector('#formula-body').innerHTML = '<p>' + escapeHtml(metric ? metric[4] : counts[key]) + '</p>';
  document.querySelector('#formula-dialog').showModal();
}
function showProxyDetails(expert) {
  const sessions = expert.sessions.filter(s => s.proxy_name);
  document.querySelector('#formula-title').textContent = expert.expert_name + ' · 全部阶段 · 代理情况';
  document.querySelector('#formula-body').innerHTML = sessions.length
    ? '<p>共' + sessions.length + '场代理参评</p><ul class="proxy-meeting-list">' + sessions.map(s => '<li><div>'
      + escapeHtml(s.project_name) + '</div><div class="muted">' + escapeHtml(s.project_code + ' · ' + s.stage)
      + '</div><div>代理人：<strong>' + escapeHtml(s.proxy_name) + '</strong></div></li>').join('') + '</ul>'
    : '<p>本批次无代理参评记录。</p>';
  document.querySelector('#formula-dialog').showModal();
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
  scroller.classList.add('table-scroll-content');
  scroller.tabIndex = 0;
  scroller.setAttribute('role', 'region');
  scroller.setAttribute('aria-label', '可横向滚动的表格');
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
  const changed=o.included!=null&&['yes','no'].includes(o.ai_status)&&o.included!==(o.ai_status==='yes');
  const manualLabel=changed?'手动修改':o.included!=null&&o.ai_status==='suspected'?'人工确认':'';
  if (o.ai_status !== "pending") html += '<div class="solution-actions" aria-label="是否计入对策统计">'
    + [true, false].map(include => '<button type="button" class="secondary-button" data-opinion="' + o.opinion_id
      + '" data-include="' + include + '" aria-pressed="' + (selection === include)
      + '">' + (include ? '计入统计' : '不计入统计') + '</button>').join("") + (manualLabel?'<span class="manual-decision">'+manualLabel+'</span>':'') + '</div>';
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
    state.analysis = await requestJson(window.workspace?"/api/workspace/solution-selection":"/api/facts/solution-selection", {
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
