<script setup lang="ts">
import {ref, computed, watch, onBeforeUnmount} from 'vue';
import {apiError} from './apiError';

const props = defineProps<{projectId: string}>();
const project = ref<any>(null);
const engineering = ref<any>(null);
const jobs = ref<any[]>([]);
const selected = ref<any>(null);
const windows = ref<any[]>([]);
const detail = ref<any>(null);
const error = ref('');
const busy = ref(false);
const mode = ref('calendar_year');
const start = ref('2026-01-01T00:00');
const dt = ref(1);
const seriesSteps = ref(48);
const forecastSteps = ref(48);
const commitSteps = ref(24);
const wallSeconds = ref(600);
const grid = ref(0);
const hardTargets = ref(false);
const candidates = ref(false);
const name = ref('逐设备年度滚动计算');
const provenance = ref('');
const input = ref('{}');
let generation = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
const terminal = new Set(['succeeded', 'incomplete', 'failed', 'cancelled', 'interrupted']);
const statuses: Record<string, string> = {queued: '排队', running: '计算中', cancel_requested: '等待取消',
  succeeded: '计算完成', incomplete: '结果不完整', failed: '失败', cancelled: '已取消', interrupted: '中断'};
const totalSteps = computed(() => {
  if (mode.value === 'series') return seriesSteps.value;
  const year = Number(start.value.slice(0, 4));
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return (leap ? 8784 : 8760) / dt.value;
});
const committedSteps = computed(() => windows.value.reduce((sum, row) => sum + row.committed_steps, 0));
const extraKeys = new Set(['base', 'source_curve_kw', 'load_curve_kw', 'grid_available_kw',
  'device_availability', 'line_status', 'source_commitment', 'required_energized_nodes', 'source_energy_additions_kwh']);

async function api(path: string, options?: RequestInit) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw Error(apiError(data.detail));
  return data;
}
async function refresh() {
  const current = generation;
  clearTimeout(timer);
  if (!props.projectId) return;
  try {
    const records = await api('/api/study-jobs?project_id=' + props.projectId);
    if (current !== generation) return;
    jobs.value = records.filter((row: any) => row.module === 'annual_dispatch');
    if (selected.value) await inspect(selected.value.id, false);
    if (current === generation && jobs.value.some(row => !terminal.has(row.status))) {
      timer = setTimeout(refresh, 2000);
    }
  } catch (caught) {
    if (current === generation) {
      error.value = String(caught);
      timer = setTimeout(refresh, 5000);
    }
  }
}
async function readInputs() {
  const current = generation;
  const id = props.projectId;
  if (!id) return;
  const values = await Promise.all([api('/api/projects/' + id), api('/api/engineering/projects/' + id)]);
  if (current === generation) [project.value, engineering.value] = values;
}
async function inspect(id: string, reset = true) {
  const current = generation;
  const [job, records] = await Promise.all([
    api('/api/study-jobs/' + id + '?include_result=true'),
    api('/api/study-jobs/' + id + '/annual-windows')
  ]);
  if (current !== generation || (!reset && selected.value?.id !== id)) return;
  selected.value = job;
  windows.value = records;
  if (reset) detail.value = null;
}
async function openWindow(id: string) {
  const current = generation;
  const jobId = selected.value.id;
  const data = await api('/api/study-jobs/' + jobId + '/annual-windows/' + id);
  if (current === generation && selected.value?.id === jobId) detail.value = data;
}
async function submit() {
  const current = generation;
  busy.value = true;
  error.value = '';
  try {
    await readInputs();
    if (current !== generation) return;
    const extra = JSON.parse(input.value);
    if (!extra || typeof extra !== 'object' || Array.isArray(extra)) throw Error('曲线与初态须为JSON对象');
    const unknown = Object.keys(extra).filter(key => !extraKeys.has(key));
    if (unknown.length) throw Error('未支持的年度字段 ' + unknown.join('、'));
    if (extra.base && (typeof extra.base !== 'object' || Array.isArray(extra.base))) throw Error('base须为JSON对象');
    const parameters = {...extra, name: name.value, coverage_mode: mode.value, total_steps: totalSteps.value,
      commit_steps: commitSteps.value, wall_time_seconds: wallSeconds.value, provenance: provenance.value,
      base: {...extra.base, project_id: props.projectId, project_revision: project.value.revision,
        engineering_revision: engineering.value.revision, start: start.value, step_hours: dt.value,
        steps: forecastSteps.value, grid_available_kw: [grid.value], enforce_load_targets: hardTargets.value,
        include_candidates: candidates.value}};
    const job = await api('/api/study-jobs', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({module: 'annual_dispatch', parameters})});
    if (current !== generation) return;
    await inspect(job.id);
    await refresh();
  } catch (caught) {
    if (current === generation) error.value = String(caught);
  } finally {
    if (current === generation) busy.value = false;
  }
}
async function action(kind: string) {
  const current = generation;
  const value = await api('/api/study-jobs/' + selected.value.id + '/' + kind, {method: 'POST'});
  if (current !== generation) return;
  await inspect(value.id);
  await refresh();
}
async function upload(event: Event) {
  const element = event.target as HTMLInputElement;
  const current = generation;
  try {
    const file = element.files?.[0];
    if (!file) return;
    if (file.size > 20000000) throw Error('JSON文件不能超过20MB');
    const text = await file.text();
    JSON.parse(text);
    if (current === generation) input.value = text;
  } catch (caught) {
    if (current === generation) error.value = String(caught);
  } finally {
    element.value = '';
  }
}
function reportError(caught: unknown) { error.value = String(caught); }
watch(() => props.projectId, async () => {
  ++generation;
  clearTimeout(timer);
  project.value = engineering.value = selected.value = detail.value = null;
  jobs.value = []; windows.value = []; input.value = '{}'; provenance.value = ''; error.value = ''; busy.value = false;
  try { await readInputs(); await refresh(); } catch (caught) { reportError(caught); }
}, {immediate: true});
onBeforeUnmount(() => { ++generation; clearTimeout(timer); });
</script>

<template>
  <article data-testid="annual-workspace">
    <h3>逐设备年度滚动计算</h3>
    <p>读取已保存工程的辐射网与台账。逐窗口优化，提交前缀后传递源储能量、启停、运行小时和保供中断前史。统计累计实际提交区间，支持完整日历年与指定时段。</p>
    <p>工程版本 {{project?.revision ?? '—'}} · 台账版本 {{engineering?.revision ?? '—'}}。前瞻窗口最多672步且最长168小时，支持2至100节点。年度全局最优性与项目规模性能验收待完成。</p>
    <p v-if="error" class="error" role="alert">{{error}}</p>
    <div class="fields">
      <label>名称<input v-model="name" :disabled="busy"></label>
      <label>覆盖范围<select v-model="mode" :disabled="busy"><option value="calendar_year">完整日历年</option><option value="series">指定时段</option></select></label>
      <label>开始时间<input type="datetime-local" v-model="start" :disabled="busy"></label>
      <label>步长<select v-model.number="dt" :disabled="busy"><option :value="1">60分钟</option><option :value=".5">30分钟</option><option :value=".25">15分钟</option></select></label>
      <label v-if="mode==='series'">总步数<input type="number" min="1" max="35136" v-model.number="seriesSteps" :disabled="busy"></label>
      <label>前瞻步数<input type="number" min="1" max="672" v-model.number="forecastSteps" :disabled="busy"></label>
      <label>每窗提交步数<input type="number" min="1" :max="forecastSteps" v-model.number="commitSteps" :disabled="busy"></label>
      <label>总时限 / 秒<input type="number" min="1" max="3600" v-model.number="wallSeconds" :disabled="busy"></label>
      <label>常值网供上限 / kW<input type="number" min="0" v-model.number="grid" :disabled="busy"></label>
      <label>强制台账保供目标<input type="checkbox" v-model="hardTargets" :disabled="busy"></label>
      <label>纳入候选设备<input type="checkbox" v-model="candidates" :disabled="busy"></label>
    </div>
    <p>输入 {{totalSteps}} 步，共 {{totalSteps*dt}} 小时。完整年度须从1月1日零时开始，闰年覆盖8784小时。单窗口求解上限沿用base.time_limit_seconds，缺省60秒、最多120秒。</p>
    <label class="wide">数据来源与工况说明<input v-model="provenance" :disabled="busy" placeholder="填写实测资料、日期、单位或人工假设"></label>
    <label class="wide">曲线与初态 JSON<textarea v-model="input" :disabled="busy" spellcheck="false" aria-label="年度曲线与初态 JSON"></textarea></label>
    <div class="actions"><label class="button">导入年度 JSON<input type="file" accept=".json" hidden @change="upload" :disabled="busy"></label><a href="/openapi.json" target="_blank">输入字段定义</a></div>
    <details><summary>逐设备曲线、事件与初态填写方法</summary>
      <p>source_curve_kw和load_curve_kw以设备ID为键，单位kW，数组长度为1或总步数。空缺时读取台账曲线，风光水缺曲线会提示补齐。24小时典型曲线需要提供完整年度序列。常值表示整个输入区间固定值。</p>
      <p>grid_available_kw可覆盖常值网供。device_availability、line_status、source_commitment、required_energized_nodes、source_energy_additions_kwh支持常值或完整序列。补给单位kWh，在该步开始生效。线路与启停状态为0/1。</p>
      <p>base可填写逐设备初态、费用、无功限额和load_target_start_hours。目标起始小时相对事件起点计，缺省从事件零时开始，台账target_hours决定持续时长。已逝事件须声明完整目标前史。表单中的时间网格、版本和硬目标设置优先。</p>
      <pre>{"source_curve_kw":{},"load_curve_kw":{},"base":{"load_target_start_hours":{}}}</pre>
    </details>
    <button class="primary" @click="submit" :disabled="busy||!engineering?.revision||!provenance.trim()">{{busy?'正在提交…':'提交年度滚动任务'}}</button>
  </article>
  <article>
    <h3>年度滚动任务档案</h3>
    <button @click="refresh">刷新年度任务</button>
    <button v-for="job in jobs" :key="job.id" class="record" @click="inspect(job.id).catch(reportError)">{{job.name}} · {{statuses[job.status]}} · {{job.id.slice(0,8)}}</button>
    <p v-if="!jobs.length">本工程暂无年度滚动任务。</p>
  </article>
  <article v-if="selected" data-testid="annual-result">
    <h3>{{selected.name}} · {{statuses[selected.status]}}</h3>
    <p>{{selected.id}} · {{selected.input_sha256}}</p>
    <p>已归档 {{windows.length}} 个窗口，提交 {{committedSteps}} 步。{{selected.progress?.phase}}。取消在当前有界求解结束后生效，已提交窗口可继续下载，重试从冻结输入起点重新计算。</p>
    <p class="error" v-if="selected.error">{{selected.error}}</p>
    <div class="actions">
      <button v-if="!terminal.has(selected.status)" @click="action('cancel').catch(reportError)" :disabled="selected.status==='cancel_requested'">取消年度任务</button>
      <button v-else @click="action('retry').catch(reportError)">冻结输入重试年度任务</button>
      <a :href="'/api/study-jobs/'+selected.id+'/download'">冻结快照与汇总 JSON</a>
      <a :href="'/api/study-jobs/'+selected.id+'/csv'">已提交轨迹 CSV</a>
      <a v-if="selected.result" :href="'/api/study-jobs/'+selected.id+'/report'">年度报告 HTML</a>
      <a :href="'/api/study-jobs/'+selected.id+'/log'" target="_blank">工作日志</a>
    </div>
    <template v-if="selected.result">
      <p>覆盖 {{selected.result.coverage.completed_steps}} / {{selected.result.coverage.requested_steps}} 步 · 完整日历年{{selected.result.coverage.calendar_year_complete?'已覆盖':'尚未覆盖'}} · 结果{{selected.result.status}}</p>
      <div class="metric-grid">
        <p>负荷电量 <strong>{{selected.result.metrics.load_energy_kwh.toFixed(3)}} kWh</strong></p>
        <p>供电量 <strong>{{selected.result.metrics.served_energy_kwh.toFixed(3)}} kWh</strong></p>
        <p>未供电量 <strong>{{selected.result.metrics.total_unsupplied_energy_kwh.toFixed(3)}} kWh</strong></p>
        <p>运行费用 <strong>{{selected.result.metrics.study_dispatch_cost_yuan.toFixed(3)}} 元</strong></p>
      </div>
      <p v-if="selected.result.stop_reason">停止记录 {{JSON.stringify(selected.result.stop_reason)}}</p>
      <div class="scroll"><table><tr><th>负荷</th><th>最大连续中断 / h</th><th>累计中断 / h</th><th>目标状态</th></tr><tr v-for="load in selected.result.load_metrics" :key="load.id"><td>{{load.id}}</td><td>{{load.maximum_target_interruption_hours}}</td><td>{{load.total_target_interruption_hours}}</td><td>{{load.target_status}}</td></tr></table></div>
      <details><summary>计算范围与方法</summary><p v-for="scope in selected.result.scope">{{scope}}</p></details>
    </template>
    <div class="scroll"><table><tr><th>窗口</th><th>开始</th><th>提交/前瞻步</th><th>供电 / kWh</th><th>证据</th></tr><tr v-for="row in windows" :key="row.id"><td>{{row.id}}</td><td>{{row.start}}</td><td>{{row.committed_steps}} / {{row.forecast_steps}}</td><td>{{row.metrics.served_energy_kwh.toFixed(3)}}</td><td><button @click="openWindow(row.id).catch(reportError)">查看窗口</button> <a :href="'/api/study-jobs/'+selected.id+'/annual-windows/'+row.id">窗口 JSON</a></td></tr></table></div>
    <section v-if="detail"><h4>窗口提交轨迹 · {{detail.summary.id}}</h4>
      <div class="scroll"><table><tr><th>全局步</th><th>时间</th><th>负荷 kW</th><th>供电 kW</th><th>缺供 kW</th></tr><tr v-for="row in detail.committed_rows" :key="row.global_step"><td>{{row.global_step}}</td><td>{{row.timestamp}}</td><td>{{row.load_kw}}</td><td>{{row.served_kw}}</td><td>{{row.total_unsupplied_kw}}</td></tr></table></div>
      <details><summary>实际末状态与前瞻求解证据</summary><pre>{{JSON.stringify({state_after:detail.state_after,forecast_solver:detail.forecast_solver},null,2)}}</pre></details>
    </section>
  </article>
</template>
<style scoped>
.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
label{display:flex;flex-direction:column;gap:6px}.wide{margin:16px 0}textarea{min-height:160px;font-family:monospace}
.actions{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}.scroll{overflow:auto;max-height:400px;margin:16px 0}
pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto}td,th{white-space:nowrap}
</style>
