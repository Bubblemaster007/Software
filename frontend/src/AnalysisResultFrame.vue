<script setup lang="ts">
import {computed} from 'vue';const props=defineProps<{module:string;tab:string}>();
const definitions:Record<string,{cards:string[];columns:string[];checks:string[]}>={
'承灾极限分析':{cards:['最大承灾强度 / pu','临界保供时长 / h','承灾裕度 / %'],columns:['设备编号','设备类型','临界强度 / pu','故障后功率缺额 / MW','薄弱等级'],checks:['灾害物理量与标幺基准','设备脆弱性参数','分类保供目标','承灾边界扫描算法']},
'离网稳定判别':{cards:['离网稳定性','持续保供能力','风险等级'],columns:['判别指标','计算值','判别阈值','裕度','判别结果'],checks:['频率稳定模型','电压稳定模型','惯量与短路比参数','扰动与控制方式']},
'黑启动路径优化':{cards:['恢复总时长 / min','恢复负荷 / MW','重要负荷恢复率 / %'],columns:['步骤','操作设备','恢复路径','预计时间 / min','恢复负荷 / MW','校核结果'],checks:['电压频率稳定','励磁涌流','开关布点','自动化终端','通信路由']},
'源储协同配置':{cards:['新增电源 / kW','新增储能 / kWh','总投资 / 元'],columns:['资源类型','接入节点','建设阶段','新增功率 / kW','新增容量 / kWh','投资 / 元'],checks:['候选资源与节点','阶段投资约束','概率约束模型','配置后时序复核']}}
const definition=computed(()=>definitions[props.module]);
</script>
<template><template v-if="definition"><div class="metrics"><article v-for="card in definition.cards"><span>{{card}}</span><strong>—</strong><small>等待算法结果</small></article></div><article><h3>{{tab}} / 结果工作区</h3><div class="scroll"><table><tr><th v-for="column in definition.columns">{{column}}</th></tr><tr><td :colspan="definition.columns.length" class="empty-cell">尚无计算记录。完成算法接入后，此处展示与当前工程和场景绑定的结果。</td></tr></table></div></article><article><h3>计算与校核准备</h3><table><tr><th>项目</th><th>状态</th></tr><tr v-for="check in definition.checks"><td>{{check}}</td><td><span class="pending">待接入 / 待验证</span></td></tr></table><p>当前页可维护参数草稿。已接通的课题2简化规划与真实时序复核在配置页面下方操作。</p></article></template></template>
<style scoped>.empty-cell{text-align:center;padding:40px;color:#859ba0}.pending{background:#f0f3f5;padding:5px 9px;border-radius:5px;color:#6b8188}.scroll{overflow:auto}.metrics strong{color:#a4babc}</style>
