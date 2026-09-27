/* Local identity selection and persisted assessment workspace. */
window.workspace = {
  user: null, users: [], bindings: {}, saveTimer: null,
  async initialize() {
    const session = await requestJson('/api/workspace/session');
    this.user = session.user; this.users = session.users;
    document.body.dataset.workspaceRole = this.user?.role || 'guest';
    document.querySelectorAll('.back-to-mode').forEach(b=>b.textContent='返回考核列表');
    let header = sq('#workspace-account');
    if (!header) {
      header = document.createElement('div'); header.id = 'workspace-account'; header.className = 'workspace-actions';
      sq('.toolrow').append(header);
    }
    header.innerHTML = this.user ? `<span>${escapeHtml(this.user.name)} · ${escapeHtml(this.user.employee_id)} · ${this.user.role==='admin'?'管理员':'项目经理'}</span><button type="button" class="ghost-button" id="workspace-home">考核列表</button><button type="button" class="ghost-button" id="workspace-logout">切换身份</button>` : '';
    if (this.user) {
      sq('#workspace-home').onclick = () => this.home();
      sq('#workspace-logout').onclick = async () => {
        if (!await flushSubjectiveChanges()) return;
        await assessmentPost('/api/workspace/logout', {});
        subjective.drafts.clear(); subjective.analysisId = null; subjectiveGuideSeen = false;
        sessionStorage.removeItem('tdt-subjective-guide-seen');
        clearAnalysisState(); await this.initialize();
      };
      return this.home();
    }
    const host = sq('#workspace-panel');
    showPanel(host); activateStep(0);
    host.innerHTML = `<div class="workspace-login"><p class="section-index">本机工作区</p><h2>${this.users.length?'选择身份登录':'登记首位管理员'}</h2><form id="workspace-login-form" class="workspace-form">${this.users.length ? `<label class="field"><span>姓名与工号</span><select name="employee_id" required>${this.userOptions()}</select></label>` : '<label class="field"><span>姓名</span><input name="name" maxlength="80" required autocomplete="name" /></label><label class="field"><span>工号</span><input name="employee_id" maxlength="64" required autocomplete="off" /></label>'}<button class="primary-button">进入系统</button><p id="workspace-error" role="status"></p></form><p class="muted">按约定选择本人身份，无需密码。问卷保存于当前电脑。</p></div>`;
    sq('#workspace-login-form').onsubmit = async e => {
      e.preventDefault(); const button=e.target.querySelector('button'); button.disabled=true;
      try {
        await assessmentPost(`/api/workspace/${this.users.length?'login':'bootstrap'}`, Object.fromEntries(new FormData(e.target)));
        subjectiveGuideSeen=false; sessionStorage.removeItem('tdt-subjective-guide-seen');
        await this.initialize();
      } catch (err) {sq('#workspace-error').textContent=err.message;} finally {button.disabled=false;}
    };
  },
  userOptions(selected='') {
    return '<option value="">请选择</option>' + this.users.map(u=>`<option value="${escapeHtml(u.employee_id)}" ${selected===u.employee_id?'selected':''}>${escapeHtml(u.name)} · ${escapeHtml(u.employee_id)}</option>`).join('');
  },
  async home() {
    if (!await flushSubjectiveChanges()) return;
    if (state.importActive) {setNotice('请等待报告读取完成后再返回考核列表。');return;}
    const host=sq('#workspace-panel');
    showPanel(host); activateStep(0); host.innerHTML='<p>正在读取已保存考核…</p>';
    try {
      const rows=await requestJson('/api/workspace/analyses');
      const admin=this.user.role==='admin';
      if(admin) this.bindings=await requestJson('/api/workspace/bindings');
      host.innerHTML=`<div class="panel-heading"><div><p class="section-index">${admin?'管理工作台':'我的问卷'}</p><h2>考核列表</h2></div><div class="workspace-actions"><button class="secondary-button" data-workspace-refresh>刷新进度</button>${admin?'<button class="primary-button" id="workspace-new">新建考核</button>':''}</div></div><p class="workspace-status" role="status" id="workspace-error"></p><div class="workspace-list">${rows.map(row=>`<article class="workspace-assessment"><div class="panel-heading"><div><h3>${escapeHtml(row.name)}</h3><p class="muted">${row.created_at?new Date(row.created_at).toLocaleString()+' · ':''}${row.finalized?'主观结果已确认':row.confirmed?'问卷填写中':'待确认名单'} · ${escapeHtml(row.id.slice(0,8))}</p></div><button class="primary-button" data-workspace-open="${row.id}">${admin?'打开考核':'填写／查看问卷'}</button></div>${row.managers.length?`<div class="score-statistics-table-wrap"><table class="score-table"><thead><tr><th>项目经理</th><th>工号</th><th>已完成／应评价</th><th>问卷</th></tr></thead><tbody>${row.managers.map(m=>`<tr><td>${escapeHtml(m.name)}</td><td>${escapeHtml(m.manager_id)}</td><td>${m.completed}／${m.expected}</td><td><button class="ghost-button" data-workspace-open="${row.id}" data-workspace-manager="${escapeHtml(m.manager_id)}">查看问卷</button></td></tr>`).join('')}</tbody></table></div>`:''}${admin&&row.confirmed?`<div class="workspace-actions"><button class="secondary-button" data-workspace-final="${row.id}" data-reopen="${row.finalized}">${row.finalized?'重新开放问卷':'确认最终主观结果'}</button><a class="secondary-button" href="/api/workspace/export?analysis_id=${encodeURIComponent(row.id)}">导出${row.finalized?'正式':'过程'}结果</a></div>`:''}</article>`).join('') || '<p class="muted">'+(admin?'尚无考核，请先登记项目经理，再新建考核导入报告。':'暂未分配问卷，请等待管理员确认考核名单。')+'</p>'}</div>${admin?`<details class="workspace-management"><summary>账号登记与本机备份</summary><h3>登记姓名与工号</h3><form id="workspace-add-user" class="workspace-actions"><label class="field"><span>姓名</span><input name="name" maxlength="80" required /></label><label class="field"><span>工号</span><input name="employee_id" maxlength="64" required /></label><label class="field"><span>角色</span><select name="role"><option value="manager">项目经理</option><option value="admin">管理员（可兼任经理）</option></select></label><button class="secondary-button">登记账号</button></form><div id="workspace-users"></div><h3>本机数据备份</h3><div class="workspace-actions"><a class="secondary-button" href="/api/workspace/backup">下载完整备份</a><label class="field"><span>选择恢复文件</span><input type="file" id="workspace-backup-file" accept=".sqlite3" /></label></div><p class="muted">本机保存账号、报告事实、问卷及修改历史。建议把下载备份另存一处；本机保存不等于云端同步。</p><div id="workspace-restore-preview"></div></details>`:''}`;
      host.querySelector('[data-workspace-refresh]').onclick=()=>this.home();
      host.querySelectorAll('[data-workspace-open]').forEach(b=>b.onclick=()=>this.open(b.dataset.workspaceOpen,b.dataset.workspaceManager));
      host.querySelectorAll('[data-workspace-final]').forEach(b=>b.onclick=async()=>{
        const reopen=b.dataset.reopen==='true';
        try{await assessmentPost('/api/workspace/finalize',{analysis_id:b.dataset.workspaceFinal,reopen});await this.home();}catch(e){sq('#workspace-error').textContent=e.message;}
      });
      if(admin) {
        this.renderUsers();
        sq('#workspace-new').onclick=()=>{clearAnalysisState();selectWorkflow('central');elements.importModeLabel.textContent='管理员统一导入 · 步骤 1';checkFeishuAuthorization();};
        sq('#workspace-add-user').onsubmit=async e=>{
          e.preventDefault();const form=e.target,button=form.querySelector('button');button.disabled=true;
          try{
            const user=await assessmentPost('/api/workspace/users',Object.fromEntries(new FormData(form)));
            this.users.push(user);this.renderUsers();
            form.elements.name.value='';form.elements.employee_id.value='';
            sq('#workspace-error').textContent='';
          }catch(err){sq('#workspace-error').textContent=err.message;}
          finally{button.disabled=false;}
        };
        sq('#workspace-backup-file').onchange=async e=>{
          const file=e.target.files[0];if(!file)return;
          try {
            const preview=await requestJson('/api/workspace/restore-preview',{method:'POST',body:file});
            sq('#workspace-restore-preview').innerHTML=`<p>备份包含${preview.users}个账号、${preview.analyses}次考核。恢复会替换当前工作区；系统会先备份现有数据。</p><button class="secondary-button" id="workspace-restore-confirm">确认恢复并重新登录</button>`;
            sq('#workspace-restore-confirm').onclick=async()=>{try{await assessmentPost('/api/workspace/restore',{digest:preview.digest,confirmed:true});subjective.drafts.clear();subjective.analysisId=null;clearAnalysisState();await this.initialize();}catch(err){sq('#workspace-error').textContent=err.message;}};
          } catch(err) {sq('#workspace-error').textContent=err.message;}
        };
      }
    } catch(error) {host.textContent=error.message;}
  },
  renderUsers() {
    const host=sq('#workspace-users');
    host.innerHTML=this.users.map(u=>`<div class="workspace-user-row"><span>${escapeHtml(u.name)} · ${escapeHtml(u.employee_id)}（${u.role==='admin'?'管理员':'项目经理'}）</span>${u.employee_id===this.user.employee_id?'<span class="muted">当前登录</span>':`<button type="button" class="ghost-button" data-delete-user="${escapeHtml(u.employee_id)}" aria-label="删除账号 ${escapeHtml(u.name)} ${escapeHtml(u.employee_id)}">删除账号</button>`}</div>`).join('')+'<div id="workspace-delete-confirm" role="status"></div>';
    host.querySelectorAll('[data-delete-user]').forEach(button=>button.onclick=()=>{
      const user=this.users.find(u=>u.employee_id===button.dataset.deleteUser);
      const confirmation=sq('#workspace-delete-confirm');
      confirmation.innerHTML=`<p>确认删除账号：${escapeHtml(user.name)} · ${escapeHtml(user.employee_id)}？删除后将无法选择该身份登录。</p><div class="workspace-actions"><button type="button" class="secondary-button" id="workspace-delete-submit">确认删除</button><button type="button" class="ghost-button" id="workspace-delete-cancel">取消</button></div><p id="workspace-delete-message"></p>`;
      sq('#workspace-delete-cancel').onclick=()=>{confirmation.innerHTML='';button.focus();};
      sq('#workspace-delete-submit').onclick=async e=>{
        const buttons=[...host.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
        try{
          await requestJson('/api/workspace/users/'+encodeURIComponent(user.employee_id),{method:'DELETE'});
          this.users=(await requestJson('/api/workspace/session')).users;
          this.renderUsers();
          sq('#workspace-delete-confirm').textContent='账号已删除。';
        }catch(err){const message=sq('#workspace-delete-message');if(message)message.textContent=err.message;}
        finally{buttons.forEach(b=>b.disabled=false);}
      };
      sq('#workspace-delete-cancel').focus();
    });
  },
  async open(id, manager='') {
    if(!await flushSubjectiveChanges())return;
    try {
      const analysis=await requestJson(`/api/workspace/analyses/${encodeURIComponent(id)}`);
      subjective.drafts.clear();subjective.analysisId=null;
      state.workflowMode='central';state.analysis=analysis;state.analysisStale=false;
      state.analysisServiceInstanceId=state.serviceInstanceId;
      elements.projectSummary.textContent=`${analysis.source_name} · ${analysis.experts.length}位评审人`;
      if(this.user.role==='admin') {
        await receiveAnalysis(analysis);showPanel(elements.importPanel);
        checkFeishuAuthorization();
      }
      if(this.user.role==='manager'||manager) {assessmentUI.managerId=manager||this.user.employee_id;await openSubjective();}
    } catch(error){const message=sq('#workspace-error');if(message)message.textContent=error.message;else setNotice(error.message);}
  },
  renderBindings() {
    const a=state.analysis;
    if(!a||a.assessment?.confirmed)return;
    sq('#assessment-local-managers').innerHTML=(a.reports||[]).map((r,i)=>{
      const owner=r.manager_identity?.owner_id||'';
      const local=r.source_type==='local_excel'&&!r.manager_identity?.source_token;
      const selected=local&&owner.startsWith('local:')?owner.slice(6):this.bindings[owner]||'';
      return `<div class="workspace-binding"><span>${escapeHtml(r.source_name)}${local?'':' · 原文件所有者：'+escapeHtml(r.manager_identity?.name||'待识别')}</span><select aria-label="${escapeHtml(r.source_name)}的项目经理" data-workspace-bind-select="${i}">${this.userOptions(selected)}</select><button class="secondary-button" data-workspace-bind="${i}" ${!local&&!owner?'disabled':''}>关联经理</button><span>${selected?'已关联':'待关联'}</span></div>`;
    }).join('');
    sq('#assessment-local-managers').querySelectorAll('[data-workspace-bind]').forEach(b=>b.onclick=async()=>{
      const index=Number(b.dataset.workspaceBind),r=a.reports[index],employee=sq(`[data-workspace-bind-select="${index}"]`).value;
      try{
        if(r.source_type==='local_excel'&&!r.manager_identity?.source_token) state.analysis=await assessmentPost('/api/assessment/local-manager',{analysis_id:a.analysis_id,source_name:r.source_name,manager_id:employee});
        else {await assessmentPost('/api/workspace/bindings',{owner_id:r.manager_identity.owner_id,employee_id:employee});this.bindings[r.manager_identity.owner_id]=employee;}
        renderAssessmentSetup();
      }catch(err){sq('#assessment-result').textContent=err.message;}
    });
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
    if(!sq('#subjective-form'))return;
    let tools=sq('#workspace-questionnaire-tools');
    if(!tools){tools=document.createElement('div');tools.id='workspace-questionnaire-tools';sq('#subjective-editor').prepend(tools);}
    const record=managerSaved(subjective.expert),locked=this.readonly();
    tools.innerHTML=`<p>${state.analysis.assessment?.finalized?'主观结果已确认，问卷只读。':record?.locked_by_admin?'管理员已调整此问卷；退回后经理可继续填写。':'填写后自动保存到本机，未完成的问卷也会保存。'}</p><div class="workspace-actions">${!locked?'<button type="button" class="secondary-button" id="workspace-save">保存问卷</button>':''}<button type="button" class="ghost-button" id="workspace-history">查看修改记录</button>${this.user.role==='admin'&&record?.locked_by_admin&&!state.analysis.assessment?.finalized?'<button type="button" class="secondary-button" id="workspace-return">退回经理填写</button>':''}</div><div id="workspace-history-content"></div>`;
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
