const fs=require('fs');let s=fs.readFileSync('frontend/src/InvestmentWorkspace.vue','utf8');
s=s.replace('<script setup lang="ts">',"<script setup lang=\"ts\">\nimport {useParameterTransaction} from './useParameterTransaction';");
s=s.replace('projectId:string;section:string}>','projectId:string;section:string;editing?:boolean}>');
s=s.replace('</script>',`const editSession=ref(false);
const commitSettings=useParameterTransaction(editSession,{candidates,name,minutes,steps,probability,targetPolicy,riskScope,discount,salvage,budget,wall,gap,protectedClasses,stages,scenarioText,validationText,advanced,jointText,flexText});
watch(()=>props.editing,value=>editSession.value=!!value);
defineExpose({acceptSettings:()=>commitSettings(false)});
</script>`);
// Submitting freezes the fields currently shown, while cancellation still discards later edits.
s=s.replace(/async function (submit|run)\(([^)]*)\)\{/g,'async function $1($2){commitSettings(false);');
fs.writeFileSync('frontend/src/InvestmentWorkspace.vue',s);
let c=fs.readFileSync('frontend/src/ConfigOverview.vue','utf8');c=c.replace("const context=ref<any>({});const tab=ref('配置总览');","const investmentEditor=ref<InstanceType<typeof InvestmentWorkspace>>();\nconst context=ref<any>({});const tab=ref('配置方案');");
c=c.replace("const tabs=['配置总览','容量方案','保供效果','经济分析'];","const tabs=['配置方案','保供效果','经济性分析','空间配置'];");
c=c.replaceAll("tab.value='配置总览'","tab.value='配置方案'").replaceAll("['配置总览','容量方案'].includes(tab)","tab==='配置方案'").replaceAll("['配置总览','保供效果'].includes(tab)","tab==='保供效果'").replaceAll("['配置总览','经济分析'].includes(tab)","tab==='经济性分析'");
c=c.replace('<InvestmentWorkspace :project-id=', '<InvestmentWorkspace ref="investmentEditor" :editing="settingsOpen" :project-id=');
c=c.replace('</InvestmentWorkspace>','</InvestmentWorkspace>');
c=c.replace('@context="context=$event"/></ParameterDialog>', '@context="context=$event"/><template #footer><button @click="settingsOpen=false">取消</button><button class="primary" @click="investmentEditor?.acceptSettings();settingsOpen=false">应用配置参数</button></template></ParameterDialog>');
c=c.replace('<div v-if="result" class="config-grid">','<div v-if="result" class="config-grid"><article v-if="tab===\'空间配置\'" class="spatial-assets"><h3>选定资源接入位置</h3><table><tr><th>资源</th><th>节点</th><th>投运年</th></tr><tr v-for="a in assets"><td>{{a.asset_id}}</td><td>{{a.node??\'未记录\'}}</td><td>{{a.commission_year??\'未记录\'}}</td></tr></table><p v-if="!assets.length">当前任务没有选定资源。</p></article>');
fs.writeFileSync('frontend/src/ConfigOverview.vue',c);
