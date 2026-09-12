const subjective = {analysisId: null, catalog: null, expert: "", drafts: new Map(), busy: false};
const sq = selector => document.querySelector(selector);

function subjectiveDraft() {
  if (!subjective.drafts.has(subjective.expert)) {
    const saved = state.analysis.subjective_reviews?.[subjective.expert];
    subjective.drafts.set(subjective.expert, {
      evaluator: saved?.evaluator || "", ratings: structuredClone(saved?.ratings || {}), dirty: false,
    });
  }
  return subjective.drafts.get(subjective.expert);
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
    showPanel(sq("#subjective-panel"));
    activateStep(3);
    sq("#subjective-message").textContent = "";
    renderSubjectiveRail();
    renderSubjectiveEditor();
  } catch (error) { window.alert(error.message); }
}

function renderSubjectiveRail() {
  const experts = state.analysis.experts;
  const completed = experts.filter(e => state.analysis.subjective_reviews?.[e.expert_name]?.status === "已完成").length;
  sq("#subjective-progress").textContent = `已保存完成 ${completed}／${experts.length}人`;
  const visible = experts.filter(e => reviewerMatchesSearch(e, normalizedReviewerSearch(sq("#subjective-search").value)));
  sq("#subjective-experts").innerHTML = visible.map(e => {
    const draft = subjective.drafts.get(e.expert_name);
    const label = draft?.dirty ? "未保存" : state.analysis.subjective_reviews?.[e.expert_name]?.status || "待评价";
    return `<button type="button" class="subjective-person" data-person="${escapeHtml(e.expert_name)}"
      aria-pressed="${e.expert_name === subjective.expert}" ${subjective.busy ? "disabled" : ""}>
      <strong>${escapeHtml(e.expert_name)}</strong><span>${label}</span></button>`;
  }).join("") || '<p class="muted">没有匹配的评审人</p>';
}

function renderSubjectiveEditor() {
  hideSubjectiveTooltip();
  const expert = state.analysis.experts.find(e => e.expert_name === subjective.expert);
  if (!expert) { sq("#subjective-editor").innerHTML = '<p class="muted">当前无可评价的评审人。</p>'; return; }
  const draft = subjectiveDraft();
  const projects = [...new Map(expert.sessions.map(s => [s.project_code, s.project_name])).entries()];
  const projectOptions = selected => '<option value="">关联项目</option>' + projects.map(([code, name]) =>
    `<option value="${escapeHtml(code)}" ${code === selected ? "selected" : ""}>${escapeHtml(name)}（${escapeHtml(code)}）</option>`).join("");
  sq("#subjective-editor").innerHTML = `<form id="subjective-form">
    <fieldset class="subjective-fields" ${subjective.busy ? "disabled" : ""}>
      <div class="subjective-heading"><div><h3>${escapeHtml(expert.expert_name)}</h3>
        <p class="muted">本批次 ${projects.length}个项目 · ${expert.sessions.length}场评审</p></div>
        <button class="secondary-button" type="button" id="subjective-facts">查看评审过程详情</button>
        <div class="subjective-completion" id="subjective-completion" aria-live="polite"></div></div>
      <details class="subjective-facts-summary"><summary>客观事实参考</summary><p>${[
        ["出勤率", expert.overall.attendance_rate], ["会签率", expert.overall.signoff_rate],
        ["意见提出率", expert.overall.opinion_rate], ["含对策意见率", expert.overall.solution_rate],
        ["代理率", expert.overall.proxy_rate],
      ].map(([name, value]) => `${name}：${value == null ? "—" : value + "％"}`).join("　")}</p>
        <p>应参${expert.overall.expected}场 · 实参${expert.overall.attended}场 · 意见${expert.overall.opinions}条；未识别的对策不作为已确认事实。</p></details>
      <label class="field subjective-evaluator"><span>评价人</span><input id="subjective-evaluator" maxlength="80" required
        placeholder="填写本人姓名" value="${escapeHtml(draft.evaluator)}" /></label>
      ${subjective.catalog.map((d, index) => {
        const rating = draft.ratings[d.id];
        const required = rating && subjectiveRequired(d.id, rating.option);
        return `<fieldset class="subjective-dimension"><legend>${index + 1}．${d.title}</legend>
          <div class="subjective-options">${d.options.map(o => `<div class="subjective-option">
            <label for="${d.id}-${o.id}"><input type="radio" name="${d.id}" id="${d.id}-${o.id}" value="${o.id}" ${rating?.option === o.id ? "checked" : ""} />
              <span><strong>${o.title}</strong></span></label>
            <button type="button" class="subjective-help" data-help="${d.id}:${o.id}" aria-label="${o.title}的解释" aria-describedby="subjective-tooltip">!</button>
          </div>`).join("")}</div>
          ${rating ? `<div class="subjective-row-tools"><button type="button" class="ghost-button" data-clear="${d.id}">恢复待评价</button>
            </div>
            <details class="subjective-evidence" ${required || rating.note || rating.project_code ? "open" : ""}><summary>${required ? "事实依据（必填）" : "补充依据（选填）"}</summary>
              <div class="subjective-evidence-fields"><label class="field"><span>关联项目</span><select data-project="${d.id}">${projectOptions(rating.project_code)}</select></label>
                <label class="field"><span>具体事实（100字以内）</span><input data-note="${d.id}" maxlength="100" placeholder="写明具体行为及影响" value="${escapeHtml(rating.note)}" /></label></div></details>` : ""}
        </fieldset>`;
      }).join("")}
      <div class="subjective-footer"><span id="subjective-save-state" class="muted"></span><button class="primary-button" id="save-subjective" type="submit">保存当前问卷</button></div>
    </fieldset></form>`;
  updateSubjectiveSummary();
}

function updateSubjectiveSummary() {
  const draft = subjectiveDraft();
  const summary = subjectiveSummary(draft);
  sq("#subjective-completion").textContent = `${summary.count}／6项 · ${summary.status}`;
  sq("#subjective-save-state").textContent = draft.dirty ? "有未保存修改" : state.analysis.subjective_reviews?.[subjective.expert] ? "已保存至本次分析" : "尚未保存";
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
  if (!draft.evaluator.trim()) { sq("#subjective-evaluator").focus(); return; }
  const name = subjective.expert, analysis = state.analysis;
  subjective.busy = true;
  sq(".subjective-fields").disabled = true;
  renderSubjectiveRail();
  try {
    const review = await requestJson("/api/subjective/review", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({analysis_id: analysis.analysis_id, expert_name: name, evaluator: draft.evaluator, ratings: draft.ratings})});
    analysis.subjective_reviews ||= {};
    analysis.subjective_reviews[name] = review;
    draft.dirty = false;
    sq("#subjective-message").textContent = `问卷已保存：${review.status}。分数请到「分数统计」查看。`;
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
    link.download = "主观问卷.xlsx";
    document.body.append(link); link.click(); link.remove();
    sq("#subjective-message").textContent = "已请求下载主观问卷，文件仅保留选项与依据。";
  } catch (error) { sq("#subjective-message").textContent = error.message; }
  finally { button.disabled = false; }
}

function hideSubjectiveTooltip() {
  const tooltip = sq("#subjective-tooltip");
  if (tooltip) tooltip.hidden = true;
}

function showSubjectiveTooltip(button) {
  const [dimension, option] = button.dataset.help.split(":");
  const text = subjective.catalog.find(d => d.id === dimension).options.find(o => o.id === option).description;
  const tooltip = sq("#subjective-tooltip");
  tooltip.textContent = text;
  tooltip.hidden = false;
  const rect = button.getBoundingClientRect();
  tooltip.style.left = Math.max(8, Math.min(rect.right - tooltip.offsetWidth, window.innerWidth - tooltip.offsetWidth - 8)) + "px";
  tooltip.style.top = (rect.bottom + 8 + tooltip.offsetHeight < window.innerHeight ? rect.bottom + 8 : Math.max(8, rect.top - tooltip.offsetHeight - 8)) + "px";
}

function initializeSubjectiveUI() {
  sq("#open-subjective").addEventListener("click", () => navigateStep(3));
  sq("#subjective-search").addEventListener("input", renderSubjectiveRail);
  sq("#export-subjective").addEventListener("click", exportSubjective);
  sq("#subjective-experts").addEventListener("click", event => {
    const button = event.target.closest("[data-person]");
    if (!button || subjective.busy) return;
    subjective.expert = button.dataset.person;
    sq("#subjective-message").textContent = "";
    renderSubjectiveRail(); renderSubjectiveEditor();
  });
  const editor = sq("#subjective-editor");
  editor.addEventListener("submit", saveSubjective);
  editor.addEventListener("input", event => {
    const input = event.target;
    if (input.id === "subjective-evaluator") subjectiveDraft().evaluator = input.value;
    else if (input.dataset.note) subjectiveDraft().ratings[input.dataset.note].note = input.value;
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
    const help = event.target.closest("[data-help]");
    if (help) { showSubjectiveTooltip(help); return; }
    const clear = event.target.closest("[data-clear]");
    if (clear) { delete subjectiveDraft().ratings[clear.dataset.clear]; subjectiveChanged(); renderSubjectiveEditor(); return; }
    if (event.target.closest("#subjective-facts")) openDimensionOneEvidence(subjective.expert);
  });
  editor.addEventListener("pointerover", event => { const b = event.target.closest("[data-help]"); if (b) showSubjectiveTooltip(b); });
  editor.addEventListener("pointerout", event => { if (event.target.closest("[data-help]") && event.relatedTarget !== sq("#subjective-tooltip")) hideSubjectiveTooltip(); });
  editor.addEventListener("focusin", event => { if (event.target.matches("[data-help]")) showSubjectiveTooltip(event.target); });
  editor.addEventListener("focusout", hideSubjectiveTooltip);
  sq("#subjective-tooltip").addEventListener("pointerleave", hideSubjectiveTooltip);
  document.addEventListener("keydown", event => { if (event.key === "Escape") hideSubjectiveTooltip(); });
  document.addEventListener("click", event => { if (!event.target.closest("[data-help], #subjective-tooltip")) hideSubjectiveTooltip(); });
  window.addEventListener("scroll", hideSubjectiveTooltip, true);
  window.addEventListener("resize", hideSubjectiveTooltip);
  window.addEventListener("beforeunload", event => {
    if (subjective.analysisId === state.analysis?.analysis_id && ([...subjective.drafts.values()].some(d => d.dirty) || Object.keys(state.analysis.subjective_reviews || {}).length)) {
      event.preventDefault(); event.returnValue = "";
    }
  });
}
