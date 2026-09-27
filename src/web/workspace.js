/* Local identity selection and persisted assessment workspace. */
window.workspace = {
  user: null, users: [], bindings: {}, saveTimer: null, managerErrors: [], managerCheckPending: false, managerCheckSequence: 0,
  taskId: null, importJobs: {},
  async initialize() {
    const session=await requestJson('/api/workspace/session');
    this.user=session.user;this.users=session.users;this.accountsFile=session.accounts_file;
    document.body.dataset.workspaceRole=this.user?.role||'guest';
    let header=sq('#workspace-account');
    if(!header){header=document.createElement('div');header.id='workspace-account';header.className='workspace-actions';sq('.topbar').insertBefore(header,sq('#service-status'));}
    header.innerHTML=this.user?`<span>${escapeHtml(this.user.name)} · ${escapeHtml(this.user.employee_id)} · ${this.user.role==='admin'?'管理员':'项目经理'}</span><button class="ghost-button" id="workspace-logout">log out</button>`:'';
    if(this.user){
      sq('#workspace-logout').onclick=async()=>{if(!await flushSubjectiveChanges())return;await assessmentPost('/api/workspace/logout',{});subjective.drafts.clear();subjective.analysisId=null;subjectiveGuideSeen=false;sessionStorage.removeItem('tdt-subjective-guide-seen');this.taskId=null;clearAnalysisState();await this.initialize();};
      return this.home();
    }
    const host=sq('#workspace-panel');showPanel(host);activateStep(0);
    host.innerHTML=`<div class="workspace-login"><h2>${this.users.length?'选择账号登录':'登记首位管理员'}</h2><form id="workspace-login-form" class="workspace-form">${this.users.length?`<label class="field"><span>姓名与工号</span><select name="employee_id" required>${this.userOptions()}</select></label>`:'<label class="field"><span>姓名</span><input name="name" maxlength="80" required /></label><label class="field"><span>工号</span><input name="employee_id" maxlength="64" required /></label>'}<div id="workspace-password-fields"><label class="field"><span>管理员密码</span><span class="password-control"><input name="password" type="password" minlength="8" maxlength="128" autocomplete="current-password"/><button type="button" id="workspace-password-eye" aria-label="显示密码" aria-pressed="false">${this.eyeIcon(false)}</button></span></label>${session.password_configured?'':'<label class="field"><span>首次设置，再次输入密码</span><input name="confirmation" type="password" minlength="8" maxlength="128" autocomplete="new-password"/></label>'}</div><button type="submit" class="primary-button">登录系统</button><p id="workspace-error" role="status"></p></form></div>`;
    const form=sq('#workspace-login-form'),sync=()=>{const admin=!this.users.length||this.users.find(u=>u.employee_id===form.elements.employee_id.value)?.role==='admin';sq('#workspace-password-fields').hidden=!admin;for(const name of ['password','confirmation'])if(form.elements[name]){form.elements[name].required=admin;form.elements[name].disabled=!admin;}};
    if(this.users.length)form.elements.employee_id.onchange=sync;sync();
    sq('#workspace-password-eye').onclick=()=>{const visible=form.elements.password.type==='password';form.elements.password.type=visible?'text':'password';const b=sq('#workspace-password-eye');b.innerHTML=this.eyeIcon(visible);b.setAttribute('aria-label',visible?'隐藏密码':'显示密码');b.setAttribute('aria-pressed',String(visible));};
    form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('[type="submit"]');button.disabled=true;try{await assessmentPost('/api/workspace/'+(this.users.length?'login':'bootstrap'),Object.fromEntries(new FormData(form)));subjectiveGuideSeen=false;sessionStorage.removeItem('tdt-subjective-guide-seen');await this.initialize();}catch(err){sq('#workspace-error').textContent=err.message;}finally{button.disabled=false;}};
  },
  eyeIcon(visible){return `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>${visible?'':'<path d="m3 3 18 18"/>'}</svg>`;},
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
        host.innerHTML=`<div class="panel-heading"><h2>我的问卷 <span class="muted">共${rows.reduce((n,r)=>n+r.managers.reduce((v,m)=>v+m.expected,0),0)}个评审人</span></h2></div><div class="workspace-list">${rows.map(r=>r.managers.map(m=>Object.keys(m.experts).map(name=>{const saved=m.reviews[name],complete=saved.status==='已完成';return `<article class="workspace-assessment"><div class="panel-heading"><div><h3>${escapeHtml(name)}</h3><p class="muted">${escapeHtml(r.name)}</p><p>${complete?'已保存 · 6／6题':saved.selected?'已保存 · '+saved.answered+'／6题 · '+saved.status:'尚未填写 · 0／6题'}</p></div><button class="primary-button" data-pm-task="${r.id}" data-pm-name="${escapeHtml(name)}">查看／修改问卷</button></div></article>`}).join('')).join('')).join('')||'<p>暂未分配问卷。</p>'}</div>`;
        host.querySelectorAll('[data-pm-task]').forEach(b=>b.onclick=()=>this.open(b.dataset.pmTask,this.user.employee_id,b.dataset.pmName));return;
      }
      host.innerHTML=`<div class="panel-heading"><h2>考核任务信息</h2></div><p id="workspace-error" role="status"></p><div class="workspace-list"><button class="workspace-task new-task" id="workspace-create">＋ 新建考评任务</button>${rows.map(r=>{const expected=r.managers.reduce((n,m)=>n+m.expected,0),done=r.managers.reduce((n,m)=>n+m.completed,0),begun=r.managers.filter(m=>m.started).length;return `<article class="workspace-task-entry"><button class="workspace-task" data-workspace-open="${r.id}" data-completed="${r.completed}"><span class="workspace-task-heading"><strong>${escapeHtml(r.name)}</strong><span class="task-badge">${r.completed?'已完成':'进行中'}</span></span><span class="task-meta">${r.report_count}份报告 · ${r.expert_count}位评审人</span>${r.completed?'':`<span class="task-progress"><span>客观数据评价</span><span>${r.objective_complete?'已完成':r.confirmed?'待识别与评分':r.report_count?'待确认名单':'待读取报告'}</span></span><progress max="100" value="${r.objective_complete?100:r.confirmed?50:r.report_count?25:0}"></progress><span class="task-progress"><span>主观评价 · 已开始${begun}／${r.managers.length}人</span><span>${done}／${expected}份问卷已完成</span></span><progress max="${expected||1}" value="${done}"></progress>`}</button><div class="task-buttons">${r.completed?'':`<button class="secondary-button" data-task-policy="${r.id}" data-policy-scope="objective">客观评分参数</button><button class="secondary-button" data-task-policy="${r.id}" data-policy-scope="subjective">主观评分参数</button>`}<button class="secondary-button" data-task-delete="${r.id}">删除任务</button></div></article>`}).join('')}</div>`;
      sq('#workspace-create').onclick=()=>this.createPage();
      host.querySelectorAll('[data-workspace-open]').forEach(b=>b.onclick=()=>b.dataset.completed==='true'?this.history(b.dataset.workspaceOpen):this.open(b.dataset.workspaceOpen));
      host.querySelectorAll('[data-task-policy]').forEach(b=>b.onclick=()=>window.openTaskPolicy(b.dataset.taskPolicy,b.dataset.policyScope));
      host.querySelectorAll('[data-task-delete]').forEach(b=>b.onclick=()=>{const row=rows.find(r=>r.id===b.dataset.taskDelete);this.confirm('删除任务',row.name+'。确认后此任务将从列表移除。',async()=>{await requestJson('/api/workspace/tasks/'+row.id,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:row.name,confirmed:true})});if(this.taskId===row.id){this.taskId=null;clearAnalysisState();subjective.drafts.clear();}await this.home();});});
    }catch(e){host.textContent=e.message;}
  },
  createPage(){
    const host=sq('#workspace-panel'),year=new Date().getFullYear();
    host.innerHTML=`<div class="panel-heading"><h2>新建考评任务</h2><button class="ghost-button" id="create-cancel">取消</button></div><form id="workspace-create-form"><div class="creation-fields"><label class="field"><span>年份</span><select name="year">${Array.from({length:7},(_,i)=>year-3+i).map(y=>`<option ${y===year?'selected':''}>${y}</option>`).join('')}</select></label><label class="field"><span>考评周期</span><select name="period"><option>年度</option><option>上半年</option><option>下半年</option></select></label><label class="field"><span>导入项目经理名单（账号配置）</span><input type="file" id="create-accounts" accept=".json" required /></label></div><p id="create-account-status" role="status"></p><p id="workspace-error" role="status"></p><div class="assessment-pager"><button class="primary-button" type="submit">下一步 →</button></div></form>`;
    let config=null;sq('#create-cancel').onclick=()=>this.home();sq('#create-accounts').onchange=async e=>{config=null;try{config=JSON.parse((await e.target.files[0].text()).replace(/^\uFEFF/,''));if(!Array.isArray(config.users))throw Error('请选择有效账号配置');sq('#create-account-status').textContent='已读取'+config.users.length+'个账号，创建时校验并同步。';}catch(error){sq('#create-account-status').textContent=error.message;}};
    sq('#workspace-create-form').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('[type="submit"]');b.disabled=true;try{if(!config)throw Error('请先导入账号配置');await assessmentPost('/api/workspace/tasks',{...Object.fromEntries(new FormData(e.target)),accounts:config});await this.home();}catch(error){sq('#workspace-error').textContent=error.message;}finally{b.disabled=false;}};
  },
  confirm(title,message,action){
    const dialog=sq('#workspace-dialog');sq('#workspace-dialog-title').textContent=title;sq('#workspace-dialog-body').textContent=message;sq('#workspace-dialog-error').textContent='';const button=sq('#workspace-dialog-confirm');button.hidden=false;button.disabled=false;button.textContent='确认'+title;
    button.onclick=async()=>{button.disabled=true;try{await action();dialog.close();}catch(e){sq('#workspace-dialog-error').textContent=e.message;}finally{button.disabled=false;}};dialog.showModal();
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
    if(!sq('#subjective-form'))return;
    let tools=sq('#workspace-questionnaire-tools');
    if(!tools){tools=document.createElement('div');tools.id='workspace-questionnaire-tools';sq('#subjective-editor').prepend(tools);}
    const record=managerSaved(subjective.expert),locked=this.readonly();
    tools.hidden=this.user.role!=='admin';
    tools.innerHTML=`<p>${state.analysis.assessment?.finalized?'主观结果已确认，问卷只读。':record?.locked_by_admin?'管理员已调整此问卷；退回后项目经理可继续填写。':'填写后自动保存到本机，未完成的问卷也会保存。'}</p><div class="workspace-actions">${!locked?'<button type="button" class="secondary-button" id="workspace-save">保存问卷</button>':''}<button type="button" class="ghost-button" id="workspace-history">查看修改记录</button>${this.user.role==='admin'&&record?.locked_by_admin&&!state.analysis.assessment?.finalized?'<button type="button" class="secondary-button" id="workspace-return">退回项目经理填写</button>':''}</div><div id="workspace-history-content"></div>`;
    if(sq('#workspace-save'))sq('#workspace-save').onclick=()=>flushSubjectiveChanges();
    if(sq('#workspace-return'))sq('#workspace-return').onclick=async()=>{
      if(!await flushSubjectiveChanges())return;
      try{await assessmentPost('/api/workspace/return',{analysis_id:state.analysis.analysis_id,manager_id:assessmentUI.managerId,expert_name:subjective.expert,expected_revision:managerSaved(subjective.expert).revision});subjective.drafts.delete(managerDraftKey());await loadManagerTasks();renderSubjectiveEditor();}catch(e){sq('#subjective-message').textContent=e.message;}
    };
    sq('#workspace-history').onclick=async()=>{
      const query=new URLSearchParams({analysis_id:state.analysis.analysis_id,manager_id:assessmentUI.managerId,expert_name:subjective.expert});
      try{
        const entries=await requestJson('/api/workspace/history?'+query);
        const answer=(d,r)=>{const item=r?.ratings?.[d.id]||{};return [d.options.find(o=>o.id===item.option)?.title||(item.option==='unable'?'暂无法判断':'未填写'),item.reason,...subjectiveEvidence(item).map(e=>[e.project_code,e.note].filter(Boolean).join('：'))].filter(Boolean).join('；');};
        sq('#workspace-history-content').innerHTML=entries.slice().reverse().map(e=>`<details class="workspace-history-entry"><summary>${escapeHtml(e.action)} · ${escapeHtml(e.actor.name)} · ${new Date(e.at).toLocaleString()} · 修订${e.after.revision||0}</summary>${subjective.catalog.map(d=>`<p><strong>${escapeHtml(d.title)}</strong><br>修改前：${escapeHtml(answer(d,e.before))}<br>修改后：${escapeHtml(answer(d,e.after))}</p>`).join('')}</details>`).join('')||'<p>尚无保存记录。</p>';
      }catch(e){sq('#workspace-history-content').textContent=e.message;}
    };
  },
};
