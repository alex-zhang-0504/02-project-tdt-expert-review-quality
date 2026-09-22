(() => {
  const dialog = sq('#policy-settings-dialog');
  const status = sq('#policy-admin-status');
  let receipt = null, token = '', configured = false, busy = false, preview = null, expiry;
  const groups = [
    ['阶段权重', [['stage_weights.TDR1','TDR1权重'],['stage_weights.TDR2','TDR2权重'],['stage_weights.TDR3','TDR3权重']]],
    ['客观基础与参与度', [['components.attendance','出勤满分'],['components.signoff','会签满分'],['components.opinion','意见满分'],['participation.minimum_sessions','参与度最低场次'],['participation.tier_scores.0','参与度高档'],['participation.tier_scores.1','参与度中档'],['participation.tier_scores.2','参与度低档']]],
    ['意见与奖励', [['opinion_threshold','每场意见基准条数'],['excess_opinion_points','超额意见每条奖励'],['solution_points','输出对策每条奖励']]],
    ['主观评价各档分值', [['preparation','项目理解与评审准备'],['judgment','风险识别与专业判断'],['guidance','改善建议与方案指导'],['verification','验证把关与闭环质量'],['collaboration','沟通协作与评审担当'],['contribution','突出贡献']].flatMap(([key,label]) => (key==='contribution'?['high','low']:['high','medium','low']).map(tier=>[`subjective.${key}.${tier}`,`${label} · ${{high:'高档',medium:'中档',low:'低档'}[tier]}`]))],
    ['总分与精度', [['total_cap','总分上限'],['precision','分数小数位数']]],
  ];
  const valueAt = (obj, path) => path.split('.').reduce((value,key)=>value[key], obj);
  const api = (path, options={}) => requestJson('/api/assessment/admin/'+path, {...options, headers:{'Content-Type':'application/json','X-Policy-Request':'1','X-Policy-Session':token,...options.headers}});
  const button = document.createElement('button');
  button.id = 'open-policy-settings'; button.type='button'; button.className='ghost-button policy-settings-button';
  button.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M7 10V7a5 5 0 0 1 10 0v3"/><rect x="4" y="10" width="16" height="12" rx="2"/><path d="M12 14v4"/></svg><span>评分参数</span>';
  document.querySelector('#objective-table-footer').append(button);

  function refreshAccess() {
    sq('#policy-fields').disabled = !token || busy;
    sq('#policy-save').disabled = !token || busy || !receipt;
    sq('#policy-save').textContent = busy ? '正在处理…' : preview ? '确认并永久保存' : '预览修改';
    sq('#policy-unlock').disabled = busy || !receipt;
    sq('#policy-unlock-form').hidden = !!token;
    sq('#policy-confirm-field').hidden = configured;
    sq('#policy-password-confirm').required = !configured;
    sq('#policy-unlock').textContent = configured ? '解锁修改' : '设置密码并解锁';
    sq('#policy-auth-hint').textContent = configured ? '当前为只读。输入管理员密码后可修改，授权有效期10分钟。' : '首次使用：请由本机管理员设置密码（8至128位）。密码不设默认值，仅保存加盐哈希。';
    sq('#policy-relock').hidden = !token;
    sq('#policy-relock').disabled = busy;
    sq('#close-policy-settings').disabled = busy;
  }
  function resetPreview() {
    preview = null; sq('#policy-change-preview').hidden=true; refreshAccess();
  }
  function renderFields() {
    sq('#policy-fields').innerHTML = groups.map(([title,fields])=>`<section class="policy-group"><h4>${title}</h4><div class="policy-field-grid">${fields.map(([path,label])=> {
      const integer=['precision','participation.minimum_sessions'].includes(path);
      const min=path==='participation.minimum_sessions'?1:path.startsWith('stage_weights.') || ['opinion_threshold','total_cap'].includes(path)?0.0001:0;
      return `<label class="field"><span>${label}</span><input data-policy-path="${path}" type="number" min="${min}" ${path==='precision'?'max="4"':''} step="${integer?'1':'any'}" required value="${valueAt(receipt.parameters,path)}" /></label>`;
    }).join('')}</div></section>`).join('');
    resetPreview();
  }
  async function relock() {
    clearTimeout(expiry);
    if(token) { try { await api('lock',{method:'POST'}); } catch { /* Authorization also expires server-side. */ } }
    token=''; resetPreview();
  }
  button.onclick=async()=> {
    dialog.showModal(); dialog.scrollTop=0; busy=true; receipt=null; status.textContent='正在读取评分参数…'; refreshAccess();
    try {
      const [access, policy]=await Promise.all([api('status'),requestJson('/api/assessment/policy')]);
      configured=access.configured; receipt=policy; renderFields();
      status.textContent=`已读取配置 V${policy.version}；修改并确认后才会写入文件。`;
    } catch(error) {status.textContent=error.message;}
    finally {busy=false;refreshAccess();}
  };
  sq('#policy-unlock-form').onsubmit=async event=> {
    event.preventDefault(); if(busy)return; busy=true;refreshAccess();
    try {
      const result=await api('unlock',{method:'POST',body:JSON.stringify({setup:!configured,password:sq('#policy-password').value,confirmation:sq('#policy-password-confirm').value})});
      configured=true; token=result.token;
      clearTimeout(expiry); expiry=setTimeout(()=>{token='';resetPreview();status.textContent='授权已到期，请重新解锁后继续修改。';},result.expires_in*1000);
      status.textContent='已解锁，可修改参数。仅完整通过校验并写后核验成功，才显示保存成功。';
    } catch(error) {status.textContent=error.message;}
    finally {sq('#policy-password').value='';sq('#policy-password-confirm').value='';busy=false;refreshAccess();}
  };
  sq('#policy-fields').addEventListener('input',resetPreview);
  sq('#policy-editor-form').onsubmit=async event=> {
    event.preventDefault(); if(busy || !token || !receipt)return;
    if(!preview) {
      const parameters=structuredClone(receipt.parameters), changes=[];
      for(const [path,label] of groups.flatMap(([,fields])=>fields)) {
        const value=Number(sq(`[data-policy-path="${path}"]`).value);
        if(value!==valueAt(receipt.parameters,path))changes.push(`${label}：${valueAt(receipt.parameters,path)} → ${value}`);
        const parts=path.split('.'), key=parts.pop();
        let target=parameters; for(const part of parts)target=target[part]; target[key]=value;
      }
      if(!changes.length){status.textContent='参数未变化，无需写入。';return;}
      preview=parameters;
      sq('#policy-change-preview').innerHTML=`<p>请核对以下修改，保存后用于新考核：</p><ul>${changes.map(c=>`<li>${escapeHtml(c)}</li>`).join('')}</ul>`;
      sq('#policy-change-preview').hidden=false;refreshAccess();sq('#policy-change-preview').scrollIntoView({block:'nearest'});return;
    }
    busy=true;refreshAccess();
    try {
      receipt=await api('policy',{method:'PUT',body:JSON.stringify({previous_hash:receipt.sha256,parameters:preview})});
      renderFields();
      status.textContent=`已永久保存并重新读取核验 · ${receipt.file} · ${new Date(receipt.loaded_at).toLocaleString()}。已开始的考核保持原配置。`;
      if(!state.analysis?.assessment?.confirmed) {assessmentUI.policy=null;sq('#assessment-policy').textContent='评分参数已更新，请读取最新配置。';syncAssessmentActions();}
    } catch(error) {status.textContent=error.message;}
    finally {busy=false;refreshAccess();status.scrollIntoView({block:'nearest'});}
  };
  sq('#policy-relock').onclick=async()=>{await relock();status.textContent='已结束修改，当前为只读。';};
  sq('#close-policy-settings').onclick=async()=>{if(busy)return;await relock();dialog.close();};
  dialog.addEventListener('cancel',event=>{event.preventDefault();if(!busy)sq('#close-policy-settings').click();});
})();
