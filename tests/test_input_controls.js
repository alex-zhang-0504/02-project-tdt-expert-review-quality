const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element extends EventTarget {
  constructor(){super();this.attributes={};this.type='password';this.disabled=false;this.files=[];}
  setAttribute(key,value){this.attributes[key]=value;}
}
const windowTarget=new EventTarget(),documentTarget=new EventTarget(),nodes={};
const root={AbortController,window:windowTarget,document:documentTarget,sq:id=>nodes[id]};
vm.createContext(root);vm.runInContext(fs.readFileSync('src/web/workspace.js','utf8'),root);
const workspace=root.window.workspace,input=new Element(),button=new Element();
function dispatch(target,type,properties={}){const e=new Event(type,{cancelable:true});Object.assign(e,properties);target.dispatchEvent(e);return e;}
const dispose=workspace.bindPasswordReveal(button,input);
assert.equal(input.type,'password');
dispatch(button,'click');assert.equal(input.type,'password','单击不能切换为持续可见');
dispatch(button,'pointerdown',{button:2});assert.equal(input.type,'password');
for(const [target,event] of [[windowTarget,'pointerup'],[windowTarget,'pointercancel'],[button,'pointerleave'],[button,'blur'],[windowTarget,'blur'],[documentTarget,'visibilitychange']]){
 dispatch(button,'pointerdown',{button:0});assert.equal(input.type,'text','仅按住时显示');
 dispatch(target,event);assert.equal(input.type,'password',event+'必须隐藏密码');
 assert.equal(button.attributes['aria-pressed'],'false');
}
for(const key of [' ','Enter']){
 assert.equal(dispatch(button,'keydown',{key}).defaultPrevented,true);
 assert.equal(input.type,'text');dispatch(windowTarget,'keyup',{key});assert.equal(input.type,'password');
}
dispatch(button,'pointerdown',{button:0});dispose();assert.equal(input.type,'password');
dispatch(button,'pointerdown',{button:0});assert.equal(input.type,'password','关闭窗口须清理事件');
nodes['#file']=new Element();nodes['#choose']=new Element();let clicks=0;
nodes['#file'].click=()=>clicks++;
workspace.bindFilePicker('file','choose');nodes['#choose'].onclick();assert.equal(clicks,1);
nodes['#file'].files=[{name:'虚拟项目经理名单.json'}];dispatch(nodes['#file'],'change');
assert.equal(nodes['#choose'].textContent,'虚拟项目经理名单.json');
nodes['#file'].files=[];dispatch(nodes['#file'],'change');assert.equal(nodes['#choose'].textContent,'选择文件');
console.log('密码按住显示、释放及离开隐藏、事件清理、整条文件选择和文件名显示通过');
