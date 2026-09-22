const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes={},timers=[],requests=[];
const element=()=>({textContent:'',value:'',dataset:{},style:{},handlers:{},disabled:false,
  addEventListener(name,fn){this.handlers[name]=fn;},append(){},showModal(){this.open=true;},close(){this.open=false;}});
const node=s=>nodes[s]||=(element());
const receipt={version:'0.1',file:'virtual.json',confirmed_examples:0,sha256:'virtual-hash',loaded:true,loaded_at:'2026-09-22T00:00:00Z'};
const analysis={analysis_id:'a',experts:[{overall:{opinions:8,pending:8,suspected:0}}]};
let job={id:'j',analysis_id:'a',status:'running',completed:0,total:8,failed:0,suspected:0,remaining:8,message:'',policy:receipt,analysis};
const root={document:{querySelector:node,getElementById:id=>node('#'+id),createElement:element},
  state:{analysis},elements:{dimensionOneTableWrap:{scrollLeft:0},evidenceDrawer:{}},
  syncServiceActions(){node('#identify-solutions').disabled=node('#identify-solutions').dataset.busy==='true';},
  renderDimensionOneTable(){root.window.reviewAI.refresh();},
  window:{setInterval(){},setTimeout:fn=>timers.push(fn)},
  fetch:async(url,options)=>{
    requests.push({url,body:JSON.parse(options.body)});
    let data=url.endsWith('/settings')?{session:'virtual',expires_in:3600}:
      url.endsWith('/test')?{model:'virtual',policy:receipt}:
      url.endsWith('/policy')?receipt:job;
    if(url.endsWith('/cancel'))data={...job,status:'stopping'};
    return {ok:true,json:async()=>data};
  }};
vm.createContext(root);vm.runInContext(fs.readFileSync('src/web/experiment.js','utf8'),root);
const click=selector=>node(selector).handlers.click({currentTarget:node(selector)});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
  root.window.reviewAI.refresh();assert.equal(node('#identify-solutions').textContent,'对策有效性识别');
  await root.window.reviewAI.start();assert.equal(node('#experiment-dialog').open,true);
  await click('#close-experiment');
  node('#experiment-key').value='virtual-model-key';await click('#save-experiment');
  await root.window.reviewAI.start();assert.equal(node('#ai-consent-dialog').open,true);
  await click('#configure-identification');assert.equal(node('#ai-consent-dialog').open,false);assert.equal(node('#experiment-dialog').open,true);
  await click('#close-experiment');await root.window.reviewAI.start();await click('#start-ai-analysis');await tick();
  assert.match(node('#identify-solutions').textContent,/0／8条 · 点击停止/);
  await root.window.reviewAI.start();assert.equal(node('#identify-solutions').textContent,'正在停止…');
  assert.equal(node('#identify-solutions').disabled,true);
  const before=requests.length;await root.window.reviewAI.start();assert.equal(requests.length,before);
  job={...job,status:'cancelled',completed:1,remaining:7};await timers.shift()();
  assert.match(node('#identify-solutions').textContent,/已停止1／8条 · 点击继续/);
  await root.window.reviewAI.start();assert.match(node('#ai-consent-summary').textContent,/继续识别7条/);
  job={...job,status:'running'};await click('#start-ai-analysis');await tick();
  assert.equal(requests.filter(r=>r.url.endsWith('/jobs')).at(-1).body.mode,'resume');
  job={...job,status:'completed',completed:8,remaining:0};analysis.experts[0].overall.pending=0;
  await timers.shift()();await root.window.reviewAI.start();
  assert.match(node('#ai-consent-summary').textContent,/重新识别全部8条/);
  job={...job,status:'partial',completed:7,failed:1};await click('#start-ai-analysis');await tick();
  assert.equal(requests.filter(r=>r.url.endsWith('/jobs')).at(-1).body.mode,'all');
  assert.match(node('#identify-solutions').textContent,/失败1条 · 点击继续/);
  await root.window.reviewAI.start();assert.match(node('#ai-consent-summary').textContent,/继续识别1条/);
  node('#experiment-key').value='virtual-new-key';await click('#save-experiment');
  await root.window.reviewAI.start();assert.match(node('#ai-consent-summary').textContent,/重新识别全部8条/);
  console.log('识别按钮：运行、停止防重、继续、全量重识别、失败重试及更换会话通过');
})().catch(error=>{console.error(error);process.exitCode=1;});
