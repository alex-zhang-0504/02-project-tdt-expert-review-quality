const scoreStatistics = {analysisId: null, data: null, requestId: 0};
const scoreText = value => value == null ? "—" : Number(value).toFixed(2).replace(/\.00$/, "");

function hasUnsavedQuestionnaires() {
  return subjective.analysisId === state.analysis?.analysis_id && [...subjective.drafts.values()].some(d => d.dirty);
}

async function openScoreStatistics() {
  if (!qualityGatePassed()) return;
  if (hasUnsavedQuestionnaires() || subjective.busy) {
    window.alert("问卷尚有未保存修改，请先保存后查看分数统计。");
    return;
  }
  if (scoreStatistics.analysisId !== state.analysis.analysis_id) {
    scoreStatistics.analysisId = state.analysis.analysis_id;
    sq("#score-scope-confirmed").checked = false;
  }
  showPanel(sq("#score-statistics-panel"));
  activateStep(4);
  await refreshScoreStatistics();
}

async function refreshScoreStatistics() {
  const requestId = ++scoreStatistics.requestId;
  const analysisId = state.analysis?.analysis_id;
  scoreStatistics.data = null;
  sq("#export-score-statistics").disabled = true;
  sq("#score-statistics-table").innerHTML = "";
  sq("#score-statistics-details").innerHTML = "";
  if (!analysisId || !qualityGatePassed() || hasUnsavedQuestionnaires()) {
    sq("#score-statistics-message").textContent = "请先完成数据检查并保存问卷修改。";
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
  const data = scoreStatistics.data;
  sq("#score-statistics-message").textContent = `${data.rows.length}位评审人 · ${data.rows.filter(r => r.total !== null).length}人可试算总分${data.scope_confirmed ? "" : " · 请先确认报告范围"}`;
  const stageCell = result => result.applicable ? `${scoreText(result.score)}<small>应参${result.expected}场<br>权重${result.weight}％</small>` : "不适用";
  sq("#score-statistics-table").innerHTML = `<table class="score-table score-summary-table"><colgroup><col style="width:12%"><col span="3" style="width:9%"><col span="6" style="width:7%"><col style="width:9%"><col style="width:10%"></colgroup><thead><tr><th>评审人</th><th>TDR1／25</th><th>TDR2／25</th><th>TDR3／25</th><th>参与度／5</th><th>过程表现／30</th><th>专业价值／70</th><th>超额意见奖励</th><th>对策奖励</th><th>总分／100</th><th>状态</th><th>依据</th></tr></thead><tbody>${data.rows.map((r, index) =>
    `<tr><th scope="row">${escapeHtml(r.expert_name)}<small>${r.projects}个项目 · ${r.sessions}场</small></th>
      ${['TDR1','TDR2','TDR3'].map(s => `<td>${stageCell(r.stages[s])}</td>`).join('')}
      <td>${scoreText(r.participation_score)}<small>实参${scoreText(r.participation_count)}场</small></td>
      <td>${scoreText(r.objective_total)}</td><td>${scoreText(r.subjective_total)}</td><td>${scoreText(r.opinion_bonus)}</td><td>${scoreText(r.solution_bonus)}</td><td><strong>${scoreText(r.total)}</strong>${r.uncapped_total > 100 ? '<small>已封顶</small>' : ''}</td>
      <td>${r.total === null ? "待统计" : r.suspected ? "试算 · 含待确认" : "试算"}</td>
      <td><button class="ghost-button" type="button" data-score-detail="${index}">查看明细</button></td></tr>`).join('')}</tbody></table>`;
  sq("#score-statistics-details").innerHTML = data.rows.map((r, index) => `<details class="score-detail" id="score-detail-${index}">
    <summary>${escapeHtml(r.expert_name)} · 计分依据</summary>
    ${r.reasons.length ? `<p>${escapeHtml(r.reasons.join('；'))}</p>` : '<p>客观与主观已具备试算条件。</p>'}
    <p class="muted">阶段基础分按25分计算，再乘有效权重；不适用阶段不计权重，待处理阶段不会被剔除。</p>
    <div class="score-statistics-table-wrap"><table class="score-table score-stage-table"><colgroup><col style="width:20%"><col span="8" style="width:10%"></colgroup><thead><tr><th>阶段</th><th>出勤／5</th><th>会签／10</th><th>意见基础／10</th><th>阶段／25</th><th>有效权重</th><th>加权贡献</th><th>超额奖励</th><th>对策奖励</th></tr></thead><tbody>
      ${Object.entries(r.stages).map(([s, v]) => `<tr><th>${s}${v.applicable ? '' : '（不适用）'}</th>${['attendance','signoff','opinion'].map(k=>`<td>${scoreText(v.components[k])}</td>`).join('')}
        <td>${scoreText(v.score)}</td><td>${v.weight}％</td><td>${scoreText(v.contribution)}</td><td>${scoreText(v.opinion_bonus)}<small>意见${v.opinions}条－实参${v.attended}场</small></td><td>${scoreText(v.solution_bonus)}<small>含对策${v.solutions}条×2分</small></td></tr>`).join('')}
    </tbody></table></div>
    <p>评审参与度：实参${scoreText(r.participation_count)}场，${r.participation_score == null ? '待统计' : r.participation_tier ? '第' + r.participation_tier + '数量档' : '未达到3场'}，得${scoreText(r.participation_score)}分。</p>
    <p>阶段加权${scoreText(r.process_total)}＋参与度${scoreText(r.participation_score)}＝过程表现${scoreText(r.objective_total)}分。</p>
    <p class="muted">意见基础分＝min（意见条数÷实参场次，1）×10；每阶段超额奖励＝max（意见条数－实参场次，0），直接相加、不乘阶段权重；含对策意见每条另加2分。</p>
    <p>过程表现${scoreText(r.objective_total)}＋专业价值${scoreText(r.subjective_total)}＋超额意见奖励${scoreText(r.opinion_bonus)}＋对策奖励${scoreText(r.solution_bonus)}＝${scoreText(r.uncapped_total)}；最终${scoreText(r.total)}分，最高100分。</p>
    <p class="muted">专业价值：按已保存问卷换算，未完成或必填依据不全时不产生合计。</p>
    <div class="score-subjective-items">${r.subjective_items.map(item => `<p><strong>${item.dimension}</strong>：${item.option} · ${scoreText(item.score)}分${item.evidence_missing ? ' · 待补依据' : ''}</p>`).join('')}</div>
    <button class="secondary-button" type="button" data-score-evidence="${index}">查看评审过程详情</button>
  </details>`).join('');
  document.querySelectorAll('#score-statistics-panel .score-statistics-table-wrap').forEach(makeTableScrollable);
}

async function exportScoreStatistics() {
  if (!scoreStatistics.data || hasUnsavedQuestionnaires() || !await checkServiceHealth() || state.analysisStale) return;
  const link = document.createElement('a');
  link.href = `/api/statistics/scores/export?analysis_id=${encodeURIComponent(state.analysis.analysis_id)}&scope_confirmed=${scoreStatistics.data.scope_confirmed}`;
  link.download = '分数统计.xlsx';
  document.body.append(link); link.click(); link.remove();
}

function initializeScoreStatisticsUI() {
  sq("#open-score-statistics").addEventListener('click', () => navigateStep(4));
  sq("#score-scope-confirmed").addEventListener('change', refreshScoreStatistics);
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
