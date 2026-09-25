const subjective = {analysisId: null, catalog: null, expert: "", drafts: new Map(), busy: false};
const sq = selector => document.querySelector(selector);
let subjectiveGuideSeen = false;

function showSubjectiveGuide() {
  if (subjectiveGuideSeen) return;
  try { if (sessionStorage.getItem('tdt-subjective-guide-seen') === '1') return; } catch (_) {}
  sq('#subjective-guide-content').textContent = subjective.catalog[0].instructions;
  sq('#subjective-guide').showModal();
}

function subjectiveDraft() {
  if (!subjective.drafts.has(managerDraftKey())) {
    const saved = managerSaved(subjective.expert);
    subjective.drafts.set(managerDraftKey(), {
      evaluator: currentManager()?.name || "", ratings: structuredClone(saved?.rule_version === subjective.catalog?.[0]?.rule_version ? saved?.ratings || {} : {}), dirty: false,
    });
  }
  return subjective.drafts.get(managerDraftKey());
}

function subjectiveRequired(id, option) {
  return id === "contribution" ? option === "high" : id !== "preparation" && option === "low";
}

function subjectiveEvidence(rating) {
  return rating.evidence || (rating.project_code || rating.note ? [{project_code:rating.project_code || '',note:rating.note || ''}] : []);
}

function subjectiveSummary(draft) {
  let count = 0, missing = 0;
  subjective.catalog.forEach(d => {
    const rating = draft.ratings[d.id];
    const skipped = (d.response_options || []).some(o => o.id === rating?.option);
    const option = d.options.find(o => o.id === rating?.option);
    if (!option && !skipped) return;
    count++;
    const evidence = subjectiveEvidence(rating).filter(e => e.note?.trim() || e.project_code);
    if (skipped ? !rating.reason?.trim() : ((subjectiveRequired(d.id, option.id) && !evidence.length) || evidence.some(e => !e.note?.trim() || !e.project_code))) missing++;

  });
  return {count,
    status: count < 6 ? "待评价" : missing ? "待补依据" : "已完成"};
}

async function openSubjective() {
  if (!qualityGatePassed()) return;
  try {
    if (!subjective.catalog || subjective.analysisId !== state.analysis.analysis_id) subjective.catalog = await requestJson(`/api/subjective/catalog?analysis_id=${encodeURIComponent(state.analysis.analysis_id)}`);
    if (subjective.analysisId !== state.analysis.analysis_id) {
      subjective.analysisId = state.analysis.analysis_id;
      subjective.drafts.clear();
      subjective.expert = state.analysis.experts[0]?.expert_name || "";
    }
    await loadManagerTasks();
    if (!managerExperts().some(e=>e.expert_name===subjective.expert)) subjective.expert=managerExperts()[0]?.expert_name || "";
    showPanel(sq("#subjective-panel"));
    activateStep(3);
    sq("#subjective-message").textContent = "";
    renderSubjectiveRail();
    renderSubjectiveEditor();
    showSubjectiveGuide();
  } catch (error) { window.alert(error.message); }
}

function renderSubjectiveRail() {
  const experts = managerExperts();
  const completed = experts.filter(e => managerSaved(e.expert_name)?.status === "已完成").length;
  sq("#subjective-progress").textContent = `已完成 ${completed}／${experts.length}人`;
  sq("#subjective-experts").innerHTML = experts.map(e => {
    const draft = subjective.drafts.get(managerDraftKey(e.expert_name));
    const label = subjectiveExclusion(e.expert_name) ? "已排除" : draft?.dirty ? "编辑中" : (managerSaved(e.expert_name) && managerSaved(e.expert_name).rule_version !== subjective.catalog?.[0]?.rule_version ? "旧版待确认" : managerSaved(e.expert_name)?.status) || "待评价";
    return `<button type="button" class="subjective-person" data-person="${escapeHtml(e.expert_name)}"
      aria-pressed="${e.expert_name === subjective.expert}" ${subjective.busy ? "disabled" : ""}>
      <strong>${escapeHtml(e.expert_name)}</strong><span>${label}</span></button>`;
  }).join("") || '<p class="muted">没有匹配的评审人</p>';
}

function subjectiveExclusion(name=subjective.expert) {
  return Object.entries(state.analysis.assessment?.exclusions || {}).find(([key]) => {
    const [manager, expert] = JSON.parse(key);
    return manager === assessmentUI.managerId && expert === name;
  })?.[1] || '';
}

function renderSubjectiveEditor() {
  const expert = state.analysis.experts.find(e => e.expert_name === subjective.expert);
  if (!expert) { sq("#subjective-editor").innerHTML = '<p class="muted">当前无可评价的评审人。</p>'; return; }
  const draft = subjectiveDraft();
  const allowed = currentManager()?.experts[expert.expert_name] || [];
  const projects = [...new Map(expert.sessions.filter(s=>allowed.includes(s.project_code)).map(s => [s.project_code, s.project_name])).entries()];
  const projectOptions = selected => '<option value="">关联项目</option>' + projects.map(([code, name]) =>
    `<option value="${escapeHtml(code)}" ${code === selected ? "selected" : ""}>${escapeHtml(name)}（${escapeHtml(code)}）</option>`).join("");
  sq("#subjective-editor").innerHTML = `<form id="subjective-form">
    <fieldset class="subjective-fields" ${subjective.busy ? "disabled" : ""}>
      <div class="subjective-heading"><h3>${escapeHtml(expert.expert_name)}</h3><button class="secondary-button" type="button" id="subjective-facts">查看评审过程详情</button></div>
      ${managerSaved(expert.expert_name) && managerSaved(expert.expert_name).rule_version !== subjective.catalog?.[0]?.rule_version ? '<p class="subjective-boundary">旧版问卷已保留，请按本版题目重新确认；旧答案不自动参与新规则计分。</p>' : ''}
      ${subjectiveExclusion() ? `<p class="subjective-boundary">此任务已有排除记录：${escapeHtml(subjectiveExclusion())}。原记录保留。</p>` : ''}
      ${subjective.catalog.map((d, index) => {
        const rating = draft.ratings[d.id];
        const skipped = (d.response_options || []).some(o => o.id === rating?.option);
        const required = rating && subjectiveRequired(d.id, rating.option);
        const evidence = rating ? subjectiveEvidence(rating) : [];
        if (rating && !skipped && !evidence.length) evidence.push({project_code:'',note:''});
        if (rating) { rating.evidence=evidence; rating.project_code=''; rating.note=''; }
        return `<fieldset class="subjective-dimension"><legend>${index + 1}．${escapeHtml(d.title)}</legend>
          <p class="subjective-question">${escapeHtml(d.prompt || '')}</p>
          <p class="subjective-boundary">职责边界：${escapeHtml(d.boundary || '')}</p>
          ${rating?.option === 'no_opportunity' ? '<p class="subjective-boundary">原选择「本期无相关职责／机会」已保留，可重新选择下方卡片。</p>' : ''}
          <div class="subjective-options">${[...d.options, ...(d.response_options || []).filter(o=>o.id==='unable')].map(o => `<div class="subjective-option">
            <label for="${d.id}-${o.id}"><input type="radio" name="${d.id}" id="${d.id}-${o.id}" value="${o.id}" ${rating?.option === o.id ? "checked" : ""} />
              <span><strong>${escapeHtml(o.title)}</strong><span class="subjective-description">${escapeHtml(o.description)}</span></span></label>

          </div>`).join("")}</div>
          ${rating ? `<div class="subjective-rating-tools"><div>${skipped ? `<label class="field"><span>原因（必填）</span><input data-reason="${d.id}" maxlength="500" value="${escapeHtml(rating.reason || '')}" placeholder="${escapeHtml(d.reason_prompt || '说明暂无法判断的原因')}" /></label>` : `<details class="subjective-evidence" ${required || evidence.some(e=>e.note || e.project_code) ? 'open' : ''}><summary>${required ? '事实依据（必填）' : '代表性依据'}</summary>
          <p>${d.id==='contribution'?escapeHtml(d.contribution_prompt):'可关联多个共同项目或同项目的多次记录，以支持周期判断。'}</p>
          ${evidence.map((e,i)=>`<div class="subjective-evidence-fields"><label class="field"><span>关联项目</span><select data-project="${d.id}" data-evidence-index="${i}">${projectOptions(e.project_code)}</select></label><label class="field"><span>事实及证据位置（每条100字）</span><input data-note="${d.id}" data-evidence-index="${i}" maxlength="100" value="${escapeHtml(e.note || '')}" /></label><button type="button" class="secondary-button" data-remove-evidence="${d.id}" data-evidence-index="${i}">移除</button></div>`).join('')}
          <button type="button" class="secondary-button" data-add-evidence="${d.id}">增加依据</button></details>`}</div></div>` : ''}
        </fieldset>`;
      }).join("")}
      <div class="subjective-footer"><div class="subjective-save-progress"><div class="subjective-completion" id="subjective-completion" aria-live="polite"></div><progress id="subjective-completion-bar" max="6" value="0" aria-label="问卷填答进度"></progress></div><span id="subjective-save-state" class="muted"></span></div>
    </fieldset></form>`;
  updateSubjectiveSummary();
}

function updateSubjectiveSummary() {
  const draft = subjectiveDraft();
  const summary = subjectiveSummary(draft);
  sq("#subjective-completion").textContent = `${summary.count}／6项 · ${summary.status}`;
  sq('#subjective-completion-bar').value = summary.count;
  sq("#subjective-save-state").textContent = subjective.busy ? "正在提交…" : draft.dirty ? "待自动提交" : managerSaved(subjective.expert) ? "已保存" : "";
}

function subjectiveChanged() {
  subjectiveDraft().dirty = true;
  sq("#subjective-message").textContent = "";
  updateSubjectiveSummary();
  renderSubjectiveRail();
}

async function flushSubjectiveChanges() {
  if (subjective.busy) return false;
  if (subjective.analysisId !== state.analysis?.analysis_id) return true;
  const pending = [...subjective.drafts.entries()].filter(([, draft]) => draft.dirty);
  if (!pending.length) return true;
  const analysis = state.analysis;
  let failedKey = pending[0][0];
  subjective.busy = true;
  sq('#assessment-manager').disabled = true;
  if (sq('.subjective-fields')) sq('.subjective-fields').disabled = true;
  if (sq('#subjective-save-state')) sq('#subjective-save-state').textContent = '正在提交…';
  renderSubjectiveRail();
  try {
    if (!await checkServiceHealth() || state.analysisStale) throw new Error('服务不可用或分析已失效');
    for (const [key, draft] of pending) {
      failedKey = key;
      const [managerId, name] = JSON.parse(key);
      const review = await requestJson("/api/subjective/review", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({analysis_id: analysis.analysis_id, expert_name: name, evaluator: draft.evaluator, manager_id: managerId, ratings: draft.ratings, rule_version: subjective.catalog[0].rule_version, questionnaire_hash: subjective.catalog[0].questionnaire_hash})});
      analysis.manager_reviews ||= {};
      analysis.manager_reviews[managerId] ||= {};
      analysis.manager_reviews[managerId][name] = review;
      draft.dirty = false;
    }
    sq('#subjective-message').textContent = '';
    return true;
  } catch (error) {
    [assessmentUI.managerId, subjective.expert] = JSON.parse(failedKey);
    sq('#assessment-manager').value = assessmentUI.managerId;
    showPanel(sq('#subjective-panel')); activateStep(3);
    sq('#subjective-page-one').hidden = false; sq('#subjective-page-two').hidden = true;
    sq('#export-subjective').hidden = false;
    sq('#subjective-page-toggle').textContent = '查看主观打分 →';
    sq('#subjective-page-toggle').dataset.dimensionPage = 'subjective:2';
    const message = `自动提交失败：${currentManager()?.name || '当前经理'}／${subjective.expert}。${error.message}。内容已保留，请重试切换或查看主观打分。`;
    sq('#subjective-message').textContent = message;
    window.alert(message);
    return false;
  } finally {
    subjective.busy = false; sq('#assessment-manager').disabled = false;
    renderSubjectiveRail(); renderSubjectiveEditor();
  }
}

async function exportSubjective() {
  if (subjective.busy || !await checkServiceHealth() || state.analysisStale) return;
  if (!await flushSubjectiveChanges()) return;
  const button = sq("#export-subjective");
  button.disabled = true;
  try {
    const link = document.createElement("a");
    link.href = `/api/subjective/export?analysis_id=${encodeURIComponent(state.analysis.analysis_id)}`;
    link.download = "";
    document.body.append(link); link.click(); link.remove();
    sq("#subjective-message").textContent = "已请求下载主观打分及经理评价依据。";
  } catch (error) { sq("#subjective-message").textContent = error.message; }
  finally { button.disabled = false; }
}

function initializeSubjectiveUI() {
  sq('#subjective-guide-known').addEventListener('click', () => {
    subjectiveGuideSeen = true;
    try { sessionStorage.setItem('tdt-subjective-guide-seen', '1'); } catch (_) {}
    sq('#subjective-guide').close();
  });
  sq('#subjective-guide').addEventListener('cancel', event => event.preventDefault());
  sq("#export-subjective").addEventListener("click", exportSubjective);
  sq("#subjective-experts").addEventListener("click", async event => {
    const button = event.target.closest("[data-person]");
    if (!button || subjective.busy) return;
    if (!await flushSubjectiveChanges()) return;
    subjective.expert = button.dataset.person;
    sq("#subjective-message").textContent = "";
    renderSubjectiveRail(); renderSubjectiveEditor();
    sq('.subjective-heading')?.scrollIntoView({block:'start', behavior:'smooth'});
  });
  const editor = sq("#subjective-editor");
  editor.addEventListener("submit", event => event.preventDefault());
  editor.addEventListener("input", event => {
    const input = event.target;
    if (input.dataset.note) subjectiveDraft().ratings[input.dataset.note].evidence[Number(input.dataset.evidenceIndex)].note = input.value;
    else if (input.dataset.reason) subjectiveDraft().ratings[input.dataset.reason].reason = input.value;
    else return;
    subjectiveChanged();
  });
  editor.addEventListener("change", event => {
    const input = event.target;
    if (input.type === "radio") {
      const previous = subjectiveDraft().ratings[input.name];
      subjectiveDraft().ratings[input.name] = {option: input.value, project_code: "", note: "", evidence: previous ? subjectiveEvidence(previous) : [], reason: previous?.reason || ""};
      subjectiveChanged(); renderSubjectiveEditor(); sq(`#${input.id}`).focus({preventScroll: true});
    } else if (input.dataset.project) {
      subjectiveDraft().ratings[input.dataset.project].evidence[Number(input.dataset.evidenceIndex)].project_code = input.value;
      subjectiveChanged();
    }
  });
  editor.addEventListener("click", event => {
    const radio = event.target.closest('input[type="radio"]');
    if (radio && subjectiveDraft().ratings[radio.name]?.option === radio.value) {
      event.preventDefault();
      delete subjectiveDraft().ratings[radio.name];
      subjectiveChanged(); renderSubjectiveEditor(); sq(`#${radio.id}`).focus({preventScroll:true}); return;
    }
    const add = event.target.closest('[data-add-evidence]');
    const remove = event.target.closest('[data-remove-evidence]');
    if (add || remove) {
      const id = add?.dataset.addEvidence || remove.dataset.removeEvidence;
      const rows = subjectiveDraft().ratings[id].evidence;
      if (add) rows.push({project_code:'',note:''}); else rows.splice(Number(remove.dataset.evidenceIndex),1);
      subjectiveChanged(); renderSubjectiveEditor(); return;
    }
    if (event.target.closest("#subjective-facts")) openDimensionOneEvidence(subjective.expert);
  });
  window.addEventListener("beforeunload", event => {
    if (subjective.analysisId === state.analysis?.analysis_id && ([...subjective.drafts.values()].some(d => d.dirty) || Object.keys(state.analysis.manager_reviews || {}).length)) {
      event.preventDefault(); event.returnValue = "";
    }
  });
}
