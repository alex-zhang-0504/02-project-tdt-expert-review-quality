const objectiveFilter = {analysisId: null, names: null};

function objectiveReviewers() {
  if (objectiveFilter.analysisId !== state.analysis?.analysis_id) {
    objectiveFilter.analysisId = state.analysis?.analysis_id;
    objectiveFilter.names = null;
  }
  const included = state.analysis?.assessment?.included;
  return (state.analysis?.experts || []).filter(e => !included || included.includes(e.expert_name));
}
function objectiveReviewerVisible(name) {
  return objectiveFilter.names === null || objectiveFilter.names.has(name);
}
function objectiveReviewerHeader() {
  const all = objectiveReviewers();
  const selected = all.filter(e => objectiveReviewerVisible(e.expert_name)).length;
  return `<button type="button" class="reviewer-filter-trigger" data-reviewer-filter aria-haspopup="dialog">评审人 <span aria-hidden="true">▾</span><small>${selected === all.length ? '全部' : '已选' + selected + '人'}</small></button>`;
}
function refreshObjectiveFilter() {
  renderDimensionOneTable();
  const scoreHost = document.querySelector('#objective-page-two');
  scoreHost.querySelectorAll('tbody tr[data-reviewer]').forEach(row => {
    row.hidden = !objectiveReviewerVisible(row.dataset.reviewer);
  });
  scoreHost.querySelectorAll('thead th:first-child').forEach(th => th.innerHTML = objectiveReviewerHeader());
  const empty = scoreHost.querySelector('[data-reviewer-empty]');
  if (empty) empty.hidden = !!objectiveReviewers().some(e => objectiveReviewerVisible(e.expert_name));
  document.querySelector('#reviewer-filter-count').textContent = '已选' + objectiveReviewers().filter(e => objectiveReviewerVisible(e.expert_name)).length + '人';
}
function renderReviewerChoices() {
  const query = normalizedReviewerSearch(document.querySelector('#reviewer-filter-search').value);
  const experts = objectiveReviewers().filter(e => reviewerMatchesSearch(e, query));
  document.querySelector('#reviewer-filter-list').innerHTML = experts.map(e => `<label><input type="checkbox" value="${escapeHtml(e.expert_name)}" ${objectiveReviewerVisible(e.expert_name) ? 'checked' : ''} /><span>${escapeHtml(e.expert_name)}</span></label>`).join('') || '<p>没有匹配的评审人。</p>';
  document.querySelector('#reviewer-filter-count').textContent = '已选' + objectiveReviewers().filter(e => objectiveReviewerVisible(e.expert_name)).length + '人';
}
document.addEventListener('click', event => {
  const dialog = document.querySelector('#reviewer-filter-dialog');
  const trigger = event.target.closest('[data-reviewer-filter]');
  if (trigger) {
    const rect = trigger.getBoundingClientRect();
    document.querySelector('#reviewer-filter-search').value = '';
    renderReviewerChoices();
    dialog.show();
    dialog.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - dialog.offsetWidth - 8)) + 'px';
    dialog.style.top = Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - dialog.offsetHeight - 8)) + 'px';
    document.querySelector('#reviewer-filter-search').focus();
    return;
  }
  const action = event.target.closest('[data-reviewer-select]');
  if (action) {
    objectiveFilter.names = action.dataset.reviewerSelect === 'all' ? null : new Set();
    refreshObjectiveFilter();
    renderReviewerChoices();
  }
  if (event.target.closest('[data-reviewer-filter-close]') || (dialog.open && !dialog.contains(event.target))) dialog.close();
});
document.addEventListener('input', event => {
  if (event.target.id === 'reviewer-filter-search') renderReviewerChoices();
});
document.addEventListener('change', event => {
  if (!event.target.matches('#reviewer-filter-list input')) return;
  if (objectiveFilter.names === null) objectiveFilter.names = new Set(objectiveReviewers().map(e => e.expert_name));
  if (event.target.checked) objectiveFilter.names.add(event.target.value);
  else objectiveFilter.names.delete(event.target.value);
  refreshObjectiveFilter();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') document.querySelector('#reviewer-filter-dialog').close();
});
