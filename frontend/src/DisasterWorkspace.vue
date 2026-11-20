<script setup lang="ts">
import {computed,ref,watch,onBeforeUnmount} from 'vue';
import {apiError} from './apiError';
const props=defineProps<{projectId:string;section:string}>();
const project=ref<any>(null),engineering=ref<any>(null),network=ref<any>(null),jobs=ref<any[]>([]),job=ref<any>(null);
const error=ref(''),busy=ref(false);let generation=0,timer:ReturnType<typeof setTimeout>|undefined;
const name=ref('承灾强度与时长扫描'),intensities=ref('0,1,2'),durations=ref('1,4'),grid=ref('1000');
const steps=ref(24),dt=ref(1),eventStart=ref(0),samples=ref(20),seed=ref(2026),probability=ref(.95),confidence=ref(.95);
const criterion=ref('load_targets'),budget=ref(0),judgement=ref('wilson_lower'),wallTime=ref(600);
const advanced=ref('{"initial_energized_nodes":[],"device_availability":{},"line_status":{},"time_limit_seconds":30}');
type Frag={target:string;reference_intensity:number;reference_duration_hours:number;failure_probability:number;shape:number;repair_hours:number;failed_availability:number;common_group:string;provenance:string;weakness:boolean};
const fragilities=ref<Frag[]>([]);
const terminal=new Set(['succeeded','incomplete','failed','cancelled','interrupted']);
const statusNames:Record<string,string>={queued:'排队',running:'计算中',cancel_requested:'等待取消',succeeded:'计算完成',incomplete:'结果不完整',failed:'失败',cancelled:'已取消',interrupted:'中断',passed:'达标',uncertain:'证据不足',unknown:'未判定'};
const caseLabel=(s:string)=>s==='failed'?'未达标':statusNames[s]||s;
const result=computed(()=>job.value?.result);
const activeJob=computed(()=>job.value&&!terminal.has(job.value.status));
const targets=computed(()=>{
 const inv=engineering.value?.inventory;if(!inv)return [];
 return [{key:'grid:grid',name:'外部供电'},...(network.value?.lines||[]).map((a:any)=>({key:'line:'+a.line,name:'线路 '+a.line+' '+(a.name||'')})),
 ...['sources','storage','transformers','switches'].flatMap((k,i)=>(inv[k]||[]).filter((a:any)=>a.existing).map((a:any)=>({key:['source','storage','transformer','switch'][i]+':'+a.id,name:a.name+' ('+a.id+')'})))];
});
async function api(url:string,options?:RequestInit){const r=await fetch(url,options);const d=await r.json();if(!r.ok)throw Error(apiError(d.detail));return d}
function numeric(text:string){const a=text.trim().split(/[,，\s]+/).map(Number);if(!text.trim()||!a.every(Number.isFinite))throw Error('请输入逗号分隔的有限数值');return a}
function add(){fragilities.value.push({target:targets.value[0]?.key||'grid:grid',reference_intensity:1,reference_duration_hours:1,failure_probability:.1,shape:2,repair_hours:4,failed_availability:0,common_group:'',provenance:'用户研究假设，未经地区校准',weakness:false})}
async function refresh(){const g=++generation;clearTimeout(timer);busy.value=false;job.value=null;project.value=null;engineering.value=null;network.value=null;jobs.value=[];fragilities.value=[];error.value='';if(!props.projectId)return;
 try{const [p,e,h]=await Promise.all([api('/api/projects/'+props.projectId),api('/api/engineering/projects/'+props.projectId),api('/api/study-jobs?project_id='+props.projectId)]);const n=p.state.network||await api('/api/network/case33');if(g!==generation)return;project.value=p;engineering.value=e;network.value=n;jobs.value=h.filter((j:any)=>j.module==='disaster_scan');add();if(jobs.value.length)await inspect(jobs.value[0].id)}catch(e){if(g===generation)error.value=String(e)}}
async function poll(id:string,g:number){if(g!==generation)return;try{const d=await api('/api/study-jobs/'+id);if(g!==generation||job.value?.id!==id)return;if(terminal.has(d.status)){const full=await api('/api/study-jobs/'+id+'?include_input=true&include_result=true');if(g!==generation||job.value?.id!==id)return;job.value=full;const h=await api('/api/study-jobs?project_id='+props.projectId);if(g===generation)jobs.value=h.filter((j:any)=>j.module==='disaster_scan')}else{job.value=d;timer=setTimeout(()=>poll(id,g),1200)}}catch(e){if(g===generation){error.value=String(e);timer=setTimeout(()=>poll(id,g),3000)}}}
async function inspect(id:string){clearTimeout(timer);const g=generation;try{const d=await api('/api/study-jobs/'+id+'?include_input=true&include_result=true');if(g!==generation||d.project_id!==props.projectId)return;job.value=d;if(!terminal.has(d.status))timer=setTimeout(()=>poll(id,g),500)}catch(e){if(g===generation)error.value=String(e)}}
async function submit(){const g=generation;busy.value=true;error.value='';try{if(!engineering.value?.revision||!project.value)throw Error('请先保存本工程的设备及负荷台账');const extra=JSON.parse(advanced.value);if(!extra||Array.isArray(extra)||typeof extra!=='object')throw Error('调度参数须为JSON对象');const base={...extra,project_id:props.projectId,project_revision:project.value.revision,engineering_revision:engineering.value.revision,name:name.value,steps:steps.value,step_hours:dt.value,grid_available_kw:numeric(grid.value)};
 const f=fragilities.value.map(({target,weakness,...values})=>{const split=target.indexOf(':');return {...values,kind:target.slice(0,split),target_id:target.slice(split+1)}});
 const parameters={base,name:name.value,intensities:numeric(intensities.value),durations_hours:numeric(durations.value),event_start_step:eventStart.value,samples:samples.value,seed:seed.value,fragilities:f,criterion:criterion.value,maximum_unsupplied_kwh:budget.value,required_success_probability:probability.value,confidence:confidence.value,judgement:judgement.value,wall_time_seconds:wallTime.value,weakness_targets:fragilities.value.filter(f=>f.weakness).map(f=>f.target)};
 const d=await api('/api/study-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({module:'disaster_scan',parameters})});if(g!==generation)return;job.value=d;jobs.value=[d,...jobs.value];timer=setTimeout(()=>poll(d.id,g),300)}catch(e){if(g===generation)error.value=String(e)}finally{if(g===generation)busy.value=false}}
async function cancel(){const id=job.value?.id,g=generation;if(!id)return;try{const d=await api('/api/study-jobs/'+id+'/cancel',{method:'POST'});if(g===generation&&job.value?.id===id){job.value=d;clearTimeout(timer);timer=setTimeout(()=>poll(id,g),200)}}catch(e){if(g===generation)error.value=String(e)}}
async function retry(){const id=job.value?.id,g=generation;busy.value=true;try{const d=await api('/api/study-jobs/'+id+'/retry',{method:'POST'});if(g===generation){job.value=d;jobs.value=[d,...jobs.value];timer=setTimeout(()=>poll(d.id,g),200)}}catch(e){if(g===generation)error.value=String(e)}finally{if(g===generation)busy.value=false}}
watch(()=>props.projectId,refresh,{immediate:true});onBeforeUnmount(()=>{++generation;clearTimeout(timer)});
const fmt=(n:any,d=3)=>typeof n==='number'?n.toFixed(d):'—';
</script>
<template>
<article><h3>承灾极限分析 · {{section}}</h3><p>按强度与持续时长抽样设备故障，逐场景调用实际多节点源储MILP。参考概率和共因相关结构须有来源；当前为用户参数下的条件研究，边界限于已扫描范围，动态稳定、涌流与通信未校核。</p><p v-if="error" class="error">{{error}}</p>
 <div class="actions"><button @click="refresh" :disabled="busy">重新读取输入与任务</button><span>工程版本 {{project?.revision||'—'}} / 台账版本 {{engineering?.revision||0}} / 当前最多2个后台研究任务</span></div>
 <template v-if="section==='分析设置'">
 <div class="fields">
 <label>任务名称<input v-model="name"></label><label>时间步 / h<select v-model.number="dt"><option :value=".25">0.25</option><option :value=".5">0.5</option><option :value="1">1</option></select></label>
 <label>总步数<input type="number" v-model.number="steps" min="1" max="672"></label><label>事件起始步（从0计）<input type="number" v-model.number="eventStart" min="0"></label>
 <label>扫描强度<input v-model="intensities" placeholder="0,1,2"></label><label>事件时长 / h<input v-model="durations" placeholder="1,4"></label>
 <label>外部供电 / kW<input v-model="grid" placeholder="单值或逐步容量"></label><label>每个工况样本数<input type="number" v-model.number="samples" min="1" max="1000"></label>
 <label>随机种子<input type="number" v-model.number="seed" min="0" max="4294967295"></label><label>任务总时限 / s<input type="number" v-model.number="wallTime" min="1" max="3600"></label>
 <label>成功判据<select v-model="criterion"><option value="load_targets">逐负荷分类目标</option><option value="energy_budget">总未供电量预算</option></select></label><label v-if="criterion==='energy_budget'">未供电量上限 / kWh<input type="number" v-model.number="budget" min="0"></label>
 <label>要求成功概率<input type="number" v-model.number="probability" min="0.001" max="1" step=".01"></label><label>置信度<input type="number" v-model.number="confidence" min=".501" max=".999" step=".01"></label>
 <label>判定方法<select v-model="judgement"><option value="wilson_lower">Wilson置信下界</option><option value="empirical">经验成功比例（研究）</option></select></label>
 </div><p>小样本即使全部成功，置信下界仍可能不足；“证据不足”不能当作已证明失败。逐负荷目标需要足够时域；时间步、曲线长度和故障恢复须一致。总时域最长168h，扫描与设备对照合计最多5000次调度。</p>
 <h4>设备脆弱性参数</h4><p>参考概率指指定强度、参考持续时长内的条件失效概率；强度0时不触发本机制。共因组为空时独立，同组共享随机冲击。修复向上对齐时间步，未修复故障可延续到灾害结束之后。</p>
 <div class="scroll"><table><thead><tr><th>目标</th><th>参考强度</th><th>参考时长 h</th><th>参考概率</th><th>形状</th><th>修复 h</th><th>失效后可用率</th><th>共因组</th><th>参数来源</th><th>薄弱性对照</th><th></th></tr></thead><tbody><tr v-for="(f,i) in fragilities" :key="i">
 <td><select v-model="f.target"><option v-for="t in targets" :value="t.key">{{t.name}}</option></select></td>
 <td><input type="number" v-model.number="f.reference_intensity" min=".001" step=".1"></td><td><input type="number" v-model.number="f.reference_duration_hours" min=".01" step=".25"></td>
 <td><input type="number" v-model.number="f.failure_probability" min="0" max="1" step=".01"></td><td><input type="number" v-model.number="f.shape" min=".01" max="10" step=".1"></td>
 <td><input type="number" v-model.number="f.repair_hours" min=".01" step=".25"></td><td><input type="number" v-model.number="f.failed_availability" min="0" max="1" step=".1"></td>
 <td><input v-model="f.common_group"></td><td><input v-model="f.provenance"></td><td><input type="checkbox" v-model="f.weakness"></td><td><button @click="fragilities.splice(i,1)">移除</button></td></tr></tbody></table></div>
 <button @click="add">添加脆弱性目标</button><p>勾选对照后，在最大扫描强度和最大持续时长下，逐个移除目标脆弱性机制并复算；其他冲击和原有检修保持一致。线路/开关失效后可用率只允许0或1。</p>
 <details><summary>调度高级参数 JSON：曲线、基准故障、燃料与构网条件等</summary><p>覆盖DispatchInput中除工程版本、名称、步数、时间步、外部供电以外的字段。负荷和源储曲线来自已保存台账，不会隐式截取或重采样。</p><textarea v-model="advanced" rows="8" spellcheck="false"></textarea></details>
 <button class="primary" @click="submit" :disabled="busy||!engineering?.revision">{{busy?'正在提交…':'冻结输入并提交后台扫描'}}</button>
 </template>
</article>
<article v-if="job"><h3>任务 {{job.name}} · {{statusNames[job.status]||job.status}}</h3><p>{{job.id}} · 输入摘要 {{job.input_sha256}}</p>
 <p v-if="job.input">本档案判据：{{job.input.parameters.criterion==='energy_budget'?'总未供电量 ≤ '+job.input.parameters.maximum_unsupplied_kwh+' kWh':'逐负荷分类目标'}}；{{job.input.parameters.judgement==='empirical'?'经验成功比例':'Wilson置信下界'}} ≥ {{job.input.parameters.required_success_probability}}；置信度 {{job.input.parameters.confidence}}；每工况样本 {{job.input.parameters.samples}}，种子 {{job.input.parameters.seed}}。表格和结论取自冻结参数。</p>
 <progress :value="job.progress?.fraction||0" max="1"></progress><p>{{job.progress?.phase}} · 已完成 {{job.progress?.completed||0}} / {{job.progress?.total||'—'}} · 当前强度 {{job.progress?.intensity??'—'}} · 时长 {{job.progress?.duration_hours??'—'}} h</p>
 <p v-if="job.error" class="error">{{job.error}}</p><p v-if="activeJob">取消会在建模或当前有界MILP调用结束后生效，单次调度上限最多120秒；刷新或离开页面不会停止后台任务。</p>
 <div class="actions"><button v-if="activeJob" @click="cancel" :disabled="job.status==='cancel_requested'">请求取消</button><button v-else @click="retry" :disabled="busy">用冻结输入新建重试</button><a :href="'/api/study-jobs/'+job.id+'/download'">下载完整输入与结果 JSON</a><a :href="'/api/study-jobs/'+job.id+'/log'" target="_blank">工作日志</a><a v-if="result" :href="'/api/study-jobs/'+job.id+'/csv'">样本台账 CSV</a></div>
 <template v-if="result">
 <p>已计算 {{result.completed_solves}} / {{result.requested_solves}} 次；{{fmt(result.runtime_seconds,2)}} s。{{result.status==='complete'?'扫描任务结束，达标结论见各工况。':result.status==='incomplete_time_limit'?'达到任务时限，未测项保留未知。':'存在求解未完成或目标未完整校核项，不可认定全部完成。'}}</p>
 <template v-if="section!=='薄弱环节'"><h4>已测承灾边界</h4><div class="scroll"><table><tr><th>事件时长 h</th><th>已测达标强度集合</th><th>最大已测达标强度</th><th>右侧未封闭</th><th>非单调</th></tr><tr v-for="b in result.boundaries"><td>{{b.duration_hours}}</td><td>{{b.tested_feasible_intensities.join(', ')||'无达标证据'}}</td><td>{{b.maximum_tested_feasible_intensity??'—'}}</td><td>{{b.right_censored?'是，不能外推更大极限':'否/未证明'}}</td><td>{{b.nonmonotone?'是，保留离散可行区间':'未发现'}}</td></tr></table></div>
 <h4>工况判定与置信区间</h4><div class="scroll"><table><tr><th>强度</th><th>时长 h</th><th>完成/计划</th><th>成功/失败/未知</th><th>保守/乐观成功比例</th><th>Wilson保守区间</th><th>平均未供电 kWh</th><th>结论</th></tr><tr v-for="c in result.cases"><td>{{c.intensity}}</td><td>{{c.duration_hours}}</td><td>{{c.completed}}/{{c.requested}}</td><td>{{c.successes}}/{{c.failures}}/{{c.unknown}}</td><td>{{fmt(c.success_fraction_lower)}} / {{fmt(c.success_fraction_upper)}}</td><td>{{c.wilson_conservative.map((v:number)=>v.toFixed(3)).join(' — ')}}</td><td>{{fmt(c.mean_unsupplied_kwh)}}</td><td>{{caseLabel(c.judgement)}}</td></tr></table></div></template>
 <h4>设备薄弱性对照</h4><p>正值表示移除该故障机制后减少未供电量；负值保留。只有两次调度均完成分层优化的配对进入排序。排序针对指定工况和调度策略，不代表所有灾种的通用重要度。</p>
 <div class="scroll" v-if="result.weakness.length"><table><tr><th>目标</th><th>强度 / 时长h</th><th>可靠配对/计划</th><th>平均避免未供电 kWh</th><th>标准误 kWh</th><th>状态</th></tr><tr v-for="w in result.weakness"><td>{{w.target}}</td><td>{{w.intensity}} / {{w.duration_hours}}</td><td>{{w.reliable_pairs}}/{{w.requested_pairs}}</td><td>{{fmt(w.mean_avoided_unsupplied_kwh)}}</td><td>{{fmt(w.standard_error_kwh)}}</td><td>{{w.status==='complete'?'完整':'不完整'}}</td></tr></table></div><p v-else>本任务未选择设备对照。</p>
 <details><summary>模型边界与最差样本轨迹</summary><p v-for="line in result.scope">{{line}}</p><pre>{{JSON.stringify(result.worst_trace,null,2)}}</pre></details>
 </template></article>
<article><h3>本工程扫描任务档案</h3><p v-if="!jobs.length">尚无扫描任务。</p><button class="record" v-for="j in jobs" :key="j.id" @click="inspect(j.id)">{{j.name}} · {{statusNames[j.status]||j.status}} · {{new Date(j.created*1000).toLocaleString()}}</button></article>
</template>
<style scoped>
.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px;margin:20px 0}.fields label{display:flex;justify-content:space-between;align-items:center;gap:12px}.fields input,.fields select{width:210px}input,select{padding:7px;border:1px solid #c8dcdf;max-width:100%}.actions{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:16px 0}.scroll{overflow:auto;max-height:480px;margin:16px 0}td input{width:95px}td select{width:200px}td input[type=checkbox]{width:20px}td:nth-child(9) input{width:220px}td,th{white-space:nowrap}textarea{width:100%;box-sizing:border-box;font-family:monospace}details{margin:20px 0}pre{max-height:400px;overflow:auto}progress{width:100%;height:18px}.record{display:block;margin:12px 0}.primary{margin:24px 0}@media(max-width:1050px){.fields{grid-template-columns:1fr}}
</style>
