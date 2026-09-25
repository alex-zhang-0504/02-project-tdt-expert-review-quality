const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = {};
const root = {console, structuredClone, document:{querySelector:s=>nodes[s] ||= {dataset:{},textContent:'',innerHTML:'',value:'',open:false,removeAttribute(){}}},
  state:{analysis:{experts:[{expert_name:'虚拟专家甲',sessions:[{project_code:'P1',project_name:'虚拟项目'}],overall:{}}],assessment:{exclusions:{}},manager_reviews:{}}},
  escapeHtml:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
  reviewerMatchesSearch:()=>true,normalizedReviewerSearch:s=>s};
vm.createContext(root);
for (const file of ['subjective.js','assessment.js']) vm.runInContext(fs.readFileSync('src/web/'+file,'utf8'),root);
vm.runInContext(`assessmentUI.managerId='a'; assessmentUI.tasks=[{manager_id:'a',name:'虚拟经理甲',experts:{'虚拟专家甲':['P1']}},{manager_id:'b',name:'虚拟经理乙',experts:{'虚拟专家甲':['P1']}}];
  subjective.expert='虚拟专家甲'; subjective.catalog=Array.from({length:6},(_,i)=>({id:'d'+i,title:'维度'+i,options:[{id:'high',title:'高档',description:'解释<示例>'},{id:'low',title:'低档',description:'低档解释'}]}));`,root);
root.renderSubjectiveEditor();
assert.ok(nodes['#subjective-editor'].innerHTML.includes('解释&lt;示例>'));
assert.ok(!nodes['#subjective-editor'].innerHTML.includes('id="subjective-evaluator"'));
assert.equal(nodes['#subjective-completion-bar'].value,0);
root.subjectiveDraft().ratings.d0={option:'high',note:'',project_code:''};
root.subjectiveDraft().dirty=true;
root.renderSubjectiveEditor();
assert.equal(nodes['#subjective-completion-bar'].value,1);
vm.runInContext("assessmentUI.managerId='b'",root);
root.renderSubjectiveEditor();
assert.equal(nodes['#subjective-completion-bar'].value,0);
vm.runInContext("assessmentUI.managerId='a'",root);
root.renderSubjectiveEditor();
assert.equal(nodes['#subjective-completion-bar'].value,1);
root.state.analysis.assessment.exclusions['["a", "虚拟专家甲"]']='无需评价';
root.renderSubjectiveEditor();root.renderSubjectiveRail();
assert.ok(nodes['#subjective-editor'].innerHTML.includes('此任务已有排除记录'));
assert.ok(nodes['#subjective-experts'].innerHTML.includes('已排除'));
vm.runInContext("assessmentUI.managerId='b'",root);
root.renderSubjectiveEditor();
assert.ok(!nodes['#subjective-editor'].innerHTML.includes('此任务已有排除记录'));
assert.ok(!nodes['#subjective-editor'].innerHTML.includes('恢复待评价'));
console.log('主观界面：经理草稿隔离、填答进度、任务状态及解释转义通过');
vm.runInContext("subjective.catalog[0].response_options=[{id:'unable',title:'暂无法判断'},{id:'no_opportunity',title:'本期无相关职责／机会'}]",root);
root.renderSubjectiveEditor();
assert.ok(nodes['#subjective-editor'].innerHTML.includes('id="d0-unable"'));
assert.ok(!nodes['#subjective-editor'].innerHTML.includes('id="d0-no_opportunity"'));
assert.ok(!nodes['#subjective-editor'].innerHTML.includes('subjective-cycle-guide'));
let guideShows=0;
nodes['#subjective-guide']={showModal(){guideShows++;}};
root.sessionStorage={getItem:()=>null};
root.showSubjectiveGuide();
assert.equal(guideShows,1);
root.sessionStorage.getItem=()=> '1';
root.showSubjectiveGuide();
assert.equal(guideShows,1,'已知后同会话不重复弹窗');

(async () => {
  const requests = [], alerts = [], pages = [];
  root.document.querySelectorAll = () => [];
  root.window = {alert: message => alerts.push(message)};
  root.showPanel = () => {};
  root.activateStep = () => {};
  root.checkServiceHealth = async () => true;
  root.renderDimensionScores = async kind => pages.push(kind);
  root.requestJson = async (url, options) => {
    const body = JSON.parse(options.body);
    requests.push(body);
    return {ratings: body.ratings, status: Object.keys(body.ratings).length === 6 ? '已完成' : '待评价'};
  };
  nodes['.subjective-heading'] = {scrollIntoView() {}};
  nodes['#subjective-panel'] = {scrollIntoView() {}};
  root.state.analysis.analysis_id = 'test-analysis';
  root.state.analysis.assessment.exclusions = {};
  vm.runInContext("subjective.analysisId='test-analysis'; subjective.drafts.clear(); assessmentUI.managerId='a'", root);
  root.subjectiveDraft();
  vm.runInContext("assessmentUI.managerId='b'", root);
  root.subjectiveDraft();
  assert.equal(await root.flushSubjectiveChanges(), true);
  assert.equal(requests.length, 0, '仅浏览多位经理不得提交空问卷');

  // A hidden modified questionnaire is submitted by its own manager/person key.
  vm.runInContext("assessmentUI.managerId='a'", root);
  root.subjectiveDraft().ratings.d0 = {option:'high', note:'', project_code:''};
  root.subjectiveDraft().dirty = true;
  vm.runInContext("assessmentUI.managerId='b'", root);
  assert.equal(await root.flushSubjectiveChanges(), true);
  assert.equal(requests[0].manager_id, 'a');
  assert.equal(requests[0].expert_name, '虚拟专家甲');
  assert.equal(root.state.analysis.manager_reviews.a['虚拟专家甲'].status, '待评价');
  await root.showDimensionPage('subjective', 2);
  assert.deepEqual(pages, ['subjective']);
  assert.equal(alerts.length, 0, '浏览的空问卷不应阻断评分页');

  root.state.analysis.experts.push({expert_name:'虚拟专家乙', sessions:[], overall:{}}, {expert_name:'虚拟专家丙', sessions:[], overall:{}});
  vm.runInContext("assessmentUI.managerId='a'; assessmentUI.tasks[0].experts['虚拟专家乙']=[]; assessmentUI.tasks[0].experts['虚拟专家丙']=[]", root);
  root.state.analysis.assessment.exclusions['["a", "虚拟专家乙"]'] = '无需评价';
  await root.showDimensionPage('subjective', 1);
  assert.equal(nodes['#subjective-page-toggle'].textContent, '查看主观打分 →');
  assert.equal(nodes['#subjective-page-toggle'].dataset.dimensionPage, 'subjective:2');
  await root.showDimensionPage('subjective', 2);
  assert.equal(nodes['#subjective-page-toggle'].textContent, '← 返回主观问卷');
  assert.equal(nodes['#subjective-page-toggle'].dataset.dimensionPage, 'subjective:1');
  assert.equal(requests.length, 1, '未修改问卷不重复提交');

  root.subjectiveDraft().ratings.d0 = {option:'low', note:'', project_code:''};
  root.subjectiveDraft().dirty = true;
  const healthyRequest = root.requestJson;
  root.requestJson = async () => { throw new Error('模拟网络失败'); };
  assert.equal(await root.flushSubjectiveChanges(), false);
  assert.equal(root.subjectiveDraft().dirty, true);
  assert.ok(alerts[0].includes('虚拟经理甲／虚拟专家甲'));
  assert.equal(nodes['#subjective-page-one'].hidden, false);
  assert.equal(nodes['#assessment-manager'].disabled, false);
  root.requestJson = healthyRequest;
  assert.equal(await root.flushSubjectiveChanges(), true);
  assert.equal(root.subjectiveDraft().dirty, false);

  // Guard before the first await: two fast clicks must not send two requests.
  root.subjectiveDraft().dirty = true;
  let release;
  root.checkServiceHealth = () => new Promise(resolve => { release = resolve; });
  const first = root.flushSubjectiveChanges();
  assert.equal(await root.flushSubjectiveChanges(), false);
  release(true);
  assert.equal(await first, true);
  assert.equal(requests.length, 3);
  assert.ok(!nodes['#subjective-editor'].innerHTML.includes('>下一步</button>'));
  assert.ok(!nodes['#subjective-editor'].innerHTML.includes('客观事实参考'));
  assert.equal(nodes['#subjective-page-toggle'].textContent, '查看主观打分 →');
  console.log('问卷推进：仅浏览、隐藏修改、归属、单按钮往返、失败保留及重试、重复点击通过');
})().catch(error => { console.error(error); process.exitCode = 1; });
