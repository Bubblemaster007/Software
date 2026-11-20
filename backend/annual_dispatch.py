"""Rolling device/network dispatch with committed-prefix accounting and archives."""
import calendar
import math
import time
from datetime import datetime, timedelta
from typing import Literal
from pydantic import Field, model_validator
from backend.engineering import StrictModel, Inventory, canonical_sha
from backend.resource_dispatch import (DispatchInput, dispatch, continuation_state,
                                       DispatchIncomplete, DispatchInfeasible)
from backend.study_control import StudyCancelled

METHOD = 'devices.radial.annual-rolling.v1'


class AnnualDispatchInput(StrictModel):
    base: DispatchInput
    name: str = Field('逐设备年度滚动生产模拟', min_length=1, max_length=100)
    coverage_mode: Literal['calendar_year', 'series'] = 'calendar_year'
    total_steps: int = Field(8760, ge=1, le=35136)
    commit_steps: int = Field(24, ge=1, le=672)
    wall_time_seconds: float = Field(600, ge=1, le=3600)
    grid_available_kw: list[float] | None = None
    source_curve_kw: dict[str, list[float]] = Field(default_factory=dict)
    load_curve_kw: dict[str, list[float]] = Field(default_factory=dict)
    device_availability: dict[str, list[float]] = Field(default_factory=dict)
    line_status: dict[int, list[Literal[0, 1]]] = Field(default_factory=dict)
    source_commitment: dict[str, list[Literal[0, 1]]] = Field(default_factory=dict)
    required_energized_nodes: dict[int, list[Literal[0, 1]]] = Field(default_factory=dict)
    source_energy_additions_kwh: dict[str, list[float]] = Field(default_factory=dict)
    provenance: str = Field('用户提供年度剖面，请填写数据来源', min_length=1, max_length=2000)

    @model_validator(mode='after')
    def timing(self):
        if self.base.step_hours not in (.25, .5, 1):
            raise ValueError('年度入口支持15/30/60分钟')
        if self.commit_steps > self.base.steps:
            raise ValueError('提交步数须不大于前瞻窗口步数')
        if self.coverage_mode == 'calendar_year':
            start = self.base.start
            if (start.month, start.day, start.hour, start.minute, start.second, start.microsecond) != (1, 1, 0, 0, 0, 0):
                raise ValueError('完整年度须从1月1日零时开始，短序列请选择指定时段')
            hours = (366 if calendar.isleap(start.year) else 365)*24
            if abs(self.total_steps*self.base.step_hours-hours) > 1e-8:
                raise ValueError('完整年度步数须覆盖该日历年的全部小时，闰年含8784小时')
        return self


PROFILE_FIELDS = ('device_availability', 'line_status', 'source_commitment',
                  'required_energized_nodes', 'source_energy_additions_kwh')


def check_curve(values, count, name, maximum=1000000):
    if len(values) not in (1, count) or any(not math.isfinite(v) or not 0 <= v <= maximum for v in values):
        raise ValueError(name+'须为一个常值或与年度步数一致的有限非负数组')


def slice_curve(values, offset, count):
    return values[:] if len(values) == 1 else values[offset:offset+count]


def profiles(req, inventory):
    sources = [a for a in inventory.sources if a.existing or req.base.include_candidates]
    loads = [a for a in inventory.loads if a.existing or req.base.include_candidates]
    if not loads:
        raise ValueError('年度模拟须有参与负荷')
    if not req.source_curve_kw.keys() <= {a.id for a in sources} or not req.load_curve_kw.keys() <= {a.id for a in loads}:
        raise ValueError('年度源荷曲线引用未参与的设备')
    result = {'grid_available_kw': req.grid_available_kw if req.grid_available_kw is not None else req.base.grid_available_kw,
              'source_curve_kw': {}, 'load_curve_kw': {}}
    check_curve(result['grid_available_kw'], req.total_steps, '年度网供')
    for key in PROFILE_FIELDS:
        result[key] = {**getattr(req.base, key), **getattr(req, key)}
        for ident, values in result[key].items():
            check_curve(values, req.total_steps, str(ident), 1 if key != 'source_energy_additions_kwh' else 1e12)
    for asset in sources:
        values = req.source_curve_kw.get(asset.id, asset.curve_kw)
        if not values:
            if asset.kind in ('风电', '光伏', '小水电'):
                raise ValueError(asset.id+'缺少年度风光水曲线')
            values = [asset.rated_kw]
        check_curve(values, req.total_steps, asset.id+'年度出力', asset.rated_kw)
        result['source_curve_kw'][asset.id] = values
    for asset in loads:
        values = req.load_curve_kw.get(asset.id, asset.curve_kw or [asset.peak_kw])
        check_curve(values, req.total_steps, asset.id+'年度负荷', asset.peak_kw)
        result['load_curve_kw'][asset.id] = values
    return result


def window_input(req, inventory, data, offset, state):
    count = min(req.base.steps, req.total_steps-offset)
    values = req.base.model_dump(mode='json') | state
    values.update(steps=count, start=(req.base.start+timedelta(hours=offset*req.base.step_hours)).isoformat(),
                  elapsed_hours=req.base.elapsed_hours+offset*req.base.step_hours,
                  require_complete_target_horizon=False, allow_zero_demand=True)
    values['grid_available_kw'] = slice_curve(data['grid_available_kw'], offset, count)
    for key in PROFILE_FIELDS:
        values[key] = {ident: slice_curve(curve, offset, count) for ident, curve in data[key].items()}
    # Keep one reserve definition across all windows, including future deliveries.
    values['source_forming_reserve_kwh'] = req.base.source_forming_reserve_kwh.copy()
    for asset in inventory.sources:
        if not asset.existing and not req.base.include_candidates:
            continue
        if asset.fuel_kwh is None or asset.id in values['source_forming_reserve_kwh']:
            continue
        reference = max(asset.fuel_kwh, req.base.initial_source_fuel_kwh.get(asset.id, asset.fuel_kwh),
                        max(data['source_energy_additions_kwh'].get(asset.id, [0])))
        if reference > 0:
            values['source_forming_reserve_kwh'][asset.id] = reference*req.base.forming_reserve_ratio
    actual = inventory.model_copy(deep=True)
    for key, assets in [('source_curve_kw', actual.sources), ('load_curve_kw', actual.loads)]:
        for asset in assets:
            if asset.id in data[key]:
                asset.curve_kw = slice_curve(data[key][asset.id], offset, count)
    return DispatchInput.model_validate(values), actual


def validate_annual(req, inventory, network):
    from backend.resource_dispatch import build_dispatch_model
    data = profiles(req, inventory)
    # Check references and physical schema without solving a preview window.
    params, actual = window_input(req, inventory, data, 0, {})
    build_dispatch_model(params, actual, network)
    return data


def committed_metrics(rows, req, inventory):
    dt = req.step_hours
    result = {name: sum(row[key] for row in rows)*dt for name, key in (
        ('load_energy_kwh', 'load_kw'), ('served_energy_kwh', 'served_kw'),
        ('total_unsupplied_energy_kwh', 'total_unsupplied_kw'),
        ('controlled_curtailment_energy_kwh', 'controlled_curtailment_kw'),
        ('shortage_energy_kwh', 'shortage_kw'), ('grid_energy_kwh', 'grid_kw'))}
    result['maximum_shortage_kw'] = max((row['total_unsupplied_kw'] for row in rows), default=0)
    result['maximum_balance_residual_kw'] = max((abs(row['power_balance_residual_kw']) for row in rows), default=0)
    result['unsupplied_hours'] = sum(row['total_unsupplied_kw'] > 1e-6 for row in rows)*dt
    result['renewable_curtailment_energy_kwh'] = sum(a['renewable_curtailment_kw'] for row in rows for a in row['sources'])*dt
    thermal = {a.id for a in inventory.sources if a.kind in ('柴油机', '移动发电车')}
    cost = 0.
    for row in rows:
        cost += row['grid_kw']*dt*req.grid_energy_yuan_per_kwh
        cost += sum(a['dispatch_kw'] for a in row['sources'] if a['id'] in thermal)*dt*inventory.economics.fuel_yuan_per_kwh
        cost += sum(bool(a['startup_command']) for a in row['sources'])*req.source_start_cost_yuan
        cost += sum(a['charge_kw']+a['discharge_kw'] for a in row['storage'])*dt*req.storage_cycle_yuan_per_kwh
        cost += row['controlled_curtailment_kw']*dt*inventory.economics.curtailment_yuan_per_kwh
    result['study_dispatch_cost_yuan'] = cost
    return result


def run_annual(req, inventory, network, progress=None, cancelled=None, window_sink=None):
    started = time.monotonic()
    data = validate_annual(req, inventory, network)
    offset, state, windows, details = 0, {}, [], []
    totals = {key: 0. for key in ('load_energy_kwh', 'served_energy_kwh', 'total_unsupplied_energy_kwh',
              'controlled_curtailment_energy_kwh', 'shortage_energy_kwh', 'grid_energy_kwh', 'study_dispatch_cost_yuan',
              'unsupplied_hours', 'renewable_curtailment_energy_kwh')}
    totals.update(maximum_shortage_kw=0., maximum_balance_residual_kw=0.)
    reason, limited = None, 0
    while offset < req.total_steps:
        if cancelled and cancelled():
            raise StudyCancelled('年度计算已取消，已提交窗口保存在独立档案')
        remaining = req.wall_time_seconds-(time.monotonic()-started)
        if remaining < 1:
            reason = {'kind': 'time_limit', 'at_step': offset}
            break
        params, actual = window_input(req, inventory, data, offset, state)
        params.time_limit_seconds = min(params.time_limit_seconds, remaining)
        def window_progress(value):
            if progress:
                progress({'phase': 'annual_rolling', 'completed_steps': offset, 'total_steps': req.total_steps,
                          'window_phase': value.get('phase'), 'fraction': offset/req.total_steps})
        try:
            forecast = dispatch(params, actual, network, window_progress, cancelled)
        except (DispatchIncomplete, DispatchInfeasible) as error:
            reason = {'kind': 'window_time_limit' if isinstance(error, DispatchIncomplete) else 'rolling_window_infeasible',
                      'at_step': offset, 'message': str(error)}
            break
        count = min(req.commit_steps, params.steps)
        committed = forecast['rows'][:count]
        for index, row in enumerate(committed):
            row['global_step'] = offset+index
        metrics = committed_metrics(committed, params, actual)
        next_state = continuation_state(params, actual, forecast, count)
        identity = f'window-{len(windows)+1:05}'
        signature = canonical_sha({'parameters': params.model_dump(mode='json'),
                                  'inventory': actual.model_dump(mode='json'), 'network': network.model_dump(mode='json')})
        summary = {'id': identity, 'offset_step': offset, 'committed_steps': count, 'forecast_steps': params.steps,
                   'start': committed[0]['timestamp'], 'end': next_state['start'], 'status': forecast['status'],
                   'input_sha256': signature, 'state_after_sha256': canonical_sha(next_state), 'metrics': metrics}
        artifact = {'summary': summary, 'parameters': params.model_dump(mode='json'),
                    'committed_rows': committed, 'state_after': next_state,
                    'forecast_metrics': forecast['metrics'], 'forecast_solver': {key: forecast[key] for key in (
                        'method', 'status', 'variables', 'constraints', 'solver', 'maximum_constraint_violation',
                        'maximum_bound_violation', 'maximum_integer_violation')},
                    'inventory_sha256': canonical_sha(actual.model_dump(mode='json'))}
        if window_sink:
            window_sink(identity, artifact)
        else:
            details.append(artifact)
        windows.append(summary)
        for key in totals:
            totals[key] = max(totals[key], metrics[key]) if key.startswith('maximum_') else totals[key]+metrics[key]
        limited += forecast['status'] != 'optimal'
        offset += count
        state = next_state
        if progress:
            progress({'phase': 'annual_committed', 'completed_steps': offset, 'total_steps': req.total_steps,
                      'completed_windows': len(windows), 'fraction': offset/req.total_steps})
    full = offset == req.total_steps
    target_results = []
    for asset in inventory.loads:
        if not asset.existing and not req.base.include_candidates:
            continue
        maximum = state.get('initial_max_target_interruption_hours', req.base.initial_max_target_interruption_hours).get(
            asset.id, req.base.initial_target_interruption_hours.get(asset.id, 0))
        allowance = asset.maximum_interruption_hours if asset.interruption_allowed else 0
        end = req.base.load_target_start_hours.get(asset.id, 0)+asset.target_hours
        status = ('failed' if maximum > allowance+1e-8 else 'not_checked'
                  if req.base.elapsed_hours+offset*req.base.step_hours+1e-9 < end or not windows
                  or not state.get('prior_target_history_complete') else 'passed')
        target_results.append({'id': asset.id, 'maximum_target_interruption_hours': maximum,
                               'total_target_interruption_hours': state.get('initial_total_target_interruption_hours', {}).get(asset.id, 0),
                               'target_status': status})
    totals['load_supply_ratio'] = totals['served_energy_kwh']/totals['load_energy_kwh'] if totals['load_energy_kwh'] else None
    result = {'method': METHOD, 'status': 'complete' if full and not limited else 'incomplete',
              'coverage': {'mode': req.coverage_mode, 'requested_steps': req.total_steps, 'completed_steps': offset,
                           'step_hours': req.base.step_hours, 'full_input_covered': full,
                           'calendar_year_complete': full and req.coverage_mode == 'calendar_year'},
              'metrics': totals, 'load_metrics': target_results, 'windows': windows,
              'terminal_state': state, 'stop_reason': reason, 'limited_windows': limited,
              'runtime_seconds': time.monotonic()-started,
              'scope': ['按前瞻窗口重新优化，提交前缀后传递实际末状态。时间网格固定，经济结果为滚动策略的实际结果。全年度全局最优性仍待验证。',
                        '统计仅累计已提交区间，前瞻重叠部分保留预测求解指标。完整年度模式校验日历年和闰年，指定时段模式按实际覆盖计。',
                        '目标起始小时以同一事件起点计，支持年内事件窗口。短前瞻内硬目标逐步约束，完整目标判定随已确认前史和实际覆盖更新。',
                        '源荷曲线按设备逐条提供常值或完整序列。数据首项对应输入开始时刻，常值明确表示整个输入区间的固定值。',
                        '已提交窗口独立归档，包含完整提交轨迹、实际末状态、前瞻指标和求解残差。任务中断后仍可读取这些窗口。重试从冻结输入重新计算。',
                        '本模块采用无损LinDistFlow和既有设备假设，空载耗油、启动辅助能量、多电压交流及动态过程仍待补齐。项目规模和精度验收继续进行。']}
    if not window_sink:
        result['window_details'] = details
    return result
