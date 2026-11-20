"""Expose actual integration coverage instead of equating copied files with working features."""
from pathlib import Path
from backend.workspace import ROOT

CAPABILITIES=[
 ('源荷分解与多水平年背景','/api/source-studies','integrated','滚动均值近似分解、经验分位边界、独立重采样；不冒充VMD/Res-GRU/WGAN','load_uncertainty_model.py;renewable_uncertainty_model.py;annual_background_generator.py'),
 ('源荷耦合与压力窗口','/api/source-analysis','integrated','窗口评分映射不是灾害发生概率','source_load_coupling.py;src/chapter3/extreme_generator_adapter.py'),
 ('设备故障与连续修复','/api/scenarios/faults; /api/scenarios/sequential','integrated','参数由用户假设，尚需区域校准','topic2_remaining_code/fault_probability_model.py;src/chapter3/sequential_resource_states.py'),
 ('工况耦合与事件嵌入','/api/production-sequences','integrated','故障场景与事件时间轴须一致','topic2_remaining_code/coupled_condition_builder.py;topic2_remaining_code/annual_sequence_embedder.py'),
 ('平衡与分阶段指标','/api/balance; /api/random-balance','integrated','交互IEEE33限168小时，汇总模型限8760小时；随机统计是条件样本结果','src/chapter4/power_energy_balance.py;src/chapter4/case33_network_balance.py;phase_balance_analysis/src/phase_metrics.py'),
 ('八项提升策略','/api/strategy-evaluation','integrated','规则触发建议，移动资源调配和可达性尚未形成完整物理模型','topic2_remaining_code/strategy_trigger.py'),
 ('源储配置试算与复核','/api/planning; /api/plans/{id}/verify','simplified','原代码仅启发式枚举，尚无正式机会约束、位置与多阶段联合求解','topic2_remaining_code/resilience_reliability_planner.py'),
 ('论文SC-RCRB与训练实验','待补冻结成果后接入','awaiting_artifacts','研究脚本已保留；原配置论文路径不适用于本机，冻结模型、候选库、publication_protocol须补齐并验证','src/chapter3/current_paper_adapter.py;ExtremeScene_extreme_generation_package_clean_20260706_133018/code'),
 ('原生年度网络下游','/api/native-jobs','integrated','独立后台任务支持8760小时及原生天气、事件、容量和故障字段；固定IEEE33和测试故障率，未认证SC-RCRB','src/chapter3/current_paper_adapter.py;scripts/run_paper_reference_case33.py'),
 ('兰考拓扑与敏感性实验','研究脚本','research_only','参考拓扑适配和成对敏感性实验尚未形成通用平台入口；正式示范拓扑仍待接入','src/chapter3/lankao_topology_adapter.py;scripts/run_paper_reference_case33.py')
]
def catalog():
 return [{'name':name,'endpoint':endpoint,'status':status,'scope':scope,'sources':sources.split(';'),'source_present':all((ROOT/'vendor/topic2'/p).exists() for p in sources.split(';'))} for name,endpoint,status,scope,sources in CAPABILITIES]
