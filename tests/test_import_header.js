const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('src/web/app.js', 'utf8');
const node = () => ({textContent: '', innerHTML: '', className: '', classList: {toggle() {}}, querySelectorAll() { return []; }});
const context = {state: {importActive: true}, elements: {checkTitle: node(), checkState: node(), issueSummary: node(), warningConfirm: node(), continueAnalysis: node()}, validationCounts: () => ({errors: 0, warnings: 0}), qualityGatePassed: () => false, activateStep() {}, escapeHtml: String};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function renderIssues('), source.indexOf('async function confirmReviewerNamesDistinct(')), context);
context.elements.checkTitle.textContent = '正在逐份检查3份评审报告';
context.elements.checkState.textContent = '1完成';
const error = {severity: 'error', code: 'test', message: '虚拟报告格式错误'};
for (const issues of [[], [error], []]) {
  context.renderIssues(issues, '虚拟报告');
  assert.equal(context.elements.checkTitle.textContent, '正在逐份检查3份评审报告');
  assert.equal(context.elements.checkState.textContent, '1完成');
}
context.renderIssues([error], '虚拟报告');
assert.match(context.elements.issueSummary.innerHTML, /虚拟报告格式错误/);
context.state.importActive = false;
context.renderIssues([error], '虚拟报告');
assert.equal(context.elements.checkTitle.textContent, '“虚拟报告”存在错误');
console.log('扫描标题与文件问题展示隔离验证通过');
