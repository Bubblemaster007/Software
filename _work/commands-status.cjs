const fs=require('fs');let p=fs.readFileSync('frontend/src/useEngineeringProject.ts','utf8');
const names={'context.import':'data.import','context.network':'network.edit','context.edit':'data.edit','context.validate':'data.validate','context.parameters':'workspace.settings','context.run':'balance.run','context.export':'result.export'};
for(const [old,id] of Object.entries(names))p=p.replace("{id:'"+old+"'","{id:'"+id+"',surface:'context'");
p=p.replace("const parametersDraft=ref<any>(null);", "const parametersDraft=ref<any>(null);");
p=p.replace("const helpOpen=ref(false),projectSettingsOpen=ref(false);",`const helpOpen=ref(false),projectSettingsOpen=ref(false);
const projectSettingsTab=ref('工程信息');const projectDraft=ref<any>({});
watch(projectSettingsOpen,open=>{if(open){projectSettingsTab.value='工程信息';projectDraft.value={name:project.value?.name||'',region:project.value?.region||'',kind:project.value?.kind||'村镇级'}}});
async function applyProjectSettings(){if(!project.value)return;Object.assign(project.value,projectDraft.value);await saveProject();projectSettingsOpen.value=false}
const savedFingerprint=ref('');
function fingerprint(){return JSON.stringify({state:state(),name:project.value?.name,region:project.value?.region,kind:project.value?.kind})}
const unsaved=computed(()=>!!project.value&&!!savedFingerprint.value&&fingerprint()!==savedFingerprint.value);
const statusText=computed(()=>(unsaved.value?'未保存修改 · ':'')+(projectMessage.value||'本地工程工作区')+(result.value?' · 当前结果输入 v'+(result.value.project_revision??'未记录'):''));
`);
p=p.replace("projectMessage.value='工程已保存 · 版本 '+project.value.revision;", "savedFingerprint.value=fingerprint();projectMessage.value='工程已保存 · 版本 '+project.value.revision;");
p=p.replace("projectMessage.value='当前工程：'+p.name+' · 版本 '+p.revision", "savedFingerprint.value=fingerprint();projectMessage.value='当前工程：'+p.name+' · 版本 '+p.revision");
p=p.replace("layout.bottom.value='';layout.right.value='';", "layout.bottom.value='';layout.right.value='';validation.value=[];projectSettingsOpen.value=false;");
p=p.replace('return {layout,','return {projectSettingsTab,projectDraft,applyProjectSettings,unsaved,statusText,layout,');
fs.writeFileSync('frontend/src/useEngineeringProject.ts',p);
let layout=fs.readFileSync('frontend/src/EngineeringLayout.vue','utf8').replace("c.id.startsWith('context.')","c.surface==='context'");fs.writeFileSync('frontend/src/EngineeringLayout.vue',layout);
let reg=fs.readFileSync('frontend/src/workspaceRegistry.ts','utf8').replace("['network.import','data.edit','data.validate']","['network.edit','data.validate']").replace("['workspace.settings','balance.validate','balance.run','result.export']","['workspace.settings','data.validate','balance.run','result.export']");fs.writeFileSync('frontend/src/workspaceRegistry.ts',reg);
let app=fs.readFileSync('frontend/src/App.vue','utf8').replace("const {",'const {projectSettingsTab,projectDraft,applyProjectSettings,statusText,');
app=app.replace(':status="projectMessage"',':status="statusText"');
app=app.replace('title="工程设置"><article v-if="project">', 'title="工程设置" :tabs="[\'工程信息\',\'经济参数\']" v-model:active="projectSettingsTab"><article v-if="project&&projectSettingsTab===\'工程信息\'">').replace('v-model="project.name"','v-model="projectDraft.name"').replace('v-model="project.region"','v-model="projectDraft.region"').replace('v-model="project.kind"','v-model="projectDraft.kind"');
app=app.replace('<template #footer><button @click="projectSettingsOpen=false">关闭</button><button class="primary" @click="commandRegistry.execute(\'project.save\')"', '<EngineeringWorkspace v-if="projectSettingsTab===\'经济参数\'" :project-id="project?.id||\'\'" section="经济参数"/><template #footer><button @click="projectSettingsOpen=false">取消</button><button v-if="projectSettingsTab===\'工程信息\'" class="primary" @click="applyProjectSettings"');
app=app.replace("import EngineeringLayout from", "import EngineeringWorkspace from './EngineeringWorkspace.vue';\nimport EngineeringLayout from");
fs.writeFileSync('frontend/src/App.vue',app);
let progress=fs.readFileSync('frontend/src/workflowProgress.ts','utf8').replace('Date.parse(b.created)||0','Date.parse(b.created)/1000||0').replace('Date.parse(a.created)||0','Date.parse(a.created)/1000||0');
progress=progress.replace("if(dirty){for(const group", "if(dirty&&scenario==='applied')result['场景生成']=status('待核对','warning','当前输入已有修改，已保存引用仍对应原状态；请核对后保存或重新生成');\n  if(dirty){for(const group");fs.writeFileSync('frontend/src/workflowProgress.ts',progress);
