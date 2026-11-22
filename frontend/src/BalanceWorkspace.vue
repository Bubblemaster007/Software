<script setup lang="ts">
import SeriesPreview from "./SeriesPreview.vue";
import ParameterDialog from "./ParameterDialog.vue";
import { inspectTimeSeries } from "./timeSeries";
import NativePipeline from "./NativePipeline.vue";
import AnnualWorkspace from "./AnnualWorkspace.vue";
import ResultOverview from "./ResultOverview.vue";
import RandomBalance from "./RandomBalance.vue";
import DeviceDispatch from "./DeviceDispatch.vue";
import FaultPicker from "./FaultPicker.vue";
import PhaseEditor from "./PhaseEditor.vue";
import { useEngineeringContext } from "./useEngineeringProject";

const {scene,navigateWorkspace,taskFocus,layout,
  resultRange,
  customNetwork,
  currentLines,
  networkParameters,
  activeProductionId,
  project,
  scenarioId,
  stages,
  model,
  branchLimit,
  active,
  csv,
  busy,
  result,
  parameterTab,
  balanceParametersOpen,
  workspacePanel,
  balanceMode,
  params,
  labels,
  parametersDraft,
  applyBalanceParameters,
  draftFaultSelection,
  inputChanged,
} = useEngineeringContext();
</script>
<template>
  <div class="balance-workspace">
    <article class="confirmed-scenario-summary"><div class="actions"><strong>{{scene.confirmed.value?.name||'场景尚未确认'}}</strong><span>{{scene.confirmed.value?.snapshot.condition||'工况待确认'}}</span><span>{{inspectTimeSeries(csv).count}}小时 · {{scene.confirmed.value?.faultMode==='manual'?'手动线路故障':scene.confirmed.value?.faultMode==='random'?'随机设备故障':'无设备故障'}} · {{scene.valid.value?'场景有效':'待重新确认'}}</span><button @click="navigateWorkspace('scenario.workspace')">修改场景</button></div><p>{{csv.trim().split(/\r?\n/)[1]?.split(',')[0]}} — {{csv.trim().split(/\r?\n/).slice(-1)[0]?.split(',')[0]}} · 全时域故障 {{scene.confirmed.value?.snapshot.failedLines.length||0}}条 · 阶段故障 {{scene.confirmed.value?.snapshot.stages.reduce((n:number,s:any)=>n+(s.failed_lines?.length||0),0)||0}}条次</p></article>
    <template v-if="balanceMode === '汇总／网络平衡'"
      ><p v-if="inputChanged" class="notice">
        输入已修改，当前展示历史输入的结果，需重新计算。
      </p>
      <ResultOverview
        v-if="result"
        :selected-range="resultRange"
        :result="result" />
      <div v-else class="balance-input-preview">
        <p class="notice">
          尚未选择计算档案。当前输入
          {{
            inspectTimeSeries(csv).count
          }}
          小时；请核对参数后提交计算，或选择已保存结果。
        </p>
        <SeriesPreview :csv="csv" /></div></template
    ><DeviceDispatch @task="id=>{taskFocus=id;layout.bottom.value='计算任务'}"
      v-else-if="balanceMode === '逐设备时序调度'"
      :project-id="project?.id || ''"
    /><RandomBalance
      v-else-if="balanceMode === '随机生产模拟'"
      :source="result"
      :project-id="project?.id || ''"
    /><AnnualWorkspace
      v-else-if="balanceMode === '逐设备年度滚动'"
      :project-id="project?.id || ''"
    /><NativePipeline
      v-else-if="balanceMode === '原生年度流水线'"
      :project-id="project?.id || ''"
      :csv="csv"
      :parameters="params"
      :network-parameters="networkParameters"
      :branch-limit="branchLimit"
    /><ParameterDialog
      v-model:open="balanceParametersOpen"
      title="平衡分析参数"
      note="取消放弃本次修改；应用只更新工作区，不保存工程或提交计算。"
:compact="true" :tabs="model==='case33'?['资源参数','网络约束']:['资源参数']"
      v-model:active="parameterTab"
      ><template v-if="parametersDraft"
        ><p>当前模型（只读）：{{model==='case33'?'节点网络平衡':'汇总逐时平衡'}}。模型切换使用工作区顶部唯一选择器，场景与故障在场景生成设置中修改。</p>
        <article v-show="parameterTab === '资源参数'">
          <h3>资源参数</h3>
          <div class="balance-parameter-grid"><label v-for="(_, key) in parametersDraft.parameters" class="field"
            >{{ labels[key]
            }}<input
              type="number"
              v-model.number="parametersDraft.parameters[key]"
              :disabled="busy"
              :step="
                String(key).includes('ratio') || String(key).startsWith('eta_')
                  ? 0.01
                  : 100
              "
              min="0"
          /></label>
</div>          <p>
            关键、重要负荷按占比分组，其余为一般负荷。参数保存不等于提交计算。
          </p>
        </article>
        <article v-show="parameterTab === '网络约束'">
          <h3>网络接入与故障</h3>
          <template v-if="parametersDraft.model === 'case33'"
            ><p>
              采用已应用网络（未配置时使用IEEE33示例），2–168小时。负荷按节点基准比例分配，风光接入节点可设置，其余资源接根节点；仅处理根节点连通区域。
            </p>
            <label class="field"
              >风电接入节点编号<input
                type="number"
                min="1"
                max="99999"
                step="1"
                v-model.number="parametersDraft.networkParameters.wind_node"
                :disabled="busy" /></label
            ><label class="field"
              >光伏接入节点编号<input
                type="number"
                min="1"
                max="99999"
                step="1"
                v-model.number="parametersDraft.networkParameters.pv_node"
                :disabled="busy" /></label
            ><label class="field"
              >电压下限 / pu<input
                type="number"
                min="0.8"
                max="1"
                step="0.001"
                v-model.number="
                  parametersDraft.networkParameters.voltage_min_pu
                "
                :disabled="busy" /></label
            ><label class="field"
              >电压上限 / pu<input
                type="number"
                min="1"
                max="1.2"
                step="0.001"
                v-model.number="
                  parametersDraft.networkParameters.voltage_max_pu
                "
                :disabled="busy" /></label
            ><label class="field"
              >线性调度电压保护阈值 / pu<input
                type="number"
                min="0.8"
                max="1"
                step="0.001"
                v-model.number="
                  parametersDraft.networkParameters.linear_voltage_guard_pu
                "
                :disabled="busy"
            /></label>
            <p>
              根节点电压固定为1
              pu；保护阈值用于线性调度，其值须不小于电压下限。交流潮流另按上下限复核。
            </p>
            <label class="field"
              >统一支路容量 / kW<input
                type="number"
                v-model.number="parametersDraft.branchLimit"
                :disabled="busy" /></label
          ></template>
          <p v-if="parametersDraft.model !== 'case33'">
            当前汇总模型无网络参数，选择节点网络模型后设置。
          </p>
        </article>
</template
      ><template #footer
        ><button @click="workspacePanel = ''">取消</button
        ><button
          class="primary"
          @click="applyBalanceParameters"
          :disabled="busy"
        >
          应用参数
        </button></template
      ></ParameterDialog
    >
  </div>
</template>
<style scoped>
.input-reference {
  font-size: 12px;
  margin: 0 0 8px;
}
.balance-workspace {
  min-width: 0;
}
.balance-input-preview {
  min-height: 360px;
}
</style>

<style scoped>.balance-parameter-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 16px}.balance-parameter-grid .field{display:grid;grid-template-columns:minmax(0,1fr) 110px;gap:8px;align-items:center;font-size:12px}.balance-parameter-grid input{width:110px;min-width:0}.confirmed-scenario-summary{padding:10px 12px}.confirmed-scenario-summary .actions strong{margin-right:auto}.confirmed-scenario-summary p{font-size:11px;margin-bottom:0}@media(max-width:650px){.balance-parameter-grid{grid-template-columns:minmax(0,1fr)}}</style>
