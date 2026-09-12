const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const nodes = {};
const element = () => ({innerHTML:"", textContent:"", value:"", open:false,
  classList:{toggle(){}}, querySelectorAll(){return [];}, showModal(){this.open=true;}, close(){this.open=false;}});
const root = {document:{querySelector(s){return nodes[s] ||= element();}}, console,
  escapeHtml:s=>String(s??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll('"',"&quot;"),
  normalizedReviewerSearch:s=>s, reviewerMatchesSearch:()=>true, syncServiceActions(){},
  state:{workflowMode:"central"}, elements:{dimensionOneSearch:element(),dimensionOneStage:element(),
    analysisSummary:element(),dimensionOneTableWrap:element(),evidenceDrawerTitle:element(),
    evidenceDrawerContent:element(),evidenceDrawer:element()}};
vm.createContext(root);
vm.runInContext(fs.readFileSync("src/web/facts.js","utf8"),root);
const stats={expected:12,attended:12,unknown:0,signed:10,opinions:24,solutions:6,pending:0,suspected:0,
  attendance_rate:100,signoff_rate:83.33,opinion_rate:200,solution_rate:25,proxy:2,proxy_rate:16.67};
assert.equal(root.factCellText(stats,"proxy_rate"),"2/12");
assert.equal(root.subtaskDisplayName("虚拟大TDT-虚拟子任务-射频"),"虚拟子任务-射频");
assert.equal(root.subtaskDisplayName("虚拟子任务"),"虚拟子任务");
assert.equal(root.factCellText(stats,"opinions"),"24");
assert.equal(root.factCellText(stats,"opinion_rate"),"200％");
assert.equal(root.factCellText({...stats,pending:3},"solutions"),"—");
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
assert.equal((root.elements.dimensionOneTableWrap.innerHTML.match(/<td /g)||[]).length,31);
assert.ok(root.elements.dimensionOneTableWrap.innerHTML.includes('colspan="9"'));
assert.ok(root.elements.dimensionOneTableWrap.innerHTML.includes("代理情况"));
assert.ok(root.elements.dimensionOneTableWrap.innerHTML.includes('评审参与度'));
assert.ok(root.elements.dimensionOneTableWrap.innerHTML.includes('data-participation="0">12场'));
root.elements.dimensionOneStage.value="TDR2";
root.renderDimensionOneTable();
assert.equal((root.elements.dimensionOneTableWrap.innerHTML.match(/<td /g)||[]).length,13);
assert.ok(root.elements.dimensionOneTableWrap.innerHTML.includes('data-participation="0">12场'));
root.openDimensionOneEvidence("虚拟评审人");
const detail=root.elements.evidenceDrawerContent.innerHTML;
assert.equal((detail.match(/<th scope/g)||[]).length,5);
assert.equal((detail.match(/<tr>/g)||[]).length,2);
assert.ok(detail.includes("TDR1")&&detail.includes("TDR2"));
assert.ok(detail.includes('<td data-stage="TDR3"><p class="muted">本批次无参评记录。</p></td>'));
const stageCells = [...detail.matchAll(/<td data-stage="(TDR[123])">([\s\S]*?)<\/td>/g)];
assert.ok(stageCells[0][2].includes("&lt;script>意见"));
assert.ok(!stageCells[0][2].includes("TDR2独立意见"));
assert.ok(stageCells[1][2].includes("TDR2独立意见"));
assert.ok(detail.includes("查看证据")&&detail.includes("不计入统计"));
assert.ok(detail.includes("&lt;script>"));
assert.ok(!detail.includes("项目经理")&&!detail.includes("出勤：")&&!detail.includes("<script>"));
assert.equal(root.elements.evidenceDrawer.open,true);
console.log("主副表交互渲染断言通过");
