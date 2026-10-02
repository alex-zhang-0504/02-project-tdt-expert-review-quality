const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('src/web/assessment.js','utf8');
const host={innerHTML:'',querySelectorAll:()=>[]};
const base={stages:Object.fromEntries(['TDR1','TDR2','TDR3'].map(s=>[s,{score:0}])),subjective_items:[],subjective_progress:{provisional:0,completed:0,expected:1}};
const fixtures=[['虚拟零分',0,0],['虚拟待统计',null,null],['虚拟甲',20,30],['虚拟乙',10,60],['虚拟同分',10,30]].map(([expert_name,objective_with_rewards,subjective_total])=>({...base,expert_name,objective_with_rewards,subjective_total}));
const ctx={sq:()=>host,state:{analysis:{analysis_id:'test'}},subjective:{catalog:[]},requestJson:async()=>({rows:structuredClone(fixtures),policy:{parameters:{components:{attendance:5},participation:{tier_scores:[5]},subjective:{a:{high:10}}}}}),scoreText:x=>x??'待统计',escapeHtml:String,objectiveReviewerHeader:()=>'',objectiveReviewerVisible:name=>name!=='虚拟甲',importHint:()=>'',makeTableScrollable(){}};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('async function renderDimensionScores('),source.indexOf('function downloadAssessment(')),ctx);
(async()=>{
  for(const [kind,expected] of [
    ['objective',['虚拟甲','虚拟乙','虚拟同分','虚拟零分','虚拟待统计']],
    ['subjective',['虚拟乙','虚拟甲','虚拟同分','虚拟零分','虚拟待统计']],
  ]){
    await ctx.renderDimensionScores(kind);
    const names=[...host.innerHTML.matchAll(/<td>(虚拟[^<]*)<\/td>/g)].map(m=>m[1]);
    assert.deepEqual(names,expected);
    if(kind==='objective')assert.match(host.innerHTML,/<tr data-reviewer="虚拟甲" hidden>/);
  }
  assert.equal(fixtures[0].expert_name,'虚拟零分');
  console.log('主客观降序：独立总分、同分稳定、零分、待统计置后及筛选保持通过');
})().catch(error=>{console.error(error);process.exitCode=1;});
