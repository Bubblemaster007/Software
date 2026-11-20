const fields:Record<string,string>={engineering_revision:'台账版本',project_revision:'工程版本',step_hours:'时间步长',steps:'计算步数',grid_available_kw:'电网容量曲线',grid_reactive_limit_kvar:'电网无功限额',branch_limit_kva:'线路容量',forming_reserve_ratio:'构网预留比例',device_availability:'设备可用系数',line_status:'线路状态',reactive_limit_kvar:'设备无功上限',apparent_limit_kva:'设备视在功率上限',capacity_kva:'线路视在功率容量',time_limit_seconds:'求解时限',voltage_min_pu:'电压下限',voltage_max_pu:'电压上限',linear_voltage_guard_pu:'线性调度电压保护阈值',network_parameters:'网络参数',wind_node:'风电接入节点',pv_node:'光伏接入节点',parameters:'资源参数',stages:'运行阶段',name:'名称',end_hour:'结束小时',grid_ratio:'电网可用比例',emergency_ratio:'应急电源可用比例',failed_lines:'故障支路',storage_power_kw:'储能功率',storage_energy_kwh:'储能容量',emergency_gen_kw:'应急电源功率',grid_channel_kw:'外部供电上限',soc_initial_ratio:'初始SOC',soc_min_ratio:'SOC下限',soc_max_ratio:'SOC上限',eta_charge:'充电效率',eta_discharge:'放电效率',critical_load_ratio:'关键负荷占比',important_load_ratio:'重要负荷占比',csv:'源荷CSV',event_csv:'事件CSV',background_csv:'背景CSV',samples:'样本数',seed:'随机种子',start_hour:'嵌入起始小时',ramp_hours:'平滑时长',window:'窗口时长',growth:'负荷增长比例',wind_scale:'风电系数',pv_scale:'光伏系数',branch_limit_kw:'支路容量',rated_kw:'资源额定容量',rate_per_hour:'每小时失效率',failure_rate_per_hour:'每小时失效率',repair_hours:'修复时长'};
Object.assign(fields,{candidates:'候选设备',asset_id:'设备编号',capex_yuan:'投资成本',annual_maintenance_yuan:'年维护费',lifetime_years:'寿命',earliest_year:'最早投运年',latest_year:'最晚投运年',stages:'建设阶段',year:'年份',duration_years:'覆盖年数',budget_yuan:'阶段预算',annual_occurrences:'年事件频次',scenarios:'训练场景',validation_scenarios:'样本外场景',required_probability:'目标概率',risk_scope:'联合范围',protected_classes:'保护类别',weight:'场景权重',probability_provenance:'概率来源',load_scale:'负荷系数',source_curve_kw:'电源曲线',load_curve_kw:'负荷曲线',base:'调度参数'});

Object.assign(fields,{enforce_load_targets:'强制台账保供目标',target_policy:'保供目标判据',sizing_mode:'容量方式',fuel_budget_mode:'燃料预算方式',minimum_power_fraction:'最小功率比例',maximum_power_fraction:'最大功率比例',minimum_energy_fraction:'最小能量比例',maximum_energy_fraction:'最大能量比例',power_capex_yuan:'参考功率投资',energy_capex_yuan:'参考能量投资',power_maintenance_yuan:'参考功率维护费',energy_maintenance_yuan:'参考能量维护费',fixed_capex_yuan:'固定建设费',fixed_annual_maintenance_yuan:'固定年维护费',minimum_duration_hours:'最小储能时长',maximum_duration_hours:'最大储能时长'});
function location(loc:unknown):string{
 if(!Array.isArray(loc))return '';
 return loc.filter(x=>x!=='body').map(x=>typeof x==='number'?`第${x+1}项`:(fields[x]||x)).join(' / ');
}
function message(item:any):string{
 const c=item.ctx||{};
 const bounds:Record<string,string>={greater_than_equal:`须大于或等于${c.ge}`,greater_than:`须大于${c.gt}`,less_than_equal:`须小于或等于${c.le}`,less_than:`须小于${c.lt}`};
 if(bounds[item.type])return bounds[item.type];
 if(item.type==='missing')return '请填写此项';
 if(item.type==='finite_number')return '须为有限数值';
 if(['float_parsing','float_type','int_parsing','int_type'].includes(item.type))return '请输入有效数值';
 if(item.type==='int_from_float')return '须为整数';
 if(item.type==='string_too_short')return `至少填写${c.min_length}个字符`;
 if(item.type==='string_too_long')return `最多填写${c.max_length}个字符`;
 if(item.type==='extra_forbidden')return '不支持此参数';
 return String(item.msg||'输入不符合要求').replace(/^Value error, /,'');
}
export function apiError(detail:unknown,status?:number):string{
 if(typeof detail==='string'&&detail.trim())return detail;
 if(Array.isArray(detail)&&detail.length)return detail.map(item=>[location(item.loc),message(item)].filter(Boolean).join('：')).join('；');
 if(status===409)return '工程版本已更新，请重新载入工程后重试';
 if(status===404)return '未找到所选记录，请刷新后重试';
 if(status&&status>=500)return '计算服务发生错误，请保留当前输入并检查本地服务日志';
 return '请求未能完成，请检查输入后重试';
}
