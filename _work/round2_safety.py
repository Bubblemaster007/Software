from pathlib import Path
r=Path('frontend/src')
p=r/'FaultPicker.vue';s=p.read_text(encoding='utf-8').replace('v-for="l in available"','v-for="l in shown"');p.write_text(s,encoding='utf-8')
p=r/'ScenarioSettingsWorkspace.vue';s=p.read_text(encoding='utf-8').replace(':lines="shownLines"',':lines="customNetwork?.lines||[]" :search="search"')
# Fetch immutable details so the library can display real time bounds rather than invent them.
s=s.replace("records.value=[...faults.map((s:any)=>({...s,kind:'fault'})),...sequences.map((s:any)=>({...s,kind:'sequence'}))]", "const details=await Promise.all(faults.map(async (s:any)=>{const response=await fetch('/api/scenarios/'+s.id);if(!response.ok)throw Error('历史场景详情读取失败');return {...await response.json(),kind:'fault'}}));if(token!==request||project.value?.id!==id)return;records.value=[...details,...sequences.map((s:any)=>({...s,kind:'sequence'}))]")
p.write_text(s,encoding='utf-8')
p=r/'useScenarioConfiguration.ts';s=p.read_text(encoding='utf-8');s=s.replace('function ensure(){if(!draft.value)reset()}',"function ensure(){if(!draft.value){reset();if(context.scenarioId.value)selectScenario(context.scenarioId.value).catch(e=>error.value=String(e))}}")
# Avoid ensure -> select -> ensure recursion: select only creates when absent, after successful fetch.
s=s.replace("ensure();draft.value!.scenario=value", "if(!draft.value)reset();draft.value!.scenario=value")
s=s.replace("const upstream=()=>JSON.stringify({csv:context.csv.value,network:context.customNetwork.value});", "const upstream=()=>JSON.stringify({csv:context.csv.value,network:context.customNetwork.value});")
s=s.replace("function selectEvent(csv:string,asInput=false){", "function selectEvent(csv:string,asInput=false){")
s=s.replace("const d=draft.value!;d.eventCsv=csv;", "const d=draft.value!;d.productionId=null;d.productionCsv='';d.embeddedScenarioId=null;d.eventCsv=csv;")
# Hydrate applied draft metadata without interpreting historical tasks.
s=s.replace("eventCsv:'',eventMode:'none'", "eventCsv:'',eventMode:old?.eventMode||'none'")
# Existing production is already final input and may be confirmed without demanding a discarded old event.
s=s.replace("eventMode:old?.eventMode||'none'", "eventMode:'none'")
p.write_text(s,encoding='utf-8')
p=r/'useEngineeringProject.ts';s=p.read_text(encoding='utf-8');s=s.replace('"经济参数",\n  ];','"经济参数",\n    "分类目标与优先级", "典型场景库",\n  ];',1)
s=s.replace('parameterTab.value = section === "运行阶段" ? "运行阶段" : "计算模型";', 'parameterTab.value = "资源参数";')
s=s.replace("    if(!scene.valid.value)return", "    if(scene.confirmed.value?.faultMode==='manual'&&(model.value!=='case33'||balanceMode.value!=='汇总／网络平衡'))return '当前场景含手动线路故障，请使用节点网络平衡；高级模式不自动继承此场景';\n    if(!scene.valid.value)return")
s=s.replace("{csv:context", "{csv:context")
s=s.replace('    else parametersDraft.value = null;', '    else parametersDraft.value = null;')
s=s.replace('    if (open)\n      parametersDraft.value =', '    if(open)parameterTab.value="资源参数";\n    if (open)\n      parametersDraft.value =')
s=s.replace('数据准备 → 场景生成 →','数据准备 → 场景生成设置 →')
p.write_text(s,encoding='utf-8')
p=r/'WorkspaceHost.vue';s=p.read_text(encoding='utf-8').replace("              '典型场景库',\n              '分类目标与优先级',\n",'');p.write_text(s,encoding='utf-8')
p=r/'ScenarioWorkspace.vue';s=p.read_text(encoding='utf-8').replace('<ScenarioDashboard :csv="csv"', '<ScenarioDashboard v-if="!draftMode" :csv="csv"');s=s.replace('<ParameterDialog transactional','<article v-if="draftMode&&selected"><h3>已选随机场景预览 · {{selected.name}}</h3><FaultStatePlot :states="selected.states||[]"/><p>生成结果已保存；点击“选用随机场景到草稿”后，再到场景确认统一应用。</p></article><ParameterDialog transactional',1);p.write_text(s,encoding='utf-8')
