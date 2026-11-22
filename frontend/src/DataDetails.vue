<script setup lang="ts">
import {computed,ref,watch} from 'vue';
const props=defineProps<{rows:any[]}>();const page=ref(0),size=48;
const columns=computed(()=>Object.keys(props.rows[0]||{}));
const names:Record<string,string>={timestamp:'时间',load_kw:'负荷 / kW',wind_kw:'风电 / kW',pv_kw:'光伏 / kW',load_served_kw:'供电 / kW',power_deficit_kw:'缺供 / kW',soc:'SOC（比例）'};
watch(()=>props.rows,()=>page.value=0);
</script>
<template><p v-if="!rows.length">当前对象没有明细数据。</p><template v-else><div class="actions"><span>共 {{rows.length}} 行 · 第 {{page+1}} / {{Math.ceil(rows.length/size)}} 页</span><button @click="page--" :disabled="page===0">上一页</button><button @click="page++" :disabled="(page+1)*size>=rows.length">下一页</button></div><table><thead><tr><th v-for="c in columns">{{names[c]||c}}</th></tr></thead><tbody><tr v-for="(row,i) in rows.slice(page*size,(page+1)*size)" :key="page*size+i"><td v-for="c in columns">{{row[c]??'未记录'}}</td></tr></tbody></table></template></template>
