<script setup lang="ts">
import {computed,ref} from 'vue';
import AnalysisChart from './AnalysisChart.vue';
import FaultStatePlot from './FaultStatePlot.vue';
const props=defineProps<{csv:string;condition:string;eventCsv?:string;scenario?:any}>();
const tab=ref('场景总览');const range=ref<[number,number]>([0,100]);
function parse(csv:string){return csv.trim().split(/\r?\n/).slice(1).filter(l=>l.trim()).map(l=>{const [timestamp,load,wind,pv]=l.split(',');return {timestamp,load:Number(load),wind:Number(wind),pv:Number(pv)}})}
const rows=computed(()=>parse(props.csv));const eventRows=computed(()=>parse(props.eventCsv||''));
function series(data:ReturnType<typeof parse>){return [['负荷','load'],['风电','wind'],['光伏','pv']].map(([name,key])=>({name,data:data.map(r=>Number.isFinite((r as any)[key])?(r as any)[key]:null)}))}
const states=computed(()=>props.scenario?.states||[]);
</script>
<template><div class="scenario-overview"><nav class="fixed-tabs" aria-label="场景图形视图"><button v-for="name in ['场景总览','年度时序','极端片段','故障状态']" :key="name" :class="{active:tab===name}" @click="tab=name">{{name}}</button></nav><div class="scenario-grid"><AnalysisChart v-if="['场景总览','年度时序'].includes(tab)" title="背景源荷时序" :labels="rows.map(r=>r.timestamp)" :series="series(rows)" unit="kW" :range="range" @range="range=$event"/><AnalysisChart v-if="['场景总览','极端片段'].includes(tab)" title="选定极端片段（原事件时间轴）" :labels="eventRows.map(r=>r.timestamp)" :series="series(eventRows)" unit="kW"/><article v-if="['场景总览','故障状态'].includes(tab)" class="fault-panel"><h3>已选场景设备状态</h3><FaultStatePlot :states="states"/><p v-if="!states.length">请在下方场景选择器加载已保存场景，或配置并生成故障状态。</p></article><article v-if="tab==='场景总览'" class="scenario-summary"><h3>当前场景上下文</h3><p>运行工况：{{condition}}（配置引导）</p><p>背景：{{rows.length}} 个逐时时段</p><p>极端片段：{{eventRows.length?eventRows.length+' 个时段':'尚未选定'}}</p><p>故障场景：{{scenario?.name||'尚未选择'}}</p><p>场景标识：{{scenario?.id||'—'}}</p><p>生成结果由原接口保存；应用需明确点击下方“应用当前场景”。</p></article></div></div></template>
<style scoped>
.scenario-overview{padding:14px 0}.fixed-tabs{display:flex;gap:12px;border-bottom:1px solid #e4e9f0;margin-bottom:14px}.fixed-tabs button{border:0;border-radius:0!important;background:transparent!important;padding:10px;border-bottom:2px solid transparent}.fixed-tabs button.active{color:#245fd6!important;border-bottom-color:#245fd6}.scenario-grid{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:14px}.scenario-grid article{margin:0!important;min-width:0}.scenario-grid h3{font-size:15px}.scenario-summary p,.fault-panel p{font-size:12px;color:#71819a}
</style>
