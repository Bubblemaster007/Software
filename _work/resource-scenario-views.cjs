const fs=require('fs');let e=fs.readFileSync('frontend/src/EngineeringWorkspace.vue','utf8');
e=e.replace("import {computed,ref,watch} from 'vue';","import {computed,ref,watch} from 'vue';\nimport AnalysisChart from './AnalysisChart.vue';\nimport EditorSurface from './EditorSurface.vue';");
const extra=`
const isLedger=computed(()=>['电源台账','储能台账','负荷与保供目标','变压器与开关','二次设备与通信'].includes(props.section||''));
const ledgerOpen=ref(false);let ledgerBaseline='';
function openLedger(){ledgerBaseline=JSON.stringify(inventory.value);ledgerOpen.value=true}
function closeLedger(value:boolean){if(!value&&ledgerOpen.value&&ledgerBaseline){inventory.value=JSON.parse(ledgerBaseline);ledgerOpen.value=false}}
const ledgerKeys=computed(()=>Object.keys(visibleGroups.value));
const ledgerRows=computed(()=>ledgerKeys.value.flatMap(k=>(inventory.value?.[k]||[]).map((r:any)=>({...r,groupLabel:groups[k].label}))));
const ledgerPower=computed(()=>ledgerRows.value.map((r:any)=>typeof (r.rated_kw??r.power_kw??r.peak_kw)==='number'?(r.rated_kw??r.power_kw??r.peak_kw)/1000:null));
watch(()=>props.section,()=>{if(ledgerOpen.value)closeLedger(false)});
`;
e=e.replace('</script>',extra+'</script>');
e=e.replace("message.value='台账已校验保存为版本 '+d.revision+'，历史版本保留。'", "message.value='台账已校验保存为版本 '+d.revision+'，历史版本保留。';ledgerOpen.value=false");
e=e.replace('<template><article>',`<template><div v-if="isLedger" class="resource-overview"><div class="actions"><strong>{{section}} · 台账版本 {{revision}}</strong><button @click="openLedger" :disabled="!inventory">打开数据编辑器</button><button @click="download" :disabled="!inventory">导出台账 JSON</button></div><p v-if="message">{{message}}</p><p v-if="!inventory">{{error||'正在读取当前工程台账…'}}</p><template v-else><p>当前 {{ledgerRows.length}} 项设备或负荷。台账与工程运行参数、优化候选资源分别维护。</p><AnalysisChart v-if="ledgerRows.length&&ledgerPower.some(v=>v!==null)" :zoom="false" :title="section+' · 记录功率'" :labels="ledgerRows.map((r:any)=>r.name||r.id)" :series="[{name:'台账记录功率',type:'bar',data:ledgerPower}]" unit="MW"/><AnalysisChart v-if="section==='储能台账'&&ledgerRows.length" :zoom="false" title="储能能量" :labels="ledgerRows.map((r:any)=>r.name||r.id)" :series="[{name:'台账记录能量',type:'bar',data:ledgerRows.map((r:any)=>typeof r.energy_kwh==='number'?r.energy_kwh/1000:null)}]" unit="MWh"/><p v-if="!ledgerRows.length" class="notice">当前台账没有记录；打开编辑器录入真实资源后保存。</p><div class="scroll"><table><tr><th>编号</th><th>名称</th><th>类别</th><th>关联节点</th></tr><tr v-for="r in ledgerRows.slice(0,8)"><td>{{r.id}}</td><td>{{r.name||'未命名'}}</td><td>{{r.groupLabel}}</td><td>{{r.node??'未记录'}}</td></tr></table></div></template></div><EditorSurface :enabled="isLedger" :open="ledgerOpen" :title="section||'台账编辑'" @update:open="closeLedger"><article>`);
e=e.replace('</article></template>','</article><template #footer><button @click="closeLedger(false)">取消</button><button class="primary" @click="save" :disabled="busy||!inventory">校验并保存台账</button></template></EditorSurface></template>');
e=e.replace('<button @click="save" :disabled="busy||!inventory">','<button v-if="!isLedger" @click="save" :disabled="busy||!inventory">');
fs.writeFileSync('frontend/src/EngineeringWorkspace.vue',e);
for(const name of ['SourceStudy','SourceAnalysis','SequenceWorkspace']){
 let s=fs.readFileSync('frontend/src/'+name+'.vue','utf8');s=s.replace('<script setup lang="ts">','<script setup lang="ts">\nimport SeriesPreview from \'./SeriesPreview.vue\';');
 if(name==='SourceStudy'){
  s=s.replace("import {ref,watch} from 'vue';", "import {ref,watch,onBeforeUnmount} from 'vue';");
  s=s.replace('</script>',`const previewCsv=ref('');let previewRequest=0;
watch([selected,horizon],async()=>{const token=++previewRequest;previewCsv.value='';if(!selected.value)return;try{const r=await fetch(url('annual'));if(!r.ok)throw Error('年度背景预览读取失败');const value=await r.text();if(token===previewRequest)previewCsv.value=value.replace(/^\\uFEFF/,'')}catch(e){if(token===previewRequest)error.value=String(e)}});
onBeforeUnmount(()=>{previewRequest++});
</script>`);
  s=s.replace('<h3>已保存研究</h3>','<SeriesPreview :csv="previewCsv||csv"/><details><summary>选择已保存背景研究</summary>').replace('<template v-if="selected"><p>','</details><template v-if="selected"><p>');
 }else if(name==='SourceAnalysis'){
  s=s.replace('<template v-if="result"><p>','<SeriesPreview :csv="result?.extreme_window?.csv||csv"/><template v-if="result"><p>');
 }else{
  s=s.replace('<template v-if="selected"><p>','<SeriesPreview :csv="selected?.csv||csv"/><template v-if="selected"><p>');
 }
 fs.writeFileSync('frontend/src/'+name+'.vue',s);
}
