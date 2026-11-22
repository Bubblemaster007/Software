from pathlib import Path
root=Path('frontend/src')
p=root/'useEngineeringProject.ts';s=p.read_text(encoding='utf-8-sig')
s="import {useScenarioConfiguration} from './useScenarioConfiguration';\nimport {validateScenarioDraft} from './scenarioConfiguration';\n"+s
marker='  const progressEvidence = useWorkflowProgress(project, subsection);'
s=s.replace(marker,"  const scene=useScenarioConfiguration({project,csv,customNetwork,operatingCondition,scenarioId,activeProductionId,faultSelection,stages,sourceImport,productionId,productionCsv,failedLines,model,balanceMode,projectMessage,navigateWorkspace});\n"+marker)
s=s.replace('    return workflowStatuses({','    const statuses=workflowStatuses({',1)
end='''    });
  });
  const inputIssue'''
s=s.replace(end,'''    });
    if(scene.confirmed.value)statuses['场景生成']={label:scene.valid.value?'已应用':'配置已失效',tone:scene.valid.value?'done':'warning',detail:scene.valid.value?'已统一确认并应用当前场景配置':'上游源荷、网架、故障或阶段已变化，请重新确认场景'};
    else if(scene.draft.value)statuses['场景生成']={label:scene.stale.value?'配置已失效':'配置中',tone:'warning',detail:'场景草稿尚未正式应用'};
    return statuses;
  });
  const inputIssue''',1)
s=s.replace('    const check = inspectTimeSeries(csv.value);\n    if (check.count',"    if(!scene.valid.value)return '请先在场景生成设置中确认当前场景；历史档案仍可只读查看';\n    const check = inspectTimeSeries(csv.value);\n    if (check.count",1)
s=s.replace('      operatingCondition: operatingCondition.value,','      scenarioConfiguration:scene.confirmed.value,\n      operatingCondition: operatingCondition.value,',1)
s=s.replace('    if (w) navigateSection(w.menu, w.defaultView);','    if(w?.id===\'scenario.workspace\')scene.ensure();\n    if (w) navigateSection(w.menu, w.defaultView);')
s=s.replace('  function applyProjected(value: string) {',"  function applyProjected(value: string) {\n    if(active.value==='保供场景生成'){scene.selectBackground(value);return}")
s=s.replace('  ) {\n    applyProjected(value);\n    productionId.value = id;',"  ) {\n    if(active.value==='保供场景生成'){scene.selectProduction(value,id,embeddedScenarioId).catch(e=>error.value=String(e));return}\n    applyProjected(value);\n    productionId.value = id;")
s=s.replace('  function applyScenario(id: string) {',"  function applyScenario(id: string) {\n    if(active.value==='保供场景生成'){scene.selectScenario(id).catch(e=>error.value=String(e));return}")
s=s.replace('const parameterTab = ref("计算模型")','const parameterTab = ref("资源参数")')
# Parameter application no longer owns scenario fields or the model selector.
s=s.replace('    model.value = d.model;','')
s=s.replace('    stages.value = JSON.parse(JSON.stringify(d.stages));','').replace('    failedLines.value = d.failedLines;','')
s=s.replace('  const commandRegistry = useCommands(','''  async function validateNetwork(){if(!customNetwork.value){error.value='尚无已应用网架';return}const response=await fetch('/api/network/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(customNetwork.value)});const value=await response.json();validation.value=[response.ok?'当前网架模型校验通过':JSON.stringify(value.detail)];layout.bottom.value='校验信息'}
  function networkChanged(value:any){customNetwork.value=value;failedLines.value='';stages.value=stages.value.map(stage=>({...stage,failed_lines:[]}));scenarioId.value=null;productionId.value=null;projectMessage.value='网架已更新；旧故障、阶段线路及场景/生产序列引用已解除，请重新确认场景';}
  const commandRegistry = useCommands(''')
s=s.replace('    [{id:"project.versions"', '''    [{id:'scenario.library',label:'载入已有场景',surface:'context',visible:()=>workspaceId.value==='scenario.workspace',execute:()=>{scene.ensure();scene.libraryOpen.value=true}},
      {id:'network.import',label:'导入网架',surface:'context',visible:()=>workspaceId.value==='data.network'&&subsection.value==='电网拓扑',execute:()=>dataWorkspace.value?.openNetworkImport()},
      {id:'network.validate',label:'校验模型',surface:'context',visible:()=>workspaceId.value==='data.network'&&subsection.value==='电网拓扑',execute:validateNetwork},
      {id:"project.versions"''')
s=s.replace('        label: "导入数据",','        label: "导入数据",icon:"▱",primary:true,')
s=s.replace('        label: "编辑网络模型",','        label: "编辑网架",')
s=s.replace('workspaceId.value.startsWith("data.") ||', '(workspaceId.value.startsWith("data.")&&workspaceId.value!=="data.network") ||')
s=s.replace('  return {\n    versionsOpen,','  return {\n    scene,networkChanged,\n    versionsOpen,')
# Prevent saving displayed unknown metadata from incorrectly marking configuration applied.
s=s.replace('      projectSettingsOpen.value = false;\n      workspacePanel.value', '      projectSettingsOpen.value = false;scene.confirmed.value=v.scenarioConfiguration||null;\n      workspacePanel.value')
p.write_text(s,encoding='utf-8')
p=root/'WorkspaceHost.vue';s=p.read_text(encoding='utf-8');s="".join([s])
s=s.replace('import ParameterDialog',"import ScenarioSettingsWorkspace from './ScenarioSettingsWorkspace.vue';\nimport ParameterDialog",1)
s=s.replace('  layout,','  networkChanged,\n  layout,',1)
s=s.replace("        'scenario.workspace',\n",'')
start=s.index('    ><button\n      v-if="workspaceId === \'scenario.workspace\'"');end=s.index('    ><button',start+8)
s=s[:start]+s[end:]
s=s.replace('@update:network="model = \'case33\'"','@update:network="networkChanged"')
start=s.index('  <template v-else-if="active === \'保供场景生成\'"');end=s.index('<BalanceWorkspace v-else-if=',start)
s=s[:start]+'''  <ScenarioSettingsWorkspace v-else-if="active==='保供场景生成'"/>
  '''+s[end:]
start=s.find('  <ParameterDialog\n    v-model:open="scenarioLibraryOpen"')
if start>=0:s=s[:start]+s[s.index('</ParameterDialog>',start)+18:]
# Priority editor uses the existing sole inventory model in resource workspace.
s=s.replace("['典型场景库',", "['典型场景库',")
s=s.replace("'示范区实证',\n", "'示范区实证',\n")
p.write_text(s,encoding='utf-8')
p=root/'workspaceRegistry.ts';s=p.read_text(encoding='utf-8').replace('"scenario.workspace", "场景生成",','"scenario.workspace", "场景生成设置",')
s=s.replace('["电源台账", "储能台账", "负荷与保供目标"]','["电源台账", "储能台账", "负荷与保供目标", "分类目标与优先级", "典型场景库"]')
s+="\nexport const stageDisplayNames:Record<string,string>={'场景生成':'场景生成设置'};\n"
p.write_text(s,encoding='utf-8')
p=root/'EngineeringLayout.vue';s=p.read_text(encoding='utf-8').replace('import { workspaces }','import { workspaces,stageDisplayNames }').replace('{{ group }}','{{ stageDisplayNames[group]||group }}')
s=s.replace('{{ c.label }}','<span v-if="c.icon" aria-hidden="true">{{c.icon}} </span>{{ c.label }}')
p.write_text(s,encoding='utf-8')
p=root/'ProjectOverview.vue';s=p.read_text(encoding='utf-8').replace("title:'场景生成',","title:'场景生成',display:'场景生成设置',")
s=s.replace('{{step.title}}','{{step.display||step.title}}');p.write_text(s,encoding='utf-8')
p=root/'App.vue';s=p.read_text(encoding='utf-8').replace('  operatingCondition,','  scene,')
start=s.index('><select\n          aria-label="输入运行工况"');end=s.index('><select aria-label="计算模式"',start)
s=s[:start]+s[end:]
s=s.replace('<template #toolbar\n      ><template', '''<template #toolbar><template v-if="workspaceId==='scenario.workspace'&&scene.draft.value"><label class="toolbar-condition">运行工况 <select aria-label="场景运行工况" v-model="scene.draft.value.condition" @change="scene.draft.value.conditionConfirmed=true;scene.draft.value.step='background';if(scene.draft.value.condition==='常规运行'){scene.draft.value.faultMode='none';scene.draft.value.eventMode='none';scene.draft.value.eventCsv='';scene.clearEmbedded()}"><option>常规运行</option><option>极端保供</option></select></label></template><template''',1)
s=s.replace('数据准备 → 场景生成','数据准备 → 场景生成设置')
p.write_text(s,encoding='utf-8')
for name in ['SourceStudy','SourceAnalysis','SequenceWorkspace','ScenarioWorkspace']:
 p=root/(name+'.vue');s=p.read_text(encoding='utf-8');s=s.replace('projectId:string;', 'draftMode?:boolean;projectId:string;',1)
 labels={'将此水平年全年背景应用到工程':"{{draftMode?'选用背景序列到草稿':'将此水平年全年背景应用到工程'}}",'将极端窗口应用到当前工程':"{{draftMode?'选用极端片段作为输入草稿':'将极端窗口应用到当前工程'}}",'送入生产序列嵌入':"{{draftMode?'选用片段用于嵌入':'送入生产序列嵌入'}}",'将增长后序列应用到当前工程':"{{draftMode?'选用增长序列到草稿':'将增长后序列应用到当前工程'}}",'将生产序列应用到当前工程':"{{draftMode?'选用生产序列到草稿':'将生产序列应用到当前工程'}}",'✓ 应用当前场景':"{{draftMode?'选用随机场景到草稿':'✓ 应用当前场景'}}",'将此场景应用到电力电量平衡':"{{draftMode?'选用此场景到草稿':'将此场景应用到电力电量平衡'}}"}
 for a,b in labels.items():s=s.replace('>'+a+'<','>'+b+'<')
 s=s.replace('应用会替换当前时序并解除旧场景与生产序列引用。','选用只更新场景草稿；统一确认后才应用工程输入。' if name=='SourceStudy' else '应用会替换当前时序并解除旧场景与生产序列引用。')
 p.write_text(s,encoding='utf-8')
