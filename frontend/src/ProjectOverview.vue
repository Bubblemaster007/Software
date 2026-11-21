<script setup lang="ts">
import {computed} from 'vue';
import {inspectTimeSeries} from './timeSeries';
const props=defineProps<{csv:string;history:any[];scenarioId:string|null;productionId:string|null;model:string;stages:number}>();
const emit=defineEmits<{navigate:[menu:string];open:[id:string]}>();
const inspection=computed(()=>inspectTimeSeries(props.csv));
const steps=[
 {menu:'数据管理',title:'数据准备',description:'核实源荷、拓扑、资源与参数，完成数据检查。'},
 {menu:'保供场景生成',title:'场景生成',description:'配置背景、极端窗口及故障，生成后明确应用。'},
 {menu:'电力电量平衡',title:'平衡分析',description:'核对输入、选择计算模式、提交并查看结果。'},
 {menu:'保供能力提升',title:'保供优化',description:'以基准结果开展策略复算或源储协同配置。'},
 {menu:'方案与报告',title:'成果管理',description:'查看已存档案、比较方案和导出成果。'}
];
const nextMenu=computed(()=>inspection.value.totalIssues?'数据管理':!props.history.length?'电力电量平衡':'方案与报告');

</script>
<template>
<article><h3>继续工程分析</h3><p>{{inspection.totalIssues?'先修正源荷数据格式':history.length?'已有平衡档案，可查看结果或继续优化':'当前时序格式通过，可核对模型设置后计算'}}；此提示不替代具体模型的输入校验。</p><button class="primary" @click="emit('navigate',nextMenu)">继续当前步骤 →</button></article><article class="overview" id="project-overview"><h3>工程准备状态</h3><div class="overview-metrics"><div><span>源荷时序</span><strong>{{inspection.count}} <small>小时</small></strong><p>{{inspection.totalIssues?'有'+inspection.totalIssues+'项录入问题':'本地格式校验通过'}}</p></div><div><span>运行模型</span><strong>{{model==='case33'?'IEEE33网络':'汇总平衡'}}</strong><p>{{stages?stages+'个运行阶段':'全时域统一参数'}}</p></div><div><span>输入引用</span><strong>{{scenarioId?'已选故障场景':'未选故障场景'}}</strong><p>{{productionId?'已关联生产序列':'使用当前源荷输入'}}</p></div><div><span>已归档平衡结果</span><strong>{{history.length}}{{history.length===100?'+':''}} <small>次</small></strong><button v-if="history.length" @click="emit('open',history[0].id)">加载最近一次结果</button><p v-else>完成计算后自动归档</p></div></div><p class="overview-note">准备状态按当前工作区输入显示；历史结果保留各次计算的输入快照。选择场景不是运行平衡计算的必填条件。</p></article>
<article><h3>下一步待办</h3><p v-if="inspection.totalIssues">源荷存在{{inspection.totalIssues}}项问题，请到数据准备修正。</p><p v-if="!scenarioId">尚未应用故障场景；常规运行可直接使用当前源荷，不强制配置故障。</p><p v-if="!history.length">本工程暂无平衡档案，请完成分析设置后提交计算。</p><button @click="emit('navigate','系统与接口')">查看实际计算任务</button></article><article id="project-workflow"><h3>核心业务步骤 · 从数据开始</h3><div class="workflow"><button v-for="(step,index) in steps" :key="step.menu" @click="emit('navigate',step.menu)"><span class="step-number">{{String(index+1).padStart(2,'0')}}</span><div><b>{{step.title}}</b><p>{{step.description}}</p><span class="entry">进入{{step.menu}} →</span></div></button></div></article>
</template>
<style scoped>
.overview-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.overview-metrics>div{background:#f0f7f7;border-radius:6px;padding:16px}.overview-metrics span{color:#526e73;font-size:12px}.overview-metrics strong{display:block;font-size:20px;color:#087b7b;margin:10px 0}.overview-metrics small{font-size:12px;font-weight:400}.overview-metrics p,.overview-note{font-size:12px;line-height:1.7;color:#607b80}.overview-metrics button{font-size:12px;padding:5px 8px}.workflow{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px}.workflow>button{display:flex;flex-direction:column;align-items:flex-start;gap:16px;text-align:left;padding:18px;background:white;border:1px solid #d4e5e5;white-space:normal}.workflow>button:hover{background:#f2f9f8;border-color:#087b7b}.step-number{color:#087b7b;font-size:22px;font-weight:700}.workflow b{color:#25454c;font-size:14px}.workflow p{font-weight:400;font-size:12px;color:#607b80;line-height:1.8;margin:8px 0}.entry{color:#087b7b;font-size:12px}@media(max-width:1100px){.overview-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.overview-metrics,.workflow{grid-template-columns:minmax(0,1fr)}}
</style>
