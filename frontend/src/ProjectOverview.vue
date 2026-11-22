<script setup lang="ts">
import {computed} from 'vue';
import {inspectTimeSeries} from './timeSeries';
const props=defineProps<{csv:string;history:any[];scenarioId:string|null;productionId:string|null;model:string;networkName?:string;stages:number;progress?:Record<string,any>;project?:any}>();
const emit=defineEmits<{navigate:[menu:string];open:[id:string]}>();
const inspection=computed(()=>inspectTimeSeries(props.csv));
const steps=[
 {menu:'数据管理',title:'数据准备',description:'核实源荷、拓扑、资源与参数，完成数据检查。'},
 {menu:'保供场景生成',title:'场景生成',display:'场景生成设置',description:'配置背景、极端窗口及故障，生成后明确应用。'},
 {menu:'电力电量平衡',title:'平衡分析',description:'核对输入、选择计算模式、提交并查看结果。'},
 {menu:'保供能力提升',title:'保供优化',description:'以基准结果开展策略复算或源储协同配置。'},
 {menu:'方案与报告',title:'成果管理',description:'查看已存档案、比较方案和导出成果。'}
];
const nextMenu=computed(()=>inspection.value.totalIssues?'数据管理':!props.history.length?'电力电量平衡':'方案与报告');

</script>
<template><article class="project-meta"><h3>{{project?.name||'工程首页'}}</h3><p>{{project?.region||'地区未填写'}} · 工程 v{{project?.revision??'—'}} · 最后保存 {{project?.updated||'未记录'}}</p><p>源荷 {{inspection.count}} 小时 · {{model==='case33'?(networkName||'IEEE33网络'):'汇总平衡'}} · {{stages?stages+'个运行阶段':'全时域统一参数'}}</p></article><article id="project-workflow"><h3>工程进度与下一步工作</h3><div class="workflow"><button v-for="(step,index) in steps" :key="step.menu" @click="emit('navigate',step.menu)"><span class="step-number">{{String(index+1).padStart(2,'0')}}</span><div><b>{{step.display||step.title}}</b><p :class="progress?.[step.title]?.tone">{{progress?.[step.title]?.label||'状态未知'}}</p><p>{{progress?.[step.title]?.detail||step.description}}</p><span class="entry">进入工作区 →</span></div></button></div></article><article><h3>最近计算成果</h3><p v-if="!history.length">本工程尚无平衡计算成果。配置并计算后自动归档；不以示例数值填充。</p><div class="scroll" v-else><table><tr><th>计算档案</th><th>创建时间</th><th>输入版本</th><th>操作</th></tr><tr v-for="h in history.slice(0,5)" :key="h.id"><td>{{h.id.slice(0,8)}}</td><td>{{h.created}}</td><td>{{h.project_revision??'未记录'}}</td><td><button @click="emit('open',h.id)">查看结果</button></td></tr></table></div></article><p class="overview-note">阶段状态按当前工程引用与冻结快照判断；任务执行完成不等于方案可行或算法验收通过。</p></template>
<style scoped>
.overview-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.overview-metrics>div{background:#f0f7f7;border-radius:6px;padding:16px}.overview-metrics span{color:#526e73;font-size:12px}.overview-metrics strong{display:block;font-size:20px;color:#087b7b;margin:10px 0}.overview-metrics small{font-size:12px;font-weight:400}.overview-metrics p,.overview-note{font-size:12px;line-height:1.7;color:#607b80}.overview-metrics button{font-size:12px;padding:5px 8px}.workflow{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px}.workflow>button{display:flex;flex-direction:column;align-items:flex-start;gap:16px;text-align:left;padding:18px;background:white;border:1px solid #d4e5e5;white-space:normal}.workflow>button:hover{background:#f2f9f8;border-color:#087b7b}.step-number{color:#087b7b;font-size:22px;font-weight:700}.workflow b{color:#25454c;font-size:14px}.workflow p{font-weight:400;font-size:12px;color:#607b80;line-height:1.8;margin:8px 0}.entry{color:#087b7b;font-size:12px}@media(max-width:1100px){.overview-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.overview-metrics,.workflow{grid-template-columns:minmax(0,1fr)}}
</style>
