const fs=require('fs'),ts=require('../frontend/node_modules/typescript');
const root='frontend/src/';const original=fs.readFileSync('_work/App-before-workspace-20261122.vue','utf8');
const script=original.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1];
const ast=ts.createSourceFile('App.ts',script,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);
const imports=ast.statements.filter(ts.isImportDeclaration).map(n=>n.getText(ast)).join('\n');
let logic=ast.statements.filter(n=>!ts.isImportDeclaration(n)).map(n=>n.getText(ast)).join('\n');
logic=logic.replace(/const contextTools=computed\([\s\S]*?const inputIssue=/,'const inputIssue=');
logic=logic.replace(/watch\(active,\(\)=>\{subsection.value=children\[active.value\]\?\.\[0\]\|\|''\},\{flush:'sync'\}\);/,'');
logic=logic.replace(/async function draw\(\)\{[\s\S]*?\nlet archiveRead=0;/,'async function draw(){}\nlet archiveRead=0;');
logic=logic.replace("window.addEventListener('resize',()=>plot?.resize())",'');
logic=logic.replace("const sidebarCompact=ref(false);",'const layout=useLayoutPreferences();const sidebarCompact=layout.compact;');
logic=logic.replace("const workspacePanel=ref('');const presentation=ref(false);","const workspacePanel=ref('');const presentation=layout.presentation;");
// Layout must be initialized before any aliases reference it.
logic=logic.replace('const layout=useLayoutPreferences();const sidebarCompact=layout.compact;','const sidebarCompact=layout.compact;');
logic='const layout=useLayoutPreferences();\n'+logic;
logic=logic.replace("const currentNavigation=computed(()=>workflowNavigation", "const currentNavigation=computed(()=>workflowNavigation");
logic=logic.replace(/async function navigateSection\(menu:string,section:string\)\{[\s\S]*?\n\}/,`async function navigateSection(menu:string,section:string){
 const target=resolveWorkspace(menu,section);workspaceId.value=target.id;
 if(menu==='系统与接口'&&section==='计算任务'){layout.bottom.value='计算任务';return}
 if(menu==='数据管理'&&section==='数据版本管理'){validateInput();return}
 active.value=target.menu;subsection.value=section||target.defaultView;
 if(menu==='电力电量平衡'&&['逐设备时序调度','随机生产模拟','逐设备年度滚动','原生年度流水线'].includes(section))balanceMode.value=section;
 if(menu==='电力电量平衡'&&['模型与资源','运行阶段'].includes(section)){workspacePanel.value='参数';parameterTab.value=section==='运行阶段'?'运行阶段':'计算模型'}
 await nextTick();
}`);
logic=logic.replace("result.value=null;projects.value=await api('/api/projects');", "result.value=null;layout.bottom.value='';layout.right.value='';workspacePanel.value='';dataParametersOpen.value=false;balanceMode.value='汇总／网络平衡';projects.value=await api('/api/projects');");
logic=logic.replace("active.value='电力电量平衡';projectMessage.value='故障场景", "navigateWorkspace('balance.workspace');projectMessage.value='故障场景");
// Closed modal remains mounted, but changing project must drop all object-local state.
const added=`
const workspaceId=ref('project.home');
watch([active,subsection],()=>{workspaceId.value=resolveWorkspace(active.value,subsection.value).id});
function navigateWorkspace(id:string){const w=workspaces.find(v=>v.id===id);if(w)navigateSection(w.menu,w.defaultView)}
const validation=ref<string[]>([]);
function validateInput(){const check=inspectTimeSeries(csv.value);validation.value=[check.totalIssues?'源荷格式：'+check.totalIssues+'项问题':'源荷格式检查通过（'+check.count+'小时）',...check.issues.map(i=>(i.row?'第'+i.row+'行：':'')+i.message),inputIssue.value||'本地时序与阶段限制检查通过；服务端继续核验资源、场景和模型约束'];layout.bottom.value='校验信息'}
const modeId=computed({get:()=>balanceMode.value==='汇总／网络平衡'?model.value:balanceMode.value,set:(v:string)=>{if(['aggregate','case33'].includes(v)){balanceMode.value='汇总／网络平衡';model.value=v}else balanceMode.value=v}});
const selectedModeResult=computed(()=>balanceMode.value==='汇总／网络平衡'?result.value:null);
const parametersDraft=ref<any>(null);
watch(balanceParametersOpen,open=>{if(open)parametersDraft.value=JSON.parse(JSON.stringify({model:model.value,parameters:params.value,networkParameters:networkParameters.value,stages:stages.value,failedLines:failedLines.value,branchLimit:branchLimit.value}));else parametersDraft.value=null});
function applyBalanceParameters(){const d=parametersDraft.value;if(!d)return;
 if(Object.values(d.parameters).some(v=>typeof v!=='number'||!Number.isFinite(v))){error.value='参数须为有限数值';return}
 model.value=d.model;params.value={...d.parameters};networkParameters.value={...d.networkParameters};stages.value=JSON.parse(JSON.stringify(d.stages));failedLines.value=d.failedLines;branchLimit.value=d.branchLimit;workspacePanel.value='';projectMessage.value='参数已应用至工作区，尚未保存或提交计算';
}
const draftFaultSelection=computed<number[]>({get:()=>parametersDraft.value?.failedLines?.split(/[,，]/).filter(Boolean).map(Number)||[],set:v=>{if(parametersDraft.value)parametersDraft.value.failedLines=v.join(',')}});
const inputChanged=computed(()=>!!result.value&&(csv.value!==result.value.input_csv||!sameParameters(params.value,result.value.parameters)||model.value!==(result.value.model||'aggregate')||scenarioId.value!==(result.value.scenario_id||null)||activeProductionId.value!==(result.value.production_sequence_id||null)||JSON.stringify(stages.value)!==stageSnapshot.value||failedLines.value!==(result.value.failed_lines||[]).join(',')||branchLimit.value!==(result.value.branch_limit_kw||5000)||model.value==='case33'&&(!sameParameters(networkParameters.value,{...networkDefaults,...result.value.network_parameters})||JSON.stringify(customNetwork.value)!==JSON.stringify(result.value.network||null))));
const helpOpen=ref(false),projectSettingsOpen=ref(false);
const commandRegistry=useCommands([
 {id:'project.create',label:'新建工程',execute:createProject,enabled:()=>!busy.value},
 {id:'project.open',label:'打开 / 切换工程',execute:()=>document.querySelector<HTMLSelectElement>('[aria-label="切换工程"]')?.focus()},
 {id:'project.save',label:'保存工程',shortcut:'Ctrl+S',execute:saveProject,enabled:()=>!!project.value&&!busy.value},
 {id:'project.backup',label:'备份已保存数据',execute:()=>{window.location.href='/api/backup'}},
 {id:'project.settings',label:'工程设置',execute:()=>projectSettingsOpen.value=true},
 {id:'edit.current',label:'编辑当前数据',execute:()=>dataWorkspace.value?.openEditor(),enabled:()=>active.value==='数据管理'&&!!dataWorkspace.value,reason:()=> '当前工作区没有可用的源荷或网络编辑器'},
 {id:'layout.sidebar',label:'展开 / 收起导航',execute:()=>{layout.compact.value=!layout.compact.value}},
 {id:'layout.right',label:'属性 / 结果快照',execute:()=>{layout.right.value=layout.right.value?'':'属性与输入快照'}},
 {id:'layout.tasks',label:'计算任务面板',execute:()=>{layout.bottom.value=layout.bottom.value==='计算任务'?'':'计算任务'}},
 {id:'layout.details',label:'数据明细面板',execute:()=>{layout.bottom.value=layout.bottom.value==='数据明细'?'':'数据明细'}},
 {id:'layout.presentation',label:'切换图形展示',execute:()=>{presentation.value=!presentation.value}},
 {id:'layout.reset',label:'恢复默认布局',execute:layout.reset},
 {id:'help.guide',label:'使用说明与功能边界',execute:()=>helpOpen.value=true},
 {id:'help.version',label:'版本信息',execute:()=>helpOpen.value=true},
 {id:'context.import',label:'导入数据',execute:()=>dataWorkspace.value?.openDatasetPicker(),visible:()=>workspaceId.value==='data.source'&&subsection.value==='源荷时序'},
 {id:'context.network',label:'编辑网络模型',execute:()=>dataWorkspace.value?.openEditor(),visible:()=>workspaceId.value==='data.network'&&subsection.value==='电网拓扑'},
 {id:'context.edit',label:'编辑数据',execute:()=>dataWorkspace.value?.openEditor(),visible:()=>workspaceId.value==='data.source'&&subsection.value==='源荷时序'},
 {id:'context.validate',label:'校验输入',execute:validateInput,visible:()=>workspaceId.value.startsWith('data.')||workspaceId.value==='balance.workspace'},
 {id:'context.parameters',label:'参数设置',execute:()=>{if(active.value==='电力电量平衡')workspacePanel.value='参数';else if(active.value==='承灾极限分析')disasterWorkspace.value?.openSettings();else if(active.value==='黑启动路径优化')restorationWorkspace.value?.openSettings();else dataParametersOpen.value=true},visible:()=>balanceMode.value==='汇总／网络平衡'&&workspaceId.value==='balance.workspace'||['research.disaster','research.blackstart'].includes(workspaceId.value)},
 {id:'context.run',label:'提交计算',primary:true,execute:async()=>{layout.bottom.value='计算任务';await run()},visible:()=>workspaceId.value==='balance.workspace'&&balanceMode.value==='汇总／网络平衡',enabled:()=>!!project.value&&!busy.value&&!inputIssue.value,reason:()=>inputIssue.value||'计算或保存处理中'},
 {id:'context.export',label:'导出结果 CSV',execute:()=>{window.location.href='/api/runs/'+result.value.id+'/csv'},visible:()=>workspaceId.value==='balance.workspace'&&balanceMode.value==='汇总／网络平衡',enabled:()=>!!result.value,reason:()=> '请先选择真实计算档案'}
],message=>error.value=message);
const globalMenus=[{label:'工程',ids:['project.create','project.open','project.save','project.backup','project.settings']},{label:'编辑',ids:['edit.current']},{label:'视图',ids:['layout.sidebar','layout.right','layout.tasks','layout.details','layout.presentation','layout.reset']},{label:'帮助',ids:['help.guide','help.version']}];
function shortcut(e:KeyboardEvent){if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();commandRegistry.execute('project.save')}}
onMounted(()=>document.addEventListener('keydown',shortcut));onBeforeUnmount(()=>document.removeEventListener('keydown',shortcut));
`;
logic+=added;
const bodyAST=ts.createSourceFile('controller.ts',logic,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);const names=[];
for(const n of bodyAST.statements){if(ts.isVariableStatement(n))for(const d of n.declarationList.declarations){if(ts.isIdentifier(d.name))names.push(d.name.text)}else if(ts.isFunctionDeclaration(n)&&n.name)names.push(n.name.text)}
fs.writeFileSync(root+'useEngineeringProject.ts',imports+"\nimport {inject,onBeforeUnmount,provide} from 'vue';\nimport {workspaces,resolveWorkspace} from './workspaceRegistry';\nimport {useLayoutPreferences} from './useLayoutPreferences';\nimport {useCommands} from './commands';\nexport function useEngineeringProject(){\n"+logic+'\nreturn {'+names.join(',')+'};\n}\nconst engineeringKey=Symbol("engineering-project");\nexport function provideEngineeringProject(value:ReturnType<typeof useEngineeringProject>){provide(engineeringKey,value)}\nexport function useEngineeringContext(){const value=inject<ReturnType<typeof useEngineeringProject>>(engineeringKey);if(!value)throw Error("工程上下文未提供");return value}\n');
let template=original.slice(original.indexOf('<template><div class="shell"'));
let business=template.slice(template.indexOf('<template v-if="active===\'工程工作台\''),template.indexOf('<ParameterDialog v-model:open="dataParametersOpen"'));
const balanceStart=business.indexOf('<template v-else-if="active===\'电力电量平衡\'">');const balanceEnd=business.indexOf('<StrategyWorkspace',balanceStart);
const balanceOriginal=business.slice(balanceStart,balanceEnd);let params=balanceOriginal.slice(balanceOriginal.indexOf('<ParameterDialog'),balanceOriginal.indexOf('</ParameterDialog>')+18);
params=params.replace(/:tabs="\['计算模型','资源参数','网络与故障','运行阶段'\]"/,':tabs="parametersDraft?.model===\'case33\'?[\'计算模型\',\'资源参数\',\'网络与故障\',\'运行阶段\']:[\'计算模型\',\'资源参数\',\'运行阶段\']"');
params=params.replace('<article v-show="parameterTab===\'计算模型\'">','<article v-if="parametersDraft" v-show="parameterTab===\'计算模型\'">');
params=params.replace(/\bparams\b/g,'parametersDraft.parameters').replace(/\bnetworkParameters\b/g,'parametersDraft.networkParameters').replace(/\bbranchLimit\b/g,'parametersDraft.branchLimit').replace(/\bstages\b/g,'parametersDraft.stages').replace(/\bfaultSelection\b/g,'draftFaultSelection').replace(/\bmodel\b(?!=|:|\s*:\s*)/g,'model');
params=params.replace(/v-model="model"/g,'v-model="parametersDraft.model"').replace(/model==='case33'/g,"parametersDraft.model==='case33'").replace(/model!=='case33'/g,"parametersDraft.model!=='case33'");
params=params.replace(/<template #footer>[\s\S]*?<\/template>/,'<template #footer><button @click="workspacePanel=\'\'">取消</button><button class="primary" @click="applyBalanceParameters" :disabled="busy">应用参数</button></template>');
params=params.replace('title="平衡分析参数"','title="平衡分析参数" note="取消放弃本次修改；应用只更新工作区，不保存工程或提交计算。"');
// Guard the whole dialog contents against null drafts after close.
params=params.replace('<article v-if="parametersDraft"','<template v-if="parametersDraft"><article').replace('<template #footer>','</template><template #footer>');
const ctxNames=names.join(',');
const balanceTemplate=`<div class="balance-workspace"><p v-if="scenarioId||activeProductionId" class="input-reference">当前输入：{{activeProductionId?'生产序列 '+activeProductionId.slice(0,8):'工程源荷'}} · {{scenarioId?'故障场景 '+scenarioId.slice(0,8):'未关联故障场景'}}</p><template v-if="balanceMode==='汇总／网络平衡'"><p v-if="inputChanged" class="notice">输入已修改，当前展示历史输入的结果，需重新计算。</p><ResultOverview v-if="result" :result="result"/><div v-else class="balance-input-preview"><p class="notice">尚未选择计算档案。当前输入 {{inspectTimeSeries(csv).count}} 小时；请核对参数后提交计算，或选择已保存结果。</p><SeriesPreview :csv="csv"/></div></template><DeviceDispatch v-else-if="balanceMode==='逐设备时序调度'" :project-id="project?.id||''"/><RandomBalance v-else-if="balanceMode==='随机生产模拟'" :source="result" :project-id="project?.id||''"/><AnnualWorkspace v-else-if="balanceMode==='逐设备年度滚动'" :project-id="project?.id||''"/><NativePipeline v-else-if="balanceMode==='原生年度流水线'" :project-id="project?.id||''" :csv="csv" :parameters="params" :network-parameters="networkParameters" :branch-limit="branchLimit"/>${params}</div>`;
fs.writeFileSync(root+'BalanceWorkspace.vue',`<script setup lang="ts">\n${imports}\nimport {useEngineeringContext} from './useEngineeringProject';\nconst {${ctxNames}}=useEngineeringContext();\n</script>\n<template>${balanceTemplate}</template>\n<style scoped>.input-reference{font-size:12px;margin:0 0 8px}.balance-workspace{min-width:0}.balance-input-preview{min-height:360px}</style>`);
business=business.slice(0,balanceStart)+`<BalanceWorkspace v-else-if="active==='电力电量平衡'"/>\n`+business.slice(balanceEnd);
// Home gets project metadata only from one settings dialog; no default inline form.
business=business.replace(/<details><summary>工程信息详情<\/summary>[\s\S]*?<\/details>/,'');
business=business.replace('@navigate="active=$event"','@navigate="navigateSection($event,resolveWorkspace($event).defaultView)"');
business=business.replace('<StudyTasks v-else-if="active===\'系统与接口\'&&subsection===\'计算任务\'" :project-id="project?.id||\'\'"/>','');
business=business.replace('<DevelopmentPlan v-else-if=', '<DevelopmentPlan v-else-if=');
// Legacy subviews are fixed tabs inside their one business workspace.
const tabs=`<div v-if="['data.source','data.network','data.resources','scenario.workspace','results.workspace','system.integration'].includes(workspaceId)" class="module-tabs" aria-label="工作区视图"><button v-for="s in workspaces.find(w=>w.id===workspaceId)?.sections.filter(s=>!['典型场景库','分类目标与优先级','配置方案','示范区实证'].includes(s))" :class="{current:subsection===s}" @click="navigateSection(active,s)">{{stepLabels[s]||s}}</button><button v-if="workspaceId==='scenario.workspace'" @click="scenarioLibraryOpen=true">场景库与优先级…</button><button v-if="workspaceId==='results.workspace'&&subsection==='成果与交付'" @click="subsection='示范区实证'">示范区实证</button></div>`;
const dataDialog=template.slice(template.indexOf('<ParameterDialog v-model:open="dataParametersOpen"'),template.indexOf('<div class="right-tool-rail"'));
const extra=`<ParameterDialog v-model:open="helpOpen" title="使用说明与研发边界"><article><h3>工程分析工作流程</h3><p>数据准备 → 场景生成（常规可跳过故障）→ 平衡分析 → 保供优化 → 成果管理。编辑、应用、工程保存和任务提交是独立操作。关闭任务面板不会中断后台计算。</p><p>汇总平衡 2–8760 小时；节点网络平衡 2–168 小时。随机、逐设备、年度和原生模式保留独立输入限制与归档。</p><p>阿拉山口为历史重建数据集，来源与质量说明随输入保留。确定性轨迹的时段占比与累计电量不等同于灾害概率或期望。离网稳定动态方程、权重及验证资料待接入。</p><p>版本 0.1.0 · Vue 3 / 本地离线工程工作空间</p></article></ParameterDialog><ParameterDialog v-model:open="projectSettingsOpen" title="工程设置"><article v-if="project"><label class="field">工程名称<input v-model="project.name"></label><label class="field">地区<input v-model="project.region"></label><label class="field">类型<select v-model="project.kind"><option>县域级</option><option>乡镇级</option><option>村级</option><option>村镇级</option></select></label></article><template #footer><button @click="projectSettingsOpen=false">关闭</button><button class="primary" @click="commandRegistry.execute('project.save')" :disabled="busy">保存工程</button></template></ParameterDialog>`;
const app=`<script setup lang="ts">\n${imports}\nimport EngineeringLayout from './EngineeringLayout.vue';\nimport BalanceWorkspace from './BalanceWorkspace.vue';\nimport {workspaces,resolveWorkspace,stepLabels} from './workspaceRegistry';\nimport {useEngineeringProject,provideEngineeringProject} from './useEngineeringProject';\nconst context=useEngineeringProject();provideEngineeringProject(context);\nconst {${ctxNames}}=context;\nconst scenarioLibraryOpen=ref(false);const scenarioLibraryTab=ref('典型场景库');\n</script>\n<template><EngineeringLayout :project="project" :projects="projects" :workspace="workspaceId" :progress="engineeringProgress" :commands="commandRegistry.available()" :menus="globalMenus" :disabled="commandRegistry.disabled" :busy="busy" :status="projectMessage" v-model:compact="layout.compact.value" v-model:presentation="layout.presentation.value" v-model:bottom="layout.bottom.value" v-model:bottom-height="layout.bottomHeight.value" v-model:right="layout.right.value" v-model:right-width="layout.rightWidth.value" @navigate="navigateWorkspace" @command="commandRegistry.execute" @project="openProject">
<template #toolbar><template v-if="workspaceId==='balance.workspace'"><select aria-label="计算模式" v-model="modeId"><optgroup label="普通计算"><option value="aggregate">汇总逐时平衡</option><option value="case33">节点网络平衡</option></optgroup><optgroup label="高级计算"><option v-for="m in ['逐设备时序调度','随机生产模拟','逐设备年度滚动','原生年度流水线']">{{m}}</option></optgroup></select><select v-if="balanceMode==='汇总／网络平衡'" aria-label="当前平衡结果" :value="result?.id||''" @change="load(($event.target as HTMLSelectElement).value)"><option value="" disabled>选择已存结果</option><option v-for="h in history" :value="h.id">{{h.created}} · v{{h.project_revision??'—'}} · {{h.model==='case33'?'网络':'汇总'}}</option></select></template></template>
<p v-if="error" class="error" role="alert">{{error}}</p>${tabs}${business}<template v-if="active==='系统配置'"><article><h3>工作空间布局</h3><p>导航宽度及面板尺寸保存在本机偏好中，与工程数据分离。</p><button @click="layout.reset">恢复默认布局</button></article></template>
<template #right><article><h3>当前工程</h3><p>{{project?.name}} · v{{project?.revision}}</p><p>源荷 {{inspectTimeSeries(csv).count}} 小时 · 模型 {{model}}</p><p v-if="result">档案 {{result.id}} · 输入版本 {{result.project_revision??'未记录'}}</p><details v-if="result"><summary>任务参数快照（只读）</summary><pre>{{JSON.stringify(result.parameters,null,2)}}</pre></details><p v-else>尚未选择结果或对象。</p></article></template>
<template #bottom><template v-if="layout.bottom.value==='计算任务'"><p v-if="busy" role="status">正在处理当前工程请求；同步平衡接口未提供精确百分比。</p><p v-if="result">当前平衡档案 {{result.id}} · 工程版本 {{result.project_revision??'未记录'}} · 已归档</p><StudyTasks :project-id="project?.id||''"/></template><ul v-else-if="layout.bottom.value==='校验信息'"><li v-for="v in validation">{{v}}</li><li v-if="!validation.length">尚未执行当前输入校验。</li></ul><div v-else-if="layout.bottom.value==='分阶段指标'"><table v-if="result?.phase_metrics?.length"><tr><th>阶段</th><th>最大缺额 MW</th><th>累计缺供 MWh</th></tr><tr v-for="p in result.phase_metrics"><td>{{p.stage}}</td><td>{{p.maximum_electricity_shortage_mw}}</td><td>{{p.expected_energy_not_served_mwh}}</td></tr></table><p v-else>当前结果没有分阶段指标。</p></div><div v-else><table v-if="result?.rows?.length"><tr><th>时间</th><th>负荷 kW</th><th>供电 kW</th><th>缺供 kW</th><th>SOC</th></tr><tr v-for="r in result.rows.slice(0,168)"><td>{{r.timestamp}}</td><td>{{r.load_kw}}</td><td>{{r.load_served_kw}}</td><td>{{r.power_deficit_kw}}</td><td>{{r.soc}}</td></tr></table><p v-else>尚无已选结果；请先完成计算或打开历史档案。</p></div></template>
</EngineeringLayout>${dataDialog}${extra}<ParameterDialog v-model:open="scenarioLibraryOpen" title="场景库与保供优先级" :tabs="['典型场景库','分类目标与优先级']" v-model:active="scenarioLibraryTab"><EngineeringWorkspace :project-id="project?.id||''" :section="scenarioLibraryTab"/></ParameterDialog></template>`;
fs.writeFileSync(root+'App.vue',app);
