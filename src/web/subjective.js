const subjective = {analysisId: null, catalog: null, expert: "", drafts: new Map(), busy: false};
const sq = selector => document.querySelector(selector);

function subjectiveDraft() {
  if (!subjective.drafts.has(managerDraftKey())) {
    const saved = managerSaved(subjective.expert);
    subjective.drafts.set(managerDraftKey(), {
      evaluator: currentManager()?.name || "", ratings: structuredClone(saved?.ratings || {}), dirty: false,
    });
  }
  return subjective.drafts.get(managerDraftKey());
}

function subjectiveRequired(id, option) {
  return id === "contribution" ? option === "high" : option === "low";
}

function subjectiveSummary(draft) {
  let count = 0, missing = 0;
  subjective.catalog.forEach(d => {
    const rating = draft.ratings[d.id];
    const option = d.options.find(o => o.id === rating?.option);
    if (!option) return;
    count++;
    if (subjectiveRequired(d.id, option.id) && (!rating.note.trim() || !rating.project_code)) missing++;
  });
  return {count,
    status: count < 6 ? "待评价" : missing ? "待补依据" : "已完成"};
}

async function openSubjective() {
  if (!qualityGatePassed()) return;
  try {
    if (!subjective.catalog) subjective.catalog = await requestJson("/api/subjective/catalog");
    if (subjective.analysisId !== state.analysis.analysis_id) {
      subjective.analysisId = state.analysis.analysis_id;
      subjective.drafts.clear();
      subjective.expert = state.analysis.experts[0]?.expert_name || "";
      sq("#subjective-search").value = "";
    }
    await loadManagerTasks();
    if (!managerExperts().some(e=>e.expert_name===subjective.expert)) subjective.expert=managerExperts()[0]?.expert_name || "";
    showPanel(sq("#subjective-panel"));
    activateStep(3);
    sq("#subjective-message").textContent = "";
    renderSubjectiveRail();
    renderSubjectiveEditor();
  } catch (error) { window.alert(error.message); }
}

function renderSubjectiveRail() {
  const experts = managerExperts();
  const completed = experts.filter(e => managerSaved(e.expert_name)?.status === "已完成").length;
  sq("#subjective-progress").textContent = `已保存完成 ${completed}／${experts.length}人`;
  const visible = experts.filter(e => reviewerMatchesSearch(e, normalizedReviewerSearch(sq("#subjective-search").value)));
  sq("#subjective-experts").innerHTML = visible.map(e => {
    const draft = subjective.drafts.get(managerDraftKey(e.expert_name));
    const label = subjectiveExclusion(e.expert_name) ? "已排除" : draft?.dirty ? "未保存" : managerSaved(e.expert_name)?.status || "待评价";
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

function syncSubjectiveTaskManagement() {
  const host = sq('#subjective-task-management');
  host.hidden = !subjective.expert;
  const reason = subjectiveExclusion();
  const key = managerDraftKey();
  if (host.dataset.task !== key) { host.open = false; sq('#exclude-task-reason').value = reason; host.dataset.task = key; }
  sq('#subjective-task-status').textContent = reason ? '已排除 · ' + reason : '无需评价时，可填写理由排除';
  sq('#exclude-manager-task').hidden = !!reason;
  sq('#restore-manager-task').hidden = !reason;
  sq('#exclude-task-reason').disabled = !!reason;
  if (reason) sq('#exclude-task-reason').value = reason;
}

function renderSubjectiveEditor() {
  syncSubjectiveTaskManagement();
  const expert = state.analysis.experts.find(e => e.expert_name === subjective.expert);
  if (!expert) { sq("#subjective-editor").innerHTML = '<p class="muted">当前无可评价的评审人。</p>'; return; }
  const draft = subjectiveDraft();
  const allowed = currentManager()?.experts[expert.expert_name] || [];
  const projects = [...new Map(expert.sessions.filter(s=>allowed.includes(s.project_code)).map(s => [s.project_code, s.project_name])).entries()];
  const projectOptions = selected => '<option value="">关联项目</option>' + projects.map(([code, name]) =>
    `<option value="${escapeHtml(code)}" ${code === selected ? "selected" : ""}>${escapeHtml(name)}（${escapeHtml(code)}）</option>`).join("");
  sq("#subjective-editor").innerHTML = `<form id="subjective-form">
    <fieldset class="subjective-fields" ${subjective.busy ? "disabled" : ""}>
      <div class="subjective-heading"><div><h3>${escapeHtml(expert.expert_name)}</h3>
        <p class="muted">共同项目 ${projects.length}个 · ${expert.sessions.filter(s=>allowed.includes(s.project_code)).length}场评审<span class="subjective-evaluator-name">评价人：<strong>${escapeHtml(draft.evaluator)}</strong></span></p></div>
        <button class="secondary-button" type="button" id="subjective-facts">查看评审过程详情</button></div>
      <details class="subjective-facts-summary"><summary>客观事实参考</summary><p>${[
        ["出勤率", expert.overall.attendance_rate], ["会签率", expert.overall.signoff_rate],
        ["意见提出平均数", expert.overall.opinion_average],
        ["代理率", expert.overall.proxy_rate],
      ].map(([name, value]) => `${name}：${value == null ? "—" : name === "意见提出平均数" ? Number(value).toFixed(1) : value + "％"}`).join("　")}</p>
        <p>应参${expert.overall.expected}场 · 实参${expert.overall.attended}场 · 意见${expert.overall.opinions}条 · 含对策${expert.overall.pending ? '待统计' : expert.overall.solutions + '条'}；未识别的对策不作为已确认事实。</p></details>
      ${subjective.catalog.map((d, index) => {
        const rating = draft.ratings[d.id];
        const required = rating && subjectiveRequired(d.id, rating.option);
        return `<fieldset class="subjective-dimension"><legend>${index + 1}．${d.title}</legend>
          <div class="subjective-options">${d.options.map(o => `<div class="subjective-option">
            <label for="${d.id}-${o.id}"><input type="radio" name="${d.id}" id="${d.id}-${o.id}" value="${o.id}" ${rating?.option === o.id ? "checked" : ""} />
              <span><strong>${o.title}</strong><span class="subjective-description">${escapeHtml(o.description)}</span></span></label>

          </div>`).join("")}</div>
          ${rating ? `<div class="subjective-rating-tools"><details class="subjective-evidence" ${required || rating.note || rating.project_code ? "open" : ""}><summary>${required ? "事实依据（必填）" : "补充依据（选填）"}</summary>
              <div class="subjective-evidence-fields"><label class="field"><span>关联项目</span><select data-project="${d.id}">${projectOptions(rating.project_code)}</select></label>
                <label class="field"><span>具体事实（100字以内）</span><input data-note="${d.id}" maxlength="100" placeholder="写明具体行为及影响" value="${escapeHtml(rating.note)}" /></label></div></details>
            <button type="button" class="secondary-button subjective-reset" data-clear="${d.id}">恢复待评价</button></div>` : ""}
        </fieldset>`;
      }).join("")}
      <div class="subjective-footer"><div class="subjective-save-progress"><div class="subjective-completion" id="subjective-completion" aria-live="polite"></div><progress id="subjective-completion-bar" max="6" value="0" aria-label="问卷填答进度"></progress></div><span id="subjective-save-state" class="muted"></span><button class="primary-button" id="save-subjective" type="submit">保存当前问卷</button></div>
    </fieldset></form>`;
  updateSubjectiveSummary();
}

function updateSubjectiveSummary() {
  const draft = subjectiveDraft();
  const summary = subjectiveSummary(draft);
  sq("#subjective-completion").textContent = `${summary.count}／6项 · ${summary.status}`;
  sq('#subjective-completion-bar').value = summary.count;
  sq("#subjective-save-state").textContent = draft.dirty ? "有未保存修改" : managerSaved(subjective.expert) ? "已保存至本次分析" : "尚未保存";
}

function subjectiveChanged() {
  subjectiveDraft().dirty = true;
  sq("#subjective-message").textContent = "";
  updateSubjectiveSummary();
  renderSubjectiveRail();
}

async function saveSubjective(event) {
  event.preventDefault();
  if (subjective.busy || !await checkServiceHealth() || state.analysisStale) return;
  const draft = subjectiveDraft();
  if (!draft.evaluator.trim()) { sq("#assessment-manager").focus(); return; }
  const name = subjective.expert, analysis = state.analysis, managerId = assessmentUI.managerId;
  subjective.busy = true;
  sq(".subjective-fields").disabled = true;
  renderSubjectiveRail();
  try {
    const review = await requestJson("/api/subjective/review", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({analysis_id: analysis.analysis_id, expert_name: name, evaluator: draft.evaluator, manager_id:managerId, ratings: draft.ratings})});
    analysis.manager_reviews ||= {};
    analysis.manager_reviews[managerId] ||= {};
    analysis.manager_reviews[managerId][name] = review;
    draft.dirty = false;
    sq("#subjective-message").textContent = `问卷已保存：${review.status}。分数可在本模块「主观评分」页查看。`;
  } catch (error) { sq("#subjective-message").textContent = error.message; }
  finally { subjective.busy = false; renderSubjectiveRail(); renderSubjectiveEditor(); }
}

async function exportSubjective() {
  if (subjective.busy || !await checkServiceHealth() || state.analysisStale) return;
  if ([...subjective.drafts.values()].some(d => d.dirty)) {
    sq("#subjective-message").textContent = "仍有未保存评价，请逐人保存后导出。";
    return;
  }
  const button = sq("#export-subjective");
  button.disabled = true;
  try {
    const link = document.createElement("a");
    link.href = `/api/subjective/export?analysis_id=${encodeURIComponent(state.analysis.analysis_id)}`;
    link.download = "";
    document.body.append(link); link.click(); link.remove();
    sq("#subjective-message").textContent = "已请求下载主观评分及经理评价依据。";
  } catch (error) { sq("#subjective-message").textContent = error.message; }
  finally { button.disabled = false; }
}

function initializeSubjectiveUI() {
  sq("#subjective-search").addEventListener("input", renderSubjectiveRail);
  sq("#export-subjective").addEventListener("click", exportSubjective);
  sq("#subjective-experts").addEventListener("click", event => {
    const button = event.target.closest("[data-person]");
    if (!button || subjective.busy) return;
    subjective.expert = button.dataset.person;
    sq("#subjective-message").textContent = "";
    renderSubjectiveRail(); renderSubjectiveEditor();
    sq('.subjective-heading')?.scrollIntoView({block:'start', behavior:'smooth'});
  });
  const editor = sq("#subjective-editor");
  editor.addEventListener("submit", saveSubjective);
  editor.addEventListener("input", event => {
    const input = event.target;
    if (input.dataset.note) subjectiveDraft().ratings[input.dataset.note].note = input.value;
    else return;
    subjectiveChanged();
  });
  editor.addEventListener("change", event => {
    const input = event.target;
    if (input.type === "radio") {
      const previous = subjectiveDraft().ratings[input.name];
      subjectiveDraft().ratings[input.name] = {option: input.value, project_code: previous?.project_code || "", note: previous?.note || ""};
      subjectiveChanged(); renderSubjectiveEditor(); sq(`#${input.id}`).focus({preventScroll: true});
    } else if (input.dataset.project) {
      subjectiveDraft().ratings[input.dataset.project].project_code = input.value;
      subjectiveChanged();
    }
  });
  editor.addEventListener("click", event => {
    const clear = event.target.closest("[data-clear]");
    if (clear) { delete subjectiveDraft().ratings[clear.dataset.clear]; subjectiveChanged(); renderSubjectiveEditor(); return; }
    if (event.target.closest("#subjective-facts")) openDimensionOneEvidence(subjective.expert);
  });
  window.addEventListener("beforeunload", event => {
    if (subjective.analysisId === state.analysis?.analysis_id && ([...subjective.drafts.values()].some(d => d.dirty) || Object.keys(state.analysis.manager_reviews || {}).length)) {
      event.preventDefault(); event.returnValue = "";
    }
  });
}
