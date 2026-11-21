<script setup lang="ts">
import {computed,ref,watch} from 'vue';
import AnalysisChart from './AnalysisChart.vue';
import InvestmentWorkspace from './InvestmentWorkspace.vue';
const props=defineProps<{projectId:string;section:string}>();
const context=ref<any>({});const tab=ref('配置总览');const editor=ref('');const editorSection=ref('候选资源');
const tabs=['配置总览','容量方案','保供效果','经济分析'];
const job=computed(()=>context.value.job);const result=computed(()=>job.value?.result);
const assets=computed(()=>result.value?.selected_assets||[]);
const compliance=computed(()=>result.value?.compliance||[]);
const cashflows=computed(()=>result.value?.cashflows||[]);
const label=(x:any)=>`${x.asset_id} · ${x.commission_year}`;
const capacity=computed(()=>[{name:'选定功率',type:'bar',data:assets.value.map((x:any)=>x.power_kw==null?null:x.power_kw/1000)}]);
const energy=computed(()=>[{name:'选定储能能量',type:'bar',data:assets.value.filter((x:any)=>x.energy_kwh!=null).map((x:any)=>x.energy_kwh/1000)}]);
const effect=computed(()=>[{name:'模型实际达标权重',type:'bar',data:compliance.value.map((x:any)=>x.actual_probability==null?null:100*x.actual_probability)},{name:'要求权重',data:compliance.value.map((x:any)=>x.required_probability==null?null:100*x.required_probability)}]);
const costs=computed(()=>[['投资','capex_yuan'],['维护','annual_maintenance_yuan'],['预期运行','expected_operating_yuan'],['期末残值','terminal_salvage_yuan']].map(([name,key])=>({name,type:'bar',data:cashflows.value.map((x:any)=>x[key]==null?null:x[key]/10000)})));
function open(section:string){editorSection.value=section;editor.value=section}
watch(()=>props.projectId,()=>{context.value={};tab.value='配置总览';editor.value=''});
watch(()=>props.section,(section)=>{if(section==='配置结果'){editor.value='';tab.value='配置总览'}else open(section)});
const money=(x:any)=>typeof x==='number'?(x/10000).toFixed(2)+' 万元':'—';
</script>
<template>
<div class="configuration-console">
 <div class="config-actions"><strong>源储协同配置</strong><button @click="open('候选资源')">候选资源</button><button @click="open('目标与约束')">目标与约束</button><button @click="open('规划阶段')">规划阶段</button><button @click="open('配置结果')">任务与详细结果</button><details><summary>研究草稿</summary><button @click="open('一二次协同规划')">一二次协同规划</button><button @click="open('灵活组网')">灵活组网</button></details></div>
 <nav class="fixed-tabs" aria-label="配置结果视图"><button v-for="t in tabs" :key="t" :class="{active:tab===t}" @click="tab=t;editor=''">{{t}}</button></nav>
 <div v-if="!editor">
  <p class="config-context">{{job?`任务 ${job.id} · 状态 ${job.status} · 台账版本 ${job.input?.parameters?.base?.engineering_revision??'—'}`:'尚未选择配置任务'}}<span v-if="job"> · 输入摘要 {{job.input_sha256||'—'}}</span></p>
  <div class="config-metrics"><article><small>选定资源</small><strong>{{result?assets.length:'—'}}</strong></article><article><small>目标折现成本</small><strong>{{money(result?.objective_yuan)}}</strong></article><article><small>模型相对间隙</small><strong>{{typeof result?.solver?.verified_relative_gap==='number'?(100*result.solver.verified_relative_gap).toFixed(3)+'%':'—'}}</strong></article></div>
  <p v-if="!result" class="notice">当前任务没有可展示的配置结果。通过“候选资源”设置方案并提交，或在“任务与详细结果”选择历史任务。</p>
  <div v-if="result" class="config-grid">
   <AnalysisChart :zoom="false" v-if="['配置总览','容量方案'].includes(tab)" title="资源配置功率" :labels="assets.map(label)" :series="capacity" unit="MW" :min="0"/>
   <AnalysisChart :zoom="false" v-if="['配置总览','容量方案'].includes(tab)" title="储能配置能量" :labels="assets.filter((x:any)=>x.energy_kwh!=null).map(label)" :series="energy" unit="MWh" :min="0"/>
   <AnalysisChart :zoom="false" v-if="['配置总览','保供效果'].includes(tab)" title="分阶段保供达标权重" :labels="compliance.map((x:any)=>`${x.stage_name} ${x.year}—${x.end_year-1}`)" :series="effect" unit="%" :min="0" :max="100"/>
   <AnalysisChart :zoom="false" v-if="['配置总览','经济分析'].includes(tab)" title="年度经济成本构成" :labels="cashflows.map((x:any)=>String(x.year))" :series="costs" unit="万元"/>
  </div>
  <p v-if="result" class="config-context">图形来自同一任务的冻结结果；模型达标权重不替代样本外验证。完整判据、样本外验证与证书可在任务明细中查看。查看方案不会覆盖工程台账。</p>
 </div>
 <div v-if="editor" class="document-toolbar"><strong>{{editor}} · 配置工作文档</strong><button @click="editor=''">收起并返回总览</button><span>收起保留当前参数；提交后冻结为独立任务。</span></div>
 <div v-show="editor"><InvestmentWorkspace :project-id="projectId" :section="editorSection" @context="context=$event"/></div>
</div>
</template>
<style scoped>
.configuration-console{padding:14px 0}.config-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.config-actions strong{margin-right:auto}.fixed-tabs{display:flex;gap:6px;margin:14px 0;border-bottom:1px solid #e4e9f0}.fixed-tabs button{width:auto!important;padding:9px 16px}.fixed-tabs .active{color:#245fd6!important;border-bottom:2px solid #245fd6!important}.config-context{font-size:12px;color:#6c7e96;overflow-wrap:anywhere}.config-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:12px 0}.config-metrics small{display:block;color:#6c7e96}.config-metrics strong{display:block;font-size:21px;margin-top:6px}.config-grid{display:grid;grid-template-columns:1.5fr 1fr;gap:14px}.document-toolbar{display:flex;align-items:center;gap:14px;padding:14px;background:white;border:1px solid #e4e9f0}.document-toolbar span{font-size:12px;color:#6c7e96}@media(max-width:950px){.config-grid{grid-template-columns:1fr}}
</style>
