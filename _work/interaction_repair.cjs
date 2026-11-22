const fs=require('fs');const root='C:/Users/13411/Desktop/software/';
function edit(file,fn){const p=root+file;fs.writeFileSync(p,fn(fs.readFileSync(p,'utf8')))}
edit('frontend/src/ResultOverview.vue',s=>s.replace(':series="supply" unit="MW"', 'unit="MW"'));
edit('frontend/src/DataWorkspace.vue',s=>s.replace('<NetworkEditor v-else-if=', '<NetworkEditor ref="networkEditor" v-else-if='));
edit('frontend/src/NetworkEditor.vue',s=>s.replace('v-if="selectedData&&!propertiesOpen"','v-if="selectedData&&inspectorOpen&&!propertiesOpen"').replace('@click="selectedObject=null"','@click="inspectorOpen=false"').replace('<NetworkView v-if="draft&&!propertiesOpen"','<div class="actions"><button :disabled="!selectedObject" @click="openProperties">对象属性</button><span v-if="message">{{message}}</span></div><NetworkView v-if="draft&&!propertiesOpen"'));
edit('frontend/src/App.vue',s=>{
 s=s.replace("const scenarioSettingsOpen=ref(false);", "const scenarioSettingsOpen=ref(0);\nconst selectedScenario=ref<any>(null);\nconst dataWorkspace=ref<InstanceType<typeof DataWorkspace>>();");
 s=s.replaceAll('scenarioSettingsOpen.value=false','scenarioSettingsOpen.value=0').replaceAll('scenarioSettingsOpen.value=true','scenarioSettingsOpen.value++');
 s=s.replace('<DataWorkspace v-else ', '<DataWorkspace ref="dataWorkspace" v-else ');
 s=s.replace(':open-settings="scenarioSettingsOpen" @apply="applyScenario"', ':open-settings="scenarioSettingsOpen" @selected="selectedScenario=$event" @apply="applyScenario"');
 s=s.replace('<ScenarioDashboard v-if="subsection===\'故障与恢复场景\'" :csv="csv" :condition="operatingCondition"/>','<ScenarioDashboard v-if="subsection===\'故障与恢复场景\'" :csv="csv" :event-csv="eventCsv" :scenario="selectedScenario" :condition="operatingCondition"/>');
 const a=s.indexOf(" if(tool==='数据编辑'||tool==='属性')");const b=s.indexOf(" if(tool==='校验'",a);
 if(a<0||b<0)throw Error('data tool anchor missing');
 s=s.slice(0,a)+` if(tool==='数据编辑'||tool==='属性') {if(tool==='属性')dataWorkspace.value?.openProperties();else dataWorkspace.value?.openEditor();return}\n`+s.slice(b);
 s=s.replace("if(tool==='导入数据') {navigateSection('数据管理','源荷时序');return}","if(tool==='导入数据') {navigateSection('数据管理','源荷时序').then(()=>dataWorkspace.value?.openEditor());return}");
 s=s.replace("if(tool==='导入拓扑') {navigateSection('数据管理','电网拓扑');return}","if(tool==='导入拓扑') {navigateSection('数据管理','电网拓扑').then(()=>dataWorkspace.value?.openEditor());return}");
 s=s.replace("if(tool==='保存'||tool==='保存场景'||tool==='保存方案')", "if(tool==='保存工程'||tool==='保存')");
 s=s.replace("? ['嵌入参数','生成场景','保存场景','应用场景'] : ['场景模板','工况选择','参数设置','生成当前视图','保存']", "? ['场景模板','故障场景','保存工程'] : ['场景模板','故障场景','保存工程']");
 s=s.replace("if(tool==='任务中心')", "if(tool==='故障场景'){navigateSection('保供场景生成','故障与恢复场景');return}\n if(tool==='任务中心')");
 s=s.replace("? ['计算模式','设置','提交计算','任务详情']", "? ['分析设置','任务中心']");
 s=s.replace("? ['结果类型','时间范围','指标','逐时明细','导出']", "? ['指标','逐时明细','计算档案']");
 s=s.replace("if(tool==='指标')", "if(tool==='计算档案'){navigateSection('方案与报告','计算档案');return}\n if(tool==='分析设置'&&active.value==='电力电量平衡'){navigateSection(active.value,'模型与资源');return}\n if(tool==='指标')");
 // Retain original mode-specific submit controls; no global command may invoke another solver.
 s=s.replace("if(tool==='提交计算') {if(active.value==='电力电量平衡') run().catch(e=>error.value=String(e));return}", "if(tool==='提交计算') {if(active.value==='电力电量平衡'&&balanceMode.value==='汇总／网络平衡')run().catch(e=>error.value=String(e));return}");
 s=s.replace("async function run(){busy.value=true;", "async function run(){if(busy.value)return;if(inputIssue.value){error.value=inputIssue.value;await navigateSection('电力电量平衡','模型与资源');workspacePanel.value='参数';return}busy.value=true;");
 s=s.replace("const p=await api('/api/projects/'+id);project.value=p;eventCsv.value='';", "const p=await api('/api/projects/'+id);project.value=p;selectedScenario.value=null;eventCsv.value='';");
 return s;
});
console.log('Interaction wiring updated');
