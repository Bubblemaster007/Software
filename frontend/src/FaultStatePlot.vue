<script setup lang="ts">
import {computed,ref} from 'vue';
const props=defineProps<{states:any[]}>();const offset=ref(0);
const times=computed(()=>[...new Set(props.states.map(s=>String(s.timestamp)))].sort());
const devices=computed(()=>[...new Set(props.states.map(s=>String(s.device_id)))]);
const shownTimes=computed(()=>times.value.slice(offset.value,offset.value+48));
const lookup=computed(()=>new Map(props.states.map(s=>[s.device_id+'|'+s.timestamp,s])));
const colors:Record<string,string>={normal:'#4685ce',failed:'#f18b37',derated:'#edc65b',recovery:'#80b9a6'};
</script>
<template><div class="fault-plot"><div class="plot-controls"><h3>设备故障状态</h3><span>正常 ● 蓝　故障 ● 橙　降额 ● 黄　恢复 ● 绿</span><button :disabled="offset===0" @click="offset=Math.max(0,offset-48)">上一时段</button><button :disabled="offset+48>=times.length" @click="offset+=48">下一时段</button></div><p v-if="!states.length">尚无已生成设备状态，请选择已保存场景或打开场景设置生成。</p><div v-else class="heat-scroll"><svg :viewBox="`0 0 1100 ${100+devices.length*38}`" role="img" aria-label="实际场景设备逐时故障状态热力图"><text x="20" y="25">设备</text><g v-for="(id,i) in devices" :key="id"><text x="10" :y="57+i*38" font-size="13">{{id}}</text><g v-for="(time,j) in shownTimes" :key="time"><rect :x="130+j*940/shownTimes.length" :y="35+i*38" :width="940/shownTimes.length" height="38" :fill="colors[lookup.get(id+'|'+time)?.state]||'#e7ebf0'" stroke="white" stroke-width=".6"><title>{{id}} · {{time}} · {{lookup.get(id+'|'+time)?.state||'无记录'}} · {{lookup.get(id+'|'+time)?.available_kw??'—'}} kW</title></rect></g></g><text x="130" :y="65+devices.length*38" font-size="12">{{shownTimes[0]}}</text><text x="1070" :y="65+devices.length*38" font-size="12" text-anchor="end">{{shownTimes[shownTimes.length-1]}}</text></svg></div><p>实际场景输出，每页最多48个时间点；空白表示未记录，不视为正常。</p></div></template>
<style scoped>.fault-plot{background:white;padding:20px;min-height:420px}.plot-controls{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.plot-controls h3{margin-right:auto}.plot-controls span,p{font-size:12px;color:#5b6c83}.heat-scroll{overflow:auto;margin-top:35px}svg{width:100%;min-width:700px;max-height:620px}text{fill:#263d59}</style>
