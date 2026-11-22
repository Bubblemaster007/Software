<script setup lang="ts">
import ScenarioSettingsWorkspace from './ScenarioSettingsWorkspace.vue';
import ParameterDialog from "./ParameterDialog.vue";
import { inspectTimeSeries } from "./timeSeries";
import SourceStudy from "./SourceStudy.vue";
import IntegrationWorkspace from "./IntegrationWorkspace.vue";
import ProjectOverview from "./ProjectOverview.vue";
import SourceAnalysis from "./SourceAnalysis.vue";
import SequenceWorkspace from "./SequenceWorkspace.vue";
import NetworkSummary from "./NetworkSummary.vue";
import ConfigOverview from "./ConfigOverview.vue";
import StrategyWorkspace from "./StrategyWorkspace.vue";
import ReportWorkspace from "./ReportWorkspace.vue";
import DataWorkspace from "./DataWorkspace.vue";
import EngineeringWorkspace from "./EngineeringWorkspace.vue";
import DataGovernance from "./DataGovernance.vue";
import DeliverablesWorkspace from "./DeliverablesWorkspace.vue";
import DevelopmentPlan from "./DevelopmentPlan.vue";
import EffectEvaluation from "./EffectEvaluation.vue";
import DisasterWorkspace from "./DisasterWorkspace.vue";
import RestorationWorkspace from "./RestorationWorkspace.vue";
import ScenarioWorkspace from "./ScenarioWorkspace.vue";
import ModuleWorkspace from "./ModuleWorkspace.vue";
import { ref } from "vue";
import BalanceWorkspace from "./BalanceWorkspace.vue";
import { workspaces, resolveWorkspace, stepLabels } from "./workspaceRegistry";
import { useEngineeringProject } from "./useEngineeringProject";
import { watch } from "vue";
import { useEngineeringContext } from "./useEngineeringProject";
const {
  networkChanged,
  layout,
  subsection,
  integrationModule,
  openIntegration,
  navigateSection,
  eventCsv,
  inventorySections,
  customNetwork,
  sourceImport,
  sourceImportCsv,
  faultSelection,
  networkParameters,
  activeProductionId,
  project,
  scenarioId,
  stages,
  model,
  active,
  csv,
  busy,
  error,
  result,
  history,
  operatingCondition,
  scenarioSettingsOpen,
  selectedScenario,
  dataWorkspace,
  disasterWorkspace,
  restorationWorkspace,
  engineeringProgress,
  params,
  applyProjected,
  applyHistoricalInput,
  applyProduction,
  applyScenario,
  load,
  workspaceId,
} = useEngineeringContext();
const scenarioLibraryOpen = ref(false);
const scenarioLibraryTab = ref("典型场景库");
watch(
  () => project.value?.id,
  () => {
    scenarioLibraryOpen.value = false;
    scenarioLibraryTab.value = "典型场景库";
  },
);
</script>
<template>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <div
    v-if="
      [
        'data.source',
        'data.network',
        'data.resources',
        'results.workspace',
        'system.integration',
      ].includes(workspaceId)
    "
    class="module-tabs"
    aria-label="工作区视图"
  >
    <button
      v-for="s in workspaces
        .find((w) => w.id === workspaceId)
        ?.sections.filter(
          (s) =>
            ![
              '配置方案',
              '示范区实证',
            ].includes(s),
        )"
      :class="{ current: subsection === s }"
      @click="navigateSection(active, s)"
    >
      {{ stepLabels[s] || s }}</button
    ><button
      v-if="workspaceId === 'results.workspace' && subsection === '成果与交付'"
      @click="subsection = '示范区实证'"
    >
      示范区实证
    </button>
  </div>
  <template v-if="active === '工程工作台' && project"
    ><ProjectOverview
      :csv="csv"
      :history="history"
      :scenario-id="scenarioId"
      :production-id="activeProductionId"
      :model="model"
      :network-name="customNetwork?.name"
      :stages="stages.length"
      :progress="engineeringProgress"
      :project="project"
      @navigate="navigateSection($event, resolveWorkspace($event).defaultView)"
      @open="load"
  /></template>
  <div
    v-else-if="active === '数据管理'"
    class="data-page"
    :class="{ 'network-page': subsection === '电网拓扑' }"
  >
    <article v-if="subsection === '数据版本管理'">
      <h3>数据校验与版本核对</h3>
      <p>
        源荷：{{ inspectTimeSeries(csv).count }}小时，{{
          inspectTimeSeries(csv).totalIssues
        }}项格式问题。网络：{{
          customNetwork
            ? "已应用自定义网络"
            : "未应用自定义网络，将使用IEEE33示例"
        }}。工程版本：{{ project?.revision || "—" }}。
      </p>
      <p>
        下方查看已保存的数据版本；逐设备计算还需在对应模式核对台账版本、设备曲线与模型限制，格式通过不代表全部模型可计算。
      </p>
      <button @click="navigateSection('保供场景生成', '典型场景库')">
        继续到场景设置
      </button>
    </article>
    <EngineeringWorkspace
      v-if="inventorySections.includes(subsection)"
      :project-id="project?.id || ''"
      :section="subsection"
    /><DataGovernance
      v-else-if="['地理与灾害', '数据版本管理'].includes(subsection)"
      :project-id="project?.id || ''"
      :section="subsection"
    /><DataWorkspace
      :source="sourceImportCsv === csv ? sourceImport : null"
      ref="dataWorkspace"
      managed
      v-else
      v-model="csv"
      v-model:network="customNetwork"
      @update:network="networkChanged"
      v-model:failures="faultSelection"
      @source="applyHistoricalInput"
      :section="subsection"
      :placement="networkParameters"
      :parameters="params"
      :disabled="busy"
    /><NetworkSummary
      v-if="subsection === '电网拓扑'"
      :network="customNetwork"
    />
  </div>
  <ScenarioSettingsWorkspace v-else-if="active==='保供场景生成'"/>
  <BalanceWorkspace v-else-if="active === '电力电量平衡'" />
  <StrategyWorkspace v-else-if="active === '保供能力提升'" :result="result" />
  <EffectEvaluation
    v-else-if="active === '方案与报告' && subsection === '质效评价'"
    :project-id="project?.id || ''"
  /><DeliverablesWorkspace
    v-else-if="
      active === '方案与报告' &&
      ['示范区实证', '成果与交付'].includes(subsection)
    "
    :project-id="project?.id || ''"
    :section="subsection"
  /><ReportWorkspace
    :section="subsection"
    v-else-if="active === '方案与报告'"
    :project-id="project?.id || ''"
    @open="load"
  />
  <DevelopmentPlan
    v-else-if="active === '系统与接口' && subsection === '功能规划与验收'"
  /><IntegrationWorkspace
    :initial-module="integrationModule"
    v-else-if="active === '系统与接口'"
    :project-id="project?.id || ''"
  /><DisasterWorkspace
    ref="disasterWorkspace"
    v-else-if="active === '承灾极限分析'"
    :project-id="project?.id || ''"
    :section="subsection"
  /><RestorationWorkspace
    ref="restorationWorkspace"
    v-else-if="active === '黑启动路径优化'"
    :project-id="project?.id || ''"
    :section="subsection"
  /><template v-else-if="active === '源储协同配置'"
    ><ConfigOverview
      :project-id="project?.id || ''"
      :section="subsection" /></template
  ><ModuleWorkspace
    @integration="openIntegration"
    v-else-if="active !== '系统配置'"
    :section="subsection"
    :module="active"
    :project-id="project?.id || 'legacy'"
  />
  <template v-if="active === '系统配置'"
    ><article>
      <h3>工作空间布局</h3>
      <p>导航宽度及面板尺寸保存在本机偏好中，与工程数据分离。</p>
      <button @click="layout.reset">恢复默认布局</button>
    </article></template
  >

</template>
