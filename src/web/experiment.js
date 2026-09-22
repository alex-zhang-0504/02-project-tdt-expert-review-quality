(() => {
  const dialog = document.querySelector('#experiment-dialog');
  const key = document.querySelector('#experiment-key');
  const status = document.querySelector('#experiment-status');
  const consent = document.querySelector('#ai-consent-dialog');
  const identify = document.querySelector('#identify-solutions');
  let token = '', busy = false, verified = false, expiresAt = 0, jobId = '', analysisId = '';
  let stopping = false, reconnecting = false, mode = 'pending', resumeId = '';
  const results = new Map();
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
  function sync() {
    const enabled = Boolean(token) && Date.now() < expiresAt;
    for (const name of ['save', 'test', 'disable']) {
      document.querySelector('#' + name + '-experiment').disabled = busy || Boolean(jobId) || (name !== 'save' && !enabled);
    }
    document.querySelector('#experiment-model').disabled = busy || Boolean(jobId) || enabled;
    key.disabled = busy || Boolean(jobId);
    renderIdentify();
  }
  function renderIdentify() {
    const analysis=state.analysis;
    if(!analysis)return;
    const data=results.get(analysis.analysis_id);
    const total=analysis.experts.reduce((n,e)=>n+e.overall.opinions,0);
    const pending=analysis.experts.reduce((n,e)=>n+e.overall.pending,0);
    const suspected=analysis.experts.reduce((n,e)=>n+e.overall.suspected,0);
    const active=jobId && analysisId===analysis.analysis_id;
    const count=data?`${data.completed}／${data.total}`:`${total-pending}／${total}`;
    identify.dataset.busy=active && stopping?'true':'false';
    if(active && stopping)identify.textContent='正在停止…';
    else if(active && reconnecting)identify.textContent='进度重连中 · 点击停止';
    else if(active)identify.textContent=`已识别${count}条 · 点击停止`;
    else if(data?.status==='cancelled')identify.textContent=`已停止${count}条 · 点击继续`;
    else if(data?.status==='partial')identify.textContent=`已识别${count}条 · 失败${data.failed}条 · 点击继续`;
    else if(!total || (!data && total===pending))identify.textContent='对策有效性识别';
    else identify.textContent=`已识别${count}条 · 疑似${suspected}条 · ${pending?'点击继续':'点击重新识别'}`;
    identify.title=data?.message || '按当前判定配置识别对策有效性，人工确认的选择予以保留。';
    syncServiceActions();
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
  document.querySelector('#configure-identification').addEventListener('click', () => { consent.close(); sync(); dialog.showModal(); readPolicy(); });
  document.querySelector('#close-experiment').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { key.value = ''; });
  document.querySelector('#save-experiment').addEventListener('click', () => action(async () => {
    const secret = key.value.trim(); key.value = ''; verified = false;
    const data = await request('settings', {api_key: secret, model: document.querySelector('#experiment-model').value});
    token = data.session; expiresAt = Date.now() + data.expires_in * 1000; results.clear();
    await verify();
  }));
  document.querySelector('#test-experiment').addEventListener('click', () => action(verify));
  document.querySelector('#disable-experiment').addEventListener('click', () => action(async () => {
    await request('disable'); token = ''; expiresAt = 0; verified = false; results.clear();
    status.textContent = '已关闭AI并清除内存密钥。';
  }));
  function showProgress(data) {
    if (state.analysis?.analysis_id !== data.analysis_id) return;
    results.set(data.analysis_id, data);
    stopping=data.status==='stopping';
    const label = {running: '正在识别', stopping: '正在停止', completed: '全部识别完成', partial: '识别结束，部分未完成', cancelled: '已停止'}[data.status];
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
      reconnecting=false;
      showProgress(data);
      if (!['running','stopping'].includes(data.status)) {
        jobId = ''; expiresAt = Date.now() + 3600000;
        stopping=false; sync();
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
        results.delete(analysisId); jobId = ''; stopping=false; sync();
        identify.textContent = '任务已失效 · 请重新识别';
        return;
      }
      reconnecting=true; renderIdentify(); identify.title='暂时无法读取进度，正在重连。'+error.message;
    }
    window.setTimeout(poll, 1200);
  }
  window.reviewAI = {refresh:renderIdentify, async start() {
    if (jobId) {
      if(stopping)return;
      stopping=true;renderIdentify();
      try {showProgress(await request('jobs/'+jobId+'/cancel'));}
      catch(error){stopping=false;renderIdentify();identify.textContent='停止请求未成功 · 点击重试';identify.title=error.message;}
      return;
    }
    if (!verified || Date.now() >= expiresAt) {
      status.textContent = '请先保存并验证AI配置。'; sync(); dialog.showModal(); await readPolicy(); return;
    }
    const total = state.analysis.experts.reduce((n,e)=>n+e.overall.opinions,0);
    if(!total){identify.textContent='无待识别意见';return;}
    const previous=results.get(state.analysis.analysis_id);
    const pending = state.analysis.experts.reduce((n, e) => n + e.overall.pending, 0);
    mode=previous && ['cancelled','partial'].includes(previous.status) && previous.completed<previous.total?'resume':pending?'pending':'all';
    resumeId=mode==='resume'?previous.id:'';
    const count=mode==='resume'?previous.total-previous.completed:mode==='all'?total:pending;
    analysisId = state.analysis.analysis_id;
    document.querySelector('#ai-consent-summary').textContent = `本次将${mode==='all'?'重新识别全部':'继续识别'}${count}条意见，按最新配置判定，保留人工确认选择。`;
    consent.showModal();
    await readPolicy();
  }};
  document.querySelector('#close-ai-consent').addEventListener('click', () => consent.close());
  document.querySelector('#start-ai-analysis').addEventListener('click', async event => {
    if (analysisId !== state.analysis?.analysis_id || state.analysisStale || jobId || !policyReceipt) return;
    const startButton = event.currentTarget; startButton.disabled = true;
    try {
      const data = await request('jobs', {analysis_id: analysisId, confirmed: true, policy_hash: policyReceipt.sha256, mode, resume_id:resumeId});
      jobId = data.id; consent.close(); showProgress(data);
      stopping=false; reconnecting=false; sync(); poll();
    } catch (error) { document.querySelector('#ai-consent-summary').textContent = error.message; policyReceipt = null; showPolicy(null, '任务未启动：' + error.message + ' 请重新打开窗口读取配置。'); }
    finally { startButton.disabled = !policyReceipt; }
  });
  window.setInterval(() => {
    if (token && Date.now() >= expiresAt && !busy && !jobId) {
      token = ''; verified = false; status.textContent = 'AI配置已过期，请重新配置。'; sync();
    }
  }, 5000);
})();
