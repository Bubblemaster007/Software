<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue';
import { apiError } from './apiError';

const props = defineProps<{ projectId: string; parameters: any }>();
defineEmits(['load-baseline']);
const plotSet = ref('training');
const levels = ref('.8,.9,.95,1');
const sensitivity = ref('[]');
const variations = ref<{name: string; parameter: string; value: number}[]>([]);
const wall = ref(600);
const perCase = ref(120);
const error = ref('');
const busy = ref(false);
const jobs = ref<any[]>([]);
const job = ref<any>(null);
const detail = ref<any>(null);
const traceIndex = ref(0);
let generation = 0;
let selection = 0;
let detailSelection = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
const terminal = new Set(['succeeded', 'incomplete', 'failed', 'cancelled', 'interrupted']);
const names: Record<string, string> = {
  complete: '已计算', infeasible: '不可行', incomplete_solve: '求解未完',
  incomplete_validation: '验证未完', not_run_time_limit: '总时限内未运行',
  passed: '通过', failed: '失败', not_checked: '未校核', queued: '排队',
  running: '计算中', cancel_requested: '等待取消', cancelled: '已取消',
  interrupted: '已中断', succeeded: '计算结束', incomplete: '未完整',
  baseline: '基准', risk: '概率扫描', sensitivity: '单因素',
};
const parameterNames: Record<string, string> = {
  required_probability: '保供概率', load_scale: '阶段负荷倍率',
  capital_cost_scale: '资本成本倍率', annual_maintenance_scale: '年维护倍率',
  fuel_price_scale: '燃料单价倍率', discount_rate: '绝对折现率',
  storage_temperature_factor: '绝对储能有效系数',
};
const result = computed(() => job.value?.result);
const active = computed(() => job.value && !terminal.has(job.value.status));
const points = computed(() => (result.value?.cases || [])
  .map((item: any) => ({
    ...item,
    plot_probability: plotSet.value === 'training'
      ? item.training_success_probability : item.validation_success_probability_lower,
  }))
  .filter((item: any) => item.kind !== 'sensitivity'
    && typeof item.objective_yuan === 'number' && typeof item.plot_probability === 'number'));
const maxCost = computed(() => Math.max(1, ...points.value.map((item: any) => item.objective_yuan)));
const trace = computed(() => detail.value?.result?.scenario_results?.[traceIndex.value]);
const fmt = (value: any, decimals = 3) => typeof value === 'number' ? value.toFixed(decimals) : '—';

function addVariation() {
  variations.value.push({name: '敏感性' + (variations.value.length + 1), parameter: 'capital_cost_scale', value: 1.1});
}

function changeParameter(item: {parameter: string; value: number}) {
  if (item.parameter === 'discount_rate') item.value = props.parameters?.discount_rate ?? .06;
  else if (item.parameter === 'storage_temperature_factor') item.value = .8;
  else item.value = 1.1;
}

function importVariations() {
  try {
    const parsed = JSON.parse(sensitivity.value);
    if (!Array.isArray(parsed) || parsed.length > 12) throw Error('请提供最多12项的参数数组');
    const allowed = Object.keys(parameterNames).filter(key => key !== 'required_probability');
    const imported = parsed.map((item, index) => {
      if (!allowed.includes(item.parameter) || typeof item.value !== 'number' || !Number.isFinite(item.value)) {
        throw Error('第' + (index + 1) + '项的因素或参数值无效');
      }
      return {name: item.name || '敏感性' + (index + 1), parameter: item.parameter, value: item.value};
    });
    variations.value = imported;
    error.value = '';
  } catch (exception) {
    error.value = String(exception);
  }
}

async function api(path: string, options?: RequestInit) {
  const response = await fetch('/api/study-jobs' + path, options);
  const data = await response.json();
  if (!response.ok) throw Error(apiError(data.detail));
  return data;
}

async function refresh() {
  const currentGeneration = ++generation;
  ++selection;
  ++detailSelection;
  clearTimeout(timer);
  job.value = null;
  detail.value = null;
  jobs.value = [];
  error.value = '';
  busy.value = false;
  if (!props.projectId) return;
  try {
    const rows = await api('?project_id=' + props.projectId);
    if (currentGeneration !== generation) return;
    jobs.value = rows.filter((item: any) => item.module === 'investment_experiments');
    if (jobs.value.length) await inspect(jobs.value[0].id);
  } catch (exception) {
    if (currentGeneration === generation) error.value = String(exception);
  }
}

async function inspect(id: string) {
  const currentGeneration = generation;
  const currentSelection = ++selection;
  ++detailSelection;
  clearTimeout(timer);
  detail.value = null;
  try {
    const data = await api('/' + id + '?include_input=true&include_result=true');
    if (currentGeneration !== generation || currentSelection !== selection
      || data.project_id !== props.projectId) return;
    job.value = data;
    if (!terminal.has(data.status)) timer = setTimeout(() => poll(id, currentGeneration, currentSelection), 500);
  } catch (exception) {
    if (currentGeneration === generation && currentSelection === selection) error.value = String(exception);
  }
}

async function poll(id: string, currentGeneration: number, currentSelection: number) {
  if (currentGeneration !== generation || currentSelection !== selection) return;
  try {
    const data = await api('/' + id + '?include_result=true');
    if (currentGeneration !== generation || currentSelection !== selection) return;
    job.value = data;
    if (!terminal.has(data.status)) {
      timer = setTimeout(() => poll(id, currentGeneration, currentSelection), 1200);
    } else {
      const history = await api('?project_id=' + props.projectId);
      if (currentGeneration === generation && currentSelection === selection) {
        jobs.value = history.filter((item: any) => item.module === 'investment_experiments');
      }
    }
  } catch (exception) {
    if (currentGeneration === generation && currentSelection === selection) {
      error.value = String(exception);
      timer = setTimeout(() => poll(id, currentGeneration, currentSelection), 3000);
    }
  }
}

async function submit() {
  const currentGeneration = generation;
  const currentSelection = ++selection;
  busy.value = true;
  error.value = '';
  clearTimeout(timer);
  try {
    if (!props.parameters || props.parameters.base.project_id !== props.projectId) {
      throw Error('请先载入当前配置参数作为基准');
    }
    const probabilityLevels = levels.value.split(/[,，\s]+/).filter(Boolean).map(Number);
    const parameters = {
      ...props.parameters,
      name: props.parameters.name + ' · 风险与敏感性',
      probability_levels: probabilityLevels,
      sensitivities: variations.value.map(item => ({...item})),
      wall_time_seconds: wall.value,
      per_case_time_seconds: perCase.value,
    };
    const data = await api('', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ module: 'investment_experiments', parameters }),
    });
    if (currentGeneration !== generation || currentSelection !== selection) return;
    job.value = data;
    detail.value = null;
    ++detailSelection;
    jobs.value = [data, ...jobs.value];
    timer = setTimeout(() => poll(data.id, currentGeneration, currentSelection), 300);
  } catch (exception) {
    if (currentGeneration === generation && currentSelection === selection) error.value = String(exception);
  } finally {
    if (currentGeneration === generation) busy.value = false;
  }
}

async function action(type: string) {
  if (!job.value) return;
  const currentGeneration = generation;
  const jobId = job.value.id;
  try {
    const data = await api('/' + jobId + '/' + type, { method: 'POST' });
    if (currentGeneration === generation && job.value?.id === jobId) await inspect(data.id);
  } catch (exception) {
    if (currentGeneration === generation) error.value = String(exception);
  }
}

async function inspectCase(id: string) {
  const currentGeneration = generation;
  const currentSelection = ++detailSelection;
  const jobId = job.value.id;
  try {
    const data = await api('/' + jobId + '/experiment-cases/' + id);
    if (currentGeneration === generation && currentSelection === detailSelection && jobId === job.value?.id) {
      detail.value = data;
      traceIndex.value = 0;
    }
  } catch (exception) {
    if (currentGeneration === generation && currentSelection === detailSelection) error.value = String(exception);
  }
}

watch(() => props.projectId, refresh, { immediate: true });
onBeforeUnmount(() => {
  ++generation;
  ++selection;
  ++detailSelection;
  clearTimeout(timer);
});
</script>
<template>
<section>
<article>
<h3>配置方案比较与敏感性</h3>
<p>概率扫描沿用冻结场景和同一投资模型。每个敏感性算例从原基准改变一个因素并重新求解。图表展示已计算概率水平的风险—成本点。</p>
<p class="error" v-if="error">{{error}}</p>
<div class="actions">
<button @click="$emit('load-baseline')" :disabled="busy||active">载入当前配置参数作为研究基准</button>
<button @click="refresh">读取比较档案</button>
</div>
<p v-if="parameters">已载入：{{parameters.name}} · 工程{{parameters.base.project_revision}} / 台账{{parameters.base.engineering_revision}} · 基准概率{{parameters.required_probability}}。修改上方配置表后需再次载入；本次比较冻结载入的参数。</p>
<p v-else>先填写候选、目标与阶段，再载入研究基准；已有比较档案可直接查看。</p>
<div class="fields">
<label>扫描达标概率<input aria-label="扫描达标概率" v-model="levels">
</label>
<label>比较总时限 s<input type="number" min="1" max="3600" v-model.number="wall">
</label>
<label>单例时限 s<input type="number" min="1" max="3600" v-model.number="perCase">
</label>
</div>
<p>基准始终计算；概率列表若含基准水平只计算一次。最多12个概率、12个敏感性算例。资本倍率影响候选容量/固定建设成本；年维护倍率影响候选容量/固定、已有逐台及全局年维护；负荷倍率作用于所有阶段且相对原基准。燃料倍率只改价格，不增库存。折现率和储能有效系数为绝对值；后者统一覆盖所有参与储能及训练/验证/阶段条件。</p>
<h4>单因素敏感性参数</h4>
<div class="scroll" v-if="variations.length"><table><tr><th>算例名称</th><th>变化因素</th><th>倍率或绝对值</th><th>操作</th></tr>
<tr v-for="(item,index) in variations" :key="index"><td><input v-model="item.name" :aria-label="'敏感性名称 '+(index+1)"></td>
<td><select v-model="item.parameter" :aria-label="'敏感性因素 '+(index+1)" @change="changeParameter(item)"><option v-for="key in Object.keys(parameterNames).filter(key=>key!=='required_probability')" :value="key">{{parameterNames[key]}}</option></select></td>
<td><input type="number" step="any" min="0" v-model.number="item.value" :aria-label="'敏感性参数值 '+(index+1)"></td><td><button @click="variations.splice(index,1)">移除因素</button></td></tr></table></div>
<button @click="addVariation" :disabled="variations.length>=12">添加敏感性因素</button>
<details><summary>批量导入敏感性参数 JSON</summary>
<textarea aria-label="单因素敏感性 JSON" v-model="sensitivity" rows="7" spellcheck="false"></textarea>
<p>导入后在上方表格核对并提交。</p><button @click="importVariations">应用敏感性 JSON</button>
</details>
<button class="primary" @click="submit" :disabled="busy||active||!parameters">提交风险成本与敏感性比较</button>
</article>
<article v-if="job">
<h3>配置比较任务 · {{names[job.status]||job.status}}</h3>
<p>{{job.id}} · {{job.input_sha256}}</p>
<p v-if="job.error" class="error">{{job.error}}</p>
<progress max="1" :value="job.progress?.fraction||0">
</progress>
<p>{{job.progress?.case_name}} · {{job.progress?.case_phase||job.progress?.phase}}</p>
<div class="actions">
<button v-if="active" @click="action('cancel')" :disabled="job.status==='cancel_requested'">取消比较研究</button>
<button v-else @click="action('retry')">按冻结输入重试比较</button>
<a :href="'/api/study-jobs/'+job.id+'/download'">研究冻结输入与汇总 JSON</a>
<a v-if="result" :href="'/api/study-jobs/'+job.id+'/csv'">比较 CSV</a>
<a v-if="result" :href="'/api/study-jobs/'+job.id+'/report'">比较报告 HTML</a>
</div>
<template v-if="result">
<p v-if="result.status!=='complete'" class="notice">研究未完整，未运行、不可行和限时结果分别保留，不能据此宣称全局最优。</p>
<h4>风险—成本已计算点</h4>
<label>概率口径<select v-model="plotSet">
<option value="training">实际训练概率</option>
<option value="validation">样本外成功概率下界</option>
</select>
</label>
<p>横轴可选训练概率或样本外成功概率下界，每期模式取最差期；纵轴为折现目标成本。绿色通过样本外、红色失败、橙色未校核。点重合时在表中分别保留。</p>
<svg v-if="points.length" viewBox="0 0 720 330" role="img" aria-label="风险成本已计算点" class="plot">
<line x1="65" y1="270" x2="680" y2="270" stroke="#829b9d"/>
<line x1="65" y1="30" x2="65" y2="270" stroke="#829b9d"/>
<text x="20" y="20">成本 元</text>
<template v-for="p in [0,.25,.5,.75,1]">
<line :x1="65+p*600" y1="270" :x2="65+p*600" y2="275" stroke="#829b9d"/>
<text :x="55+p*600" y="293">{{p}}</text>
</template>
<text x="465" y="320">{{plotSet==='training'?'实际训练达标概率':'样本外成功概率下界'}}</text>
<text x="6" y="45">{{fmt(maxCost,0)}}</text>
<text x="35" y="270">0</text>
<circle v-for="c in points" :key="c.id" :cx="65+600*c.plot_probability" :cy="270-230*c.objective_yuan/maxCost" r="7" :fill="c.validation_status==='passed'?'#138371':c.validation_status==='failed'?'#bf4747':'#bd8a25'" tabindex="0" @click="inspectCase(c.id)" @keydown.enter="inspectCase(c.id)">
<title>{{c.name}}：{{c.objective_yuan}}元 / 概率{{c.plot_probability}} / {{names[c.validation_status]}}</title>
</circle>
</svg>
<p>训练非支配：{{result.training_non_dominated.join(', ')||'无可行点'}}；已验证非支配（按样本外下界）：{{result.validated_non_dominated.join(', ')||'无'}}。动态校核按课题3资料交付状态显示。</p>
<div class="scroll">
<table>
<tr>
<th>算例 / 因素</th>
<th>参数值</th>
<th>状态</th>
<th>折现成本 元</th>
<th>较基准 元 / 比例</th>
<th>要求 / 实际训练概率</th>
<th>样本外下界 / 上界</th>
<th>最差期事件期望未供 kWh</th>
<th>样本外</th>
<th>证据</th>
</tr>
<tr v-for="c in result.cases" :key="c.id">
<td>{{c.name}} · {{names[c.kind]}}<br>{{parameterNames[c.parameter]}}</td>
<td>{{c.value}}</td>
<td>{{names[c.status]||c.status}}</td>
<td>{{fmt(c.objective_yuan)}}</td>
<td>{{fmt(c.delta_objective_yuan)}} / {{fmt(c.relative_objective_change,5)}}</td>
<td>{{fmt(c.requested_probability,6)}} / {{fmt(c.training_success_probability,6)}}</td>
<td>{{fmt(c.validation_success_probability_lower,6)}} / {{fmt(c.validation_success_probability_upper,6)}}</td>
<td>{{fmt(c.worst_period_expected_event_unsupplied_kwh)}}</td>
<td :class="{error:c.validation_status==='failed'}">{{names[c.validation_status]||'—'}}</td>
<td>
<button v-if="c.detail_archived" @click="inspectCase(c.id)">查看 {{c.id}}</button>
<p v-if="c.error">{{c.error}}</p>
</td>
</tr>
</table>
</div>
<p v-for="s in result.scope">{{s}}</p>
</template>
</article>
<article v-if="detail">
<h3>比较单例 · {{detail.definition.name}}</h3>
<p>{{detail.derived_input_sha256}}</p>
<a :href="'/api/study-jobs/'+job.id+'/experiment-cases/'+detail.definition.id">下载完整单例 JSON</a>
<p>选定设备：{{detail.result.selected_assets.map((a:any)=>a.asset_id).join(', ')||'无需新增'}} · 样本外建议：{{detail.result.recommendation_status||'未获可行解'}}</p>
<label v-if="detail.result.scenario_results?.length">单例场景<select v-model.number="traceIndex">
<option v-for="(t,i) in detail.result.scenario_results" :value="i">时期{{t.period+1}} · {{t.scenario_id}}</option>
</select>
</label>
<div v-if="trace" class="scroll">
<table>
<tr>
<th>时间</th>
<th>需求 kW</th>
<th>供电 kW</th>
<th>未供 kW</th>
</tr>
<tr v-for="r in trace.result.rows">
<td>{{r.timestamp}}</td>
<td>{{fmt(r.load_kw)}}</td>
<td>{{fmt(r.served_kw)}}</td>
<td>{{fmt(r.total_unsupplied_kw)}}</td>
</tr>
</table>
</div>
<details>
<summary>单例输入、库存成本/温度覆盖及求解证据</summary>
<pre>{{JSON.stringify({parameters:detail.parameters,inventory_overrides:detail.inventory_overrides,solver:detail.result.solver},null,2)}}</pre>
</details>
</article>
<article>
<h3>本工程配置比较档案</h3>
<p v-if="!jobs.length">暂无比较研究。</p>
<button v-for="j in jobs" :key="j.id" class="record" @click="inspect(j.id)">{{j.name}} · {{names[j.status]||j.status}} · {{new Date(j.created*1000).toLocaleString()}}</button>
</article>
</section>
</template>
<style scoped>.actions{display:flex;flex-wrap:wrap;gap:15px;margin:18px 0}.fields{display:flex;flex-wrap:wrap;gap:20px;margin:20px 0}.fields label{display:flex;gap:10px;align-items:center}input,select{padding:7px;border:1px solid #c8dcdf;max-width:100%}textarea{display:block;width:100%;box-sizing:border-box;font-family:monospace;margin:12px 0}.scroll{overflow:auto;max-height:480px;margin:20px 0}td,th{white-space:nowrap}.record{display:block;margin:12px 0}pre{max-height:400px;overflow:auto}.plot{width:100%;max-width:900px;height:330px}progress{width:100%;height:18px}svg text{font:14px sans-serif;fill:#315359}circle{cursor:pointer}</style>
