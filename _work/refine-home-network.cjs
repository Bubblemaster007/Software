const fs=require('fs');let p=fs.readFileSync('frontend/src/ProjectOverview.vue','utf8');
const start=p.indexOf('<template>'),end=p.indexOf('</template>',start)+11;
p=p.slice(0,start)+`<template><article class="project-meta"><h3>{{project?.name||'工程首页'}}</h3><p>{{project?.region||'地区未填写'}} · 工程 v{{project?.revision??'—'}} · 最后保存 {{project?.updated||'未记录'}}</p><p>源荷 {{inspection.count}} 小时 · {{model==='case33'?(networkName||'IEEE33网络'):'汇总平衡'}} · {{stages?stages+'个运行阶段':'全时域统一参数'}}</p></article><article id="project-workflow"><h3>工程进度与下一步工作</h3><div class="workflow"><button v-for="(step,index) in steps" :key="step.menu" @click="emit('navigate',step.menu)"><span class="step-number">{{String(index+1).padStart(2,'0')}}</span><div><b>{{step.title}}</b><p :class="progress?.[step.title]?.tone">{{progress?.[step.title]?.label||'状态未知'}}</p><p>{{progress?.[step.title]?.detail||step.description}}</p><span class="entry">进入工作区 →</span></div></button></div></article><article><h3>最近计算成果</h3><p v-if="!history.length">本工程尚无平衡计算成果。配置并计算后自动归档；不以示例数值填充。</p><div class="scroll" v-else><table><tr><th>计算档案</th><th>创建时间</th><th>输入版本</th><th>操作</th></tr><tr v-for="h in history.slice(0,5)" :key="h.id"><td>{{h.id.slice(0,8)}}</td><td>{{h.created}}</td><td>{{h.project_revision??'未记录'}}</td><td><button @click="emit('open',h.id)">查看结果</button></td></tr></table></div></article><p class="overview-note">阶段状态按当前工程引用与冻结快照判断；任务执行完成不等于方案可行或算法验收通过。</p></template>`+p.slice(end);
fs.writeFileSync('frontend/src/ProjectOverview.vue',p);
let n=fs.readFileSync('frontend/src/NetworkView.vue','utf8').replace("import {computed} from 'vue';","import {computed,ref,watch} from 'vue';");
n=n.replace('const viewBox=computed(', 'const naturalBox=computed(');
n=n.replace('function failed(id:number)',`const host=ref<HTMLElement>();const zoom=ref(1),pan=ref({x:0,y:0});let drag:{x:number;y:number;pan:{x:number;y:number}}|null=null;
const viewBox=computed(()=>{const [, ,w,h]=naturalBox.value.split(' ').map(Number);return pan.value.x+' '+pan.value.y+' '+w/zoom.value+' '+h/zoom.value});
function fit(){zoom.value=1;pan.value={x:0,y:0}}
function scale(factor:number){zoom.value=Math.max(.5,Math.min(6,zoom.value*factor))}
function pointerDown(e:PointerEvent){if((e.target as Element).closest('g'))return;drag={x:e.clientX,y:e.clientY,pan:{...pan.value}};(e.target as Element).setPointerCapture(e.pointerId)}
function pointerMove(e:PointerEvent){if(!drag)return;const svg=e.currentTarget as SVGSVGElement,box=svg.getBoundingClientRect();const [, ,w,h]=viewBox.value.split(' ').map(Number);pan.value={x:drag.pan.x-(e.clientX-drag.x)*w/box.width,y:drag.pan.y-(e.clientY-drag.y)*h/box.height}}
async function fullscreen(){if(!host.value)return;if(document.fullscreenElement===host.value)await document.exitFullscreen();else await host.value.requestFullscreen()}
watch(()=>props.network,fit);
function failed(id:number)`);
n=n.replace('<div class="topology"><svg', '<div ref="host" class="topology"><div class="topology-tools"><button @click="scale(1.25)" title="放大拓扑">＋</button><button @click="scale(.8)" title="缩小拓扑">−</button><button @click="fit">适应窗口</button><button @click="fullscreen">全屏</button><small>拖动空白区域平移 · 滚轮缩放</small></div><svg @wheel.prevent="scale($event.deltaY<0?1.1:.9)" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="drag=null" @pointercancel="drag=null"');
n=n.replace('preserveAspectRatio="xMinYMin meet"','preserveAspectRatio="xMidYMid meet"');
n=n.replace('.topology{overflow:auto;background:#f8fbfb}.topology svg{min-width:1000px;width:100%;max-height:480px}', '.topology{overflow:hidden;background:#fff}.topology svg{display:block;width:100%;height:420px;touch-action:none;cursor:grab}.topology-tools{display:flex;align-items:center;gap:6px;padding:6px;border-bottom:1px solid #dce3ea}.topology:fullscreen svg{height:calc(100vh - 50px)}.topology-tools small{font-size:10px}');
fs.writeFileSync('frontend/src/NetworkView.vue',n);
let e=fs.readFileSync('frontend/src/NetworkEditor.vue','utf8');
e=e.replace("function empty(){draft.value={name:'阿拉山口电网（待录入）',source:'依据SourceData图纸人工录入；待核实线路参数'", "function empty(){draft.value={name:'新建电网（待录入）',source:'人工录入；需核实线路参数'");
e=e.replace('新建阿拉山口网络草稿','新建网络草稿');
e=e.replace('@select-node="id=>selectedObject={type:\'节点\',id}"','@select-node="id=>{selectedObject={type:\'节点\',id};inspectorOpen=true}"').replace('@select-line="id=>selectedObject={type:\'线路\',id}"','@select-line="id=>{selectedObject={type:\'线路\',id};inspectorOpen=true}"');
// Browse-only attributes until the explicit editor is opened.
const inspectorStart=e.indexOf('<div v-if="selectedData&&inspectorOpen');const inspectorEnd=e.indexOf('<p v-if="!draft',inspectorStart);
let inspector=e.slice(inspectorStart,inspectorEnd).replace(/:disabled="disabled"/g,':disabled="true"').replace('修改为网络草稿，校验应用后生效；关闭面板保留草稿。','浏览模式只读；进入编辑模式后修改并校验应用。').replace('<button class="primary" @click="apply" :disabled="true">校验并应用网络</button>', '<button @click="propertiesOpen=true;editorTab=selectedObject?.type===\'节点\'?\'节点编辑\':\'线路编辑\'">编辑此对象</button>');
e=e.slice(0,inspectorStart)+inspector+e.slice(inspectorEnd);
e=e.replace('function openEditor(){propertiesOpen.value=true}',"function openEditor(){draft.value=network.value?JSON.parse(JSON.stringify(network.value)):null;propertiesOpen.value=true}");
fs.writeFileSync('frontend/src/NetworkEditor.vue',e);
let study=fs.readFileSync('frontend/src/StudyTasks.vue','utf8');
study=study.replace("{{((j.progress?.fraction||0)*100).toFixed(1)}}% · {{j.progress?.phase}}", "{{typeof j.progress?.fraction==='number'&&Number.isFinite(j.progress.fraction)?(j.progress.fraction*100).toFixed(1)+'%':'进度未量化'}} · {{j.progress?.phase||j.status}}");
fs.writeFileSync('frontend/src/StudyTasks.vue',study);
