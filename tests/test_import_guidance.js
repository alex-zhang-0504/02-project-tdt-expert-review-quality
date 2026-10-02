const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes={};const sq=s=>nodes[s]||=( {value:'',textContent:'',innerHTML:'',disabled:false} );
let counts={errors:0,warnings:2}, calls=[], fail=false;
const receipt={version:'0.1',sha256:'hash',file:'config/virtual.json',loaded_at:'2026-09-21T00:00:00Z'};
const root={window:{},sq,escapeHtml:String,state:{analysis:{analysis_id:'a',assessment:{}},importActive:false},
  elements:{continueAnalysis:{}},validationCounts:()=>counts,
  requestJson:async url=>{calls.push(url);if(fail)throw Error('模拟读取失败');return receipt;},
  renderAssessmentSetup(){},syncServiceActions(){},activateStep(){},navigateStep:step=>calls.push(step)};
vm.createContext(root);vm.runInContext(fs.readFileSync('src/web/assessment.js','utf8'),root);
root.renderAssessmentSetup=()=>{};
(async()=>{
  sq('#assessment-names').value='虚拟专家甲';
  root.syncAssessmentActions();assert.equal(root.elements.continueAnalysis.disabled,false);
  assert.equal(root.elements.continueAnalysis.textContent,'读取');
  counts.errors=1;assert.equal(root.canEnterAssessment(),false);counts.errors=0;
  root.state.importActive=true;assert.equal(root.canEnterAssessment(),false);root.state.importActive=false;
  fail=true;await root.enterAssessment();assert.equal(root.elements.continueAnalysis.textContent,'读取');
  fail=false;await root.enterAssessment();assert.equal(root.elements.continueAnalysis.textContent,'下一步');
  assert.equal(calls.includes(2),false,'读取成功只进入下一步状态，不直接导航');
  root.requestJson=async (url,options)=>{calls.push(url);return {analysis_id:'a',assessment:{confirmed:true},reports:[],sessions:[],experts:[]};};
  root.elements.projectSummary={};
  await root.enterAssessment();assert.equal(calls.at(-1),2);
  root.renderRosterResult({included:['虚拟专家甲'],unmatched:[],excluded:[]},true);
  assert.ok(sq('#assessment-result').innerHTML.includes('已匹配'));
  root.state.analysis={analysis_id:'task',assessment:{}};
  root.window.workspace={taskId:'task'};
  vm.runInContext('assessmentUI.policy=null',root);calls=[];
  root.syncAssessmentActions();assert.equal(root.elements.continueAnalysis.textContent,'下一步');
  root.requestJson=async url=>{calls.push(url);throw Error('模拟任务参数读取失败');};
  await root.enterAssessment();assert.equal(calls.includes(2),false);assert.equal(root.elements.continueAnalysis.textContent,'下一步');
  root.requestJson=async(url,options)=>{calls.push(url);if(url.endsWith('/policy/objective'))return receipt;
    assert.equal(JSON.parse(options.body).policy_hash,'hash');
    return {analysis_id:'task',assessment:{confirmed:true},reports:[],sessions:[],experts:[]};};
  calls=[];await root.enterAssessment();
  assert.deepEqual(calls,['/api/workspace/tasks/task/policy/objective','/api/assessment/roster',2]);
  console.log('任务下一步：自动校验任务参数、一次点击确认并进入、读取失败停留通过');
  console.log('导入引导：提醒放行、错误及扫描阻断、读取失败保持、两次点击及已匹配分类通过');
})().catch(e=>{console.error(e);process.exitCode=1;});
