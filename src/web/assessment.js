const assessmentUI = {managerId: '', tasks: [], scope: false, analysisId: '', policy: null, busy: false, importedRoster: null};
const assessmentPost = (url, body) => requestJson(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});

function renderRosterResult(r, confirmed=false) {
  sq('#assessment-result').innerHTML = [[confirmed ? '已确认' : '待确认', r.included], ['未匹配', r.unmatched], ['未纳入', r.excluded]].map(([label,names]) =>
    `<div class="roster-result-row"><strong>${label}<span>${names.length}人</span></strong><span>${escapeHtml(names.join('、') || '无')}</span></div>`).join('');
}

function renderScoringReceipt(p, confirmed=false) {
  sq('#assessment-policy').innerHTML = `<strong>评分配置${confirmed ? '已固定' : '已读取'} · V${escapeHtml(p.version)}</strong><details><summary>查看读取凭据</summary><div>${escapeHtml(p.file)}<br>读取时间：${escapeHtml(p.loaded_at)}<br>SHA256：${escapeHtml(p.sha256)}</div></details>`;
}

function canEnterAssessment() {
  if (!state.analysis || state.importActive || assessmentUI.busy) return false;
  const {errors,warnings} = validationCounts();
  if (errors || (warnings && !state.warningsAcknowledged)) return false;
  return !!state.analysis.assessment?.confirmed || !!(assessmentUI.policy && sq('#assessment-names').value.trim());
}

function syncAssessmentActions() {
  elements.continueAnalysis.disabled = !canEnterAssessment();
  const disabled = !state.analysis || state.importActive || assessmentUI.busy || !!state.analysis.assessment?.confirmed;
  ['assessment-preview','assessment-read-policy','assessment-names','assessment-roster-file'].forEach(id => sq('#'+id).disabled = disabled);
  const original = assessmentUI.importedRoster;
  sq('#assessment-restore-roster').disabled = disabled || !original || sq('#assessment-names').value === original.text;
  sq('#assessment-restore-roster').title = original ? `还原为「${original.filename}」成功导入时的名单，并重新比对` : '成功导入名单文件后可还原';
}

async function importAssessmentRoster(event) {
  const file = event.target.files[0];
  if (!file || assessmentUI.busy || !state.analysis || state.importActive || state.analysis.assessment?.confirmed) return;
  const analysisId = state.analysis.analysis_id;
  assessmentUI.busy = true;
  syncAssessmentActions();
  try {
    const r = await requestJson(`/api/assessment/roster-file?analysis_id=${encodeURIComponent(analysisId)}`, {method:'POST',body:file});
    if (state.analysis?.analysis_id !== analysisId) return;
    assessmentUI.importedRoster = {text:r.requested.join('\n'), filename:file.name};
    sq('#assessment-names').value = assessmentUI.importedRoster.text;
    renderRosterResult(r);
  } catch(err) {
    sq('#assessment-result').textContent = `名单未读取成功：${err.message}${assessmentUI.importedRoster ? '。此前成功导入的名单仍可还原。' : ''}`;
  } finally {assessmentUI.busy = false; syncAssessmentActions();}
}

async function restoreAssessmentRoster() {
  if (sq('#assessment-restore-roster').disabled || !assessmentUI.importedRoster) return;
  sq('#assessment-names').value = assessmentUI.importedRoster.text;
  await compareAssessment(false);
}

async function readScoringPolicy() {
  const analysisId = state.analysis?.analysis_id;
  assessmentUI.policy = null;
  assessmentUI.busy = true;
  syncAssessmentActions();
  sq('#assessment-policy').textContent = '正在读取评分配置…';
  try {
    const p = await requestJson('/api/assessment/policy');
    if (state.analysis?.analysis_id !== analysisId) return;
    assessmentUI.policy = p;
    renderScoringReceipt(p);
  } catch(e) {sq('#assessment-policy').textContent = `评分配置未读取成功：${e.message}`;}
  finally {assessmentUI.busy = false; syncAssessmentActions();}
}

async function enterAssessment() {
  if (!canEnterAssessment()) return;
  if (state.analysis.assessment?.confirmed || await compareAssessment(true)) navigateStep(2);
}

function renderAssessmentSetup() {
  const a = state.analysis;
  if (!a) return;
  if (assessmentUI.analysisId !== a.analysis_id) {
    assessmentUI.analysisId = a.analysis_id;
    assessmentUI.scope = false;
    assessmentUI.managerId = '';
    assessmentUI.policy = null;
    sq('#assessment-result').textContent = '';
    sq('#assessment-policy').textContent = '评分配置尚未读取。';
  }
  const confirmed = a.assessment?.confirmed;
  syncAssessmentActions();
  if (confirmed) {
    const r = a.assessment;
    renderRosterResult(r, true);
    const p = r.policy;
    renderScoringReceipt(p, true);
  }
  sq('#assessment-local-managers').innerHTML = confirmed ? '' : (a.reports || []).filter(r => r.source_type === 'local_excel' && !r.manager_identity?.source_token).map(r => `<div class="assessment-tools"><span>${escapeHtml(r.source_name)}</span><input data-local-id="${escapeHtml(r.source_name)}" placeholder="经理唯一编号" /><input data-local-name="${escapeHtml(r.source_name)}" placeholder="经理姓名" /><button type="button" class="secondary-button" data-local-manager="${escapeHtml(r.source_name)}">指定经理</button><span>${escapeHtml(r.manager_identity?.name || '未指定')}</span></div>`).join('');
}

async function compareAssessment(confirm=false) {
  if (assessmentUI.busy) return false;
  assessmentUI.busy = true;
  syncAssessmentActions();
  try {
    if (!state.analysis || state.importActive) throw new Error('请先完成报告读取');
    const {errors, warnings} = validationCounts();
    if (errors || (warnings && !state.warningsAcknowledged)) throw new Error('请先处理报告错误并确认提醒');
    if (confirm && !assessmentUI.policy) throw new Error('请先读取评分配置');
    const result = await assessmentPost('/api/assessment/roster', {analysis_id:state.analysis.analysis_id,
      names:[sq('#assessment-names').value], confirm, policy_hash:assessmentUI.policy?.sha256});
    if (confirm) {
      state.analysis = result;
      renderAssessmentSetup(); syncServiceActions(); activateStep(1);
      elements.projectSummary.textContent = `${result.reports.length}份报告 · ${result.sessions.length}场 · 纳入考核${result.experts.length}人`;
    } else renderRosterResult(result);
    return true;
  } catch(e) {sq('#assessment-result').textContent=e.message; return false;}
  finally {assessmentUI.busy = false; syncAssessmentActions();}
}

async function loadManagerTasks() {
  const data = await requestJson(`/api/assessment/tasks?analysis_id=${encodeURIComponent(state.analysis.analysis_id)}`);
  assessmentUI.tasks = data.managers;
  state.analysis.manager_reviews = data.reviews;
  if (!data.managers.some(m=>m.manager_id===assessmentUI.managerId)) assessmentUI.managerId = data.managers[0]?.manager_id || '';
  sq('#assessment-manager').innerHTML = data.managers.map(m=>`<option value="${escapeHtml(m.manager_id)}">${escapeHtml(m.name)}（${Object.keys(m.experts).length}人）</option>`).join('');
  sq('#assessment-manager').value = assessmentUI.managerId;
  sq('#manager-task-message').textContent = data.unresolved_reports.length ? '待识别经理：'+data.unresolved_reports.join('、') : '';
}
function currentManager() {return assessmentUI.tasks.find(m=>m.manager_id===assessmentUI.managerId);}
function managerExperts() {const names=currentManager()?.experts || {};return state.analysis.experts.filter(e=>Object.hasOwn(names,e.expert_name));}
function managerSaved(name) {return state.analysis.manager_reviews?.[assessmentUI.managerId]?.[name];}
function managerDraftKey(name=subjective.expert) {return JSON.stringify([assessmentUI.managerId,name]);}

async function showDimensionPage(kind,page) {
  if (hasUnsavedQuestionnaires() && kind==='subjective' && page===2) {window.alert('请先保存问卷修改');return;}
  sq(`#${kind}-page-one`).hidden=page!==1; sq(`#${kind}-page-two`).hidden=page!==2;
  if (kind==='subjective') sq('#export-subjective').hidden=page!==1;
  document.querySelectorAll(`[data-dimension-page^="${kind}:"]`).forEach(b=>b.setAttribute('aria-pressed',b.dataset.dimensionPage===`${kind}:${page}`));
  if (page===2) await renderDimensionScores(kind);
}

async function renderDimensionScores(kind) {
  const host=sq(`#${kind}-page-two`);
  host.textContent='正在计算…';
  try {
    const data=await requestJson(`/api/statistics/scores?analysis_id=${encodeURIComponent(state.analysis.analysis_id)}&scope_confirmed=${assessmentUI.scope}`);
    const p=data.policy.parameters, base=Object.values(p.components).reduce((a,b)=>a+b,0), participation=p.participation.tier_scores[0];
    const subjectiveMax=Object.values(p.subjective).reduce((sum,d)=>sum+d.high,0);
    const headers=kind==='objective' ? ['评审人',`TDR1／${base}`,`TDR2／${base}`,`TDR3／${base}`,`阶段加权／${base}`,`参与度／${participation}`,`基础／${base+participation}`,'超额意见奖励','输出对策奖励','客观合计'] : ['评审人',...subjective.catalog.map(d=>d.title),`最终分／${subjectiveMax}`,'暂定平均','完成／应评价'];
    const rows=data.rows.map(r=>kind==='objective' ? [r.expert_name,...['TDR1','TDR2','TDR3'].map(s=>scoreText(r.stages[s].score)),scoreText(r.process_total),scoreText(r.participation_score),scoreText(r.objective_total),scoreText(r.opinion_bonus),scoreText(r.solution_bonus),scoreText(r.objective_with_rewards)] : [r.expert_name,...r.subjective_items.map(i=>scoreText(i.score)),scoreText(r.subjective_total),scoreText(r.subjective_progress.provisional),`${r.subjective_progress.completed}/${r.subjective_progress.expected}`]);
    host.innerHTML=`<div class="assessment-tools">${kind==='objective'?`<label><input type="checkbox" id="dimension-scope" ${assessmentUI.scope?'checked':''} /> 已确认本批次报告范围完整</label>`:'<p>仅完整问卷参与平均；未收齐时显示暂定平均，最终分留空。</p>'}<button class="primary-button" data-export-dimension="${kind}">导出${kind==='objective'?'客观':'主观'}评分</button></div><p class="muted">配置V${data.policy.version} · SHA256 ${data.policy.sha256}</p><div class="score-statistics-table-wrap"><table class="score-table"><thead><tr>${headers.map(h=>`<th>${escapeHtml(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(cells=>`<tr>${cells.map(c=>`<td>${escapeHtml(String(c))}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="muted">${kind==='objective'?'客观合计包含全部奖励，可超过基础分；待识别项不按零处理。':'同一经理多个项目仍只计一票；任务排除记录随导出保留。'}</p>`;
    host.querySelectorAll('.score-statistics-table-wrap').forEach(makeTableScrollable);
  } catch(e) {host.textContent=e.message;}
}
function downloadAssessment(url) {const link=document.createElement('a');link.href=url;link.download='';document.body.append(link);link.click();link.remove();}

function initializeAssessmentUI() {
  sq('#assessment-preview').onclick=()=>compareAssessment(false);
  sq('#assessment-read-policy').onclick=readScoringPolicy;
  sq('#assessment-names').oninput=()=>{sq('#assessment-result').textContent='名单已更改，请重新对比；进入时将以当前输入确认。';syncAssessmentActions();};
  sq('#assessment-roster-file').onchange=importAssessmentRoster;
  sq('#assessment-restore-roster').onclick=restoreAssessmentRoster;
  sq('#assessment-local-managers').onclick=async e=>{const b=e.target.closest('[data-local-manager]');if(!b)return;const row=b.parentElement;try{state.analysis=await assessmentPost('/api/assessment/local-manager',{analysis_id:state.analysis.analysis_id,source_name:b.dataset.localManager,manager_id:row.querySelector('[data-local-id]').value,name:row.querySelector('[data-local-name]').value});renderAssessmentSetup();}catch(err){sq('#assessment-result').textContent=err.message;}};
  sq('#assessment-manager').onchange=()=>{if(subjective.busy){sq('#assessment-manager').value=assessmentUI.managerId;return;}assessmentUI.managerId=sq('#assessment-manager').value;subjective.expert=managerExperts()[0]?.expert_name || '';sq('#subjective-message').textContent='';sq('#manager-task-message').textContent='';renderSubjectiveRail();renderSubjectiveEditor();};
  sq('#import-manager-task-trigger').onclick=()=>sq('#import-manager-task').click();
  sq('#export-manager-task').onclick=()=>{if(hasUnsavedQuestionnaires()){sq('#manager-task-message').textContent='请先保存问卷修改';return;}downloadAssessment(`/api/assessment/task-export?analysis_id=${encodeURIComponent(state.analysis.analysis_id)}&manager_id=${encodeURIComponent(assessmentUI.managerId)}`);};
  sq('#import-manager-task').onchange=async e=>{try{if(hasUnsavedQuestionnaires())throw new Error('请先保存当前问卷修改');const f=e.target.files[0];if(!f)return;const r=await requestJson(`/api/assessment/task-import?analysis_id=${encodeURIComponent(state.analysis.analysis_id)}`,{method:'POST',body:f});state.analysis=r.analysis;subjective.drafts.clear();await loadManagerTasks();renderSubjectiveRail();renderSubjectiveEditor();sq('#manager-task-message').textContent=r.message;}catch(err){sq('#manager-task-message').textContent=err.message;}finally{e.target.value='';}};
  async function exclusion(restore) {try {const reason=restore?'':sq('#exclude-task-reason').value.trim();if(!restore&&!reason)throw new Error('请填写排除理由');state.analysis=await assessmentPost('/api/assessment/exclude-task',{analysis_id:state.analysis.analysis_id,manager_id:assessmentUI.managerId,expert_name:subjective.expert,reason});sq('#subjective-message').textContent=restore?'任务已恢复':'任务已排除，记录已保留';if(restore)sq('#exclude-task-reason').value='';renderSubjectiveRail();renderSubjectiveEditor();}catch(e){sq('#subjective-message').textContent=e.message;}}
  sq('#exclude-manager-task').onclick=()=>exclusion(false);sq('#restore-manager-task').onclick=()=>exclusion(true);
  document.addEventListener('click',e=>{const b=e.target.closest('[data-dimension-page]');if(b){const [kind,page]=b.dataset.dimensionPage.split(':');showDimensionPage(kind,Number(page));}const exp=e.target.closest('[data-export-dimension]');if(exp)downloadAssessment(`/api/statistics/scores/export?analysis_id=${encodeURIComponent(state.analysis.analysis_id)}&scope_confirmed=${assessmentUI.scope}&dimension=${exp.dataset.exportDimension}`);});
  document.addEventListener('change',e=>{if(e.target.id==='dimension-scope'){assessmentUI.scope=e.target.checked;sq('#score-scope-confirmed').checked=assessmentUI.scope;renderDimensionScores('objective');}});
}
