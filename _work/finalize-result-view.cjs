const fs=require('fs');let s=fs.readFileSync('frontend/src/ResultOverview.vue','utf8');
s=s.replace('<template><div class="balance-overview"', '<template><div class="balance-overview"');
s=s.replace("{{result.model==='case33'?'网络平衡':'汇总平衡'}} · 任务", "{{result.model==='case33'?'网络平衡':'汇总平衡'}} · {{recordedCondition(result)}} · 任务");
s=s.replace("v-if=\"tab==='结果总览'\" class=\"compact-metrics\"",'class="compact-metrics"').replace(':key="c.key"><span>',':key="c.key" :title="c.scope"><span>').replace('{{c.value}} <small>{{c.unit}}</small>',"{{c.value??'未计算'}} <small v-if=\"c.value!==null\">{{c.unit}}</small>");
s=s.replace(/\['结果总览','供需分析'\]\.includes\(tab\)/g,"tab==='供需平衡'");
// SOC is a separate figure tab, and phases belong in the bottom dock.
s=s.replace('v-if="tab===\'供需平衡\'" title="储能 SOC"','v-if="tab===\'储能状态\'" title="储能 SOC"');
s=s.replace(/<AnalysisChart v-if="tab==='结果总览'&&phases.length"[\s\S]*?unit="MWh"\/>/,'');
s=s.replace("['结果总览','资源出力'].includes(tab)","tab==='资源出力'");
s=s.replace('class="analysis-grid" :class="{detail:tab!==\'结果总览\'}"','class="analysis-grid detail"');
s=s.replace(/<a :href="'\/api\/runs\/'.*?导出逐时结果<\/a>/,'');
fs.writeFileSync('frontend/src/ResultOverview.vue',s);
let n=fs.readFileSync('frontend/src/navigation.ts','utf8');n=n.slice(0,n.indexOf('export const workflowNavigation ='))+`export {workspaces} from './workspaceRegistry';\nimport {workspaces} from './workspaceRegistry';\nexport const workflowNavigation=['工程工作台','数据准备','场景生成','平衡分析','保供优化','成果管理','专项研究','系统管理'].map(label=>({label,items:workspaces.filter(w=>w.stage===label).map(w=>({id:w.id,label:w.label,menu:w.menu,sections:w.sections}))}));\n`;fs.writeFileSync('frontend/src/navigation.ts',n);
