const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const nodes = {};
const element = () => ({innerHTML:"", textContent:"", value:"", open:false,
  classList:{toggle(){}}, querySelectorAll(){return [];}, showModal(){this.open=true;}, close(){this.open=false;}});
const root = {document:{addEventListener(){},querySelector(s){return nodes[s] ||= element();}}, console,
  escapeHtml:s=>String(s??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll('"',"&quot;"),
  normalizedReviewerSearch:s=>s, reviewerMatchesSearch:()=>true, syncServiceActions(){},
  window:{addEventListener(){}}, state:{workflowMode:"central"}, elements:{dimensionOneSearch:element(),dimensionOneStage:element(),
    analysisSummary:element(),dimensionOneTableWrap:element(),evidenceDrawerTitle:element(),
    evidenceDrawerContent:element(),evidenceDrawer:element()}};
vm.createContext(root);
vm.runInContext(fs.readFileSync("src/web/facts.js","utf8"),root);
root.makeTableScrollable = () => {};
const stats={expected:12,attended:12,unknown:0,signed:10,opinions:24,solutions:6,pending:0,suspected:0,
  attendance_rate:100,signoff_rate:83.33,opinion_rate:200,solution_rate:25,proxy:2,proxy_rate:16.67};
assert.equal(root.factCellText(stats,"proxy_rate"),"2/12");
assert.equal(root.subtaskDisplayName("虚拟大TDT-虚拟子任务-射频"),"虚拟子任务-射频");
assert.equal(root.subtaskDisplayName("虚拟子任务"),"虚拟子任务");
assert.equal(root.factCellText(stats,"opinions"),"24");
assert.equal(root.factCellText(stats,"opinion_rate"),"200％");
assert.equal(root.factCellText({...stats,pending:3},"solutions"),"待识别");
assert.equal(root.factCellText({...stats,opinions:0},"opinions"),"0");
assert.deepEqual(Array.from(root.visibleFactGroups("TDR2")),["TDR2"]);
assert.deepEqual(Array.from(root.visibleFactGroups("overall")),["全部阶段"]);
const opinion={opinion_id:"safe-id",text:"<script>意见</script>",excerpt:"",reason:"理由",ai_status:"suspected",
  included:null,cells:["D9"],raw_texts:["原文"],audit:[],rule_version:"test"};
const session={project_code:"P001",project_name:"虚拟子任务",stage:"TDR1",source_name:"虚拟报告.xlsx",
  sheet_name:"TDR1",opinions:[opinion]};
root.state.analysis={experts:[{expert_name:"虚拟评审人",overall:stats,
  stages:{TDR1:stats,TDR2:stats,TDR3:stats},sessions:[session,{...session,stage:"TDR2",opinions:[{...opinion,text:"TDR2独立意见"}]}]}]};
root.renderDimensionOneTable();
assert.equal((root.elements.dimensionOneTableWrap.innerHTML.match(/<td /g)||[]).length,28);
assert.ok(root.elements.dimensionOneTableWrap.innerHTML.includes('colspan="8"'));
assert.ok(root.elements.dimensionOneTableWrap.innerHTML.includes("代理情况"));
assert.ok(root.elements.dimensionOneTableWrap.innerHTML.includes('总参与<br>评审场次'));
assert.ok(root.elements.dimensionOneTableWrap.innerHTML.includes('data-participation="0">12场'));
root.elements.dimensionOneStage.value="TDR2";
root.renderDimensionOneTable();
assert.equal((root.elements.dimensionOneTableWrap.innerHTML.match(/<td /g)||[]).length,12);
assert.ok(root.elements.dimensionOneTableWrap.innerHTML.includes('data-participation="0">12场'));
root.openDimensionOneEvidence("虚拟评审人");
const detail=root.elements.evidenceDrawerContent.innerHTML;
assert.ok(!detail.includes('<table'));
assert.equal((detail.match(/class="review-stage"/g)||[]).length,3);
assert.ok(detail.includes('本批次未导入该阶段报告'));
assert.ok(detail.includes('TDR2独立意见'));
assert.ok(detail.includes('&lt;script>意见'));
assert.ok(!detail.includes('来源：') && !detail.includes('D9'));
assert.ok(!detail.includes('暂不判断'));
assert.equal((detail.match(/data-include=/g)||[]).length,4);
assert.ok(detail.includes('判定说明：理由'));
assert.ok(detail.includes('会签：'));
assert.equal(root.factCellText({...stats,expected:0},'opinions'),'—');
assert.equal(root.factCellText({...stats,expected:1,opinions:0},'opinions'),'0');
assert.equal(root.factCellText({...stats,unknown:1},'attendance_rate'),'待确认');
root.state.analysis.sessions=[{project_code:'P001',stage:'TDR3'}];
root.openDimensionOneEvidence('虚拟评审人');
assert.ok(root.elements.evidenceDrawerContent.innerHTML.includes('未列入本阶段评审名单'));
const identical = root.renderOpinion({...opinion,text:'同一条意见',excerpt:'同一条意见',raw_texts:['同一条意见','同一条意见']}, session, 0);
assert.ok(!identical.includes('拆分前原文'));
assert.ok(!root.elements.dimensionOneTableWrap.innerHTML.includes('含对策意见率'));
assert.ok(!detail.includes("项目经理")&&!detail.includes("出勤：")&&!detail.includes("<script>"));
assert.equal(root.elements.evidenceDrawer.open,true);
console.log("主副表交互渲染断言通过");

const latestOnly=root.renderOpinion({...opinion,audit:[{at:'2001-01-01T00:00:00Z',to:true},{at:'2026-09-14T01:02:03Z',to:false}]},session,0);
assert.equal((latestOnly.match(/最近修改：/g)||[]).length,1);
assert.ok(!latestOnly.includes('2001') && !latestOnly.includes('人工选择记录'));
assert.equal((latestOnly.match(/<strong>对策：/g)||[]).length,1);
assert.ok(!latestOnly.includes('疑似待确认'));

const unresolvedCard=root.renderOpinion(opinion,session,0);
assert.ok(unresolvedCard.includes('needs-confirmation'));
assert.equal((unresolvedCard.match(/aria-pressed="false"/g)||[]).length,2);
assert.ok(!unresolvedCard.includes('aria-pressed="true"'));
const includedCard=root.renderOpinion({...opinion,included:true},session,0);
assert.ok(!includedCard.includes('needs-confirmation'));
assert.equal((includedCard.match(/aria-pressed="true"/g)||[]).length,1);
