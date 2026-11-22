export interface WorkspaceDefinition {
  id: string;
  label: string;
  icon: string;
  stage: string;
  menu: string;
  sections: string[];
  defaultView: string;
  commands: string[];
}
const define = (
  id: string,
  label: string,
  icon: string,
  stage: string,
  menu: string,
  sections: string[],
  commands: string[] = [],
): WorkspaceDefinition => ({
  id,
  label,
  icon,
  stage,
  menu,
  sections,
  defaultView: sections[0],
  commands,
});
export const workspaces: WorkspaceDefinition[] = [
  define("project.home", "工程首页", "⌂", "工程工作台", "工程工作台", [
    "工程概览",
    "操作流程",
    "工程信息",
  ]),
  define(
    "data.source",
    "源荷与气象",
    "∿",
    "数据准备",
    "数据管理",
    ["源荷时序", "地理与灾害"],
    ["data.import", "data.edit", "data.validate"],
  ),
  define(
    "data.network",
    "电网模型",
    "◇",
    "数据准备",
    "数据管理",
    ["电网拓扑", "变压器与开关", "二次设备与通信"],
    ["network.edit", "data.validate"],
  ),
  define(
    "data.resources",
    "资源与负荷",
    "▤",
    "数据准备",
    "数据管理",
    ["电源台账", "储能台账", "负荷与保供目标", "分类目标与优先级", "典型场景库"],
    ["workspace.settings"],
  ),
  define("scenario.workspace", "场景生成设置", "≈", "场景生成", "保供场景生成", [
    "近中远期全年背景",
    "源荷增长与极端窗口",
    "故障与恢复场景",
    "生产序列嵌入",
    "典型场景库",
    "分类目标与优先级",
  ]),
  define(
    "balance.workspace",
    "平衡分析",
    "∑",
    "平衡分析",
    "电力电量平衡",
    [
      "平衡结果",
      "模型与资源",
      "运行阶段",
      "计算任务",
      "网络逐时结果",
      "逐设备时序调度",
      "随机生产模拟",
      "逐设备年度滚动",
      "原生年度流水线",
    ],
    ["workspace.settings", "data.validate", "balance.run", "result.export"],
  ),
  define(
    "optimization.strategy",
    "保供能力提升",
    "↗",
    "保供优化",
    "保供能力提升",
    ["效果对比", "策略库", "资源调整"],
  ),
  define(
    "optimization.investment",
    "源储协同配置",
    "▥",
    "保供优化",
    "源储协同配置",
    [
      "配置结果",
      "候选资源",
      "目标与约束",
      "规划阶段",
      "一二次协同规划",
      "灵活组网",
    ],
  ),
  define("results.workspace", "成果管理", "▣", "成果管理", "方案与报告", [
    "计算档案",
    "方案对比",
    "质效评价",
    "成果与交付",
    "配置方案",
    "示范区实证",
  ]),
  define(
    "research.disaster",
    "承灾极限分析",
    "△",
    "专项研究",
    "承灾极限分析",
    ["承灾边界", "分析设置", "薄弱环节"],
    ["workspace.settings"],
  ),
  define("research.island", "离网稳定判别", "◎", "专项研究", "离网稳定判别", [
    "风险结果",
    "判别对象",
    "扰动与阈值",
  ]),
  define(
    "research.blackstart",
    "黑启动路径优化",
    "⌁",
    "专项研究",
    "黑启动路径优化",
    ["恢复序列", "恢复分区", "启动资源", "一二次约束"],
    ["workspace.settings"],
  ),
  define("system.plan", "功能规划与验收", "✓", "系统管理", "系统与接口", [
    "功能规划与验收",
  ]),
  define("system.integration", "接口与交接", "⇄", "系统管理", "系统与接口", [
    "接入清单",
    "算法接口",
    "交接任务",
  ]),
  define("system.configuration", "系统配置", "⚙", "系统管理", "系统配置", [
    "系统配置",
  ]),
];
export function resolveWorkspace(menu: string, section?: string) {
  if (menu === "系统与接口" && section === "计算任务")
    return workspaces.find((w) => w.id === "balance.workspace")!;
  if (
    menu === "数据管理" &&
    ["数据版本管理", "源储参数", "经济参数"].includes(section || "")
  )
    return workspaces.find((w) => w.id === "data.source")!;
  return (
    workspaces.find(
      (w) => w.menu === menu && (!section || w.sections.includes(section)),
    ) ||
    workspaces.find((w) => w.menu === menu) ||
    workspaces[0]
  );
}
export const stepLabels: Record<string, string> = {
  近中远期全年背景: "全年背景",
  源荷增长与极端窗口: "极端事件",
  故障与恢复场景: "设备故障与恢复",
  生产序列嵌入: "生产序列嵌入",
  成果与交付: "报告与交付",
};

export const stageDisplayNames:Record<string,string>={'场景生成':'场景生成设置'};
