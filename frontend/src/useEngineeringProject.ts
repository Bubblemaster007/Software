import {useScenarioConfiguration} from './useScenarioConfiguration';
import {validateScenarioDraft} from './scenarioConfiguration';
import { inspectTimeSeries } from "./timeSeries";
import {stageSignature} from './balanceInputContext';
import { apiError } from "./apiError";
import { workflowStatuses } from "./workflowProgress";
import { useWorkflowProgress } from "./useWorkflowProgress";
import { workflowActivity, beginWorkflowActivity } from "./workflowActivity";
import DataWorkspace from "./DataWorkspace.vue";
import DisasterWorkspace from "./DisasterWorkspace.vue";
import RestorationWorkspace from "./RestorationWorkspace.vue";
import type { Stage } from "./PhaseEditor.vue";
import { ref, onMounted, nextTick, watch, computed } from "vue";
import { inject, onBeforeUnmount, provide } from "vue";
import { workspaces, resolveWorkspace } from "./workspaceRegistry";
import { useLayoutPreferences } from "./useLayoutPreferences";
import { useCommands } from "./commands";
export function useEngineeringProject() {
  const layout = useLayoutPreferences();
  const subsection = ref("工程概览");
  const integrationModule = ref("disaster_limit");
  function openIntegration(name: string) {
    integrationModule.value =
      (
        {
          承灾极限分析: "disaster_limit",
          离网稳定判别: "island_stability",
          黑启动路径优化: "black_start",
        } as Record<string, string>
      )[name] || "joint_planning";
    active.value = "系统与接口";
    nextTick(() => {
      subsection.value = "交接任务";
    });
  }
  async function navigateSection(menu: string, section: string) {
    const target = resolveWorkspace(menu, section);
    if (menu === "系统与接口" && section === "计算任务") {
      layout.bottom.value = "计算任务";
      return;
    }
    if (menu === "数据管理" && section === "数据版本管理") {
      validateInput();
      return;
    }
    workspaceId.value = target.id;
    active.value = target.menu;
    subsection.value = section || target.defaultView;
    if (
      menu === "电力电量平衡" &&
      [
        "逐设备时序调度",
        "随机生产模拟",
        "逐设备年度滚动",
        "原生年度流水线",
      ].includes(section)
    )
      balanceMode.value = section;
    if (
      menu === "电力电量平衡" &&
      ["模型与资源", "运行阶段"].includes(section)
    ) {
      workspacePanel.value = "参数";
      parameterTab.value = "资源参数";
    }
    await nextTick();
  }
  const eventCsv = ref("");
  const inventorySections = [
    "电源台账",
    "储能台账",
    "负荷与保供目标",
    "变压器与开关",
    "二次设备与通信",
    "经济参数",
    "分类目标与优先级", "典型场景库",
  ];
  const networkDefaults = {
    wind_node: 18,
    pv_node: 30,
    voltage_min_pu: 0.95,
    voltage_max_pu: 1.05,
    linear_voltage_guard_pu: 0.955,
  };
  const customNetwork = ref<any>(null);
  const sourceImport = ref<any>(null);
  const sourceImportCsv = ref("");
  const defaultNetwork = ref<any>(null);
  const currentLines = computed(
    () => customNetwork.value?.lines || defaultNetwork.value?.lines || [],
  );
  const faultSelection = computed<number[]>({
    get: () =>
      failedLines.value.trim()
        ? failedLines.value.split(/[,，]/).map(Number)
        : [],
    set: (v) => {
      failedLines.value = v.join(",");
    },
  });
  fetch("/api/network/case33")
    .then((r) => {
      if (r.ok) return r.json();
      throw Error("网络读取失败");
    })
    .then((v) => (defaultNetwork.value = v))
    .catch(() => {});
  const networkParameters = ref({ ...networkDefaults });
  const productionId = ref<string | null>(null);
  const productionCsv = ref("");
  const activeProductionId = computed(() =>
    csv.value === productionCsv.value ? productionId.value : null,
  );
  const project = ref<any>(null);
  const projects = ref<any[]>([]);
  const scenarioId = ref<string | null>(null);
  const projectMessage = ref("");
  const stages = ref<Stage[]>([]);
  const stageSnapshot = ref("[]");
  const model = ref("aggregate");
  const failedLines = ref("");
  const branchLimit = ref(5000);
  const active = ref("工程工作台");
  const csv = ref("");
  const busy = ref(true);
  const error = ref("");
  const result = ref<any>(null);
  const history = ref<any[]>([]);
  const operatingCondition = ref("未指定");
  const scenarioSettingsOpen = ref(0);
  const selectedScenario = ref<any>(null);
  const dataWorkspace = ref<InstanceType<typeof DataWorkspace>>();
  const disasterWorkspace = ref<InstanceType<typeof DisasterWorkspace>>();
  const restorationWorkspace = ref<InstanceType<typeof RestorationWorkspace>>();
  const parameterTab = ref("资源参数");
  const balanceParametersOpen = computed({
    get: () => workspacePanel.value === "参数",
    set: (value) => (workspacePanel.value = value ? "参数" : ""),
  });
  const dataParametersOpen = ref(false);
  const dataParameterTab = ref("源储参数");
  const workspacePanel = ref("");
  const presentation = ref(false);
  watch(subsection, () => {
    workspacePanel.value = "";
    dataParametersOpen.value = false;
    if (subsection.value !== "故障与恢复场景") scenarioSettingsOpen.value = 0;
  });
  const sidebarCompact = layout.compact;
  const balanceMode = ref("汇总／网络平衡");
  const scene=useScenarioConfiguration({project,csv,customNetwork,operatingCondition,scenarioId,activeProductionId,faultSelection,stages,sourceImport,productionId,productionCsv,failedLines,model,balanceMode,projectMessage,navigateWorkspace});
  const progressEvidence = useWorkflowProgress(project, subsection);
  const engineeringProgress = computed(() => {
    const v = project.value?.state || {};
    const inspection = inspectTimeSeries(csv.value);
    const dataSaved =
      csv.value === v.csv &&
      JSON.stringify(customNetwork.value) === JSON.stringify(v.network || null);
    const dirty =
      !dataSaved ||
      JSON.stringify(params.value) !== JSON.stringify(v.parameters || {}) ||
      JSON.stringify(stages.value) !== JSON.stringify(v.stages || []) ||
      model.value !== (v.model || "aggregate") ||
      scenarioId.value !== (v.scenarioId || null) ||
      JSON.stringify(networkParameters.value) !==
        JSON.stringify({ ...networkDefaults, ...v.networkParameters }) ||
      failedLines.value !== (v.failedLines || "") ||
      branchLimit.value !== (v.branchLimit || 5000);
    const statuses=workflowStatuses({
      snapshot: progressEvidence.snapshot.value,
      ready: progressEvidence.ready.value,
      error: progressEvidence.error.value,
      dataReady:
        !!project.value &&
        inspection.count >= 2 &&
        !inspection.totalIssues &&
        (model.value === "aggregate" || !!customNetwork.value),
      dataSaved,
      dirty,
      working: {
        scenario: !!workflowActivity.value[project.value?.id + ":scenario"],
        balance: !!workflowActivity.value[project.value?.id + ":balance"],
        optimization:
          !!workflowActivity.value[project.value?.id + ":optimization"],
      },
    });
    if(scene.confirmed.value)statuses['场景生成']={label:scene.valid.value?'已应用':'配置已失效',tone:scene.valid.value?'done':'warning',detail:scene.valid.value?'已统一确认并应用当前场景配置':'上游源荷、网架、故障或阶段已变化，请重新确认场景'};
    else if(scene.draft.value)statuses['场景生成']={label:scene.stale.value?'配置已失效':'配置中',tone:'warning',detail:'场景草稿尚未正式应用'};
    return statuses;
  });
  const inputIssue = computed(() => {
    if(scene.confirmed.value?.faultMode==='manual'&&(model.value!=='case33'||balanceMode.value!=='汇总／网络平衡'))return '当前场景含手动线路故障，请使用节点网络平衡；高级模式不自动继承此场景';
    if(!scene.valid.value)return '请先在场景生成设置中确认当前场景；历史档案仍可只读查看';
    const check = inspectTimeSeries(csv.value);
    if (check.count < 2 || check.count > 8760) return "时序须为2–8760小时";
    if (check.totalIssues) return `源荷格式有${check.totalIssues}项问题`;
    if (model.value === "case33" && check.count > 168)
      return "网络平衡最多168小时，请缩短时序或更换模式";
    let previous = 0;
    const names = new Set<string>();
    for (const stage of stages.value) {
      if (
        !stage.name.trim() ||
        names.has(stage.name.trim()) ||
        !Number.isInteger(stage.end_hour) ||
        stage.end_hour <= previous
      )
        return "运行阶段名称或结束小时不合法";
      names.add(stage.name.trim());
      previous = stage.end_hour;
    }
    return stages.value.length && previous !== check.count
      ? "运行阶段未覆盖完整输入时序"
      : "";
  });
  function normalizeStages(value: Stage[] | undefined) {
    return (value || []).map((stage) => ({
      ...stage,
      grid_ratio: stage.grid_ratio ?? 1,
      emergency_ratio: stage.emergency_ratio ?? 1,
      failed_lines: stage.failed_lines ?? [],
    }));
  }
  function sameParameters(
    a: Record<string, number>,
    b: Record<string, number>,
  ) {
    return (
      Object.keys(a).length === Object.keys(b).length &&
      Object.entries(a).every(([key, value]) => value === b[key])
    );
  }
  const params = ref({
    storage_power_kw: 500,
    storage_energy_kwh: 2000,
    emergency_gen_kw: 300,
    grid_channel_kw: 0,
    soc_initial_ratio: 0.8,
    soc_min_ratio: 0.1,
    soc_max_ratio: 0.95,
    eta_charge: 0.92,
    eta_discharge: 0.9,
    critical_load_ratio: 0.2,
    important_load_ratio: 0.35,
  });
  const labels: Record<string, string> = {
    storage_power_kw: "储能功率 / kW",
    storage_energy_kwh: "储能容量 / kWh",
    emergency_gen_kw: "应急电源 / kW",
    grid_channel_kw: "外部供电上限 / kW",
    soc_initial_ratio: "初始SOC / 比例",
    soc_min_ratio: "SOC下限 / 比例",
    soc_max_ratio: "SOC上限 / 比例",
    eta_charge: "充电效率 / 比例",
    eta_discharge: "放电效率 / 比例",
    critical_load_ratio: "关键负荷占比",
    important_load_ratio: "重要负荷占比",
  };
  async function api(url: string, options?: RequestInit) {
    const r = await fetch(url, options);
    const d = await r.json();
    if (!r.ok) throw Error(apiError(d.detail));
    return d;
  }
  async function refresh() {
    const id = project.value?.id;
    const records = await api("/api/runs" + (id ? "?project_id=" + id : ""));
    if (project.value?.id === id) history.value = records;
  }
  function state() {
    return {
      scenarioConfiguration:scene.confirmed.value,
      operatingCondition: operatingCondition.value,
      network: customNetwork.value,
      sourceImport:
        sourceImportCsv.value === csv.value ? sourceImport.value : null,
      csv: csv.value,
      parameters: params.value,
      stages: stages.value,
      networkParameters: networkParameters.value,
      model: model.value,
      failedLines: failedLines.value,
      branchLimit: branchLimit.value,
      scenarioId: scenarioId.value,
      productionSequenceId: activeProductionId.value,
    };
  }
  async function saveProject() {
    if (!project.value) return;
    const wasBusy = busy.value;
    busy.value = true;
    try {
      project.value = await api("/api/projects/" + project.value.id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...project.value,
          state: state(),
          expected_revision: project.value.revision,
        }),
      });
      savedFingerprint.value = fingerprint();
      projectMessage.value = "工程已保存 · 版本 " + project.value.revision;
      projects.value = await api("/api/projects");
    } finally {
      busy.value = wasBusy;
    }
  }
  async function createProject() {
    busy.value = true;
    try {
      if (project.value) await saveProject();
      const p = await api("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "新建保供工程",
          state: {
            operatingCondition: "常规运行",
            csv: "timestamp,load_kw,wind_kw,pv_kw\n",
          },
        }),
      });
      await openProject(p.id, false);
      await navigateSection("数据管理", "源荷时序");
      dataWorkspace.value?.openDatasetPicker();
    } catch (e) {
      error.value = String(e);
    } finally {
      busy.value = false;
    }
  }
  async function openProject(id: string, save = true) {
    busy.value = true;
    try {
      if (save && project.value) await saveProject();
      const p = await api("/api/projects/" + id);
      project.value = p;
      selectedScenario.value = null;
      eventCsv.value = "";
      const v = p.state;
      operatingCondition.value = v.operatingCondition || "未指定";
      customNetwork.value = v.network || null;
      sourceImport.value = v.sourceImport || null;
      csv.value = v.csv || "";
      sourceImportCsv.value = csv.value;
      productionId.value = v.productionSequenceId || null;
      productionCsv.value = csv.value;
      params.value = {
        storage_power_kw: 500,
        storage_energy_kwh: 2000,
        emergency_gen_kw: 300,
        grid_channel_kw: 0,
        soc_initial_ratio: 0.8,
        soc_min_ratio: 0.1,
        soc_max_ratio: 0.95,
        eta_charge: 0.92,
        eta_discharge: 0.9,
        critical_load_ratio: 0.2,
        important_load_ratio: 0.35,
        ...v.parameters,
      };
      networkParameters.value = { ...networkDefaults, ...v.networkParameters };
      stages.value = normalizeStages(v.stages);
      model.value = v.model || "aggregate";
      failedLines.value = v.failedLines || "";
      branchLimit.value = v.branchLimit || 5000;
      scenarioId.value = v.scenarioId || null;
      result.value = null;
      resultCondition.value = "all";
      layout.bottom.value = "";
      layout.right.value = "";
      validation.value = [];taskFocus.value='';
      projectSettingsOpen.value = false;scene.confirmed.value=v.scenarioConfiguration||null;
      workspacePanel.value = "";
      dataParametersOpen.value = false;
      balanceMode.value = "汇总／网络平衡";
      projects.value = await api("/api/projects");
      await refresh();
      localStorage.setItem("terminal-power.last-project", p.id);
      savedFingerprint.value = fingerprint();
      projectMessage.value = "当前工程：" + p.name + " · 版本 " + p.revision;
    } catch (e) {
      error.value = String(e);
    } finally {
      busy.value = false;
    }
  }
  function applyProjected(value: string) {
    if(active.value==='保供场景生成'){scene.selectBackground(value);return}
    productionId.value = null;
    csv.value = value;
    scenarioId.value = null;
    projectMessage.value = "已更新源荷序列，请保存工程";
  }
  function applyHistoricalInput(value: string, source: any) {
    if(source.kind==='external'){
      applyProjected(value);stages.value=[];eventCsv.value='';selectedScenario.value=null;failedLines.value='';
      sourceImport.value=source;sourceImportCsv.value=value;
      if(inspectTimeSeries(value).count>168)model.value='aggregate';
      projectMessage.value='历史文件已转换并应用；功率未缩放，请核实单位和资源参数后保存工程';return;
    }

    applyProjected(value);
    stages.value = [];
    eventCsv.value = "";
    selectedScenario.value = null;
    failedLines.value = "";
    const { network, network_parameters, branch_limit_kw, ...provenance } =
      source;
    customNetwork.value = network || null;
    networkParameters.value = { ...networkDefaults, ...network_parameters };
    branchLimit.value = branch_limit_kw;
    model.value = inspectTimeSeries(value).count>168?"aggregate":"case33";
    sourceImport.value = provenance;
    sourceImportCsv.value = value;
    if (project.value)
      project.value.region =
        source.kind === "alashankou" ? "阿拉山口" : "ExtremeScene / IEEE33示例";
    projectMessage.value =
      "已应用 " + source.name + "，请核实资源参数并保存工程；未提交计算";
  }
  function applyProduction(
    value: string,
    id: string,
    embeddedScenarioId?: string,
  ) {
    if(active.value==='保供场景生成'){scene.selectProduction(value,id,embeddedScenarioId).catch(e=>error.value=String(e));return}
    applyProjected(value);
    productionId.value = id;
    productionCsv.value = value;
    scenarioId.value = embeddedScenarioId || null;
    operatingCondition.value = "极端保供";
  }
  function applyScenario(id: string) {
    if(active.value==='保供场景生成'){scene.selectScenario(id).catch(e=>error.value=String(e));return}
    operatingCondition.value = "极端保供";
    scenarioId.value = id;
    navigateWorkspace("balance.workspace");
    projectMessage.value = "故障场景已选择，计算时将校验时间轴";
  }
  async function run() {
    if (busy.value) return;
    if (inputIssue.value) {
      error.value = inputIssue.value;
      await navigateSection("电力电量平衡", "模型与资源");
      workspacePanel.value = "参数";
      return;
    }
    busy.value = true;
    error.value = "";
    const submittedProject = project.value?.id;
    const finishProgress = beginWorkflowActivity(submittedProject, "balance");
    try {
      await saveProject();
      const calculated = await api("/api/balance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operating_condition:
            operatingCondition.value === "常规运行"
              ? "normal"
              : operatingCondition.value === "极端保供"
                ? "extreme"
                : null,
          network: customNetwork.value,
          source_import:
            sourceImportCsv.value === csv.value ? sourceImport.value : null,
          project_id: project.value?.id,
          project_revision: project.value?.revision,
          scenario_id: scenarioId.value,
          production_sequence_id: activeProductionId.value,
          stages: stages.value,
          network_parameters: networkParameters.value,
          csv: csv.value,
          parameters: params.value,
          model: model.value,
          failed_lines: failedLines.value.trim()
            ? failedLines.value.split(/[,，]/).map(Number)
            : [],
          branch_limit_kw: branchLimit.value,
        }),
      });
      if (project.value?.id !== submittedProject) return;
      result.value = calculated;
      stageSnapshot.value = JSON.stringify(stages.value);
      await refresh();
      if (active.value === "电力电量平衡" && subsection.value === "计算任务")
        subsection.value = "平衡结果";
      projectMessage.value = "计算完成并已归档 · " + calculated.id;
    } catch (e) {
      error.value = String(e);
    } finally {
      busy.value = false;
      finishProgress();
      progressEvidence.refresh();
    }
  }
  let archiveRead = 0;
  async function load(id: string) {
    const request = ++archiveRead;
    const projectId = project.value?.id;
    error.value = "";
    try {
      const loaded = await api("/api/runs/" + id);
      if (request !== archiveRead || project.value?.id !== projectId) return;
      if (loaded.project_id && loaded.project_id !== projectId)
        throw Error("该档案不属于当前工程");
      result.value = loaded;
      stageSnapshot.value = JSON.stringify(loaded.stages || []);
      active.value = "电力电量平衡";
      subsection.value = "平衡结果";
      balanceMode.value = "汇总／网络平衡";
      projectMessage.value =
        "已读取档案 " + id.slice(0, 8) + "，当前工程输入未被覆盖";
    } catch (e) {
      if (request === archiveRead && project.value?.id === projectId)
        error.value = String(e);
    }
  }
  async function upload(e: Event) {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (file) {
      csv.value = await file.text();
      result.value = null;
    }
  }

  onMounted(async () => {
    try {
      projects.value = await api("/api/projects");
      if (projects.value.length)
        await openProject(
          projects.value.find(
            (p) => p.id === localStorage.getItem("terminal-power.last-project"),
          )?.id || projects.value[0].id,
          false,
        );
      else await createProject();
    } catch (e) {
      error.value = String(e);
    } finally {
      busy.value = false;
    }
  });
  const workspaceId = ref("project.home");
  watch([active, subsection], () => {
    workspaceId.value = resolveWorkspace(active.value, subsection.value).id;
  });
  function navigateWorkspace(id: string) {
    const w = workspaces.find((v) => v.id === id);
    if(w?.id==='scenario.workspace')scene.ensure();
    if (w) navigateSection(w.menu, w.defaultView);
  }
  const taskFocus=ref('');
  const validation = ref<string[]>([]);
  const resultRange = ref<[number, number]>([0, 100]);
  function focusStage(p: any) {
    if (!result.value?.rows?.length || !result.value?.stages) return;
    const index = result.value.phase_metrics.indexOf(p);
    const stage = result.value.stages[index];
    if (!stage) return;
    const start = index ? result.value.stages[index - 1].end_hour : 0;
    const total = result.value.rows.length;
    resultRange.value = [(100 * start) / total, (100 * stage.end_hour) / total];
  }
  watch(
    () => result.value?.id,
    () => (resultRange.value = [0, 100]),
  );
  function validateInput() {
    const check = inspectTimeSeries(csv.value);
    validation.value = [
      check.totalIssues
        ? "源荷格式：" + check.totalIssues + "项问题"
        : "源荷格式检查通过（" + check.count + "小时）",
      ...check.issues.map(
        (i) => (i.row ? "第" + i.row + "行：" : "") + i.message,
      ),
      inputIssue.value ||
        "本地时序与阶段限制检查通过；服务端继续核验资源、场景和模型约束",
    ];
    layout.bottom.value = "校验信息";
  }
  const modeId = computed({
    get: () =>
      balanceMode.value === "汇总／网络平衡" ? model.value : balanceMode.value,
    set: (v: string) => {
      if (["aggregate", "case33"].includes(v)) {
        balanceMode.value = "汇总／网络平衡";
        model.value = v;
      } else balanceMode.value = v;
    },
  });
  const resultCondition = ref("all");
  const filteredHistory = computed(() =>
    history.value.filter(
      (h) =>
        resultCondition.value === "all" ||
        (h.operating_condition || "unknown") === resultCondition.value,
    ),
  );
  const selectedModeResult = computed(() =>
    balanceMode.value === "汇总／网络平衡" ? result.value : null,
  );
  const parametersDraft = ref<any>(null);
  watch(balanceParametersOpen, (open) => {
    if(open)parameterTab.value="资源参数";
    if (open)
      parametersDraft.value = JSON.parse(
        JSON.stringify({
          model: model.value,
          parameters: params.value,
          networkParameters: networkParameters.value,
          stages: stages.value,
          failedLines: failedLines.value,
          branchLimit: branchLimit.value,
        }),
      );
    else parametersDraft.value = null;
  });
  function applyBalanceParameters() {
    const d = parametersDraft.value;
    if (!d) return;
    if (
      Object.values(d.parameters).some(
        (v) => typeof v !== "number" || !Number.isFinite(v),
      )
    ) {
      error.value = "参数须为有限数值";
      return;
    }

    params.value = { ...d.parameters };
    networkParameters.value = { ...d.networkParameters };


    branchLimit.value = d.branchLimit;
    workspacePanel.value = "";
    projectMessage.value = "参数已应用至工作区，尚未保存或提交计算";
  }
  const draftFaultSelection = computed<number[]>({
    get: () =>
      parametersDraft.value?.failedLines
        ?.split(/[,，]/)
        .filter(Boolean)
        .map(Number) || [],
    set: (v) => {
      if (parametersDraft.value)
        parametersDraft.value.failedLines = v.join(",");
    },
  });
  const inputChanged = computed(
    () =>
      !!result.value &&
      (csv.value !== result.value.input_csv ||
        !sameParameters(params.value, result.value.parameters) ||
        model.value !== (result.value.model || "aggregate") ||
        (result.value.operating_condition ?? null) !==
          (operatingCondition.value === "常规运行"
            ? "normal"
            : operatingCondition.value === "极端保供"
              ? "extreme"
              : null) ||
        scenarioId.value !== (result.value.scenario_id || null) ||
        activeProductionId.value !==
          (result.value.production_sequence_id || null) ||
        stageSignature(stages.value,inspectTimeSeries(csv.value).count,faultSelection.value)!==stageSignature(result.value.stages||[],result.value.rows?.length||0,result.value.failed_lines||[]) ||
        failedLines.value !== (result.value.failed_lines || []).join(",") ||
        branchLimit.value !== (result.value.branch_limit_kw || 5000) ||
        (model.value === "case33" &&
          (!sameParameters(networkParameters.value, {
            ...networkDefaults,
            ...result.value.network_parameters,
          }) ||
            JSON.stringify(customNetwork.value) !==
              JSON.stringify(result.value.network || null)))),
  );
  const helpOpen = ref(false),
    projectSettingsOpen = ref(false);
  const versionsOpen=ref(false);
  const projectSettingsTab = ref("工程信息");
  const projectDraft = ref<any>({});
  watch(projectSettingsOpen, (open) => {
    if (open) {
      projectSettingsTab.value = "工程信息";
      projectDraft.value = {
        name: project.value?.name || "",
        region: project.value?.region || "",
        kind: project.value?.kind || "村镇级",
      };
    }
  });
  async function applyProjectSettings() {
    if (!project.value) return;
    Object.assign(project.value, projectDraft.value);
    await saveProject();
    projectSettingsOpen.value = false;
  }
  const savedFingerprint = ref("");
  function fingerprint() {
    return JSON.stringify({
      state: state(),
      name: project.value?.name,
      region: project.value?.region,
      kind: project.value?.kind,
    });
  }
  const unsaved = computed(
    () =>
      !!project.value &&
      !!savedFingerprint.value &&
      fingerprint() !== savedFingerprint.value,
  );
  const statusText = computed(
    () =>
      (unsaved.value ? "未保存修改 · " : "") +
      (projectMessage.value || "本地工程工作区") +
      (result.value
        ? " · 当前结果输入 v" + (result.value.project_revision ?? "未记录")
        : ""),
  );

  async function validateNetwork(){if(!customNetwork.value){error.value='尚无已应用网架';return}const response=await fetch('/api/network/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(customNetwork.value)});const value=await response.json();validation.value=[response.ok?'当前网架模型校验通过':JSON.stringify(value.detail)];layout.bottom.value='校验信息'}
  function networkChanged(value:any){customNetwork.value=value;failedLines.value='';stages.value=stages.value.map(stage=>({...stage,failed_lines:[]}));scenarioId.value=null;productionId.value=null;projectMessage.value='网架已更新；旧故障、阶段线路及场景/生产序列引用已解除，请重新确认场景';}
  const commandRegistry = useCommands(
    [{id:'scenario.library',label:'载入已有场景',surface:'context',visible:()=>workspaceId.value==='scenario.workspace',execute:()=>{scene.ensure();scene.libraryOpen.value=true}},
      {id:'network.import',label:'导入网架',surface:'context',visible:()=>workspaceId.value==='data.network'&&subsection.value==='电网拓扑',execute:()=>dataWorkspace.value?.openNetworkImport()},
      {id:'network.validate',label:'校验模型',surface:'context',visible:()=>workspaceId.value==='data.network'&&subsection.value==='电网拓扑',execute:validateNetwork},
      {id:"project.versions",label:"数据版本管理",execute:()=>versionsOpen.value=true,enabled:()=>!!project.value},
      {
        id: "project.create",
        label: "新建工程",
        execute: createProject,
        enabled: () => !busy.value,
      },
      {
        id: "project.open",
        label: "打开 / 切换工程",
        execute: () =>
          document
            .querySelector<HTMLSelectElement>('[aria-label="切换工程"]')
            ?.focus(),
      },
      {
        id: "project.save",
        label: "保存工程",
        shortcut: "Ctrl+S",
        execute: saveProject,
        enabled: () => !!project.value && !busy.value,
      },
      {
        id: "project.backup",
        label: "备份已保存数据",
        execute: () => {
          window.location.href = "/api/backup";
        },
      },
      {
        id: "project.settings",
        label: "工程设置",
        execute: () => (projectSettingsOpen.value = true),
      },
      {
        id: "edit.current",
        label: "编辑当前数据",
        execute: () => dataWorkspace.value?.openEditor(),
        enabled: () => active.value === "数据管理" && !!dataWorkspace.value,
        reason: () => "当前工作区没有可用的源荷或网络编辑器",
      },
      {
        id: "layout.sidebar",
        label: "展开 / 收起导航",
        execute: () => {
          layout.compact.value = !layout.compact.value;
        },
      },
      {
        id: "layout.right",
        label: "属性 / 结果快照",
        execute: () => {
          layout.right.value = layout.right.value ? "" : "属性与输入快照";
        },
      },
      {
        id: "layout.tasks",
        label: "计算任务面板",
        execute: () => {
          layout.bottom.value =
            layout.bottom.value === "计算任务" ? "" : "计算任务";
        },
      },
      {
        id: "layout.details",
        label: "数据明细面板",
        execute: () => {
          layout.bottom.value =
            layout.bottom.value === "数据明细" ? "" : "数据明细";
        },
      },
      {
        id: "layout.presentation",
        label: "切换图形展示",
        execute: () => {
          presentation.value = !presentation.value;
        },
      },
      { id: "layout.reset", label: "恢复默认布局", execute: layout.reset },
      {
        id: "help.guide",
        label: "使用说明与功能边界",
        execute: () => (helpOpen.value = true),
      },
      {
        id: "help.version",
        label: "版本信息",
        execute: () => (helpOpen.value = true),
      },
      {
        id: "data.import",
        surface: "context",
        label: "导入数据",icon:"▱",primary:true,
        execute: () => dataWorkspace.value?.openDatasetPicker(),
        visible: () =>
          workspaceId.value === "data.source" &&
          subsection.value === "源荷时序",
      },
      {
        id: "network.edit",
        surface: "context",
        label: "编辑网架",
        execute: () => dataWorkspace.value?.openEditor(),
        visible: () =>
          workspaceId.value === "data.network" &&
          subsection.value === "电网拓扑",
      },
      {
        id: "data.edit",
        surface: "context",
        label: "编辑数据",
        execute: () => dataWorkspace.value?.openEditor(),
        visible: () =>
          workspaceId.value === "data.source" &&
          subsection.value === "源荷时序",
      },
      {
        id: "data.validate",
        surface: "context",
        label: "校验输入",
        execute: validateInput,
        visible: () =>
          (workspaceId.value.startsWith("data.")&&workspaceId.value!=="data.network") ||
          workspaceId.value === "balance.workspace",
      },
      {
        id: "workspace.settings",
        surface: "context",
        label: "参数设置",
        execute: () => {
          if (active.value === "电力电量平衡") workspacePanel.value = "参数";
          else if (active.value === "承灾极限分析")
            disasterWorkspace.value?.openSettings();
          else if (active.value === "黑启动路径优化")
            restorationWorkspace.value?.openSettings();
          else dataParametersOpen.value = true;
        },
        visible: () =>
          (balanceMode.value === "汇总／网络平衡" &&
            workspaceId.value === "balance.workspace") ||
          ["research.disaster", "research.blackstart"].includes(
            workspaceId.value,
          ),
      },
      {
        id: "balance.run",
        surface: "context",
        label: "提交计算",
        primary: true,
        execute: async () => {
          layout.bottom.value = "计算任务";
          await run();
        },
        visible: () =>
          workspaceId.value === "balance.workspace" &&
          balanceMode.value === "汇总／网络平衡",
        enabled: () => !!project.value && !busy.value && !inputIssue.value,
        reason: () => inputIssue.value || "计算或保存处理中",
      },
      {
        id: "result.export",
        surface: "context",
        label: "导出结果 CSV",
        execute: () => {
          window.location.href = "/api/runs/" + result.value.id + "/csv";
        },
        visible: () =>
          workspaceId.value === "balance.workspace" &&
          balanceMode.value === "汇总／网络平衡",
        enabled: () => !!result.value,
        reason: () => "请先选择真实计算档案",
      },
    ],
    (message) => (error.value = message),
  );
  const globalMenus = [
    {
      label: "工程",
      ids: [
        "project.create",
        "project.open",
        "project.save",
        "project.backup",
        "project.settings",
        "project.versions",
      ],
    },
    { label: "编辑", ids: ["edit.current"] },
    {
      label: "视图",
      ids: [
        "layout.sidebar",
        "layout.right",
        "layout.tasks",
        "layout.details",
        "layout.presentation",
        "layout.reset",
      ],
    },
    { label: "帮助", ids: ["help.guide", "help.version"] },
  ];
  function shortcut(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      commandRegistry.execute("project.save");
    }
  }
  onMounted(() => document.addEventListener("keydown", shortcut));
  onBeforeUnmount(() => document.removeEventListener("keydown", shortcut));

  return {
    scene,networkChanged,
    versionsOpen,
    taskFocus,
    resultCondition,
    filteredHistory,
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
    scenarioId,
    stages,
    active,
    error,
    operatingCondition,
    scenarioSettingsOpen,
    selectedScenario,
    dataWorkspace,
    disasterWorkspace,
    restorationWorkspace,
    params,
    applyProjected,
    applyHistoricalInput,
    applyProduction,
    applyScenario,
    resultRange,
    currentLines,
    branchLimit,
    parameterTab,
    balanceParametersOpen,
    workspacePanel,
    labels,
    parametersDraft,
    applyBalanceParameters,
    draftFaultSelection,
    inputChanged,
    progressEvidence,
  };
}
const engineeringKey = Symbol("engineering-project");
export function provideEngineeringProject(
  value: ReturnType<typeof useEngineeringProject>,
) {
  provide(engineeringKey, value);
}
export function useEngineeringContext() {
  const value =
    inject<ReturnType<typeof useEngineeringProject>>(engineeringKey);
  if (!value) throw Error("工程上下文未提供");
  return value;
}
