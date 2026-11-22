<script setup lang="ts">
import DataDetails from './DataDetails.vue';
import {computed} from 'vue';
import ParameterDialog from "./ParameterDialog.vue";
import { inspectTimeSeries } from "./timeSeries";
import DataGovernance from "./DataGovernance.vue";
import TaskPanel from "./TaskPanel.vue";
import EngineeringWorkspace from "./EngineeringWorkspace.vue";
import EngineeringLayout from "./EngineeringLayout.vue";
import {
  useEngineeringProject,
  provideEngineeringProject,
} from "./useEngineeringProject";
import WorkspaceHost from "./WorkspaceHost.vue";

const context = useEngineeringProject();
provideEngineeringProject(context);
const {
  resultCondition,
  filteredHistory,
  scene,
  focusStage,
  projectSettingsTab,
  projectDraft,
  applyProjectSettings,
  statusText,
  layout,
  project,
  projects,
  projectMessage,
  model,
  csv,
  busy,
  result,
  history,
  presentation,
  balanceMode,
  engineeringProgress,
  openProject,
  load,
  workspaceId,
  navigateWorkspace,
  validation,
  modeId,
  helpOpen,
  projectSettingsOpen,
  commandRegistry,
  globalMenus,
  versionsOpen,
} = context;
const detailRows=computed(()=>workspaceId.value.startsWith('data.')?csv.value.trim().split(/\r?\n/).slice(1).filter(Boolean).map(line=>{const cells=line.split(',');return {timestamp:cells[0],load_kw:cells[1],wind_kw:cells[2],pv_kw:cells[3]}}):result.value?.rows||[]);
</script>
<template>
  <EngineeringLayout
    :project="project"
    :projects="projects"
    :workspace="workspaceId"
    :progress="engineeringProgress"
    :commands="commandRegistry.available()"
    :menus="globalMenus"
    :disabled="commandRegistry.disabled"
    :busy="busy"
    :status="statusText"
    v-model:compact="layout.compact.value"
    v-model:presentation="layout.presentation.value"
    v-model:bottom="layout.bottom.value"
    v-model:bottom-height="layout.bottomHeight.value"
    v-model:right="layout.right.value"
    v-model:right-width="layout.rightWidth.value"
    @navigate="navigateWorkspace"
    @command="commandRegistry.execute"
    @project="openProject"
  >
    <template #toolbar><template v-if="workspaceId==='scenario.workspace'&&scene.draft.value"><label class="toolbar-condition">运行工况 <select aria-label="场景运行工况" v-model="scene.draft.value.condition" @change="scene.draft.value.conditionConfirmed=true;scene.draft.value.step='background';if(scene.draft.value.condition==='常规运行'){scene.draft.value.faultMode='none';scene.draft.value.eventMode='none';scene.draft.value.eventCsv='';scene.clearEmbedded()}"><option>常规运行</option><option>极端保供</option></select></label></template><template v-if="workspaceId === 'balance.workspace'"
        ><select aria-label="计算模式" v-model="modeId">
          <optgroup label="普通计算">
            <option value="aggregate">汇总逐时平衡</option>
            <option value="case33">节点网络平衡</option>
          </optgroup>
          <optgroup label="高级计算">
            <option
              v-for="m in [
                '逐设备时序调度',
                '随机生产模拟',
                '逐设备年度滚动',
                '原生年度流水线',
              ]"
            >
              {{ m }}
            </option>
          </optgroup></select
        ><select
          v-if="balanceMode === '汇总／网络平衡'"
          aria-label="结果工况筛选"
          v-model="resultCondition"
        >
          <option value="all">全部结果工况</option>
          <option value="normal">常规运行结果</option>
          <option value="extreme">极端保供结果</option>
          <option value="unknown">工况未记录</option></select
        ><select
          v-if="balanceMode === '汇总／网络平衡'"
          aria-label="当前平衡结果"
          :value="result?.id || ''"
          @change="load(($event.target as HTMLSelectElement).value)"
        >
          <option value="" disabled>选择已存结果</option>
          <option v-for="h in filteredHistory" :value="h.id">
            {{ h.created }} · v{{ h.project_revision ?? "—" }} ·
            {{ h.model === "case33" ? "网络" : "汇总" }}
          </option>
        </select></template
      ></template
    >
    <WorkspaceHost /><template #right
      ><article>
        <h3>当前工程</h3>
        <p>{{ project?.name }} · v{{ project?.revision }}</p>
        <p>源荷 {{ inspectTimeSeries(csv).count }} 小时 · 模型 {{ model }}</p>
        <p v-if="result">
          档案 {{ result.id }} · 输入版本
          {{ result.project_revision ?? "未记录" }}
        </p>
        <details v-if="result">
          <summary>任务参数快照（只读）</summary>
          <pre>{{ JSON.stringify(result.parameters, null, 2) }}</pre>
        </details>
        <p v-else>尚未选择结果或对象。</p>
      </article></template
    >
    <template #bottom
      ><template v-if="layout.bottom.value === '计算任务'"
        ><TaskPanel
      /></template>
      <ul v-else-if="layout.bottom.value === '校验信息'">
        <li v-for="v in validation">{{ v }}</li>
        <li v-if="!validation.length">尚未执行当前输入校验。</li>
      </ul>
      <div v-else-if="layout.bottom.value === '分阶段指标'">
        <table v-if="result?.phase_metrics?.length">
          <tr>
            <th>阶段</th>
            <th>最大缺额 MW</th>
            <th>累计缺供 MWh</th>
          </tr>
          <tr
            v-for="p in result.phase_metrics"
            class="stage-evidence"
            tabindex="0"
            @click="focusStage(p)"
            @keydown.enter="focusStage(p)"
          >
            <td>{{ p.stage }}</td>
            <td>{{ p.maximum_electricity_shortage_mw }}</td>
            <td>{{ p.expected_energy_not_served_mwh }}</td>
          </tr>
        </table>
        <p v-else>当前结果没有分阶段指标。</p>
      </div>
      <div v-else><DataDetails :rows="detailRows"/></div></template
    > </EngineeringLayout
  ><ParameterDialog v-model:open="helpOpen" title="使用说明与研发边界"
    ><article>
      <h3>工程分析工作流程</h3>
      <p>
        数据准备 → 场景生成设置（常规可跳过故障）→ 平衡分析 → 保供优化 →
        成果管理。编辑、应用、工程保存和任务提交是独立操作。关闭任务面板不会中断后台计算。
      </p>
      <p>
        汇总平衡 2–8760 小时；节点网络平衡 2–168
        小时。随机、逐设备、年度和原生模式保留独立输入限制与归档。
      </p>
      <p>
        阿拉山口为历史重建数据集，来源与质量说明随输入保留。确定性轨迹的时段占比与累计电量不等同于灾害概率或期望。离网稳定动态方程、权重及验证资料待接入。
      </p>
      <p>版本 0.1.0 · Vue 3 / 本地离线工程工作空间</p>
    </article></ParameterDialog
  ><ParameterDialog
    v-model:open="projectSettingsOpen"
    title="工程设置"
    :tabs="['工程信息', '经济参数']"
    v-model:active="projectSettingsTab"
    ><article v-if="project && projectSettingsTab === '工程信息'">
      <label class="field">工程名称<input v-model="projectDraft.name" /></label
      ><label class="field">地区<input v-model="projectDraft.region" /></label
      ><label class="field"
        >类型<select v-model="projectDraft.kind">
          <option>县域级</option>
          <option>乡镇级</option>
          <option>村级</option>
          <option>村镇级</option>
        </select></label
      >
    </article>
    <EngineeringWorkspace
      v-if="projectSettingsTab === '经济参数'"
      :project-id="project?.id || ''"
      section="经济参数"
    /><template #footer
      ><button @click="projectSettingsOpen = false">取消</button
      ><button
        v-if="projectSettingsTab === '工程信息'"
        class="primary"
        @click="applyProjectSettings"
        :disabled="busy"
      >
        保存工程
      </button></template
    ></ParameterDialog
  >
<ParameterDialog v-model:open="versionsOpen" title="数据版本管理"><DataGovernance v-if="versionsOpen" :project-id="project?.id || ''" section="数据版本管理"/></ParameterDialog></template>
