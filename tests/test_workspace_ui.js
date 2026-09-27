const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map();
const sq = key => {
  if (!nodes.has(key)) nodes.set(key, {innerHTML:'',textContent:'',hidden:false,value:'虚拟专家甲',querySelectorAll:()=>[],querySelector:()=>({})});
  return nodes.get(key);
};
let response = {users:[],errors:[]};
const root = {window:{},sq,state:{analysis:{analysis_id:'a',assessment:{}},importActive:false},
  elements:{continueAnalysis:{}},escapeHtml:String,validationCounts:()=>({errors:0}),
  requestJson:async()=>response};
vm.createContext(root);
vm.runInContext(fs.readFileSync('src/web/workspace.js','utf8'),root);
vm.runInContext(fs.readFileSync('src/web/assessment.js','utf8'),root);
async function main() {
  const workspace=root.window.workspace;
  sq('#assessment-result').innerHTML='已匹配原名单';
  response={users:[],errors:[{name:'虚拟经理',owner_id:'ou_virtual',reports:['a.xlsx','b.xlsx'],reason:'待确认',can_assign:true}]};
  await workspace.renderBindings();
  assert.equal(sq('#workspace-manager-errors').hidden,false);
  assert.match(sq('#workspace-manager-errors').innerHTML,/涉及2份报告/);
  assert.equal(sq('#assessment-result').innerHTML,'已匹配原名单');
  assert.equal(root.canEnterAssessment(),false);
  response={users:[],errors:[]};
  await workspace.renderBindings();
  assert.equal(sq('#workspace-manager-errors').hidden,true);
  assert.equal(root.canEnterAssessment(),true);
  const pending=[];
  root.requestJson=()=>new Promise(resolve=>pending.push(resolve));
  const first=workspace.renderBindings();
  assert.equal(root.canEnterAssessment(),false);
  const second=workspace.renderBindings();
  pending[1]({users:[],errors:[]});await second;
  pending[0]({users:[],errors:[{reason:'过时响应'}]});await first;
  assert.equal(workspace.managerErrors.length,0);
  assert.equal(sq('#workspace-manager-errors').hidden,true);
  assert.equal(sq('#assessment-result').innerHTML,'已匹配原名单');
  console.log('经理匹配：只显异常、保留名单、阻断未确认及忽略过时响应通过');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
