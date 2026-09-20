const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = {};
const root = {console, structuredClone, document:{querySelector:s=>nodes[s] ||= {dataset:{},textContent:'',innerHTML:'',value:'',open:false}},
  state:{analysis:{experts:[{expert_name:'虚拟专家甲',sessions:[{project_code:'P1',project_name:'虚拟项目'}],overall:{}}],assessment:{exclusions:{}},manager_reviews:{}}},
  escapeHtml:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
  reviewerMatchesSearch:()=>true,normalizedReviewerSearch:s=>s};
vm.createContext(root);
for (const file of ['subjective.js','assessment.js']) vm.runInContext(fs.readFileSync('src/web/'+file,'utf8'),root);
vm.runInContext(`assessmentUI.managerId='a'; assessmentUI.tasks=[{manager_id:'a',name:'虚拟经理甲',experts:{'虚拟专家甲':['P1']}},{manager_id:'b',name:'虚拟经理乙',experts:{'虚拟专家甲':['P1']}}];
  subjective.expert='虚拟专家甲'; subjective.catalog=Array.from({length:6},(_,i)=>({id:'d'+i,title:'维度'+i,options:[{id:'high',title:'高档',description:'解释<示例>'},{id:'low',title:'低档',description:'低档解释'}]}));`,root);
root.renderSubjectiveEditor();
assert.ok(nodes['#subjective-editor'].innerHTML.includes('解释&lt;示例>'));
assert.ok(!nodes['#subjective-editor'].innerHTML.includes('id="subjective-evaluator"'));
assert.equal(nodes['#subjective-completion-bar'].value,0);
root.subjectiveDraft().ratings.d0={option:'high',note:'',project_code:''};
root.subjectiveDraft().dirty=true;
root.renderSubjectiveEditor();
assert.equal(nodes['#subjective-completion-bar'].value,1);
vm.runInContext("assessmentUI.managerId='b'",root);
root.renderSubjectiveEditor();
assert.equal(nodes['#subjective-completion-bar'].value,0);
vm.runInContext("assessmentUI.managerId='a'",root);
root.renderSubjectiveEditor();
assert.equal(nodes['#subjective-completion-bar'].value,1);
root.state.analysis.assessment.exclusions['["a", "虚拟专家甲"]']='无需评价';
root.renderSubjectiveEditor();root.renderSubjectiveRail();
assert.equal(nodes['#restore-manager-task'].hidden,false);
assert.equal(nodes['#exclude-manager-task'].hidden,true);
assert.ok(nodes['#subjective-experts'].innerHTML.includes('已排除'));
vm.runInContext("assessmentUI.managerId='b'",root);
root.renderSubjectiveEditor();
assert.equal(nodes['#restore-manager-task'].hidden,true);
assert.equal(nodes['#exclude-task-reason'].value,'');
assert.equal(nodes['#subjective-task-management'].open,false);
console.log('主观界面：经理草稿隔离、填答进度、任务状态及解释转义通过');
