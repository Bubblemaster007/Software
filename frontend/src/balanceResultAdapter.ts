export function recordedCondition(result: any): string {
  const value =
    result?.operating_condition ?? result?.input_snapshot?.operating_condition;
  return value === "normal" || value === "常规运行"
    ? "常规运行"
    : value === "extreme" || value === "极端保供"
      ? "极端保供"
      : "工况未记录";
}
export function balanceMetrics(result: any) {
  const m = result?.metrics || {};
  const definitions = [
    [
      "loss_of_load_probability",
      "缺供时段占比",
      "%",
      100,
      "单条确定性轨迹缺供时段占比，不是校准的灾害概率",
    ],
    [
      "curtailment_probability",
      "弃电时段占比",
      "%",
      100,
      "单条确定性轨迹弃电时段占比",
    ],
    [
      "max_power_deficit_kw",
      "电力不足极大值",
      "MW",
      0.001,
      "逐时功率缺额最大值，kW 转 MW",
    ],
    [
      "max_curtailment_kw",
      "弃电电力极大值",
      "MW",
      0.001,
      "逐时弃电最大值，kW 转 MW",
    ],
    [
      "expected_energy_deficit_kwh",
      "累计缺供电量",
      "MWh",
      0.001,
      "单条轨迹累计电量，不是多场景期望值",
    ],
    [
      "expected_curtailment_energy_kwh",
      "累计弃电电量",
      "MWh",
      0.001,
      "单条轨迹累计电量，不是多场景期望值",
    ],
  ] as const;
  return definitions.map(([key, label, unit, scale, scope]) => ({
    key,
    label,
    unit,
    scope,
    value:
      typeof m[key] === "number" && Number.isFinite(m[key])
        ? (m[key] * scale).toFixed(3)
        : null,
  }));
}
