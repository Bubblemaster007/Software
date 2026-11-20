"""Finite epsilon-constraint risk/cost sweep and one-factor re-optimization.

Every point uses the actual shared-investment MILP. Training and validation
frontiers are distinct; neither is claimed to be a complete/global Pareto set.
"""
import time
from typing import Literal
from pydantic import Field, model_validator
from backend.engineering import StrictModel, Inventory, canonical_sha
from backend.investment_planning import InvestmentInput, investment_plan, validate_investment
from backend.resource_dispatch import DispatchIncomplete
from backend.study_control import StudyCancelled

METHOD = 'investment.finite-risk-sweep.oat.v1'


class SensitivityCase(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    parameter: Literal['load_scale', 'capital_cost_scale', 'annual_maintenance_scale',
                       'fuel_price_scale', 'discount_rate', 'storage_temperature_factor']
    value: float = Field(ge=0, le=1000)

    @model_validator(mode='after')
    def domain(self):
        if self.parameter == 'load_scale' and self.value <= 0:
            raise ValueError('负荷倍率须大于0')
        if self.parameter in ('discount_rate', 'storage_temperature_factor') and self.value > 1:
            raise ValueError('折现率/储能有效温度系数须在0—1之间')
        return self


class InvestmentExperimentInput(InvestmentInput):
    probability_levels: list[float] = Field(default_factory=lambda: [.8, .9, .95, 1], max_length=12)
    sensitivities: list[SensitivityCase] = Field(default_factory=list, max_length=12)
    per_case_time_seconds: float = Field(120, ge=1, le=3600)

    @model_validator(mode='after')
    def experiments(self):
        if len(set(self.probability_levels)) != len(self.probability_levels) or any(not 0 < p <= 1 for p in self.probability_levels):
            raise ValueError('概率扫描水平须不重复且在0—1之间')
        if len({s.name for s in self.sensitivities}) != len(self.sensitivities):
            raise ValueError('敏感性算例名称须唯一')
        if len({(s.parameter, s.value) for s in self.sensitivities}) != len(self.sensitivities):
            raise ValueError('敏感性参数和值不得重复')
        return self


def definitions(req):
    cases = [{'id': 'baseline', 'name': '基准', 'kind': 'baseline', 'parameter': 'required_probability', 'value': req.required_probability}]
    cases += [{'id': f'risk-{i+1:02}', 'name': f'达标概率{p:g}', 'kind': 'risk', 'parameter': 'required_probability', 'value': p}
              for i, p in enumerate(req.probability_levels) if abs(p-req.required_probability) > 1e-12]
    cases += [{'id': f'sensitivity-{i+1:02}', 'kind': 'sensitivity', **s.model_dump()} for i, s in enumerate(req.sensitivities)]
    return cases


def apply_case(req, inventory, case):
    values = req.model_dump(exclude={'probability_levels', 'sensitivities', 'per_case_time_seconds'})
    actual = inventory.model_copy(deep=True)
    parameter, value = case['parameter'], case['value']
    if parameter == 'required_probability':
        values['required_probability'] = value
    elif parameter == 'discount_rate':
        values['discount_rate'] = value
    elif parameter == 'load_scale':
        for stage in values['stages']:
            stage['load_scale'] *= value
    elif parameter == 'capital_cost_scale':
        for c in values['candidates']:
            for key in ('capex_yuan', 'power_capex_yuan', 'energy_capex_yuan', 'fixed_capex_yuan'):
                if c[key] is not None:
                    c[key] *= value
    elif parameter == 'annual_maintenance_scale':
        for c in values['candidates']:
            for key in ('annual_maintenance_yuan', 'power_maintenance_yuan', 'energy_maintenance_yuan', 'fixed_annual_maintenance_yuan'):
                if c[key] is not None:
                    c[key] *= value
        values['existing_annual_maintenance_yuan'] = {k: v*value for k, v in values['existing_annual_maintenance_yuan'].items()}
        actual.economics.annual_maintenance_yuan *= value
    elif parameter == 'fuel_price_scale':
        actual.economics.fuel_yuan_per_kwh *= value
    elif parameter == 'storage_temperature_factor':
        if not actual.storage:
            raise ValueError('温度敏感性须有参与的储能台账')
        # Absolute factor for every participating storage, in every trajectory/phase.
        ids = {a.id for a in actual.storage if a.existing or a.id in {c['asset_id'] for c in values['candidates']}}
        if not ids:
            raise ValueError('温度敏感性没有参与本研究的储能')
        for a in actual.storage:
            if a.id in ids:
                a.temperature_factor = value
        for scenario in values['scenarios']+values['validation_scenarios']:
            scenario['storage_temperature_factor'].update({i: value for i in ids})
            for override in scenario['stage_overrides'].values():
                override['storage_temperature_factor'] = {**(override['storage_temperature_factor'] or {}), **{i: value for i in ids}}
    return InvestmentInput.model_validate(values), Inventory.model_validate(actual.model_dump())


def validate_experiments(req, inventory, network):
    for case in definitions(req):
        params, actual = apply_case(req, inventory, case)
        validate_investment(params, actual, network)


def non_dominated(rows, validated=False):
    probability_key = 'validation_success_probability_lower' if validated else 'training_success_probability'
    candidates = [r for r in rows if r['kind'] != 'sensitivity' and r.get('objective_yuan') is not None
                  and r.get(probability_key) is not None and (not validated or r.get('validation_status') == 'passed')]
    selected = []
    for row in candidates:
        cost, probability = row['objective_yuan'], row[probability_key]
        def dominates(other):
            tolerance = max(1e-6, abs(cost)*1e-9, abs(other['objective_yuan'])*1e-9)
            return (other['objective_yuan'] <= cost+tolerance and
                    other[probability_key] >= probability-1e-9 and
                    (other['objective_yuan'] < cost-tolerance or other[probability_key] > probability+1e-9))
        if not any(dominates(other) for other in candidates if other is not row):
            selected.append(row['id'])
    return selected


def run_experiments(req, inventory, network, progress=None, cancelled=None, solver_runner=None, case_sink=None):
    started = time.monotonic()
    validate_experiments(req, inventory, network)
    cases, rows = definitions(req), []
    for index, case in enumerate(cases):
        if cancelled and cancelled():
            raise StudyCancelled('配置对比研究已取消')
        remaining = req.wall_time_seconds-(time.monotonic()-started)
        if remaining < 1:
            rows.append({**case, 'status': 'not_run_time_limit', 'objective_yuan': None})
            continue
        params, actual = apply_case(req, inventory, case)
        params.wall_time_seconds = min(req.per_case_time_seconds, remaining)
        signature = canonical_sha({'parameters': params.model_dump(mode='json'),
                                   'inventory': actual.model_dump(mode='json'), 'network': network.model_dump(mode='json')})
        def case_progress(value):
            if progress:
                progress({'phase': 'investment_experiments', 'case_id': case['id'], 'case_name': case['name'],
                          'case_phase': value.get('phase'), 'completed_cases': index, 'requested_cases': len(cases),
                          'fraction': (index+min(.99, value.get('fraction', 0)))/len(cases)})
        print('Investment experiment case:', case['id'], signature, flush=True)
        try:
            result = investment_plan(params, actual, network, case_progress, cancelled, solver_runner)
        except StudyCancelled:
            raise
        except DispatchIncomplete as exc:
            rows.append({**case, 'status': 'incomplete_solve', 'objective_yuan': None, 'error': str(exc), 'derived_input_sha256': signature})
            continue
        # Native/protocol/physical exceptions abort the study; never disguise them as infeasible points.
        compliance = result.get('compliance', [])
        probability = (result.get('all_periods_actual_probability') if req.risk_scope == 'all_periods'
                       else min((p['actual_probability'] for p in compliance), default=None))
        validation = next((c['status'] for c in result.get('checks', []) if c['name'] == '独立输入样本外加权达标验证'), 'not_checked')
        tested = ([result['validation_all_periods']] if req.risk_scope == 'all_periods' and result.get('validation_all_periods')
                  else result.get('validation', []))
        expected = []
        for pi in range(len(compliance)):
            expected.append(sum(s.weight*trace['result']['metrics']['total_unsupplied_energy_kwh']
                                for trace in result['scenario_results'] if trace['period'] == pi
                                for s in req.scenarios if s.id == trace['scenario_id']))
        row = {**case, 'status': result['status'], 'objective_yuan': result['objective_yuan'],
               'training_success_probability': probability, 'all_periods_training_probability': result.get('all_periods_actual_probability'),
               'worst_period_expected_event_unsupplied_kwh': max(expected, default=None),
               'expected_event_unsupplied_kwh_by_period': expected,
               'validation_status': validation, 'recommendation_status': result.get('recommendation_status'),
               'validation_success_probability_lower': min((v['success_probability_lower'] for v in tested), default=None),
               'validation_success_probability_upper': min((v['success_probability_upper'] for v in tested), default=None),
               'selected_assets': result['selected_assets'], 'solver': result['solver'], 'derived_input_sha256': signature,
               'requested_probability': params.required_probability, 'case_wall_time_seconds': params.wall_time_seconds}
        if case_sink:
            case_sink(case['id'], {'definition': case, 'derived_input_sha256': signature,
                                  'parameters': params.model_dump(mode='json'), 'result': result,
                                  'inventory_sha256': canonical_sha(actual.model_dump(mode='json')),
                                  'inventory_overrides': {'economics': actual.economics.model_dump(mode='json'),
                                      'storage_temperature_factor': {a.id: a.temperature_factor for a in actual.storage}}})
            row['detail_archived'] = True
        else:
            row['detail'] = result
        rows.append(row)
    baseline = rows[0].get('objective_yuan')
    for row in rows:
        cost = row.get('objective_yuan')
        row['delta_objective_yuan'] = cost-baseline if cost is not None and baseline is not None else None
        row['relative_objective_change'] = (cost-baseline)/abs(baseline) if cost is not None and baseline is not None and abs(baseline)>1e-8 else None
    if cancelled and cancelled():
        raise StudyCancelled('配置对比提交前取消')
    if progress:
        progress({'phase': 'complete', 'fraction': 1, 'completed_cases': len(rows), 'requested_cases': len(cases)})
    return {'method': METHOD, 'status': 'complete' if all(r['status'] in ('complete', 'infeasible') for r in rows) else 'incomplete',
            'cases': rows, 'training_non_dominated': non_dominated(rows), 'validated_non_dominated': non_dominated(rows, True),
            'runtime_seconds': time.monotonic()-started,
            'scope': ['概率扫描采用同一冻结场景和投资模型，输出所计算水平下的非支配子集，保留重合点各自要求。前沿完整性和全局最优性仍需继续验证。',
                      '基准和概率扫描沿用共同成本与负荷假设进行非支配比较。敏感性算例每次相对原基准改变一个因素并重新优化。',
                      '每期模式横轴风险使用最差运营期实际训练达标概率；跨期模式使用全部时期联合达标概率，另列跨期概率。',
                      '训练集合使用实际训练概率。已验证集合使用样本外成功概率下界，并要求该算例通过样本外验证。下界按未知权重计，地区风险统计保证和动态安全许可仍待验收。',
                      '温度为各参与储能统一绝对有效系数，覆盖所有训练/验证及阶段；折现率为绝对值，其他参数为基准倍率。',
                      '缺供为最差运营期的加权代表事件未供电量，包含主动削减。统计时域为输入事件窗口，年度指标需要完整年度剖面和事件频次。',
                      '算例串行执行，总时限与单例时限同时生效，未运行、未求完和不可行分别保留。所得结论适用于输入概率和参数取值。',
                      '完整单例轨迹独立归档并保留参数与摘要；课题3资料继续留空，真实概率校准、动态及正式性能精度尚未验收。']}
