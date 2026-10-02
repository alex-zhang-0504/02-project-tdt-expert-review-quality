(() => {
  const dialog = sq('#policy-settings-dialog');
  const status = sq('#policy-admin-status');
  let receipt = null, token = '', configured = false, busy = false, preview = null, scope = 'objective', editable = [], taskId = null;
  const groups = [
    ['有TDR1&2&3', [['stage_percentages.all.TDR1','TDR1（％）'],['stage_percentages.all.TDR2','TDR2（％）'],['stage_percentages.all.TDR3','TDR3（％）']], '默认TDR1：40％，TDR2：20％，TDR3：40％'],
    ['只有TDR1和TDR3', [['stage_percentages.first_third.TDR1','TDR1（％）'],['stage_percentages.first_third.TDR3','TDR3（％）']], '默认TDR1：50％，TDR3：50％'],
    ['只有TDR1/3和TDR2', [['stage_percentages.with_second.TDR1_or_TDR3','TDR1/3（％）'],['stage_percentages.with_second.TDR2','TDR2（％）']], '默认TDR1/3：65％，TDR2：35％'],
    ['只有TDR1/2/3', [], '默认100％（固定）'],
    ['客观基础', [['components.attendance','出勤满分（分数）'],['components.signoff','会签满分（分数）'],['components.opinion','意见满分（分数）']]],
    ['参与度', [['participation.minimum_sessions','参与度最低场次（场次）'],['participation.tier_scores.0','参与度高档（分数）'],['participation.tier_scores.1','参与度中档（分数）'],['participation.tier_scores.2','参与度低档（分数）']]],
    ['意见与奖励', [['opinion_threshold','每场意见基准条数（条／场）'],['excess_opinion_points','超额意见每条奖励（分数）'],['solution_points','输出对策每条奖励（分数）']]],

  ];
  const fraction = (numerator, denominator) => `<span class="policy-fraction" role="math" aria-label="${escapeHtml(numerator)}除以${escapeHtml(denominator)}"><span>${escapeHtml(numerator)}</span><span>${escapeHtml(denominator)}</span></span>`;
  const objectiveFormula = `
    <span class="policy-formula-section">按本任务读取的参数计算，下面的满分、权重、门槛及奖励均对应页面参数。</span>
    <span class="policy-formula-section">① 每个阶段分别计算
      <span class="policy-equation">出勤得分＝出勤满分 × ${fraction('实参场次','应参场次')}</span>
      <span class="policy-equation">会签得分＝会签满分 × ${fraction('会签场次','应参场次')}</span>
      <span class="policy-equation">意见得分＝意见满分 × ${fraction('意见条数','实参场次 × 每场意见基准条数')}</span>
      <span class="policy-formula-line">意见得分最高取「意见满分」；阶段得分＝出勤得分＋会签得分＋意见得分。</span>
    </span>
    <span class="policy-formula-section">② 把适用阶段合成为一个分数
      <span class="policy-equation">阶段加权＝各适用阶段的（阶段得分 × 对应百分比）相加。</span>
      <span class="policy-formula-line">按有应参任务的阶段选用对应组合，每组独立设置，合计须为100％。有应参任务但缺席的阶段仍参与计算。</span>
      <span class="policy-formula-line">「TDR1/3」表示TDR1或TDR3，和TDR2搭配时共用同一组百分比，修改同时作用于两种情况。只有一个阶段时固定100％。</span>
      <span class="policy-formula-line">示例：只有TDR1和TDR2，阶段得分分别为25分、15分，使用默认65％、35％时：</span>
      <span class="policy-equation">阶段加权＝（25 × 65％）＋（15 × 35％）＝21.5分。</span>
    </span>
    <span class="policy-formula-section">③ 参与度与基础得分
      <span class="policy-formula-line">按本期完整名单的实参场次降序，前10％取高档分，超过10％至30％取中档分，其余取低档分。人数分界向上取整，采用并列占位名次（如1、1、3），并列跨界取高档；未达最低场次取低档分。</span>
      <span class="policy-formula-line">示例：10人参加10、10、9、8、7、6、5、4、3、2场，前两人取高档，第三人取中档，其余取低档；14人分界为第2、5名。页面筛选不改变范围。</span>
      <span class="policy-equation">基础得分＝阶段加权＋参与度得分</span>
    </span>
    <span class="policy-formula-section">④ 两项奖励与客观总得分
      <span class="policy-formula-line">每阶段超额条数＝意见条数－（实参场次 × 每场意见基准条数），小于0时取0。</span>
      <span class="policy-formula-line">评审意见超额得分＝各阶段超额条数相加 × 超额意见每条奖励。</span>
      <span class="policy-formula-line">输出有效对策得分＝计入有效对策的意见条数 × 输出对策每条奖励。疑似未确认不计入，人工确认后按选择计入或排除。</span>
      <span class="policy-formula-line">客观总得分＝基础得分＋评审意见超额得分＋输出有效对策得分。</span>
      <span class="policy-formula-line">两项奖励不乘阶段权重；使用未舍入数值计算，最终按任务精度显示。出勤未知、实参为0等异常以校验结果为准，不强行除算。</span>
    </span>`;
  const valueAt = (obj, path) => path.split('.').reduce((value,key)=>value[key], obj);
  const api = (path, options={}) => requestJson('/api/assessment/admin/'+path, {...options, headers:{'Content-Type':'application/json','X-Policy-Request':'1','X-Policy-Session':token,...options.headers}});
  const button = document.createElement('button');
  button.id = 'open-policy-settings'; button.type='button'; button.className='ghost-button policy-settings-button';
  button.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M7 10V7a5 5 0 0 1 10 0v3"/><rect x="4" y="10" width="16" height="12" rx="2"/><path d="M12 14v4"/></svg><span>评分参数</span>';
  document.querySelector('#objective-table-footer').append(button);

  const subjectiveButton = button.cloneNode(true);
  subjectiveButton.id = 'open-subjective-settings';
  document.querySelector('#subjective-policy-footer')?.append(subjectiveButton);

  function refreshAccess() {
    if(taskId){configured=true;sq('#policy-unlock').textContent='解锁修改';}

    sq('#policy-fields').disabled = !token || busy;
    sq('#policy-save').disabled = !token || busy || !receipt;
    sq('#policy-save').textContent = busy ? '正在处理…' : preview ? '确认并永久保存' : '预览修改';
    sq('#policy-unlock').disabled = busy || !receipt;
    sq('#policy-unlock-form').hidden = !!token;
    sq('#policy-confirm-field').hidden = configured || !!taskId;
    sq('#policy-password-confirm').required = !configured && !taskId;
    sq('#policy-password').required = !taskId;
    sq('#policy-password').closest('label').hidden = !!taskId;
    sq('#policy-unlock').textContent = taskId ? '解锁修改' : configured ? '解锁修改' : '设置密码并解锁';
    sq('#policy-auth-hint').textContent = taskId ? '已使用管理员身份登录。解锁后可修改，保存后自动锁定。' : configured ? '输入管理员密码后可修改，不设时限。永久保存后自动锁定；关闭窗口将放弃未保存的修改。' : '首次使用：请由本机管理员设置密码（8至128位）。密码不设默认值，仅保存加盐哈希。';
    sq('#policy-relock').hidden = !token;
    sq('#policy-relock').disabled = busy;
    sq('#close-policy-settings').disabled = busy;
  }
  function resetPreview() {
    preview = null; sq('#policy-change-preview').hidden=true; refreshAccess();
  }
  function validateStagePercentages(locate=false) {
    const errors=[];
    sq('#policy-fields').querySelectorAll('[data-percentage-group]').forEach(section=>{
      const inputs=[...section.querySelectorAll('input')];
      const values=inputs.map(input=>input.value===''?NaN:Number(input.value));
      const total=values.reduce((a,b)=>a+b,0);
      const invalidValue=values.some(v=>!Number.isFinite(v)||v<0||v>100);
      const message=invalidValue?'每项须填写0—100％的数值。':Math.abs(total-100)>1e-8?`当前合计${Number(total.toFixed(2))}％，${total<100?'未达到':'超过'}100％，请调整至100％。`:'';
      const hint=section.querySelector('.policy-percentage-error');
      hint.textContent=message;hint.hidden=!message;
      section.classList.toggle('policy-group-invalid',!!message);
      inputs.forEach(input=>{if(message)input.setAttribute('aria-invalid','true');else input.removeAttribute('aria-invalid');});
      if(message)errors.push(section);
    });
    if(errors.length){
      status.textContent='';
      if(locate){errors[0].scrollIntoView({block:'center',behavior:'smooth'});errors[0].querySelector('input').focus({preventScroll:true});}
    } else if(status.dataset.percentageError==='true') status.textContent='百分比合计校验通过，请预览修改。';
    status.dataset.percentageError=String(!!errors.length);
    return !errors.length;
  }
  function renderFields() {
    status.dataset.percentageError='false';
    sq('#policy-task-history').hidden=!taskId;
    if(taskId){const entries=receipt.history||[];sq('#policy-task-history').innerHTML=`<details><summary>参数修改记录（${entries.length}次）</summary>${entries.map(h=>`<p>${escapeHtml(h.at)} · ${escapeHtml(h.actor)} · ${escapeHtml(h.before.slice(0,12))} → ${escapeHtml(h.after.slice(0,12))} · 已重算</p>`).join('')||'<p>暂无修改。</p>'}</details>`;}
    editable = [];
    function field(path, label, numeric=false) {
      if (scope === 'subjective' && numeric) label += '（分数）';
      let context = '';
      if (scope === 'subjective' && path.startsWith('dimensions.')) {
        const parts=path.split('.'), d=receipt.parameters.dimensions[Number(parts[1])];
        context=`第${Number(parts[1])+1}题${parts[2]==='options'?' · '+d.options[Number(parts[3])].title:''} · `;
      } else if (scope === 'subjective' && path.startsWith('scores.')) {
        const [,id,tier]=path.split('.'), d=receipt.parameters.dimensions.find(d=>d.id===id);
        context=d.title+' · '+d.options.find(o=>o.id===tier).title+' · ';
      }
      editable.push([path,context+label,numeric]);
      const value = escapeHtml(String(valueAt(receipt.parameters,path)));
      return `<label class="field"><span>${escapeHtml(label)}</span>${numeric ? `<input data-policy-path="${path}" type="number" min="0" ${path.startsWith('stage_percentages.')?`max="100" step="0.01" aria-describedby="policy-weight-error-${path.split('.')[1]}"`:'step="any"'} required value="${value}" />` : `<textarea ${taskId&&receipt.content_locked?'disabled':''} data-policy-path="${path}" maxlength="2000" required rows="2">${value}</textarea>`}</label>`;
    }
    if (scope === 'objective') {
      sq('#policy-fields').innerHTML = groups.map(([title,fields,hint])=>{
        const key=fields[0]?.[0].startsWith('stage_percentages.')?fields[0][0].split('.')[1]:'';
        return `<section class="policy-group" ${key?`data-percentage-group="${key}"`:''}><h4>${escapeHtml(title)}</h4>${hint?`<p class="policy-default-hint">${hint}</p>`:''}<div class="policy-field-grid">${fields.map(([path,label])=>field(path,label,true)).join('')}${hint&&!fields.length?'<span>100％</span>':''}</div>${key?`<p id="policy-weight-error-${key}" class="policy-percentage-error" role="alert" hidden></p>`:''}</section>`;
      }).join('');
    } else {
      const p=receipt.parameters;
      sq('#policy-fields').innerHTML = `<section class="policy-group"><h4>统一填写说明</h4>${field('instructions','首次进入说明')}${field('unable.title','无法判断卡片标题')}${field('unable.description','无法判断卡片解释')}${field('unable.reason_prompt','原因填写提示')}${field('contribution_prompt','突出贡献依据提示')}</section>` + p.dimensions.map((d,i)=>`<section class="policy-group"><h4>${i+1}．${escapeHtml(d.title)}</h4>${field(`dimensions.${i}.title`,'问题标题')}${field(`dimensions.${i}.prompt`,'题干')}${field(`dimensions.${i}.boundary`,'职责边界')}<div class="policy-question-options">${d.options.map((o,j)=>`<div class="policy-option-editor">${field(`dimensions.${i}.options.${j}.title`,'卡片标题')}${field(`dimensions.${i}.options.${j}.description`,'卡片解释')}${field(`scores.${d.id}.${o.id}`,'对应分值',true)}${taskId?`<label class="policy-evidence-toggle"><input type="checkbox" data-policy-evidence="${d.id}" value="${o.id}" ${p.evidence[d.id].includes(o.id)?'checked':''} ${receipt.content_locked?'disabled':''}/>此档必须提供事实依据</label>`:''}</div>`).join('')}</div></section>`).join('');
    }
    resetPreview();
    resizeTextareas();
  }
  function resizeTextareas() {
    sq('#policy-fields').querySelectorAll('textarea').forEach(input => {
      input.style.height='auto';
      input.style.height=(input.scrollHeight+2)+'px';
    });
  }
  let fieldsWidth=0;
  new ResizeObserver(entries=>{
    const width=entries[0].contentRect.width;
    if(width!==fieldsWidth){fieldsWidth=width;resizeTextareas();}
  }).observe(sq('#policy-fields'));
  async function relock() {
    if(token && !taskId) { try { await api('lock',{method:'POST',keepalive:true}); } catch { /* Discard the local capability even if the service is unreachable. */ } }
    token=''; resetPreview();
    if(receipt)renderFields();
  }
  async function openSettings(nextScope,nextTaskId=null) {
    scope=nextScope;taskId=nextTaskId;token='';preview=null;
    const scopeNote=taskId?'保存后同步对应配置并重算本任务，其他已创建任务保留原参数，新任务读取更新后的配置。':'修改后用于新的考核，已经开始的考核仍使用原配置。';
    const hint=dialog.querySelector('.note-row .info-tip');hint.setAttribute('aria-label',scopeNote);hint.querySelector('.info-tip-text').textContent=scopeNote;
    sq('#policy-settings-title').textContent=scope==='subjective'?'主观评分参数与问卷':'客观评分参数';
    sq('#policy-formula-note').innerHTML=scope==='objective'?`<button class="info-tip policy-formula-tip" type="button" aria-label="查看客观计分公式" aria-describedby="policy-formula-content"><span class="info-tip-icon" aria-hidden="true">!</span><span id="policy-formula-content" class="info-tip-text" role="tooltip">${objectiveFormula}</span></button>`:'';
    dialog.showModal(); dialog.scrollTop=0; busy=true; receipt=null; status.textContent='正在读取评分参数…'; refreshAccess();
    try {
      const [access, policy]=taskId?[{configured:true},await requestJson('/api/workspace/tasks/'+taskId+'/policy/'+scope)]:await Promise.all([api('status'),api('policy/'+scope)]);
      configured=access.configured; receipt=policy; renderFields();
      status.textContent=`已读取 ${policy.file} · V${policy.version}；${taskId?'保存后同步配置、重算本任务，其他任务保留原参数。':''}${policy.content_locked?'问卷已开始，题干、选项及依据要求只读。':''}`;
    } catch(error) {status.textContent=error.message;}
    finally {busy=false;refreshAccess();}
  };
  window.openTaskPolicy=async(id,kind)=>{if(await flushSubjectiveChanges())return openSettings(kind,id);};
  if(window.workspace){button.hidden=true;subjectiveButton.hidden=true;}
  button.onclick=()=>openSettings('objective');
  subjectiveButton.onclick=()=>openSettings('subjective');
  sq('#policy-unlock-form').onsubmit=async event=> {
    event.preventDefault(); if(busy)return; busy=true;refreshAccess();
    try {
      const result=taskId?{token:'workspace'}:await api('unlock',{method:'POST',body:JSON.stringify({setup:!configured,password:sq('#policy-password').value,confirmation:sq('#policy-password-confirm').value})});
      configured=true; token=result.token;
      status.textContent='已解锁，可修改参数。仅完整通过校验并写后核验成功，才显示保存成功。';
    } catch(error) {status.textContent=error.message;}
    finally {sq('#policy-password').value='';sq('#policy-password-confirm').value='';busy=false;refreshAccess();}
  };
  sq('#policy-fields').addEventListener('input',()=>{resetPreview();resizeTextareas();if(scope==='objective'&&status.dataset.percentageError==='true')validateStagePercentages();});
  sq('#policy-editor-form').onsubmit=async event=> {
    event.preventDefault(); if(busy || !token || !receipt)return;
    if(!preview) {
      const parameters=structuredClone(receipt.parameters), changes=[];
      for(const [path,label,numeric] of editable) {
        const input=sq(`[data-policy-path="${path}"]`).value;
        const value=numeric?Number(input):input.trim();
        if(value!==valueAt(receipt.parameters,path))changes.push(`${label}：${valueAt(receipt.parameters,path)} → ${value}`);
        const parts=path.split('.'), key=parts.pop();
        let target=parameters; for(const part of parts)target=target[part]; target[key]=value;
      }
      if(taskId && scope==='subjective'){sq('#policy-fields').querySelectorAll('[data-policy-evidence]').forEach(input=>{const list=parameters.evidence[input.dataset.policyEvidence],had=list.includes(input.value);if(input.checked!==had){parameters.evidence[input.dataset.policyEvidence]=input.checked?[...list,input.value]:list.filter(x=>x!==input.value);changes.push('事实依据要求已修改');}});}
      if(!changes.length){status.textContent='参数未变化，无需写入。';return;}
      if(scope==='objective'&&!validateStagePercentages(true))return;
      preview=scope==='subjective'?parameters:Object.fromEntries(['stage_percentages','components','opinion_threshold','participation','excess_opinion_points','solution_points'].map(k=>[k,parameters[k]]));
      status.textContent='请核对修改后确认保存。';
      sq('#policy-change-preview').innerHTML=`<p>请核对以下修改，保存后${taskId?'同步配置并重算本任务，其他已有任务不变':'用于新考核'}：</p><ul>${changes.map(c=>`<li>${escapeHtml(c)}</li>`).join('')}</ul>`;
      sq('#policy-change-preview').hidden=false;refreshAccess();sq('#policy-change-preview').scrollIntoView({block:'nearest'});return;
    }
    busy=true;refreshAccess();
    try {
      receipt=taskId?await requestJson('/api/workspace/tasks/'+taskId+'/policy/'+scope,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({file_hash:receipt.file_hash,task_revision:receipt.task_revision,parameters:preview})}):await api('policy/'+scope,{method:'PUT',body:JSON.stringify({previous_hash:receipt.sha256,parameters:preview})});
      token='';
      renderFields();
      status.textContent=taskId?'已永久保存并同步配置，本任务评分已更新，原问卷保留；其他已有任务不变。':'已永久保存并自动锁定，新参数用于新建考核。';
      if(taskId){subjective.catalog=null;subjective.analysisId=null;subjective.drafts.clear();if(state.analysis?.analysis_id===taskId)state.analysis=await requestJson('/api/workspace/analyses/'+taskId);await window.workspace.home();}
      if(!state.analysis?.assessment?.confirmed) {assessmentUI.policy=null;sq('#assessment-policy').textContent='评分参数已更新，请读取最新配置。';syncAssessmentActions();}
    } catch(error) {status.textContent=error.message;}
    finally {busy=false;refreshAccess();status.scrollIntoView({block:'nearest'});}
  };
  sq('#policy-relock').onclick=async()=>{await relock();status.textContent='已结束修改，当前为只读。';};
  sq('#close-policy-settings').onclick=async()=>{if(busy)return;await relock();dialog.close();};
  dialog.addEventListener('cancel',event=>{event.preventDefault();if(!busy)sq('#close-policy-settings').click();});
  window.addEventListener('pagehide',()=>{if(token)void relock();});
})();
