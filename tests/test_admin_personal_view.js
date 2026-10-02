const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
let saved=true,locked=false,homeCalls=0,cleared=0;
const nodes=new Map(),sq=id=>{if(!nodes.has(id))nodes.set(id,{open:false,showModal(){this.open=true;}});return nodes.get(id)};
const root={window:{},document:{body:{dataset:{}},querySelectorAll:()=>[]},sq,
 state:{analysis:{assessment:{}},importActive:false},factsMutating:false,
 subjective:{drafts:new Map(),expert:'虚拟评审人',analysisId:'old',catalog:[]},
 assessmentUI:{managerId:'other',tasks:[]},scoreStatistics:{data:{},requestId:0},
 managerSaved:()=>({locked_by_admin:locked}),managerDraftKey:()=> 'draft',
 flushSubjectiveChanges:async()=>saved,clearAnalysisState:()=>{cleared++;root.state.analysis=null;},
 clearTimeout,setNotice:()=>{}};
vm.createContext(root);vm.runInContext(fs.readFileSync('src/web/workspace.js','utf8'),root);
async function run(){
 const w=root.window.workspace;w.user={role:'admin',employee_id:'admin'};w.home=async()=>homeCalls++;
 await w.switchView('personal');assert.equal(w.view,'management','无本人报告不能进入个人视图');w.hasPersonalProjects=true;
 locked=true;await w.switchView('personal');assert.equal(w.view,'management');assert.equal(sq('#admin-edit-warning').open,true);
 locked=false;saved=false;await w.switchView('personal');assert.equal(w.view,'management','保存失败不得切换');
 saved=true;w.pendingRequests=1;await w.switchView('personal');assert.equal(w.view,'management','读取未完成不得切换');
 w.pendingRequests=0;root.factsMutating=true;await w.switchView('personal');assert.equal(w.view,'management');
 root.factsMutating=false;root.subjective.drafts.set('old',{dirty:false});await w.switchView('personal');
 assert.equal(w.user.role,'admin');assert.equal(w.personal(),true);assert.equal(w.managing(),false);
 assert.equal(root.document.body.dataset.workspaceRole,'manager');assert.equal(root.subjective.drafts.size,0);
 assert.equal(root.scoreStatistics.data,null);assert.equal(cleared,1);assert.equal(homeCalls,1);
 await w.switchView('management');assert.equal(w.managing(),true);assert.equal(root.document.body.dataset.workspaceRole,'admin');assert.equal(homeCalls,2);
 w.user={role:'manager'};await w.switchView('personal');assert.equal(homeCalls,2);assert.equal(w.personal(),true);
 console.log('管理员双视图、请求中与保存失败阻断、代填锁、状态清理通过');
}
run().catch(e=>{console.error(e);process.exitCode=1});
