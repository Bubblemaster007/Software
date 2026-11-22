const fs=require('fs');const root='C:/Users/13411/Desktop/software/';
function edit(file,fn){const p=root+file;fs.writeFileSync(p,fn(fs.readFileSync(p,'utf8')))}
edit('frontend/src/App.vue',s=>{
 const summary='<NetworkSummary v-if="subsection===\'电网拓扑\'" :network="customNetwork"/>';
 s=s.replace(summary,'');
 s=s.replace('<template v-else-if="active===\'数据管理\'">','<div v-else-if="active===\'数据管理\'" class="data-page" :class="{\'network-page\':subsection===\'电网拓扑\'}">');
 const boundary=':parameters="params" :disabled="busy"/></template><template v-else-if="active===\'保供场景生成\'">';
 if(!s.includes(boundary))throw Error('data boundary missing');
 s=s.replace(boundary,':parameters="params" :disabled="busy"/>'+summary+'</div><template v-else-if="active===\'保供场景生成\'">');
 s=s.replace('<article><h3>场景配置与计算流程</h3>','<details class="scenario-guide"><summary>工况选择与操作说明</summary><article><h3>场景配置与计算流程</h3>');
 s=s.replace('</p></article><EngineeringWorkspace v-if="[\'典型场景库\',\'分类目标与优先级\'].includes(subsection)"','</p></article></details><EngineeringWorkspace v-if="[\'典型场景库\',\'分类目标与优先级\'].includes(subsection)"');
 // The source component owns the only selector and parameters; it also hosts the dashboard.
 const dash='<ScenarioDashboard v-if="subsection===\'故障与恢复场景\'" :csv="csv" :event-csv="eventCsv" :scenario="selectedScenario" :condition="operatingCondition"/>';
 s=s.replace(dash,'');
 s=s.replace(':open-settings="scenarioSettingsOpen" @selected="selectedScenario=$event" @apply="applyScenario"/>',':open-settings="scenarioSettingsOpen" :event-csv="eventCsv" :condition="operatingCondition" @selected="selectedScenario=$event" @apply="applyScenario"/>');
 return s;
});
edit('frontend/src/ScenarioWorkspace.vue',s=>s.replace("import FaultStatePlot from './FaultStatePlot.vue';","import FaultStatePlot from './FaultStatePlot.vue';\nimport ScenarioDashboard from './ScenarioDashboard.vue';").replace('openSettings?:number','openSettings?:number;eventCsv?:string;condition?:string').replace('<FaultStatePlot :states="selected?.states||[]"/>','<ScenarioDashboard :csv="csv" :event-csv="eventCsv" :scenario="selected" :condition="condition||\'极端保供\'"/>'));
// App no longer duplicates the scenario dashboard; owned by the stateful scene selector.
edit('frontend/src/App.vue',s=>s.replace("import ScenarioDashboard from './ScenarioDashboard.vue';\n",''));
console.log('Corrected nested height, topology overview grid and scenario command ordering');
