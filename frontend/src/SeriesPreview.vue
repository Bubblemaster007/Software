<script setup lang="ts">
import {computed,ref} from 'vue';
import {inspectTimeSeries} from './timeSeries';
const props=defineProps<{csv:string}>();
const range=ref('all');const start=ref(1);
const check=computed(()=>inspectTimeSeries(props.csv));
const rows=computed(()=>props.csv.trim().split(/\r?\n/).slice(1).filter(v=>v.trim()).map(v=>v.split(',')));
const windowRows=computed(()=>range.value==='all'?rows.value:rows.value.slice(Math.max(0,start.value-1),Math.max(0,start.value-1)+Number(range.value)));
const max=computed(()=>Math.max(1,...windowRows.value.flatMap(r=>r.slice(1).map(Number))));
const curves=computed(()=>[1,2,3].map(col=>{
 const r=windowRows.value;const stride=Math.max(1,Math.ceil(r.length/500));const indices:number[]=[];
 for(let i=0;i<r.length;i+=stride){let lo=i,hi=i;for(let j=i;j<Math.min(i+stride,r.length);j++){if(Number(r[j][col])<Number(r[lo][col]))lo=j;if(Number(r[j][col])>Number(r[hi][col]))hi=j}indices.push(...[...new Set([i,lo,hi,Math.min(i+stride-1,r.length-1)])].sort((a,b)=>a-b))}
 return indices.map(i=>`${50+900*i/Math.max(1,r.length-1)},${210-180*Number(r[i][col])/max.value}`).join(' ');
}));
</script>
<template><div class="series-preview"><h3>{{rows.length===8760?'年度风光荷时序 · 8760小时':'风光荷时序趋势'}}</h3><p>当前输入 {{rows.length}} 小时 · {{rows.length===8760?'8760小时年度序列':'按实际输入长度展示'}} · 功率 kW</p><div class="actions"><label>查看范围 <select v-model="range"><option value="all">{{rows.length===8760?'全年8760小时':'全部时段'}}</option><option value="168">连续一周</option><option value="24">连续一天</option></select></label><label v-if="range!=='all'">起始小时 <input type="number" v-model.number="start" min="1" :max="Math.max(1,rows.length)"></label></div><p v-if="check.totalIssues" class="error">当前数据有 {{check.totalIssues}} 项格式问题，修正后显示曲线。</p><template v-else><svg viewBox="0 0 980 270" preserveAspectRatio="none" role="img" aria-label="负荷、风电、光伏功率时序图"><g v-for="tick in [0,1,2,3,4]" :key="tick"><line x1="50" x2="950" :y1="210-tick*45" :y2="210-tick*45" stroke="#e1e6ee"/><text x="45" :y="214-tick*45" text-anchor="end">{{(max*tick/4).toFixed(0)}}</text></g><text x="50" y="14">功率 / kW</text><path d="M50 25V210H950" fill="none" stroke="#a6bec2"/><polyline v-for="(points,i) in curves" :key="i" :points="points" fill="none" :stroke="['#1764d8','#12a19a','#f28b2b'][i]" stroke-width="1.5"/><g v-for="fraction in [0,.25,.5,.75,1]" :key="fraction"><line :x1="50+900*fraction" :x2="50+900*fraction" y1="210" y2="215" stroke="#a6bec2"/><text :x="50+900*fraction" y="231" :text-anchor="fraction===0?'start':fraction===1?'end':'middle'">第{{Math.round(fraction*Math.max(0,windowRows.length-1))+1}}小时</text></g><text x="50" y="258">{{windowRows[0]?.[0]}}</text><text x="950" y="258" text-anchor="end">{{windowRows[windowRows.length-1]?.[0]}}</text></svg><p><span style="color:#254c77">● 负荷</span>　<span style="color:#16856b">● 风电</span>　<span style="color:#df9b24">● 光伏</span></p><small>全年视图按区间保留各曲线极值；查看一天或一周显示逐小时变化，原始数据不变。</small></template></div></template>
<style scoped>.series-preview{padding:16px;background:#f3f8f8;margin:16px 0}svg{width:100%;max-height:320px}text{font-size:12px;fill:#526e73}input{width:90px}select,input{padding:6px}</style>
