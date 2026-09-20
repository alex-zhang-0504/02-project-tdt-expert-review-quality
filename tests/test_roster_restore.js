const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map();
const sq = selector => {
  if (!nodes.has(selector)) nodes.set(selector, {value:'',textContent:'',innerHTML:'',disabled:false});
  return nodes.get(selector);
};
const calls = [];
let response = {requested:['虚拟专家甲','虚拟专家乙'],included:['虚拟专家甲'],unmatched:['虚拟专家乙'],excluded:[]};
let failure = false;
const context = {
  sq, state:{analysis:{analysis_id:'test',assessment:{}},importActive:false},
  elements:{continueAnalysis:{}}, escapeHtml:String, validationCounts:()=>({errors:0,warnings:0}),
  requestJson:async (url, options) => {calls.push([url,options]);if(failure) throw Error('无姓名列');return response;}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('src/web/assessment.js','utf8'), context);
async function main() {
  context.syncAssessmentActions();
  assert.equal(sq('#assessment-restore-roster').disabled,true);
  const upload = name => context.importAssessmentRoster({target:{files:[{name}]}});
  await upload('first.xlsx');
  const original = sq('#assessment-names').value;
  assert.equal(original,'虚拟专家甲\n虚拟专家乙');
  assert.equal(sq('#assessment-restore-roster').disabled,true);
  sq('#assessment-names').value='';
  context.syncAssessmentActions();
  assert.equal(sq('#assessment-restore-roster').disabled,false);
  await context.restoreAssessmentRoster();
  assert.equal(sq('#assessment-names').value,original);
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body).names,[original]);
  assert.equal(calls.filter(([url])=>url.includes('roster-file')).length,1);
  response = {...response,requested:['虚拟专家丙']};
  await upload('second.xlsx');
  sq('#assessment-names').value='手工修改';
  failure=true;
  await upload('invalid.xlsx');
  assert.match(sq('#assessment-result').textContent,/未读取成功/);
  assert.match(sq('#assessment-restore-roster').title,/second.xlsx/);
  failure=false;
  await context.restoreAssessmentRoster();
  assert.equal(sq('#assessment-names').value,'虚拟专家丙');
  context.state.analysis.assessment.confirmed=true;
  sq('#assessment-names').value='不得覆盖';
  context.syncAssessmentActions();
  await context.restoreAssessmentRoster();
  assert.equal(sq('#assessment-names').value,'不得覆盖');
  console.log('名单还原、重新比对、失败保留及确认后锁定验证通过');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
