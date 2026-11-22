const fs=require('fs');let s=fs.readFileSync('frontend/src/StrategyWorkspace.vue','utf8');
s=s.replace("import {ref,watch} from 'vue';","import {ref,watch,computed} from 'vue';");
s=s.replace("const comparison=ref<any>(null);", "const comparison=ref<any>(null);let generation=0;const comparisonSnapshot=ref('');const parametersFingerprint=()=>JSON.stringify({parameters:parameters.value,wind:wind.value,pv:pv.value});const comparisonStale=computed(()=>!!comparison.value&&comparisonSnapshot.value!==parametersFingerprint());");
s=s.replace("watch(()=>props.result?.id,()=>{parameters.value=", "watch(()=>props.result?.id,()=>{generation++;parameters.value=");
s=s.replace("watch([parameters,wind,pv],()=>{comparison.value=null},{deep:true});",'');
s=s.replace('async function calculate(){commitSettings(false);', "async function calculate(){commitSettings(false);const request=++generation;const baseline=props.result?.id;const snapshot=parametersFingerprint();");
s=s.replace('comparison.value=data}catch(e){error.value=String(e)}finally{busy.value=false;finishProgress()}', "if(request===generation&&props.result?.id===baseline){comparison.value=data;comparisonSnapshot.value=snapshot}}catch(e){if(request===generation)error.value=String(e)}finally{if(request===generation)busy.value=false;finishProgress()}");
s=s.replace('<template v-if="comparison"><p id="strategy-comparison">','<template v-if="comparison"><p v-if="comparisonStale" class="notice">调整参数已变化，下方保留上次归档的对比结果；重新复算后更新。</p><p id="strategy-comparison">');
fs.writeFileSync('frontend/src/StrategyWorkspace.vue',s);
