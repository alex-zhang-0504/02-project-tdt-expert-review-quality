const scoreStatistics = {analysisId: null, data: null, requestId: 0};
const scoreText = value => value == null ? "—" : Number(value).toFixed(state.analysis?.assessment?.policy?.parameters?.precision ?? 2).replace(/\.0+$/, "");

function hasUnsavedQuestionnaires() {
  return subjective.analysisId === state.analysis?.analysis_id && [...subjective.drafts.values()].some(d => d.dirty);
}

async function openScoreStatistics() {
  if (!qualityGatePassed()) return;
  if (!await flushSubjectiveChanges()) return;
  if (scoreStatistics.analysisId !== state.analysis.analysis_id) {
    scoreStatistics.analysisId = state.analysis.analysis_id;
    sq("#score-scope-confirmed").checked = assessmentUI.scope;
  }
  showPanel(sq("#score-statistics-panel"));
  activateStep(4);
  await refreshScoreStatistics();
}

async function refreshScoreStatistics() {
  if (!await flushSubjectiveChanges()) return;
  const requestId = ++scoreStatistics.requestId;
  const analysisId = state.analysis?.analysis_id;
  scoreStatistics.data = null;
  sq("#export-score-statistics").disabled = true;
  sq("#score-statistics-table").innerHTML = "";
  sq("#score-statistics-details").innerHTML = "";
  if (!analysisId || !qualityGatePassed() || hasUnsavedQuestionnaires()) {
    sq("#score-statistics-message").textContent = "请先完成数据检查。";
    return;
  }
  if (!await checkServiceHealth() || state.analysisStale) {
    sq("#score-statistics-message").textContent = "服务不可用或分析已失效，请重新读取报告。";
    return;
  }
  const confirmed = sq("#score-scope-confirmed").checked;
  sq("#score-statistics-message").textContent = "正在从当前数据和已保存问卷计算…";
  try {
    const data = await requestJson(`/api/statistics/scores?analysis_id=${encodeURIComponent(analysisId)}&scope_confirmed=${confirmed}`);
    if (requestId !== scoreStatistics.requestId || analysisId !== state.analysis?.analysis_id) return;
    scoreStatistics.data = data;
    renderScoreStatistics();
    sq("#export-score-statistics").disabled = false;
  } catch (error) { if (requestId === scoreStatistics.requestId) sq("#score-statistics-message").textContent = error.message; }
}

function renderScoreStatistics() {
  const data = scoreStatistics.data, p=data.policy.parameters;
  sq("#score-statistics-message").textContent = `${data.rows.length}位评审人 · ${data.rows.filter(r=>r.total!==null).length}人具备总分 · 配置V${data.policy.version} · SHA256 ${data.policy.sha256}`;
  sq("#score-method-note").innerHTML = importHint(`客观合计（含奖励）＋主观最终分，最高${p.total_cap}分；两维分数分别在对应模块第二页查看。`);
  sq("#score-statistics-table").innerHTML = `<table class="score-table"><thead><tr><th>评审人</th><th>客观合计（含奖励）</th><th>主观最终分</th><th>总分／${p.total_cap}</th><th>状态</th><th>依据</th></tr></thead><tbody>${data.rows.map((r,index)=>`<tr><th>${escapeHtml(r.expert_name)}</th><td>${scoreText(r.objective_with_rewards)}</td><td>${scoreText(r.subjective_total)}</td><td>${scoreText(r.total)}</td><td>${r.total===null?'待统计':r.suspected?'试算 · 含待确认':'试算'}</td><td><button class="secondary-button" data-score-detail="${index}">查看明细</button></td></tr>`).join('')}</tbody></table>`;
  sq("#score-statistics-details").innerHTML=data.rows.map((r,index)=>`<details class="score-detail" id="score-detail-${index}"><summary>${escapeHtml(r.expert_name)} · 计分依据</summary><p>${escapeHtml(r.reasons.join('；') || '已具备试算条件')}</p><p>过程基础${scoreText(r.objective_total)}＋超额意见奖励${scoreText(r.opinion_bonus)}＋输出对策奖励${scoreText(r.solution_bonus)}＝客观合计${scoreText(r.objective_with_rewards)}。</p><p>客观合计＋主观最终分${scoreText(r.subjective_total)}＝${scoreText(r.uncapped_total)}；最终${scoreText(r.total)}。</p><button class="secondary-button" data-score-evidence="${index}">查看评审过程详情</button></details>`).join('');
  sq('#score-statistics-table').querySelectorAll('table').forEach(()=>makeTableScrollable(sq('#score-statistics-table')));
}

async function exportScoreStatistics() {
  if (!await flushSubjectiveChanges()) return;
  if (!scoreStatistics.data || hasUnsavedQuestionnaires() || !await checkServiceHealth() || state.analysisStale) return;
  const link = document.createElement('a');
  link.href = `/api/statistics/scores/export?analysis_id=${encodeURIComponent(state.analysis.analysis_id)}&scope_confirmed=${scoreStatistics.data.scope_confirmed}`;
  link.download = '';
  document.body.append(link); link.click(); link.remove();
}

function initializeScoreStatisticsUI() {
  sq("#score-scope-confirmed").addEventListener('change', () => {assessmentUI.scope=sq('#score-scope-confirmed').checked;refreshScoreStatistics();});
  sq("#refresh-score-statistics").addEventListener('click', refreshScoreStatistics);
  sq("#export-score-statistics").addEventListener('click', exportScoreStatistics);
  sq("#score-statistics-table").addEventListener('click', event => {
    const button = event.target.closest('[data-score-detail]');
    if (!button) return;
    const detail = sq(`#score-detail-${button.dataset.scoreDetail}`);
    detail.open = true; detail.querySelector('summary').focus(); detail.scrollIntoView({block:'start',behavior:'smooth'});
    detail.querySelectorAll('.score-statistics-table-wrap').forEach(makeTableScrollable);
  });
  sq("#score-statistics-details").addEventListener('click', event => {
    const button = event.target.closest('[data-score-evidence]');
    if (button) openDimensionOneEvidence(scoreStatistics.data.rows[Number(button.dataset.scoreEvidence)].expert_name);
  });
}
