const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),sq=key=>{if(!nodes.has(key))nodes.set(key,{hidden:false,open:false,dataset:{},showModal(){this.open=true},setAttribute(){},removeAttribute(){},querySelectorAll(){return []}});return nodes.get(key)};
let locked=false;
const root={window:{},sq,state:{analysis:{assessment:{}}},subjective:{drafts:new Map(),expert:'虚拟评审人'},
managerSaved:()=>({locked_by_admin:locked}),managerDraftKey:()=> 'draft',flushSubjectiveChanges:async()=>true,document:{querySelectorAll:()=>[]}};
vm.createContext(root);vm.runInContext(fs.readFileSync('src/web/workspace.js','utf8'),root);vm.runInContext(fs.readFileSync('src/web/assessment.js','utf8'),root);
async function main(){
 root.managerSaved=()=>({locked_by_admin:locked});root.managerDraftKey=()=> 'draft';
 const w=root.window.workspace;w.user={role:'admin',employee_id:'admin'};
 const analysis=root.state.analysis;root.state.analysis=null;assert.equal(w.mayLeave(),true,'首次登录尚无任务时必须能进入首页');root.state.analysis=analysis;
 assert.equal(w.mayLeave(),true);
 root.subjective.drafts.set('draft',{dirty:true});assert.equal(w.mayLeave(),false,'未自动保存的管理员修改也必须拦截');
 vm.runInContext("assessmentUI.managerId='admin'",root);assert.equal(w.mayLeave(),true,'管理员本人问卷不进入代填锁定');
 vm.runInContext("assessmentUI.managerId='other'",root);
 assert.equal(sq('#admin-edit-warning').open,true);sq('#admin-edit-warning').open=false;
 root.subjective.drafts.clear();locked=true;
 assert.equal(w.mayLeave(),false);sq('#admin-edit-warning').open=false;assert.equal(w.mayLeave(),false,'了解不能解除修改状态');
 sq('#subjective-page-one').hidden=false;await root.showDimensionPage('subjective',2);assert.equal(sq('#subjective-page-one').hidden,false,'锁定时不可跳到打分页');
 locked=false;root.renderDimensionScores=async()=>{};await root.showDimensionPage('subjective',2);assert.equal(sq('#subjective-page-one').hidden,true);
 w.user={role:'manager'};sq('#objective-page-one').hidden=false;await root.showDimensionPage('objective',2);assert.equal(sq('#objective-page-one').hidden,false,'技术项目经理不能打开客观打分页');
 console.log('管理员修改状态、了解后仍阻断、主观分页及技术项目经理范围通过');
}
main().catch(e=>{console.error(e);process.exitCode=1});
