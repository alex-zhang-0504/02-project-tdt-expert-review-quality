/* Local identity selection and persisted assessment workspace. */
window.workspace = {
  user: null, users: [], bindings: {}, saveTimer: null, managerErrors: [], managerCheckPending: false, managerCheckSequence: 0,
  taskId: null, importJobs: {},
  async initialize() {
    this.releaseLoginReveal?.();
    const session=await requestJson('/api/workspace/session');
    this.user=session.user;this.users=session.users;this.accountsFile=session.accounts_file;
    document.body.dataset.workspaceRole=this.user?.role||'guest';
    let header=sq('#workspace-account');
    if(!header){header=document.createElement('div');header.id='workspace-account';header.className='workspace-actions';sq('.topbar').insertBefore(header,sq('#service-status'));}
    header.innerHTML=this.user?`<span>${escapeHtml(this.user.name)} · ${escapeHtml(this.user.employee_id)} · ${this.user.role==='admin'?'管理员':'项目经理'}</span><button class="ghost-button" id="workspace-logout">退出登录</button>`:session.password_configured?'<button class="ghost-button" id="workspace-change-password">修改密码</button>':'';
    if(!this.user&&session.password_configured)sq('#workspace-change-password').onclick=()=>this.changePassword();
    if(this.user){
      sq('#workspace-logout').onclick=async()=>{if(!await flushSubjectiveChanges())return;await assessmentPost('/api/workspace/logout',{});subjective.drafts.clear();subjective.analysisId=null;subjectiveGuideSeen=false;sessionStorage.removeItem('tdt-subjective-guide-seen');this.taskId=null;clearAnalysisState();await this.initialize();};
      return this.home();
    }
    const host=sq('#workspace-panel');showPanel(host);activateStep(0);
    host.innerHTML=`<div class="workspace-login"><h2>${this.users.length?'选择账号登录':'登记首位管理员'}</h2><form id="workspace-login-form" class="workspace-form">${this.users.length?`<label class="field"><span>姓名与工号</span><select name="employee_id" required>${this.userOptions()}</select></label>`:'<label class="field"><span>姓名</span><input name="name" maxlength="80" required /></label><label class="field"><span>工号</span><input name="employee_id" maxlength="64" required /></label>'}<div id="workspace-password-fields"><label class="field"><span>管理员密码</span><span class="password-control"><input name="password" type="password" minlength="8" maxlength="128" autocomplete="current-password"/><button type="button" id="workspace-password-eye" aria-label="显示密码" aria-pressed="false">${this.eyeIcon(false)}</button></span></label>${session.password_configured?'':'<label class="field"><span>首次设置，再次输入密码</span><input name="confirmation" type="password" minlength="8" maxlength="128" autocomplete="new-password"/></label>'}</div><button type="submit" class="primary-button">登录系统</button><p id="workspace-error" role="status"></p></form></div>`;
    const form=sq('#workspace-login-form'),sync=()=>{const admin=!this.users.length||this.users.find(u=>u.employee_id===form.elements.employee_id.value)?.role==='admin';sq('#workspace-password-fields').hidden=!admin;for(const name of ['password','confirmation'])if(form.elements[name]){form.elements[name].required=admin;form.elements[name].disabled=!admin;}};
    if(this.users.length)form.elements.employee_id.onchange=sync;sync();
    this.releaseLoginReveal=this.bindPasswordReveal(sq('#workspace-password-eye'),form.elements.password);
    form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type="submit"]');button.disabled=true;try{await assessmentPost('/api/workspace/'+(this.users.length?'login':'bootstrap'),Object.fromEntries(new FormData(form)));subjectiveGuideSeen=false;sessionStorage.removeItem('tdt-subjective-guide-seen');await this.initialize();}catch(err){sq('#workspace-error').textContent=err.message;}finally{button.disabled=false;}};
  },
  eyeIcon(visible){return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>${visible?'':'<path d="m3 3 18 18"/>'}</svg>`;},
  bindPasswordReveal(button,input){
    const controller=new AbortController(),options={signal:controller.signal};
    const update=visible=>{input.type=visible?'text':'password';button.innerHTML=this.eyeIcon(visible);button.setAttribute('aria-label',visible?'松开隐藏密码':'按住显示密码');button.setAttribute('aria-pressed',String(visible));};
    const hide=()=>update(false);hide();
    button.addEventListener('pointerdown',e=>{if(e.button!==0||input.disabled)return;e.preventDefault();update(true);},options);
    button.addEventListener('keydown',e=>{if(e.key===' '||e.key==='Enter'){e.preventDefault();update(true);}},options);
    button.addEventListener('click',e=>e.preventDefault(),options);
    for(const event of ['pointerleave','blur'])button.addEventListener(event,hide,options);
    for(const event of ['pointerup','pointercancel','keyup','blur'])window.addEventListener(event,hide,options);
    document.addEventListener('visibilitychange',hide,options);
    return ()=>{hide();controller.abort();};
  },
  bindFilePicker(inputId,buttonId){
    const input=sq('#'+inputId),button=sq('#'+buttonId);
    button.onclick=()=>input.click();
    input.addEventListener('change',()=>{const name=input.files[0]?.name;button.textContent=name||'选择文件';button.title=name||'';});
  },
  async changePassword(){
    if(!await flushSubjectiveChanges())return;
    const dialog=sq('#workspace-dialog'),body=sq('#workspace-dialog-body'),button=sq('#workspace-dialog-confirm');
    sq('#workspace-dialog-title').textContent='修改管理员密码';
    body.innerHTML=`<p>本机所有管理员共用此密码。修改成功后，管理员需重新登录。</p><form id="workspace-password-form" class="workspace-form">${[['password','原密码'],['new_password','新密码'],['confirmation','再次输入新密码']].map(([name,label])=>`<label class="field"><span>${label}</span><span class="password-control"><input name="${name}" type="password" minlength="8" maxlength="128" autocomplete="${name==='password'?'current-password':'new-password'}" required /><button type="button" data-password-eye="${name}" aria-label="显示${label}" aria-pressed="false">${this.eyeIcon(false)}</button></span></label>`).join('')}<p class="muted">新密码须为8至128位。</p></form>`;
    const form=sq('#workspace-password-form');sq('#workspace-dialog-error').textContent='';
    button.hidden=false;button.disabled=false;button.textContent='保存新密码';button.onclick=()=>form.requestSubmit();
    const releaseReveal=[...form.querySelectorAll('[data-password-eye]')].map(b=>this.bindPasswordReveal(b,form.elements[b.dataset.passwordEye]));
    let saving=false;
    const preventClose=e=>{if(saving)e.preventDefault();};dialog.addEventListener('cancel',preventClose);
    const closeButton=dialog.querySelector('.policy-editor-actions .secondary-button');
    form.onsubmit=async e=>{e.preventDefault();if(saving)return;sq('#workspace-dialog-error').textContent='';if(form.elements.new_password.value!==form.elements.confirmation.value){sq('#workspace-dialog-error').textContent='两次输入的新密码不一致';return;}saving=true;button.disabled=true;closeButton.disabled=true;try{await assessmentPost('/api/workspace/password',Object.fromEntries(new FormData(form)));dialog.close();subjective.drafts.clear();subjective.analysisId=null;subjectiveGuideSeen=false;sessionStorage.removeItem('tdt-subjective-guide-seen');this.taskId=null;clearAnalysisState();await this.initialize();sq('#workspace-error').textContent='密码已修改，请使用新密码登录。';}catch(error){sq('#workspace-dialog-error').textContent=error.message;}finally{saving=false;button.disabled=false;closeButton.disabled=false;}};
    dialog.addEventListener('close',()=>{releaseReveal.forEach(release=>release());form.reset();body.replaceChildren();button.onclick=null;dialog.removeEventListener('cancel',preventClose);},{once:true});
    dialog.showModal();
  },
  userOptions(selected='') {
    return '<option value="">请选择</option>' + this.users.filter(u=>u.enabled!==false).map(u=>`<option value="${escapeHtml(u.employee_id)}" ${selected===u.employee_id?'selected':''}>${escapeHtml(u.name)} · ${escapeHtml(u.employee_id)}</option>`).join('');
  },
  async home() {
    if(!await flushSubjectiveChanges())return;
    if(state.importActive){setNotice('请等待报告读取完成。');return;}
    const host=sq('#workspace-panel');showPanel(host);activateStep(this.user?.role==='admin'?1:3);
    try{
      const rows=await requestJson('/api/workspace/analyses');
      if(this.user.role!=='admin'){
        host.innerHTML=`<div class="panel-heading"><h2>我的问卷 <span class="muted">共${rows.reduce((n,r)=>n+r.managers.reduce((v,m)=>v+m.expected,0),0)}个评审人</span></h2></div><div class="workspace-questionnaires">${rows.map(r=>r.managers.map(m=>Object.keys(m.experts).map(name=>{const saved=m.reviews[name],complete=saved.status==='已完成',count=saved.answered||0;return `<button class="workspace-questionnaire" data-pm-task="${r.id}" data-pm-name="${escapeHtml(name)}"><span class="questionnaire-heading"><strong>${escapeHtml(name)}</strong><span class="questionnaire-badge">${complete?'✓ 已完成':saved.selected?saved.status:'未开始'}</span></span><span class="questionnaire-cycle">${escapeHtml(r.name)}</span><span class="questionnaire-bottom"><span><span class="questionnaire-count">${complete?6:count}<small> ／ 6 题</small></span><span class="questionnaire-saved">${saved.selected?'已保存':'尚未填写'}</span></span><span aria-hidden="true">→</span></span><span class="questionnaire-segments" aria-hidden="true">${Array.from({length:6},(_,i)=>`<i class="${i<(complete?6:count)?'filled':''}"></i>`).join('')}</span></button>`}).join('')).join('')).join('')||'<p>暂未分配问卷。</p>'}</div>`;
        host.querySelectorAll('[data-pm-task]').forEach(b=>b.onclick=()=>this.open(b.dataset.pmTask,this.user.employee_id,b.dataset.pmName));return;
      }
      host.innerHTML=`<div class="panel-heading"><h2>考核任务信息</h2></div><p id="workspace-error" role="status"></p><div class="workspace-list"><button class="workspace-task new-task" id="workspace-create">＋ 新建考评任务</button>${rows.map(r=>{const expected=r.managers.reduce((n,m)=>n+m.expected,0),done=r.managers.reduce((n,m)=>n+m.completed,0),begun=r.managers.filter(m=>m.started).length;return `<article class="workspace-task-entry"><button class="workspace-task" data-workspace-open="${r.id}" data-completed="${r.completed}"><span class="workspace-task-heading"><strong>${escapeHtml(r.name)}</strong><span class="task-badge">${r.completed?'已完成':'进行中'}</span></span><span class="task-meta">${r.report_count}份报告 · ${r.expert_count}位评审人</span>${r.completed?'':`<span class="task-progress"><span>客观数据评价</span><span>${r.objective_complete?'已完成':r.confirmed?'待识别与评分':r.report_count?'待确认名单':'待读取报告'}</span></span><progress max="100" value="${r.objective_complete?100:r.confirmed?50:r.report_count?25:0}"></progress><span class="task-progress"><span>主观评价 · 已开始${begun}／${r.managers.length}人</span><span>${done}／${expected}份问卷已完成</span></span><progress max="${expected||1}" value="${done}"></progress>`}</button><div class="task-buttons">${r.completed?'':`<button class="secondary-button" data-task-managers="${r.id}">修改项目经理名单</button><button class="secondary-button" data-task-policy="${r.id}" data-policy-scope="objective">客观评分参数</button><button class="secondary-button" data-task-policy="${r.id}" data-policy-scope="subjective">主观评分参数</button>`}<button class="secondary-button" data-task-delete="${r.id}">删除任务</button></div></article>`}).join('')}</div>`;
      sq('#workspace-create').onclick=()=>this.createPage();
      host.querySelectorAll('[data-task-managers]').forEach(b=>b.onclick=()=>this.editManagers(b.dataset.taskManagers));
      host.querySelectorAll('[data-workspace-open]').forEach(b=>b.onclick=()=>b.dataset.completed==='true'?this.history(b.dataset.workspaceOpen):this.open(b.dataset.workspaceOpen));
      host.querySelectorAll('[data-task-policy]').forEach(b=>b.onclick=()=>window.openTaskPolicy(b.dataset.taskPolicy,b.dataset.policyScope));
      host.querySelectorAll('[data-task-delete]').forEach(b=>b.onclick=()=>{const row=rows.find(r=>r.id===b.dataset.taskDelete);this.confirm('删除任务',row.name+'。确认后此任务将从列表移除。',async()=>{await requestJson('/api/workspace/tasks/'+row.id,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:row.name,confirmed:true})});if(this.taskId===row.id){this.taskId=null;clearAnalysisState();subjective.drafts.clear();}return ()=>this.removeTaskCard(b.closest('.workspace-task-entry'));});});
    }catch(e){host.textContent=e.message;}
  },
  removeTaskCard(entry){
    if(!entry?.isConnected)return;
    const y=window.scrollY,entries=[...sq('#workspace-panel').querySelectorAll('.workspace-task-entry')];
    const positions=new Map(entries.map(e=>[e,e.getBoundingClientRect().top]));
    const next=entry.nextElementSibling||entry.previousElementSibling;
    entry.remove();
    (next?.querySelector('[data-task-delete]')||sq('#workspace-create')).focus({preventScroll:true});
    window.scrollTo({top:Math.min(y,Math.max(0,document.documentElement.scrollHeight-window.innerHeight)),behavior:'instant'});
    if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches){
      positions.forEach((top,e)=>{if(!e.isConnected)return;const now=e.getBoundingClientRect().top,delta=top-now;if(delta&&now<window.innerHeight&&now+e.offsetHeight>0)e.animate([{transform:`translateY(${delta}px)`},{transform:'translateY(0)'}],{duration:180,easing:'ease'});});
    }
  },
  async editManagers(id){
    try{
      const receipt=await requestJson('/api/workspace/tasks/'+id+'/managers');
      const dialog=sq('#workspace-dialog'),body=sq('#workspace-dialog-body'),button=sq('#workspace-dialog-confirm');
      sq('#workspace-dialog-title').textContent='修改项目经理名单';
      body.innerHTML=`<p>重新导入姓名、工号、是否启用的JSON配置。仅更新主观问卷任务和进度。移出或停用人员的原答案保留历史、不再参与当前主观汇总；客观考评及评分参数不变。</p><p>账号停用对所有任务的登录生效，不能通过此次导入修改其他任务的历史名单。</p><p>当前名单：${receipt.users.filter(u=>u.enabled).length}人启用。</p><label class="field"><span>选择项目经理配置文件</span><button type="button" class="secondary-button file-picker-button" id="task-manager-file-button">选择文件</button><input id="task-manager-file" type="file" accept=".json" hidden /></label><div id="task-manager-preview"></div>`;
      sq('#workspace-dialog-error').textContent='';button.hidden=false;button.disabled=true;button.textContent='确认更新名单';let config=null;
      this.bindFilePicker('task-manager-file','task-manager-file-button');
      sq('#task-manager-file').onchange=async e=>{button.disabled=true;config=null;sq('#task-manager-preview').textContent='';try{const file=e.target.files[0];if(!file)return;if(!file.name.toLowerCase().endsWith('.json'))throw Error('请选择JSON配置文件');const parsed=JSON.parse((await file.text()).replace(/^\uFEFF/,''));if(!Array.isArray(parsed.users))throw Error('请选择有效的项目经理配置');config=parsed;sq('#task-manager-preview').textContent=parsed.users.map(u=>`${u.name} · ${u.employee_id} · ${u.enabled?'启用':'停用'}`).join('；');sq('#workspace-dialog-error').textContent='';button.disabled=false;}catch(error){sq('#workspace-dialog-error').textContent=error.message;}};
      let saving=false;const closeButton=dialog.querySelector('.policy-editor-actions .secondary-button'),preventClose=e=>{if(saving)e.preventDefault();};dialog.addEventListener('cancel',preventClose);
      dialog.addEventListener('close',()=>dialog.removeEventListener('cancel',preventClose),{once:true});
      button.onclick=async()=>{if(saving)return;saving=true;button.disabled=true;closeButton.disabled=true;try{await requestJson('/api/workspace/tasks/'+id+'/managers',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({...receipt,accounts:config,confirmed:true})});dialog.close();if(this.taskId===id){this.taskId=null;clearAnalysisState();subjective.drafts.clear();}await this.home();sq('#workspace-error').textContent='名单已更新，主观任务与进度已刷新，客观考评保持不变。';}catch(error){sq('#workspace-dialog-error').textContent=error.message;}finally{saving=false;button.disabled=false;closeButton.disabled=false;}};
      dialog.showModal();
    }catch(error){sq('#workspace-error').textContent=error.message;}
  },
  createPage(){
    const host=sq('#workspace-panel'),year=new Date().getFullYear();
    host.innerHTML=`<div class="panel-heading"><h2>新建考评任务</h2><button class="ghost-button" id="create-cancel">取消</button></div><form id="workspace-create-form"><div class="creation-fields"><label class="field"><span>年份</span><select name="year">${Array.from({length:7},(_,i)=>year-3+i).map(y=>`<option ${y===year?'selected':''}>${y}</option>`).join('')}</select></label><label class="field"><span>考评周期</span><select name="period"><option>年度</option><option>上半年</option><option>下半年</option></select></label><label class="field"><span>导入项目经理名单（账号配置）</span><button type="button" class="secondary-button file-picker-button" id="create-accounts-button">选择文件</button><input type="file" id="create-accounts" accept=".json" hidden /></label></div><p id="create-account-status" role="status"></p><p id="workspace-error" role="status"></p><div class="assessment-pager"><button class="primary-button" type="submit">下一步 →</button></div></form>`;
    this.bindFilePicker('create-accounts','create-accounts-button');
    let config=null;sq('#create-cancel').onclick=()=>this.home();sq('#create-accounts').onchange=async e=>{config=null;try{if(!e.target.files[0]){sq('#create-account-status').textContent='';return;}config=JSON.parse((await e.target.files[0].text()).replace(/^\uFEFF/,''));if(!Array.isArray(config.users))throw Error('请选择有效账号配置');sq('#create-account-status').textContent='已读取'+config.users.length+'个账号，创建时校验并同步。';}catch(error){sq('#create-account-status').textContent=error.message;}};
    sq('#workspace-create-form').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('[type="submit"]');b.disabled=true;try{if(!config)throw Error('请先导入账号配置');await assessmentPost('/api/workspace/tasks',{...Object.fromEntries(new FormData(e.target)),accounts:config});await this.home();}catch(error){sq('#workspace-error').textContent=error.message;}finally{b.disabled=false;}};
  },
  confirm(title,message,action){
    const dialog=sq('#workspace-dialog');sq('#workspace-dialog-title').textContent=title;sq('#workspace-dialog-body').textContent=message;sq('#workspace-dialog-error').textContent='';const button=sq('#workspace-dialog-confirm');button.hidden=false;button.disabled=false;button.textContent='确认'+title;
    button.onclick=async()=>{button.disabled=true;try{const afterClose=await action();dialog.close();if(typeof afterClose==='function')afterClose();}catch(e){sq('#workspace-dialog-error').textContent=e.message;}finally{button.disabled=false;}};dialog.showModal();
  },
  async history(id){
    const data=await requestJson('/api/workspace/tasks/'+id+'/history');sq('#workspace-dialog-title').textContent=data.name+' · 历史总分统计';sq('#workspace-dialog-body').innerHTML=`<p>${escapeHtml(data.at)} · 已完成</p><div class="score-statistics-table-wrap">${statisticsTable(data.statistics.rows,data.statistics.policy.parameters.total_cap,true)}</div>`;sq('#workspace-dialog-error').textContent='';sq('#workspace-dialog-confirm').hidden=true;sq('#workspace-dialog').showModal();
  },
  syncCompletion(){const b=sq('#workspace-complete');b.disabled=!scoreStatistics.data?.rows?.length||scoreStatistics.data.rows.some(r=>r.total===null)||!!state.analysis?.assessment?.completed||state.importActive;b.onclick=()=>{if(b.disabled)return;const id=state.analysis.analysis_id;this.confirm('完成本期考评',state.analysis.source_name+'。确认后本期结果与参数只读归档。',async()=>{await assessmentPost('/api/workspace/tasks/'+id+'/complete',{confirmed:true});this.taskId=null;clearAnalysisState();subjective.drafts.clear();await this.home();});};},
  async open(id,manager='',expert='') {
    if(!await flushSubjectiveChanges())return;
    try{
      const analysis=await requestJson('/api/workspace/analyses/'+encodeURIComponent(id));this.taskId=id;
      state.importJobId=this.importJobs[id]||null;state.displayProgressReports=[];state.importProgressReports=[];
      subjective.drafts.clear();subjective.analysisId=null;subjective.catalog=null;
      state.workflowMode='central';state.analysis=analysis;state.analysisStale=false;state.analysisServiceInstanceId=state.serviceInstanceId;
      if(this.user.role==='admin'){await receiveAnalysis(analysis);elements.checkCard.classList.toggle('is-hidden',!analysis.reports?.length);showPanel(elements.importPanel);elements.importModeLabel.textContent='读取与匹配';sq('#assessment-names').value=(analysis.assessment?.requested||[]).join('\n');assessmentUI.policy=analysis.assessment.confirmed?analysis.assessment.policy:null;syncAssessmentActions();checkFeishuAuthorization();}
      if(this.user.role==='manager'||manager){assessmentUI.managerId=manager||this.user.employee_id;await openSubjective();if(expert){subjective.expert=expert;renderSubjectiveEditor();}sq('#subjective-page-one').hidden=false;sq('#subjective-page-two').hidden=true;}
    }catch(error){setNotice(error.message);}
  },
  async adopt(analysis){if(this.taskId&&analysis.analysis_id!==this.taskId&&this.user?.role==='admin'){const adopted=await assessmentPost('/api/workspace/tasks/'+this.taskId+'/reports',{analysis_id:analysis.analysis_id});this.importJobs[this.taskId]=state.importJobId;return adopted;}return analysis;},
  async invalidateScope(){if(!state.analysis?.assessment?.confirmed)return;const id=state.analysis.analysis_id;state.analysis=await assessmentPost('/api/workspace/tasks/'+id+'/scope',{});scoreStatistics.data=null;scoreStatistics.requestId++;this.syncCompletion();syncServiceActions();activateStep(1);},
  async renderBindings() {
    const a=state.analysis,host=sq('#workspace-manager-errors');
    const check=++this.managerCheckSequence;
    this.managerErrors=[];host.hidden=true;host.innerHTML='';
    if(!a||state.importActive||a.assessment?.confirmed){this.managerCheckPending=false;syncAssessmentActions();return;}
    this.managerCheckPending=true;syncAssessmentActions();
    try{
      const result=await requestJson('/api/workspace/manager-matches?analysis_id='+encodeURIComponent(a.analysis_id));
      if(state.analysis?.analysis_id!==a.analysis_id||this.managerCheckSequence!==check)return;
      this.users=result.users;this.managerErrors=result.errors;
      if(!result.errors.length)return;
      host.hidden=false;
      host.innerHTML='<h3>项目经理匹配异常</h3><p>请确认以下归属后再确认考核名单；相同owner ID只需处理一次。</p>'+result.errors.map((item,i)=>`<div class="workspace-binding"><div><strong>${escapeHtml(item.name||'项目经理待识别')}</strong><p>${escapeHtml(item.reason)}${item.owner_id?' · '+escapeHtml(item.owner_id):''}</p><details><summary>涉及${item.reports.length}份报告</summary>${item.reports.map(name=>`<p>${escapeHtml(name)}</p>`).join('')}</details></div>${item.can_assign?`<select aria-label="${escapeHtml(item.name||item.reports[0])}对应账号" data-manager-account="${i}">${this.userOptions()}</select><button type="button" class="secondary-button" data-manager-confirm="${i}">确认归属</button>`:''}</div>`).join('')+'<p id="workspace-manager-message" role="status"></p>';
      host.querySelectorAll('[data-manager-confirm]').forEach(button=>button.onclick=async()=>{
        const item=result.errors[Number(button.dataset.managerConfirm)],employee=sq(`[data-manager-account="${button.dataset.managerConfirm}"]`).value;
        if(!employee){sq('#workspace-manager-message').textContent='请先选择已登记的启用账号。';return;}
        button.disabled=true;
        try{
          if(item.local){for(const source_name of item.reports)state.analysis=await assessmentPost('/api/assessment/local-manager',{analysis_id:a.analysis_id,source_name,manager_id:employee});}
          else await assessmentPost('/api/workspace/bindings',{owner_id:item.owner_id,employee_id:employee});
          await this.renderBindings();
        }catch(err){sq('#workspace-manager-message').textContent=err.message;button.disabled=false;}
      });
    }catch(err){
      if(state.analysis?.analysis_id!==a.analysis_id||this.managerCheckSequence!==check)return;
      this.managerErrors=[{reason:err.message}];host.hidden=false;
      host.innerHTML='<h3>项目经理配置读取失败</h3><p></p><button class="secondary-button" type="button">重新匹配</button>';
      host.querySelector('p').textContent=err.message;host.querySelector('button').onclick=()=>this.renderBindings();
    }finally{if(this.managerCheckSequence===check){this.managerCheckPending=false;syncAssessmentActions();}}
  },
  readonly() {return !!state.analysis?.assessment?.finalized || (this.user?.role==='manager' && !!managerSaved(subjective.expert)?.locked_by_admin);},
  scheduleSave() {
    clearTimeout(this.saveTimer);
    this.saveTimer=setTimeout(async()=>{
      if(subjective.busy){this.scheduleSave();return;}
      const ok=await flushSubjectiveChanges(true);
      if(ok&&[...subjective.drafts.values()].some(d=>d.dirty))this.scheduleSave();
    },900);
  },
  syncQuestionnaire() {
    sq('#workspace-my-return').hidden=this.user?.role!=='manager';
    sq('#workspace-history').hidden=this.user?.role!=='admin'||sq('#subjective-page-one').hidden||!sq('#subjective-form');
    if(!sq('#subjective-form'))return;
    let tools=sq('#workspace-questionnaire-tools');
    if(!tools){tools=document.createElement('div');tools.id='workspace-questionnaire-tools';sq('#subjective-editor').prepend(tools);}
    const record=managerSaved(subjective.expert);
    tools.hidden=this.user.role!=='admin';
    const notice=state.analysis.assessment?.finalized?'主观结果已确认，问卷只读。':record?.locked_by_admin?'管理员已调整此问卷；退回后项目经理可继续填写。':'';
    tools.innerHTML=`${notice?`<p>${notice}</p>`:''}${this.user.role==='admin'&&record?.locked_by_admin&&!state.analysis.assessment?.finalized?'<div class="workspace-actions"><button type="button" class="secondary-button" id="workspace-return">退回项目经理填写</button></div>':''}<div id="workspace-history-content"></div>`;
    if(sq('#workspace-return'))sq('#workspace-return').onclick=async()=>{
      if(!await flushSubjectiveChanges())return;
      try{await assessmentPost('/api/workspace/return',{analysis_id:state.analysis.analysis_id,manager_id:assessmentUI.managerId,expert_name:subjective.expert,expected_revision:managerSaved(subjective.expert).revision});subjective.drafts.delete(managerDraftKey());await loadManagerTasks();renderSubjectiveEditor();}catch(e){sq('#subjective-message').textContent=e.message;}
    };
    const historyButton=sq('#workspace-history');
    historyButton.textContent='查看修改记录';historyButton.setAttribute('aria-expanded','false');historyButton.setAttribute('aria-controls','workspace-history-content');
    sq('#workspace-history-content').hidden=true;
    historyButton.onclick=async()=>{
      if(!sq('#workspace-history-content').hidden){
        sq('#workspace-history-content').hidden=true;
        historyButton.textContent='查看修改记录';historyButton.setAttribute('aria-expanded','false');
        return;
      }
      if(!await flushSubjectiveChanges())return;
      const content=sq('#workspace-history-content');
      if(!content.hidden)return;
      content.hidden=false;content.textContent='正在读取修改记录…';
      historyButton.textContent='收起修改记录';historyButton.setAttribute('aria-expanded','true');
      const query=new URLSearchParams({analysis_id:state.analysis.analysis_id,manager_id:assessmentUI.managerId,expert_name:subjective.expert});
      try{
        const entries=await requestJson('/api/workspace/history?'+query);
        const answer=(d,r)=>{const item=r?.ratings?.[d.id]||{};return [d.options.find(o=>o.id===item.option)?.title||(item.option==='unable'?'暂无法判断':'未填写'),item.reason,...subjectiveEvidence(item).map(e=>[e.project_code,e.note].filter(Boolean).join('：'))].filter(Boolean).join('；');};
        content.innerHTML=entries.slice().reverse().map(e=>`<details class="workspace-history-entry"><summary>${escapeHtml(e.action)} · ${escapeHtml(e.actor.name)} · ${new Date(e.at).toLocaleString()} · 修订${e.after.revision||0}</summary>${subjective.catalog.map(d=>`<p><strong>${escapeHtml(d.title)}</strong><br>修改前：${escapeHtml(answer(d,e.before))}<br>修改后：${escapeHtml(answer(d,e.after))}</p>`).join('')}</details>`).join('')||'<p>尚无保存记录。</p>';
      }catch(e){content.textContent=e.message;}
    };
  },
};
