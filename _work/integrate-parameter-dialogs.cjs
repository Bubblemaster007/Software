const fs=require('fs');const root='C:/Users/13411/Desktop/software/frontend/src/';
function edit(name,fn){const path=root+name;fs.writeFileSync(path,fn(fs.readFileSync(path,'utf8')))}
function replace(s,a,b){if(!s.includes(a))throw Error('Missing: '+a.slice(0,90));return s.replace(a,b)}
edit('App.vue',s=>{
 s=replace(s,"import SeriesPreview from './SeriesPreview.vue';","import SeriesPreview from './SeriesPreview.vue';\nimport ParameterDialog from './ParameterDialog.vue';");
 s=replace(s,"const workspacePanel=ref('');","const parameterTab=ref('计算模型');\nconst balanceParametersOpen=computed({get:()=>workspacePanel.value==='参数',set:value=>workspacePanel.value=value?'参数':''});\nconst dataParametersOpen=ref(false);const dataParameterTab=ref('源储参数');\nconst workspacePanel=ref('');");
 s=s.replace("? ['选择场景','模型与资源','运行阶段','参数设置','输入校验']","? ['选择场景','参数设置','输入校验']");
 s=s.replace(": ['选择场景','模型与资源','运行阶段','参数设置','输入校验']",": ['选择场景','参数设置','输入校验']");
 s=s.replace("if(menu==='数据管理') return section==='源荷时序'||section==='阿拉山口资料'","if(menu==='数据管理') return section==='源荷时序'");
 s=s.replace("['导入数据','数据编辑','校验','保存']","['选择数据集','数据编辑','参数设置','校验']").replace("['导入拓扑','属性','校验','保存']","['导入拓扑','属性','参数设置','校验']").replace("['数据编辑','属性','校验','保存']","['数据编辑','参数设置','校验']");
 s=s.replace("if(tool==='参数设置'||tool==='设置'||tool==='模型与资源') {","if(tool==='选择数据集'){dataWorkspace.value?.openDatasetPicker();return}\n if(tool==='参数设置'||tool==='设置'||tool==='模型与资源') {if(active.value==='数据管理'){dataParametersOpen.value=true;return}");
 s=s.replace("if(tool==='运行阶段') {workspacePanel.value='参数';return}","if(tool==='运行阶段') {parameterTab.value='运行阶段';workspacePanel.value='参数';return}");
 s=s.replace("watch(subsection,()=>{workspacePanel.value='';","watch(subsection,()=>{workspacePanel.value='';dataParametersOpen.value=false;");
 const a=s.indexOf('<article v-show="workspacePanel===\'参数\'" class="parameter-dock">');
 const b=s.indexOf('</article></div><div v-show="balanceView===\'分析设置\'&&workspacePanel===\'参数\'"',a);
 if(a<0||b<0)throw Error('Balance parameter bounds');
 const content=s.slice(a,b);
 const model=content.slice(content.indexOf('<label class="field">计算模型'),content.indexOf('<details>'));
 const network=content.slice(content.indexOf('<template v-if="model===\'case33\'">'),content.indexOf('<label v-for="(_,key) in params"'));
 const resources=content.slice(content.indexOf('<label v-for="(_,key) in params"'),content.indexOf('</details>'));
 const phaseStart=b+'</article></div>'.length;
 const phaseEnd=s.indexOf('</div><SeriesPreview v-if="balanceView===\'计算任务\'"',phaseStart);
 const phase=s.slice(phaseStart,phaseEnd+6);const phaseTag=phase.match(/<PhaseEditor[^>]+\/>/)[0];
 const dialog=`<ParameterDialog v-model:open="balanceParametersOpen" title="平衡分析参数" :tabs="['计算模型','资源参数','网络与故障','运行阶段']" v-model:active="parameterTab"><article v-show="parameterTab==='计算模型'"><h3>计算模型</h3>${model}<p>汇总平衡可使用8760小时，节点网络平衡保持原有168小时限制。其他计算方式在任务页选择。</p></article><article v-show="parameterTab==='资源参数'"><h3>资源参数</h3>${resources}<p>关键、重要负荷按占比分组，其余为一般负荷。参数保存不等于提交计算。</p></article><article v-show="parameterTab==='网络与故障'"><h3>网络接入与故障</h3>${network}<p v-if="model!=='case33'">当前汇总模型无网络参数，选择节点网络模型后设置。</p></article><div v-show="parameterTab==='运行阶段'">${phaseTag}</div><template #footer><button @click="workspacePanel=''">收起，保留草稿</button><button class="primary" @click="saveProject().then(()=>workspacePanel='').catch(e=>error=String(e))" :disabled="busy">保存工程参数</button></template></ParameterDialog>`;
 s=s.slice(0,a)+dialog+'</div>'+s.slice(phaseEnd+6);
 const marker='<div class="right-tool-rail"';
 const dataDialog=`<ParameterDialog v-model:open="dataParametersOpen" title="工程参数设置" :tabs="['源储参数','经济参数']" v-model:active="dataParameterTab"><DataWorkspace v-show="dataParameterTab==='源储参数'" v-model="csv" v-model:network="customNetwork" v-model:failures="faultSelection" section="源储参数" :parameters="params" :placement="networkParameters" :disabled="busy"/><EngineeringWorkspace v-show="dataParameterTab==='经济参数'" :project-id="project?.id||''" section="经济参数"/><template #footer><button @click="dataParametersOpen=false">收起，保留草稿</button><button class="primary" v-if="dataParameterTab==='源储参数'" @click="saveProject().then(()=>dataParametersOpen=false).catch(e=>error=String(e))" :disabled="busy">保存工程参数</button></template></ParameterDialog>`;
 s=replace(s,marker,dataDialog+marker);
 s=s.replace("['参数','指标','明细']","['指标','明细']");
 s=s.replace("<EngineeringWorkspace v-if=\"inventorySections.includes(subsection)\"","<EngineeringWorkspace v-if=\"inventorySections.includes(subsection)\"");
 return s;
});
edit('ConfigOverview.vue',s=>{
 s=replace(s,"import AnalysisChart from './AnalysisChart.vue';","import AnalysisChart from './AnalysisChart.vue';\nimport ParameterDialog from './ParameterDialog.vue';");
 s=s.replace("const tabs=['配置总览'","const settingsOpen=computed({get:()=>!!editor.value,set:value=>{if(!value)editor.value=''}});\nconst tabs=['配置总览'");
 const a=s.indexOf(' <div class="config-actions">'),b=s.indexOf(' <nav class="fixed-tabs"',a);
 s=s.slice(0,a)+` <div class="config-actions"><strong>源储协同配置</strong><button class="primary" @click="open('候选资源')">配置参数</button><button @click="open('配置结果')">任务与详细结果</button></div>\n`+s.slice(b);
 s=s.replace('<div v-if="!editor">','<div>');
 const c=s.indexOf(' <div v-if="editor" class="document-toolbar">'),d=s.indexOf('\n</div>\n</template>',c);
 s=s.slice(0,c)+` <ParameterDialog v-model:open="settingsOpen" title="源储配置工作区" :tabs="['候选资源','目标与约束','规划阶段','配置结果','一二次协同规划','灵活组网']" v-model:active="editorSection"><InvestmentWorkspace :project-id="projectId" :section="editorSection" @context="context=$event"/></ParameterDialog>`+s.slice(d);
 return s;
});
edit('ScenarioWorkspace.vue',s=>{
 s=replace(s,"import ScenarioDashboard from './ScenarioDashboard.vue';","import ScenarioDashboard from './ScenarioDashboard.vue';\nimport ParameterDialog from './ParameterDialog.vue';");
 s=s.replace('<button @click="setupOpen=!setupOpen">⚙ 场景设置</button>','');
 s=s.replace('<div v-show="setupOpen" class="scenario-settings"><button @click="setupOpen=false">× 关闭场景设置（保留草稿）</button>','<ParameterDialog v-model:open="setupOpen" title="场景生成参数">');
 s=replace(s,'</article></div><article v-if="selected&&detailOpen">','</article></ParameterDialog><article v-if="selected&&detailOpen">');
 return s;
});
