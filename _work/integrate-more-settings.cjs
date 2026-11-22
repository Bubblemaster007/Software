const fs=require('fs');const root='C:/Users/13411/Desktop/software/frontend/src/';
function edit(name,fn){let s=fs.readFileSync(root+name,'utf8');s=fn(s);fs.writeFileSync(root+name,s)}
function add(s){return s.replace('<script setup lang="ts">',`<script setup lang="ts">\nimport ParameterDialog from './ParameterDialog.vue';\nconst settingsOpen=ref(false);`)}
function wrap(s,start,end,title){const a=s.indexOf(start,s.indexOf('<template>')),b=s.indexOf(end,a);if(a<0||b<0)throw Error(title+' bounds');return s.slice(0,a)+`<button class="settings-trigger" @click="settingsOpen=true">${title}</button><ParameterDialog v-model:open="settingsOpen" title="${title}">`+s.slice(a,b)+'</ParameterDialog>'+s.slice(b)}
for(const [file,title,start,end] of [
 ['SourceStudy.vue','年度背景参数','<div class="scroll"><table>','<h3>已保存研究</h3>'],
 ['SequenceWorkspace.vue','序列嵌入参数','<textarea v-model="eventCsv"','<h3>已保存生产序列</h3>'],
 ['RandomBalance.vue','随机模拟参数','<div class="grid">','<h3>已保存随机平衡批次</h3>'],
 ['DeviceDispatch.vue','逐设备调度参数','<div class="fields">','</article>'],
 ['NativePipeline.vue','原生流水线参数与输入','<div class="actions">','</article>'],
 ['AnnualWorkspace.vue','年度滚动参数','<div class="fields">','</article>']
])edit(file,s=>wrap(add(s),start,end,title));
edit('StrategyWorkspace.vue',s=>{
 s=add(s);const a=s.indexOf('<div class="grid">',s.indexOf('<template>')),b=s.indexOf('<template v-if="comparison">',a);
 if(a<0||b<0)throw Error('strategy bounds');return s.slice(0,a)+'<button class="settings-trigger" @click="settingsOpen=true">资源调整参数</button><ParameterDialog v-model:open="settingsOpen" title="资源调整参数">'+s.slice(a,b)+'</ParameterDialog>'+s.slice(b);
});
// The original settings article and submission logic stay mounted inside one dialog.
for(const [file,title,condition] of [['DisasterWorkspace.vue','承灾扫描参数',"section==='分析设置'"],['RestorationWorkspace.vue','恢复规划参数',"section!=='恢复序列'"]])edit(file,s=>{
 s=add(s);const a=s.indexOf('<article>',s.indexOf('<template>')),b=s.indexOf('</article>',a);
 if(a<0||b<0)throw Error(title+' bounds');return s.slice(0,a)+`<article><h3>${title}</h3><p>参数集中编辑，任务和结果沿用冻结输入。编辑后在弹窗内明确提交。</p><button class="settings-trigger" v-if="${condition}" @click="settingsOpen=true">${title}</button></article><ParameterDialog v-model:open="settingsOpen" title="${title}">`+s.slice(a,b+10)+'</ParameterDialog>'+s.slice(b+10);
});
edit('ModuleWorkspace.vue',s=>{
 s=add(s);const start='<article><h3>{{tab}} / 参数草稿</h3>',a=s.indexOf(start),b=s.indexOf('</article>',a);if(a<0||b<0)throw Error('module bounds');return s.slice(0,a)+'<div><button class="settings-trigger" @click="settingsOpen=true">编辑参数草稿</button><ParameterDialog v-model:open="settingsOpen" :title="module+\'参数草稿\'">'+s.slice(a,b+10)+'</ParameterDialog></div>'+s.slice(b+10);
});
