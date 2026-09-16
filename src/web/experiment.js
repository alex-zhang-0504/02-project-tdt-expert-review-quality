(() => {
  const dialog = document.querySelector('#experiment-dialog');
  const key = document.querySelector('#experiment-key');
  const status = document.querySelector('#experiment-status');
  const consent = document.querySelector('#ai-consent-dialog');
  const cancel = document.querySelector('#cancel-ai-analysis');
  let token = '', busy = false, verified = false, expiresAt = 0, jobId = '', analysisId = '';
  let policyReceipt = null;
  function showPolicy(receipt, message = '') {
    for (const id of ['ai-policy-settings', 'ai-policy-consent']) {
      const node = document.getElementById(id);
      node.textContent = receipt ? `判定配置已读取并校验 · V${receipt.version} · ${receipt.file} · 已确认案例${receipt.confirmed_examples}条 · 指纹${receipt.sha256.slice(0,12)} · 读取时间${new Date(receipt.loaded_at).toLocaleString()}。此状态证明后台读取成功，不代表模型判定正确。` : message;
      node.style.borderLeft = `4px solid ${receipt ? 'var(--success)' : 'var(--danger)'}`;
    }
  }
  async function readPolicy() {
    policyReceipt = null;
    showPolicy(null, '判定配置：正在读取，尚未确认成功。');
    document.querySelector('#start-ai-analysis').disabled = true;
    try {
      const receipt = await request('policy');
      if (!receipt.loaded || !receipt.sha256) throw new Error('未取得有效配置读取凭据，禁止分析。');
      policyReceipt = receipt; showPolicy(receipt);
      document.querySelector('#start-ai-analysis').disabled = false;
      return true;
    } catch (error) { showPolicy(null, '判定配置未就绪：' + error.message); return false; }
  }
  document.querySelector('#reload-ai-policy').addEventListener('click', readPolicy);
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'ghost-button'; button.id = 'open-experiment';
  button.textContent = 'AI设置';
  document.querySelector('.topbar').append(button);
  function sync() {
    const enabled = Boolean(token) && Date.now() < expiresAt;
    for (const name of ['save', 'test', 'disable']) {
      document.querySelector('#' + name + '-experiment').disabled = busy || Boolean(jobId) || (name !== 'save' && !enabled);
    }
    document.querySelector('#experiment-model').disabled = busy || Boolean(jobId) || enabled;
    key.disabled = busy || Boolean(jobId);
    button.textContent = verified && enabled ? 'AI已配置' : 'AI设置';
    cancel.hidden = !jobId;
    document.querySelector('.ai-action-group').classList.toggle('is-running', Boolean(jobId));
    document.querySelector('#facts-ai-label').textContent = jobId ? 'AI分析中' : 'AI对策分析';
  }
  async function request(path, body = {}) {
    const response = await fetch('/api/experiment/' + path, {
      method: 'POST', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-Experiment-Request': '1', 'X-Experiment-Session': token},
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) {
      const message = response.status === 404 && path === 'jobs'
        ? '当前后台是旧版本，没有全量AI分析接口。请重新双击start.cmd，使用新打开的页面重新导入并配置AI；刷新旧页面不能更新后台。'
        : typeof data.detail === 'string' ? data.detail : data.message || 'AI请求失败。';
      const error = new Error(message);
      error.status = response.status; throw error;
    }
    return data;
  }
  async function action(fn) {
    if (busy || jobId) return;
    busy = true; sync(); status.textContent = '正在验证连接，请稍候…';
    try { await fn(); }
    catch (error) { verified = false; status.textContent = error.message || '请求失败，请检查本地服务。'; if (error.message.includes('判定配置')) { policyReceipt = null; showPolicy(null, error.message); } }
    finally { busy = false; sync(); }
  }
  async function verify() {
    verified = false;
    const data = await request('test');
    showPolicy(data.policy);
    verified = true; expiresAt = Date.now() + 3600000;
    status.textContent = '配置成功 · ' + data.model + '，连接及结果格式验证通过。可关闭此窗口开始全量分析。';
  }
  button.addEventListener('click', () => { sync(); dialog.showModal(); readPolicy(); });
  document.querySelector('#close-experiment').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { key.value = ''; });
  document.querySelector('#save-experiment').addEventListener('click', () => action(async () => {
    const secret = key.value.trim(); key.value = ''; verified = false;
    const data = await request('settings', {api_key: secret, model: document.querySelector('#experiment-model').value});
    token = data.session; expiresAt = Date.now() + data.expires_in * 1000;
    await verify();
  }));
  document.querySelector('#test-experiment').addEventListener('click', () => action(verify));
  document.querySelector('#disable-experiment').addEventListener('click', () => action(async () => {
    await request('disable'); token = ''; expiresAt = 0; verified = false;
    status.textContent = '已关闭AI并清除内存密钥。';
  }));
  function showProgress(data) {
    if (state.analysis?.analysis_id !== data.analysis_id) return;
    const label = {running: '正在分析', completed: '全部分析完成', partial: '分析结束，部分未完成', cancelled: '已停止'}[data.status];
    const total = data.analysis.experts.reduce((n, e) => n + e.overall.opinions, 0);
    const pending = data.analysis.experts.reduce((n, e) => n + e.overall.pending, 0);
    showPolicy(data.policy);
    data.analysis.ai_message = `${label}：本批次${total - pending}／${total}条已识别；本次成功${data.completed}条（疑似${data.suspected}条），失败${data.failed}条，剩余${data.remaining}条。${data.message} 本任务已载入规则V${data.policy.version}（${data.policy.sha256.slice(0,12)}）。逐条结论见详情。`;
    state.analysis = data.analysis;
    const horizontal = elements.dimensionOneTableWrap.scrollLeft;
    renderDimensionOneTable(); elements.dimensionOneTableWrap.scrollLeft = horizontal;
  }
  async function poll() {
    if (!jobId) return;
    try {
      const data = await request('jobs/' + jobId);
      showProgress(data);
      if (data.status !== 'running') {
        jobId = ''; expiresAt = Date.now() + 3600000;
        setBusy(document.querySelector('#identify-solutions'), false); sync();
        if (state.analysis?.analysis_id === data.analysis_id) {
          if (state.activeStep === 4) await refreshScoreStatistics();
          if (state.activeStep === 3) renderSubjectiveEditor();
          if (elements.evidenceDrawer.open) {
            const scroll = elements.evidenceDrawerContent.scrollTop;
            openDimensionOneEvidence(evidenceExpertName);
            elements.evidenceDrawerContent.scrollTop = scroll;
          }
        }
        return;
      }
    } catch (error) {
      if (error.status === 404) {
        jobId = ''; sync(); setBusy(document.querySelector('#identify-solutions'), false);
        document.querySelector('#facts-ai-status').textContent = '当前服务中已无此任务，请重新读取报告后识别。';
        return;
      }
      document.querySelector('#facts-ai-status').textContent = '暂时无法读取进度，正在重连。' + error.message;
    }
    window.setTimeout(poll, 1200);
  }
  window.reviewAI = {async start() {
    if (jobId) { document.querySelector('#facts-ai-status').textContent = '当前任务正在分析，请等待完成。'; return; }
    if (!verified || Date.now() >= expiresAt) {
      status.textContent = '请先保存并验证AI配置。'; sync(); dialog.showModal(); await readPolicy(); return;
    }
    const count = state.analysis.experts.reduce((n, e) => n + e.overall.pending, 0);
    if (!count) { document.querySelector('#facts-ai-status').textContent = '全部意见已有结果，无需重复分析。'; return; }
    analysisId = state.analysis.analysis_id;
    document.querySelector('#ai-consent-summary').textContent = `本次将逐条分析全部${count}条待处理意见。`;
    consent.showModal();
    await readPolicy();
  }};
  document.querySelector('#close-ai-consent').addEventListener('click', () => consent.close());
  document.querySelector('#start-ai-analysis').addEventListener('click', async event => {
    if (analysisId !== state.analysis?.analysis_id || state.analysisStale || jobId || !policyReceipt) return;
    const startButton = event.currentTarget; startButton.disabled = true;
    try {
      const data = await request('jobs', {analysis_id: analysisId, confirmed: true, policy_hash: policyReceipt.sha256});
      jobId = data.id; consent.close(); showProgress(data);
      setBusy(document.querySelector('#identify-solutions'), true, '正在逐条分析…'); sync(); poll();
    } catch (error) { document.querySelector('#ai-consent-summary').textContent = error.message; policyReceipt = null; showPolicy(null, '任务未启动：' + error.message + ' 请重新打开窗口读取配置。'); }
    finally { startButton.disabled = !policyReceipt; }
  });
  cancel.addEventListener('click', async () => {
    if (!jobId) return;
    try { const data = await request('jobs/' + jobId + '/cancel'); document.querySelector('#facts-ai-status').textContent = data.message; }
    catch (error) { document.querySelector('#facts-ai-status').textContent = error.message; }
  });
  window.setInterval(() => {
    if (token && Date.now() >= expiresAt && !busy && !jobId) {
      token = ''; verified = false; status.textContent = 'AI配置已过期，请重新配置。'; sync();
    }
  }, 5000);
})();
