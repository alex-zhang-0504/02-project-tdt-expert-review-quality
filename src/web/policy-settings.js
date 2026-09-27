(() => {
  const dialog = sq('#policy-settings-dialog');
  const status = sq('#policy-admin-status');
  let receipt = null, token = '', configured = false, busy = false, preview = null, scope = 'objective', editable = [], taskId = null;
  const groups = [
    ['阶段权重', [['stage_weights.TDR1','TDR1权重'],['stage_weights.TDR2','TDR2权重'],['stage_weights.TDR3','TDR3权重']]],
    ['客观基础与参与度', [['components.attendance','出勤满分'],['components.signoff','会签满分'],['components.opinion','意见满分'],['participation.minimum_sessions','参与度最低场次'],['participation.tier_scores.0','参与度高档'],['participation.tier_scores.1','参与度中档'],['participation.tier_scores.2','参与度低档']]],
    ['意见与奖励', [['opinion_threshold','每场意见基准条数'],['excess_opinion_points','超额意见每条奖励'],['solution_points','输出对策每条奖励']]],

  ];
  const valueAt = (obj, path) => path.split('.').reduce((value,key)=>value[key], obj);
  const api = (path, options={}) => requestJson('/api/assessment/admin/'+path, {...options, headers:{'Content-Type':'application/json','X-Policy-Request':'1','X-Policy-Session':token,...options.headers}});
  const button = document.createElement('button');
  button.id = 'open-policy-settings'; button.type='button'; button.className='ghost-button policy-settings-button';
  button.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M7 10V7a5 5 0 0 1 10 0v3"/><rect x="4" y="10" width="16" height="12" rx="2"/><path d="M12 14v4"/></svg><span>评分参数</span>';
  document.querySelector('#objective-table-footer').append(button);

  const subjectiveButton = button.cloneNode(true);
  subjectiveButton.id = 'open-subjective-settings';
  document.querySelector('#subjective-policy-footer').append(subjectiveButton);

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
  function renderFields() {
    sq('#policy-task-history').hidden=!taskId;
    if(taskId){const entries=receipt.history||[];sq('#policy-task-history').innerHTML=`<details><summary>参数修改记录（${entries.length}次）</summary>${entries.map(h=>`<p>${escapeHtml(h.at)} · ${escapeHtml(h.actor)} · ${escapeHtml(h.before.slice(0,12))} → ${escapeHtml(h.after.slice(0,12))} · 已重算</p>`).join('')||'<p>暂无修改。</p>'}</details>`;}
    editable = [];
    function field(path, label, numeric=false) {
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
      return `<label class="field"><span>${escapeHtml(label)}</span>${numeric ? `<input data-policy-path="${path}" type="number" min="0" step="any" required value="${value}" />` : `<textarea ${taskId&&receipt.content_locked?'disabled':''} data-policy-path="${path}" maxlength="2000" required rows="2">${value}</textarea>`}</label>`;
    }
    if (scope === 'objective') {
      sq('#policy-fields').innerHTML = groups.map(([title,fields])=>`<section class="policy-group"><h4>${title}</h4><div class="policy-field-grid">${fields.map(([path,label])=>field(path,label,true)).join('')}</div></section>`).join('');
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
  sq('#policy-fields').addEventListener('input',()=>{resetPreview();resizeTextareas();});
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
      preview=scope==='subjective'?parameters:Object.fromEntries(['stage_weights','components','opinion_threshold','participation','excess_opinion_points','solution_points'].map(k=>[k,parameters[k]]));
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
