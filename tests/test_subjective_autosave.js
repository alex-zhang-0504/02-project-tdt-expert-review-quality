const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes={};const node=s=>nodes[s]||=( {dataset:{},textContent:'',innerHTML:'',value:'',disabled:false,removeAttribute(){}});
Object.defineProperty(node('#subjective-editor'),'innerHTML',{set(v){this.markup=v;node('.subjective-fields').disabled=/class="subjective-fields" disabled/.test(v)},get(){return this.markup}});
let release,ready,locked=false,fail=false;
const root={structuredClone,window:{workspace:{personal(){return this.user?.role==='manager'},managing(){return this.user?.role==='admin'},readonly:()=>locked,syncQuestionnaire(){}}},document:{querySelector:node,querySelectorAll:()=>[]},
state:{analysis:{analysis_id:'test',experts:[{expert_name:'虚拟评审人甲',sessions:[],overall:{}}],assessment:{},manager_reviews:{}}},escapeHtml:String,checkServiceHealth:async()=>true,
requestJson:()=>{ready();return new Promise((resolve,reject)=>release=()=>fail?reject(Error('虚拟网络失败')):resolve({revision:1,rule_version:'v',ratings:{p:{option:'high'}}}))},
reviewerMatchesSearch:()=>true,normalizedReviewerSearch:s=>s,showPanel(){},activateStep(){}};
vm.createContext(root);for(const f of ['subjective.js','assessment.js'])vm.runInContext(fs.readFileSync('src/web/'+f,'utf8'),root);
vm.runInContext(`assessmentUI.managerId='a';assessmentUI.tasks=[{manager_id:'a',name:'虚拟项目经理',experts:{'虚拟评审人甲':[]}}];subjective.analysisId='test';subjective.expert='虚拟评审人甲';subjective.catalog=[{id:'p',title:'模拟题',rule_version:'v',options:[{id:'high',title:'高',description:'说明'}]}];`,root);
async function main(){
 for(const error of [false,true]){
  fail=error;root.subjectiveDraft().dirty=true;root.subjectiveDraft().ratings.p={option:'high'};
  const waiting=new Promise(r=>ready=r);const save=root.flushSubjectiveChanges(true);await waiting;
  root.subjectiveDraft().changes++;root.renderSubjectiveEditor();release();await save;
  assert.equal(node('.subjective-fields').disabled,false,'后台提交后必须恢复连续填答');
  assert.equal(root.subjectiveDraft().dirty,true,'提交期间的新编辑及失败草稿须保留');
  assert.equal(node('#subjective-save-retry').hidden,!error,'仅保存失败时提供重试入口');
 }
 locked=true;root.subjectiveDraft().dirty=true;fail=false;
 const waiting=new Promise(r=>ready=r);const save=root.flushSubjectiveChanges(true);await waiting;root.renderSubjectiveEditor();release();await save;
 assert.equal(node('.subjective-fields').disabled,true,'管理员只读状态不得被解除');
 assert.equal(node('#subjective-save-retry').hidden,true,'重试成功后不残留保存按钮');
 root.flushSubjectiveChanges=async()=>true;root.renderDimensionScores=async()=>{};
 await root.showDimensionPage('objective',1);assert.equal(node('#export-dimension-one').hidden,true);
 await root.showDimensionPage('objective',2);assert.equal(node('#export-dimension-one').hidden,false);
 console.log('自动保存连续编辑、失败保留、只读保护及客观导出分页通过');
}
main().catch(e=>{console.error(e);process.exitCode=1});
