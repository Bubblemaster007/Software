<script setup lang="ts">
import {computed} from 'vue';
const value=defineModel<number[]>({required:true});const props=defineProps<{lines:any[];disabled?:boolean;search?:string}>();
const available=computed(()=>props.lines.filter(l=>l.status===1));
const shown=computed(()=>available.value.filter(l=>!props.search||String(l.line).includes(props.search)||String(l.name||'').includes(props.search)));
function toggle(id:number){value.value=value.value.includes(id)?value.value.filter(n=>n!==id):[...value.value,id]}
</script>
<template><div class="fault-picker"><p>已选 {{value.length}} 处故障 <button @click="value=[]" :disabled="disabled||!value.length">清除故障</button></p><label v-for="l in shown" :key="l.line"><input type="checkbox" :checked="value.includes(l.line)" @change="toggle(l.line)" :disabled="disabled">{{l.name||'线路'+l.line}} · {{l.from_node}} → {{l.to_node}}</label><p v-if="value.some(id=>!available.some(l=>l.line===id))" class="error">存在已删除或停运的故障线路，请清除后重新设置。</p></div></template>
<style scoped>.fault-picker{max-height:240px;overflow:auto}.fault-picker label{display:inline-flex;align-items:center;gap:5px;margin:6px 15px 6px 0}.fault-picker input{width:auto}</style>
