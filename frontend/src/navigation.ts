export const dataMenuGroups = [
 {label:'资料接入',items:['源荷时序']},
 {label:'网络模型',items:['电网拓扑','变压器与开关','二次设备与通信']},
 {label:'设备与负荷',items:['电源台账','储能台账','负荷与保供目标']},
 {label:'参数配置',items:['源储参数','经济参数']},
 {label:'数据治理',items:['地理与灾害','数据版本管理']}
];
export const balanceMenuGroups = [
 {label:'输入设置',items:['模型与资源','运行阶段']},
 {label:'计算分析',items:['逐设备时序调度','随机生产模拟','逐设备年度滚动']},
 {label:'结果查看',items:['平衡结果','网络逐时结果']},
 {label:'专项研究',items:['原生年度流水线']}
];
/** Business hierarchy follows the final deck; children point to working views or draft tabs. */
export const children:Record<string,string[]>={
 '工程工作台':['工程概览','操作流程','工程信息'],
 '数据管理':dataMenuGroups.flatMap(group=>group.items),
 '保供场景生成':['典型场景库','分类目标与优先级','源荷增长与极端窗口','近中远期全年背景','故障与恢复场景','生产序列嵌入'],
 '承灾极限分析':['分析设置','承灾边界','薄弱环节'],
 '电力电量平衡':balanceMenuGroups.flatMap(group=>group.items),
 '保供能力提升':['策略库','资源调整','效果对比'],
 '源储协同配置':['候选资源','目标与约束','规划阶段','一二次协同规划','灵活组网','配置结果'],
 '离网稳定判别':['判别对象','扰动与阈值','风险结果'],
 '黑启动路径优化':['恢复分区','启动资源','一二次约束','恢复序列'],
 '方案与报告':['计算档案','方案对比','配置方案','质效评价','示范区实证','成果与交付'],
 '系统与接口':['计算任务','功能规划与验收','接入清单','算法接口','交接任务']
};
export const balanceAnchors:Record<string,string>={'运行阶段':'balance-phases','模型与资源':'balance-input','平衡结果':'balance-result','随机生产模拟':'balance-random','网络逐时结果':'balance-network','逐设备时序调度':'balance-device','逐设备年度滚动':'balance-annual','原生年度流水线':'balance-native'};
export const sectionAnchors:Record<string,Record<string,string>>={
 '工程工作台':{'工程概览':'project-overview','操作流程':'project-workflow','工程信息':'project-info'},
 '电力电量平衡':balanceAnchors,
 '保供能力提升':{'策略库':'strategy-library','资源调整':'strategy-adjustment','效果对比':'strategy-comparison'},
 '方案与报告':{'计算档案':'report-archive','方案对比':'report-comparison','配置方案':'report-plans'},
 '系统与接口':{'接入清单':'integration-catalog','算法接口':'integration-modules','交接任务':'integration-requests'}
};

export {workspaces} from './workspaceRegistry';
import {workspaces} from './workspaceRegistry';
export const workflowNavigation=['工程工作台','数据准备','场景生成','平衡分析','保供优化','成果管理','专项研究','系统管理'].map(label=>({label,items:workspaces.filter(w=>w.stage===label).map(w=>({id:w.id,label:w.label,menu:w.menu,sections:w.sections}))}));
