const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes={};
const sq=id=>nodes[id] ||= {hidden:false,textContent:'',innerHTML:'',setAttribute(key,value){this[key]=value;}};
const root={window:{},sq,URLSearchParams,escapeHtml:String,managerSaved:()=>null,
  state:{analysis:{analysis_id:'virtual',assessment:{}}},managerDraftKey:()=> 'virtual-key',subjective:{drafts:new Map(),expert:'虚拟评审人',catalog:[]},
  assessmentUI:{managerId:'virtual-manager'},flushSubjectiveChanges:async()=>true};
vm.createContext(root);vm.runInContext(fs.readFileSync('src/web/workspace.js','utf8'),root);
async function main(){
  const workspace=root.window.workspace;workspace.user={role:'admin'};
  let reads=0;root.requestJson=async()=>{reads++;return [];};
  workspace.syncQuestionnaire();
  const button=sq('#workspace-history'),content=sq('#workspace-history-content');
  assert.equal(content.hidden,true);
  await button.onclick();assert.equal(content.hidden,false);assert.equal(button.textContent,'收起修改记录');
  await button.onclick();assert.equal(content.hidden,true);assert.equal(button['aria-expanded'],'false');assert.equal(reads,1);
  await button.onclick();assert.equal(content.hidden,false);assert.equal(reads,2);
  await button.onclick();
  let resolve,started;const loading=new Promise(r=>{started=r;});
  root.requestJson=()=>new Promise(r=>{resolve=r;started();});
  const opening=button.onclick();await loading;
  await button.onclick();assert.equal(content.hidden,true);
  resolve([]);await opening;assert.equal(content.hidden,true,'迟到响应不得重新展开');
  root.requestJson=async()=>{throw new Error('读取失败');};
  await button.onclick();assert.equal(content.textContent,'读取失败');
  await button.onclick();assert.equal(content.hidden,true,'错误提示也能收起');
  workspace.syncQuestionnaire();assert.equal(button.textContent,'查看修改记录');
  console.log('修改记录展开、收起、重新读取、加载中收起与错误收起通过');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
