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
  const remaining={isConnected:true,offsetHeight:200,getBoundingClientRect:()=>({top:entry.isConnected?400:160}),querySelector:()=>({focus:o=>{remaining.focusOptions=o}}),animate:(frames,options)=>{remaining.motion={frames,options}}};
  const entry={isConnected:true,getBoundingClientRect:()=>({top:160}),nextElementSibling:remaining,remove(){this.isConnected=false}};
  sq('#workspace-panel').querySelectorAll=()=>[entry,remaining];
  root.document={documentElement:{scrollHeight:2200}};
  root.window.scrollY=900;root.window.innerHeight=700;root.window.matchMedia=()=>({matches:false});root.window.scrollTo=o=>{root.scrollResult=o};
  workspace.removeTaskCard(entry);
  assert.equal(root.scrollResult.top,900);
  assert.equal(remaining.focusOptions.preventScroll,true);
  assert.equal(remaining.motion.options.duration,180);
  assert.equal(remaining.motion.frames[0].transform,'translateY(240px)');
  remaining.isConnected=true;root.window.matchMedia=()=>({matches:true});root.document.documentElement.scrollHeight=900;
  sq('#workspace-create').focus=()=>{};remaining.remove=()=>{remaining.isConnected=false};
  workspace.removeTaskCard(remaining);assert.equal(root.scrollResult.top,200);
  console.log('经理匹配及删除卡片保留视口、补位、页面底部回收通过');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
