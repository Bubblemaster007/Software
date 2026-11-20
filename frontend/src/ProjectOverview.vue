<script setup lang="ts">
import {computed} from 'vue';
import {inspectTimeSeries} from './timeSeries';
const props=defineProps<{csv:string;history:any[];scenarioId:string|null;productionId:string|null;model:string;stages:number}>();
const emit=defineEmits<{navigate:[menu:string];open:[id:string]}>();
const inspection=computed(()=>inspectTimeSeries(props.csv));
const steps=[
 {menu:'数据管理',title:'准备源荷与资源数据',description:'导入或逐格录入源荷时序，检查时间连续性，设置储能与应急电源。'},
 {menu:'保供场景生成',title:'生成故障与修复场景',description:'先查看模板或资料来源，设置增长、事件和故障修复参数；生成后主动应用到平衡计算。'},
 {menu:'电力电量平衡',title:'设置运行阶段并计算',description:'选择汇总或IEEE33网络模型，点击开始分析后调用后端，查看逐时、分阶段结果与随机样本统计。'},
 {menu:'保供能力提升',title:'评估策略与资源调整',description:'读取八项策略触发建议，调整资源并与基准进行同条件复算。'},
 {menu:'源储协同配置',title:'试算配置建议并复核',description:'设置候选源储、建设阶段与目标约束，运行逐设备配置并复核结果。'},
 {menu:'方案与报告',title:'查看档案与导出报告',description:'查看本工程计算档案，选择基准对比，导出逐时数据和计算报告。'}
];
</script>
<template>
<article class="overview" id="project-overview"><h3>工程准备状态</h3><div class="overview-metrics"><div><span>源荷时序</span><strong>{{inspection.count}} <small>小时</small></strong><p>{{inspection.totalIssues?'有'+inspection.totalIssues+'项录入问题':'本地格式校验通过'}}</p></div><div><span>运行模型</span><strong>{{model==='case33'?'IEEE33网络':'汇总平衡'}}</strong><p>{{stages?stages+'个运行阶段':'全时域统一参数'}}</p></div><div><span>输入引用</span><strong>{{scenarioId?'已选故障场景':'未选故障场景'}}</strong><p>{{productionId?'已关联生产序列':'使用当前源荷输入'}}</p></div><div><span>已归档平衡结果</span><strong>{{history.length}}{{history.length===100?'+':''}} <small>次</small></strong><button v-if="history.length" @click="emit('open',history[0].id)">加载最近一次结果</button><p v-else>完成计算后自动归档</p></div></div><p class="overview-note">准备状态按当前工作区输入显示；历史结果保留各次计算的输入快照。选择场景不是运行平衡计算的必填条件。</p></article>
<article id="project-workflow"><h3>核心业务步骤 · 从数据开始</h3><div class="workflow"><button v-for="(step,index) in steps" :key="step.menu" @click="emit('navigate',step.menu)"><span class="step-number">{{String(index+1).padStart(2,'0')}}</span><div><b>{{step.title}}</b><p>{{step.description}}</p><span class="entry">进入{{step.menu}} →</span></div></button></div></article>
</template>
<style scoped>
.overview-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.overview-metrics>div{background:#f0f7f7;border-radius:6px;padding:16px}.overview-metrics span{color:#526e73;font-size:12px}.overview-metrics strong{display:block;font-size:20px;color:#087b7b;margin:10px 0}.overview-metrics small{font-size:12px;font-weight:400}.overview-metrics p,.overview-note{font-size:12px;line-height:1.7;color:#607b80}.overview-metrics button{font-size:12px;padding:5px 8px}.workflow{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.workflow>button{display:flex;align-items:flex-start;gap:16px;text-align:left;padding:18px;background:white;border:1px solid #d4e5e5;white-space:normal}.workflow>button:hover{background:#f2f9f8;border-color:#087b7b}.step-number{color:#087b7b;font-size:22px;font-weight:700}.workflow b{color:#25454c;font-size:14px}.workflow p{font-weight:400;font-size:12px;color:#607b80;line-height:1.8;margin:8px 0}.entry{color:#087b7b;font-size:12px}@media(max-width:1100px){.overview-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.overview-metrics,.workflow{grid-template-columns:minmax(0,1fr)}}
</style>
