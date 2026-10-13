const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes={};
const sq=id=>nodes[id] ||= {innerHTML:'',textContent:'',addEventListener(type,fn){this[type]=fn;},querySelectorAll:()=>[],focus(){this.focused=true;}};
const rows=[['虚拟零分',0,0,0],['虚拟待统计',null,null,null],['虚拟甲',9,70,79],['虚拟乙',50,30,80],['虚拟同分',9,70,79]].map(([expert_name,objective_with_rewards,subjective_total,total])=>({expert_name,objective_with_rewards,subjective_total,total,reasons:[],objective_total:objective_with_rewards,opinion_bonus:0,solution_bonus:0,uncapped_total:total}));
const ctx={sq,state:{analysis:{assessment:{policy:{parameters:{precision:2}}}}},escapeHtml:String,importHint:String,makeTableScrollable(){},window:{},opened:''};
ctx.openDimensionOneEvidence=name=>ctx.opened=name;
vm.createContext(ctx);vm.runInContext(fs.readFileSync('src/web/score-statistics.js','utf8'),ctx);
ctx.document={addEventListener(){}};
ctx.state.analysis.analysis_id='virtual-first';
ctx.state.analysis.experts=rows.map(r=>({expert_name:r.expert_name}));
vm.runInContext(fs.readFileSync('src/web/reviewer-filter.js','utf8'),ctx);
ctx.fixture={rows,policy:{parameters:{total_cap:100}}};
vm.runInContext('scoreStatistics.data=fixture; initializeScoreStatisticsUI(); renderScoreStatistics();',ctx);
const names=()=>[...sq('#score-statistics-table').innerHTML.matchAll(/<tr><th>(虚拟[^<]*)<\/th>/g)].map(x=>x[1]);
const click=key=>sq('#score-statistics-table').click({target:{closest:selector=>selector==='[data-score-sort]'?{dataset:{scoreSort:key}}:null}});
assert.deepEqual(names(),['虚拟乙','虚拟甲','虚拟同分','虚拟零分','虚拟待统计']);
for(const [key,descending,ascending] of [
  ['objective_with_rewards',['虚拟乙','虚拟甲','虚拟同分','虚拟零分','虚拟待统计'],['虚拟零分','虚拟甲','虚拟同分','虚拟乙','虚拟待统计']],
  ['subjective_total',['虚拟甲','虚拟同分','虚拟乙','虚拟零分','虚拟待统计'],['虚拟零分','虚拟乙','虚拟甲','虚拟同分','虚拟待统计']],
  ['total',['虚拟乙','虚拟甲','虚拟同分','虚拟零分','虚拟待统计'],['虚拟零分','虚拟甲','虚拟同分','虚拟乙','虚拟待统计']],
]){
  click(key);assert.deepEqual(names(),descending);click(key);assert.deepEqual(names(),ascending);
  ctx.renderScoreStatistics();assert.deepEqual(names(),ascending,'刷新渲染保持排序');
  assert.match(sq('#score-statistics-table').innerHTML,/aria-sort="ascending"/);
}
const html=sq('#score-statistics-table').innerHTML;
for(const [index,row] of rows.entries())assert.ok(html.includes(`<tr><th>${row.expert_name}</th>`)&&html.split(`<tr><th>${row.expert_name}</th>`)[1].split('</tr>')[0].includes(`data-score-detail="${index}"`));
sq('#score-statistics-details').click({target:{closest:()=>({dataset:{scoreEvidence:'3'}})}});assert.equal(ctx.opened,'虚拟乙');
assert.deepEqual(rows.map(r=>r.expert_name),['虚拟零分','虚拟待统计','虚拟甲','虚拟乙','虚拟同分']);
assert.doesNotMatch(html,/含奖励|主观最终分/);assert.match(html,/客观总得分/);assert.match(html,/主观总得分/);
assert.doesNotMatch(ctx.statisticsTable(rows,100,true),/data-score-sort/);
vm.runInContext("reviewerFilters.total.names=new Set(['虚拟甲','虚拟零分']);renderScoreStatistics();",ctx);
assert.deepEqual(names(),['虚拟零分','虚拟甲']);
assert.match(sq('#score-statistics-table').innerHTML,/data-score-detail="2"/);
assert.match(sq('#score-statistics-details').innerHTML,/id="score-detail-3" hidden/);
assert.equal(ctx.objectiveReviewerVisible('虚拟乙'),true);
assert.equal(ctx.objectiveReviewerVisible('虚拟乙','subjective'),true);
assert.match(ctx.statisticsTable(rows,100,true),/虚拟乙/);
vm.runInContext('reviewerFilters.total.names=new Set();renderScoreStatistics();',ctx);
assert.match(sq('#score-statistics-table').innerHTML,/没有匹配的评审人/);
ctx.state.analysis.analysis_id='virtual-second';ctx.renderScoreStatistics();
assert.equal(names().length,5);
vm.runInContext(fs.readFileSync('src/web/workspace.js','utf8'),ctx);
ctx.requestJson=async()=>{throw new Error('session-stop');};
(async()=>{
  await assert.rejects(ctx.window.workspace.initialize(),/session-stop/);
  ctx.renderScoreStatistics();assert.deepEqual(names(),['虚拟乙','虚拟甲','虚拟同分','虚拟零分','虚拟待统计']);
  console.log('总分统计：三列双向数值排序、同分稳定、空分置后、零分、明细归属、刷新保留及登录初始化通过');
})().catch(e=>{console.error(e);process.exitCode=1;});
