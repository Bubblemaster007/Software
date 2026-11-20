"""Shared-investment, multi-period weighted joint-chance MILP.

Discrete blocks and bounded continuous designs retain device/network physics. No candidate
enumeration, ex-post capacity fudge, or per-scenario investment foresight is used.
Operating profiles are representative events; annual frequency is explicit.
"""
import math
import time
from typing import Literal
import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp
from pydantic import Field, model_validator
from backend.engineering import StrictModel, Inventory, canonical_sha
from backend.network_data import Network
from backend.resource_dispatch import (DispatchInput, SparseModel, build_dispatch_model,
                                       decode_dispatch, validate_solution, DispatchIncomplete,
                                       add_target_constraints, target_success)
from backend.study_control import StudyCancelled

METHOD = 'investment.multiperiod.weighted-joint-chance-milp.v3'
CLASSES = ('基本保障', '居民生活', '一般负荷')
MAX_VARIABLES = 250000


class CandidateInvestment(StrictModel):
    asset_id: str = Field(min_length=1, max_length=64)
    capex_yuan: float = Field(ge=0, le=1e12)
    annual_maintenance_yuan: float = Field(0, ge=0, le=1e10)
    sizing_mode: Literal['block', 'continuous'] = 'block'
    fuel_budget_mode: Literal['fixed_stock', 'proportional'] = 'fixed_stock'
    minimum_power_fraction: float = Field(.05, ge=1e-4, le=1)
    maximum_power_fraction: float = Field(1, ge=1e-4, le=1)
    minimum_energy_fraction: float = Field(.05, ge=1e-4, le=1)
    maximum_energy_fraction: float = Field(1, ge=1e-4, le=1)
    power_capex_yuan: float | None = Field(None, ge=0, le=1e12)
    energy_capex_yuan: float | None = Field(None, ge=0, le=1e12)
    power_maintenance_yuan: float | None = Field(None, ge=0, le=1e10)
    energy_maintenance_yuan: float | None = Field(None, ge=0, le=1e10)
    fixed_capex_yuan: float = Field(0, ge=0, le=1e12)
    fixed_annual_maintenance_yuan: float = Field(0, ge=0, le=1e10)
    minimum_duration_hours: float = Field(.25, ge=0, le=1000)
    maximum_duration_hours: float | None = Field(None, gt=0, le=1000)
    lifetime_years: int = Field(15, ge=1, le=100)
    earliest_year: int | None = Field(None, ge=2020, le=2200)
    latest_year: int | None = Field(None, ge=2020, le=2200)
    provenance: str = Field('用户研究成本，需工程确认', min_length=1, max_length=1000)

    @model_validator(mode='after')
    def sizing_bounds(self):
        if self.minimum_power_fraction > self.maximum_power_fraction or self.minimum_energy_fraction > self.maximum_energy_fraction:
            raise ValueError('连续容量最小比例不能超过最大比例')
        if self.maximum_duration_hours is not None and self.minimum_duration_hours > self.maximum_duration_hours:
            raise ValueError('最小储能时长不能超过最大时长')
        return self


class OperatingProfile(StrictModel):
    grid_available_kw: list[float] = Field(default_factory=lambda: [0], min_length=1, max_length=672)
    load_scale: float = Field(1, gt=0, le=100)
    source_curve_kw: dict[str, list[float]] = Field(default_factory=dict)
    load_curve_kw: dict[str, list[float]] = Field(default_factory=dict)
    device_availability: dict[str, list[float]] = Field(default_factory=dict)
    line_status: dict[int, list[Literal[0, 1]]] = Field(default_factory=dict)
    storage_temperature_factor: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode='after')
    def temperature(self):
        if any(not 0 <= value <= 1 for value in self.storage_temperature_factor.values()):
            raise ValueError('储能温度系数须在0—1之间，同时限制有效功率和能量')
        return self


class OperatingOverride(StrictModel):
    """None means inherit, including after frozen JSON roundtrips across processes."""
    grid_available_kw: list[float] | None = Field(None, min_length=1, max_length=672)
    load_scale: float | None = Field(None, gt=0, le=100)
    source_curve_kw: dict[str, list[float]] | None = None
    load_curve_kw: dict[str, list[float]] | None = None
    device_availability: dict[str, list[float]] | None = None
    line_status: dict[int, list[Literal[0, 1]]] | None = None
    storage_temperature_factor: dict[str, float] | None = None


class WeightedScenario(OperatingProfile):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field('条件研究场景', min_length=1, max_length=100)
    weight: float = Field(gt=0, le=1)
    stage_overrides: dict[int, OperatingOverride] = Field(default_factory=dict)
    provenance: str = Field('人工研究样本，未经地区概率校准', min_length=1, max_length=1000)


class ConstructionStage(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    year: int = Field(ge=2020, le=2200)
    duration_years: int = Field(1, ge=1, le=50)
    budget_yuan: float | None = Field(None, ge=0, le=1e12)
    load_scale: float = Field(1, gt=0, le=100)
    annual_occurrences: float = Field(1, ge=0, le=525600)


class InvestmentInput(StrictModel):
    base: DispatchInput
    name: str = Field('多阶段源储机会约束配置', min_length=1, max_length=100)
    candidates: list[CandidateInvestment] = Field(min_length=1, max_length=40)
    stages: list[ConstructionStage] = Field(min_length=1, max_length=8)
    scenarios: list[WeightedScenario] = Field(min_length=1, max_length=30)
    validation_scenarios: list[WeightedScenario] = Field(default_factory=list, max_length=30)
    required_probability: float = Field(.95, gt=0, le=1)
    risk_scope: Literal['per_period', 'all_periods'] = 'per_period'
    target_policy: Literal['every_step', 'interruption_budget'] = 'every_step'
    protected_classes: list[Literal['基本保障', '居民生活', '一般负荷']] = Field(default_factory=lambda: ['基本保障', '居民生活'], min_length=1, max_length=3)
    discount_rate: float = Field(.06, ge=0, le=1)
    salvage_policy: Literal['none', 'linear_remaining_life'] = 'none'
    existing_retirement_year: dict[str, int] = Field(default_factory=dict)
    existing_annual_maintenance_yuan: dict[str, float] = Field(default_factory=dict)
    total_investment_budget_yuan: float | None = Field(None, ge=0, le=1e12)
    shortage_yuan_per_kwh: dict[str, float] = Field(default_factory=dict)
    probability_provenance: str = Field('用户研究权重，非已校准地区概率', min_length=1, max_length=2000)
    wall_time_seconds: float = Field(600, ge=1, le=3600)
    relative_gap: float = Field(.001, ge=0, le=.2)

    @model_validator(mode='after')
    def consistency(self):
        if self.base.elapsed_hours > 0 and not self.base.prior_target_history_complete:
            raise ValueError('延续事件的配置验证需要完整中断前史声明')
        if len(set(self.protected_classes)) != len(self.protected_classes):
            raise ValueError('保供类别不得重复')
        if len({a.asset_id for a in self.candidates}) != len(self.candidates):
            raise ValueError('候选设备不得重复；多个单元须使用不同设备ID')
        if any(b.year != a.year+a.duration_years for a, b in zip(self.stages, self.stages[1:])):
            raise ValueError('建设阶段须按年份连续排列，避免遗漏中间年份成本与寿命')
        if self.stages[-1].year+self.stages[-1].duration_years-self.stages[0].year > 60:
            raise ValueError('规划时域最多60年')
        horizon = self.base.steps*self.base.step_hours
        if any(s.annual_occurrences*horizon > 8760+1e-8 for s in self.stages):
            raise ValueError('代表事件频次×事件时长不能超过标准年的8760小时')
        for cases in [self.scenarios, self.validation_scenarios]:
            if cases and (len({s.id for s in cases}) != len(cases) or abs(sum(s.weight for s in cases)-1) > 1e-8):
                raise ValueError('训练/验证集各自须编号唯一、权重之和为1，不自动归一化')
            if any(not set(s.stage_overrides) <= {p.year for p in self.stages} for s in cases):
                raise ValueError('场景分阶段覆盖引用不存在的建设年份')
        if {s.id for s in self.scenarios} & {s.id for s in self.validation_scenarios}:
            raise ValueError('训练与样本外验证编号须分开')
        def physical(s):
            return canonical_sha(s.model_dump(exclude={'id', 'name', 'weight', 'provenance'}))
        if {physical(s) for s in self.scenarios} & {physical(s) for s in self.validation_scenarios}:
            raise ValueError('样本外验证不能只是改名的相同物理输入')
        if not self.shortage_yuan_per_kwh.keys() <= set(CLASSES) or any(not 0 <= c <= 1e8 for c in self.shortage_yuan_per_kwh.values()):
            raise ValueError('分类缺供成本须为有效类别的有限非负数')
        if any(not 2020 <= y <= 2300 for y in self.existing_retirement_year.values()):
            raise ValueError('已有设备退役年份无效')
        if any(not 0 <= cost <= 1e10 for cost in self.existing_annual_maintenance_yuan.values()):
            raise ValueError('已有设备逐台年维护费须为有限非负数')
        for c in self.candidates:
            if c.earliest_year is not None and c.latest_year is not None and c.earliest_year > c.latest_year:
                raise ValueError('最早投运年不能晚于最晚投运年')
        return self


def prepared_inventory(req, inventory):
    candidate_ids = {c.asset_id for c in req.candidates}
    resources = {a.id: a for a in inventory.sources+inventory.storage}
    if not candidate_ids <= resources.keys() or any(resources[i].existing for i in candidate_ids):
        raise ValueError('投资候选须为台账中尚未建设的电源/储能，每个ID最多投运一次')
    for c in req.candidates:
        asset = resources[c.asset_id]
        if c.sizing_mode != 'continuous':
            if any(v is not None for v in (c.power_capex_yuan, c.energy_capex_yuan, c.power_maintenance_yuan, c.energy_maintenance_yuan)):
                raise ValueError('固定设备块只填写整台投资/维护费，不能同时填写连续容量分项成本')
            continue
        if hasattr(asset, 'energy_kwh'):
            if asset.power_kw <= 0 or asset.energy_kwh <= 0:
                raise ValueError('连续储能须提供正的台账参考功率和能量上限')
            if c.power_capex_yuan is None or c.energy_capex_yuan is None:
                raise ValueError('连续储能须分别提供满额参考功率、参考能量的投资成本，不自动拆分总价')
            if abs(c.power_capex_yuan+c.energy_capex_yuan-c.capex_yuan) > max(1e-6, c.capex_yuan*1e-8):
                raise ValueError('连续储能功率/能量投资分项之和须等于参考设备投资')
            if c.annual_maintenance_yuan and (c.power_maintenance_yuan is None or c.energy_maintenance_yuan is None):
                raise ValueError('连续储能非零维护费须分别填写功率/能量分项')
            if abs((c.power_maintenance_yuan or 0)+(c.energy_maintenance_yuan or 0)-c.annual_maintenance_yuan) > max(1e-6, c.annual_maintenance_yuan*1e-8):
                raise ValueError('连续储能维护费分项之和须等于参考设备维护费')
        elif any(v is not None for v in (c.power_capex_yuan, c.energy_capex_yuan, c.power_maintenance_yuan, c.energy_maintenance_yuan)):
            raise ValueError('连续电源按参考功率比例计价，不填写储能功率/能量分项成本')
    if not req.existing_retirement_year.keys() <= {a.id for a in resources.values() if a.existing}:
        raise ValueError('退役表只能引用已有源储设备')
    if not req.existing_annual_maintenance_yuan.keys() <= {a.id for a in resources.values() if a.existing}:
        raise ValueError('已有逐台维护费只能引用已有源储设备')
    inv = inventory.model_copy(deep=True)
    for key in ('sources', 'storage'):
        setattr(inv, key, [a for a in getattr(inv, key) if a.existing or a.id in candidate_ids])
    for key in ('loads', 'transformers', 'switches', 'controllers', 'terminals'):
        setattr(inv, key, [a for a in getattr(inv, key) if a.existing])
    return inv


def eligible_years(req, candidate):
    return [s.year for s in req.stages if (candidate.earliest_year is None or s.year >= candidate.earliest_year)
            and (candidate.latest_year is None or s.year <= candidate.latest_year)]


def operating_periods(req):
    start, end = req.stages[0].year, req.stages[-1].year+req.stages[-1].duration_years
    boundaries = {s.year for s in req.stages} | {end}
    boundaries |= {year+c.lifetime_years for c in req.candidates for year in eligible_years(req, c)
                   if start < year+c.lifetime_years < end}
    boundaries |= {y for y in req.existing_retirement_year.values() if start < y < end}
    ordered = sorted(boundaries)
    return [{'year': a, 'end_year': b, 'stage': next(s for s in req.stages if s.year <= a < s.year+s.duration_years)}
            for a, b in zip(ordered, ordered[1:])]


def validate_investment(req, inventory, network):
    inv = prepared_inventory(req, inventory)
    estimate = len(operating_periods(req))*len(req.scenarios)*req.base.steps*(len(network.nodes)+8*len(inv.sources)+8*len(inv.storage)+4*len(inv.loads))
    if estimate > MAX_VARIABLES:
        raise ValueError('联合规划预计超过25万变量；请调整输入规模，不能将缩减算例视为任务书性能验收')
    if not inv.loads:
        raise ValueError('请保存参与规划的已有负荷')


def scenario_model(req, inv, stage, scenario):
    profile = {k: getattr(scenario, k) for k in OperatingProfile.model_fields}
    if stage.year in scenario.stage_overrides:
        for key, value in scenario.stage_overrides[stage.year].model_dump(exclude_none=True).items():
            profile[key] = {**profile[key], **value} if isinstance(value, dict) else value
    profile = OperatingProfile.model_validate(profile)
    actual = inv.model_copy(deep=True)
    resources = {a.id: a for a in actual.sources}
    loads = {a.id: a for a in actual.loads}
    batteries = {a.id: a for a in actual.storage}
    if not profile.source_curve_kw.keys() <= resources.keys() or not profile.load_curve_kw.keys() <= loads.keys():
        raise ValueError('场景曲线引用不存在/未参与的电源或负荷')
    if not profile.storage_temperature_factor.keys() <= batteries.keys():
        raise ValueError('温度系数引用不存在/未参与的储能')
    for asset_id, factor in profile.storage_temperature_factor.items():
        batteries[asset_id].temperature_factor = factor
    for a in actual.sources:
        if a.id in profile.source_curve_kw:
            a.curve_kw = profile.source_curve_kw[a.id]
    for a in actual.loads:
        values = profile.load_curve_kw.get(a.id, a.curve_kw)
        scale = stage.load_scale*profile.load_scale
        ratio = a.reactive_kvar/a.peak_kw if a.peak_kw else 0
        a.peak_kw = max(a.peak_kw, max(values, default=0))*scale
        a.reactive_kvar = a.peak_kw*ratio
        a.curve_kw = [v*scale for v in values]
    actual = Inventory.model_validate(actual.model_dump())
    data = req.base.model_dump(mode='json')
    data.update(include_candidates=True, grid_available_kw=profile.grid_available_kw,
                device_availability={**data['device_availability'], **profile.device_availability},
                line_status={**data['line_status'], **profile.line_status})
    params = DispatchInput.model_validate(data)
    protected = [a for a in actual.loads if a.load_class in req.protected_classes and a.minimum_supply_ratio > 0 and a.target_hours > 0]
    if not protected or any(params.load_target_start_hours.get(a.id, 0)+a.target_hours-params.elapsed_hours
                            > params.steps*params.step_hours+1e-8 for a in protected):
        raise ValueError('机会约束须有正目标负荷，且时域必须覆盖所有受保护负荷目标时长')
    return params, actual


def economic_terms(req, inv, built):
    terms = dict(built.economics)
    for a in built.loads:
        cost = req.shortage_yuan_per_kwh.get(a.load_class, inv.economics.shortage_yuan_per_kwh)
        for f in built.frames:
            terms[f['loads'][a.id]['shortage']] = cost*built.dt
    return terms


def target_terms(req, built):
    terms, constraints = {}, []
    for a in built.loads:
        if a.load_class not in req.protected_classes:
            continue
        for f in built.frames:
            v = f['loads'][a.id]
            if v['required_kw'] > 0:
                terms[v['goal_shortage']] = built.dt
                constraints.append((v['served'], v['required_kw']))
    if not constraints:
        raise ValueError('受保护目标在本场景没有正电量，不能生成空的机会约束')
    return terms, constraints


def finite(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def meets_target(served, target):
    return served+max(1e-7, abs(target)*1e-8) >= target


def run_milp(model, terms, remaining, gap):
    objective = np.zeros(len(model.lower))
    for i, coefficient in terms.items():
        objective[i] += coefficient
    return milp(objective, integrality=np.asarray(model.integral), bounds=Bounds(model.lower, model.upper),
                constraints=LinearConstraint(model.matrix(), model.cl, model.cu),
                options={'time_limit': remaining, 'mip_rel_gap': gap})


def investment_plan(req: InvestmentInput, inventory: Inventory, network: Network, progress=None, cancelled=None, solver_runner=None):
    validate_investment(req, inventory, network)
    started = time.monotonic()
    inv, periods = prepared_inventory(req, inventory), operating_periods(req)
    base_year, end_year = req.stages[0].year, req.stages[-1].year+req.stages[-1].duration_years
    def check():
        if cancelled and cancelled():
            raise StudyCancelled('源储联合规划取消')
    def remaining():
        check()
        return req.wall_time_seconds-(time.monotonic()-started)
    def df(year):
        return (1+req.discount_rate)**(-(year-base_year))
    def add_objective(index, cost):
        objective[index] = objective.get(index, 0)+cost
    m, objective, builds, build_sizes, capital, maintenance = SparseModel(), {}, {}, {}, {}, {}
    by_id = {c.asset_id: c for c in req.candidates}
    resources = {a.id: a for a in inv.sources+inv.storage}
    for c in req.candidates:
        for year in eligible_years(req, c):
            x = m.var(0, 1, binary=True)
            builds[c.asset_id, year] = x
            if c.sizing_mode == 'continuous':
                p = m.var(0, c.maximum_power_fraction)
                m.add({p: 1, x: -c.minimum_power_fraction}, lower=0)
                m.add({p: 1, x: -c.maximum_power_fraction}, upper=0)
                if hasattr(resources[c.asset_id], 'energy_kwh'):
                    e = m.var(0, c.maximum_energy_fraction)
                    m.add({e: 1, x: -c.minimum_energy_fraction}, lower=0)
                    m.add({e: 1, x: -c.maximum_energy_fraction}, upper=0)
                    a = resources[c.asset_id]
                    m.add({e: a.energy_kwh, p: -c.minimum_duration_hours*a.power_kw}, lower=0)
                    if c.maximum_duration_hours is not None:
                        m.add({e: a.energy_kwh, p: -c.maximum_duration_hours*a.power_kw}, upper=0)
                    cap = {x: c.fixed_capex_yuan, p: c.power_capex_yuan, e: c.energy_capex_yuan}
                    om = {x: c.fixed_annual_maintenance_yuan, p: c.power_maintenance_yuan or 0, e: c.energy_maintenance_yuan or 0}
                else:
                    e = x if c.fuel_budget_mode == 'fixed_stock' else p
                    cap = {x: c.fixed_capex_yuan, p: c.capex_yuan}
                    om = {x: c.fixed_annual_maintenance_yuan, p: c.annual_maintenance_yuan}
                build_sizes[c.asset_id, year] = (p, e)
            else:
                cap = {x: c.capex_yuan+c.fixed_capex_yuan}
                om = {x: c.annual_maintenance_yuan+c.fixed_annual_maintenance_yuan}
            capital[c.asset_id, year], maintenance[c.asset_id, year] = cap, om
            salvage_fraction = max(0, year+c.lifetime_years-end_year)/c.lifetime_years if req.salvage_policy == 'linear_remaining_life' else 0
            for index, cost in cap.items():
                add_objective(index, cost*(df(year)-salvage_fraction*df(end_year)))
            for index, cost in om.items():
                add_objective(index, cost*sum(df(y+1) for y in range(year, min(end_year, year+c.lifetime_years))))
        m.add({i: 1 for (asset, year), i in builds.items() if asset == c.asset_id}, upper=1)
    for stage in req.stages:
        if stage.budget_yuan is not None:
            m.add({i: cost for (a, year), terms in capital.items() if year == stage.year for i, cost in terms.items()}, upper=stage.budget_yuan)
    budget = req.total_investment_budget_yuan
    if budget is None:
        budget = inv.economics.investment_limit_yuan
    if budget is not None:
        m.add({i: cost for terms in capital.values() for i, cost in terms.items()}, upper=budget)
    constant = inv.economics.annual_maintenance_yuan*sum(df(y+1) for y in range(base_year, end_year))
    constant += sum(cost*sum(df(y+1) for y in range(base_year, min(end_year, req.existing_retirement_year.get(asset_id, end_year))))
                    for asset_id, cost in req.existing_annual_maintenance_yuan.items())
    blocks, risk_groups, active_periods, sizing_periods = [], {}, {}, {}
    for pi, period in enumerate(periods):
        stage, year = period['stage'], period['year']
        active, sizing = {}, {}
        for c in req.candidates:
            z = m.var(0, 1)
            links = {i: -1 for (asset, built_year), i in builds.items() if asset == c.asset_id and built_year <= year < built_year+c.lifetime_years}
            m.add({z: 1, **links}, 0, 0)
            active[c.asset_id] = z
            if c.sizing_mode == 'continuous':
                fractions = []
                for dimension in (0, 1):
                    v = m.var(0, 1)
                    links = {pair[dimension]: -1 for (asset, y), pair in build_sizes.items()
                             if asset == c.asset_id and y <= year < y+c.lifetime_years}
                    m.add({v: 1, **links}, 0, 0)
                    fractions.append(v)
                sizing[c.asset_id] = tuple(fractions)
        for asset_id, retirement in req.existing_retirement_year.items():
            active[asset_id] = m.var(int(year < retirement), int(year < retirement))
        active_periods[pi] = active
        sizing_periods[pi] = sizing
        group = 'all' if req.risk_scope == 'all_periods' else str(pi)
        if group not in risk_groups:
            risk_groups[group] = {s.id: m.var(0, 1, binary=True) for s in req.scenarios}
            m.add({risk_groups[group][s.id]: s.weight for s in req.scenarios}, lower=req.required_probability)
        factor = sum(df(y+1) for y in range(year, period['end_year']))*stage.annual_occurrences
        for scenario in req.scenarios:
            check()
            if remaining() < 1:
                raise DispatchIncomplete('联合建模达到总时限，未获得投资可行解')
            params, actual = scenario_model(req, inv, stage, scenario)
            built = build_dispatch_model(params, actual, network, cancelled=cancelled, model=m, activation=active, sizing=sizing)
            _, targets = target_terms(req, built)
            good = risk_groups[group][scenario.id]
            add_target_constraints(built, req.protected_classes, good, req.target_policy)
            costs = economic_terms(req, actual, built)
            for i, coefficient in costs.items():
                add_objective(i, coefficient*scenario.weight*factor)
            blocks.append({'period': pi, 'scenario': scenario, 'built': built, 'costs': costs, 'targets': targets, 'good': good})
            if len(m.lower) > MAX_VARIABLES:
                raise ValueError('联合规划实际变量超过25万，未提交求解')
            if progress:
                progress({'phase': 'building_investment', 'fraction': .3*len(blocks)/(len(periods)*len(req.scenarios)), 'models': len(blocks)})
    if remaining() < 1:
        raise DispatchIncomplete('联合建模达到总时限，未获得投资可行解')
    if progress:
        progress({'phase': 'solving_investment', 'fraction': .35, 'variables': len(m.lower), 'constraints': len(m.cl)})
    solved = (solver_runner or run_milp)(m, objective, remaining(), req.relative_gap)
    check()
    solver = {'status': int(solved.status), 'message': str(solved.message), 'relative_gap': finite(getattr(solved, 'mip_gap', None)),
              'dual_bound_yuan': finite(getattr(solved, 'mip_dual_bound', None)), 'requested_gap': req.relative_gap,
              'variables': len(m.lower), 'constraints': len(m.cl)}
    if solver['dual_bound_yuan'] is not None:
        solver['dual_bound_yuan'] += constant
    if solved.x is None:
        if progress:
            progress({'phase': 'infeasible' if solved.status == 2 else 'incomplete_solve', 'fraction': 1})
        return {'method': METHOD, 'status': 'infeasible' if solved.status == 2 else 'incomplete_solve',
                'solver': solver, 'selected_assets': [], 'training': [], 'validation': [], 'cashflows': [],
                'objective_yuan': None, 'checks': [{'name': '给定候选/预算/场景联合约束', 'status': 'failed' if solved.status == 2 else 'not_checked'}],
                'scope': ['无投资可行解；不能以零投资和零缺供代替失败结果。', '不可行仅针对当前候选、样本和静态近似约束。']}
    x = solved.x
    # Recheck the rounded discrete decisions against the actual (money and physical) rows.
    indices = np.flatnonzero(np.asarray(m.integral))
    rounded = x.copy()
    rounded[indices] = np.rint(rounded[indices])
    for pi, active in active_periods.items():
        for asset_id, index in active.items():
            if asset_id in by_id:
                rounded[index] = sum(rounded[i] for (a, y), i in builds.items()
                                     if a == asset_id and y <= periods[pi]['year'] < y+by_id[asset_id].lifetime_years)
        for asset_id, pair in sizing_periods[pi].items():
            for d, index in enumerate(pair):
                rounded[index] = sum(rounded[pair[d]] for (a, y), pair in build_sizes.items()
                                     if a == asset_id and y <= periods[pi]['year'] < y+by_id[asset_id].lifetime_years)
    certificate = validate_solution(m, rounded)
    x = rounded
    selected = []
    resources = {a.id: a for a in inv.sources+inv.storage}
    for (asset_id, year), index in builds.items():
        if x[index] > .5:
            asset = resources[asset_id]
            pair = build_sizes.get((asset_id, year))
            pf, ef = (float(x[pair[0]]), float(x[pair[1]])) if pair else (1., 1.)
            reference_power = asset.rated_kw if hasattr(asset, 'rated_kw') else asset.power_kw
            selected.append({'asset_id': asset_id, 'name': asset.name, 'node': asset.node, 'commission_year': year,
                             'retirement_year': year+by_id[asset_id].lifetime_years,
                             'sizing_mode': by_id[asset_id].sizing_mode, 'power_fraction': pf,
                             'energy_fraction': ef if hasattr(asset, 'energy_kwh') else None,
                             'fuel_fraction': ef if hasattr(asset, 'fuel_kwh') else None,
                             'fuel_budget_mode': by_id[asset_id].fuel_budget_mode if hasattr(asset, 'fuel_kwh') else None,
                             'reference_power_kw': reference_power, 'reference_energy_kwh': getattr(asset, 'energy_kwh', None),
                             'capex_yuan': float(sum(v*x[i] for i, v in capital[asset_id, year].items())),
                             'annual_maintenance_yuan': float(sum(v*x[i] for i, v in maintenance[asset_id, year].items())),
                             'power_kw': reference_power*pf,
                             'energy_kwh': asset.energy_kwh*ef if hasattr(asset, 'energy_kwh') else None})
    training, traces, period_cost = [], [], {}
    for block in blocks:
        check()
        pi, case = block['period'], block['scenario']
        result = decode_dispatch(block['built'], x, certificate=certificate, joint=True)
        actual_good = target_success(block['built'], x, req.protected_classes, req.target_policy)
        event_cost = sum(v*x[i] for i, v in block['costs'].items())
        training.append({'period': pi, 'scenario_id': case.id, 'weight': case.weight, 'assigned_success': bool(x[block['good']]>.5),
                         'actual_success': actual_good, 'event_cost_yuan': float(event_cost),
                         'shortage_kwh': result['metrics']['shortage_energy_kwh']})
        period_cost[pi] = period_cost.get(pi, 0)+case.weight*event_cost*periods[pi]['stage'].annual_occurrences
        result['runtime_seconds'] = None
        traces.append({'period': pi, 'scenario_id': case.id, 'result': result})
    compliance = []
    for pi, period in enumerate(periods):
        rows = [r for r in training if r['period'] == pi]
        assigned = sum(r['weight'] for r in rows if r['assigned_success'])
        actual = sum(r['weight'] for r in rows if r['actual_success'])
        if actual+1e-8 < req.required_probability:
            raise ValueError('求解结果实际目标达标概率未满足机会约束，拒绝保存投资结论')
        compliance.append({'period': pi, 'year': period['year'], 'end_year': period['end_year'], 'stage_name': period['stage'].name,
                           'assigned_probability': assigned, 'actual_probability': actual, 'required_probability': req.required_probability,
                           'active_assets': [a.id for a in inv.sources+inv.storage if a.id not in active_periods[pi] or x[active_periods[pi][a.id]]>.5]})
    all_period_probability = sum(s.weight for s in req.scenarios if all(r['actual_success'] for r in training if r['scenario_id']==s.id))
    if req.risk_scope == 'all_periods' and all_period_probability+1e-8 < req.required_probability:
        raise ValueError('跨期联合达标概率校核失败')
    cashflows = []
    for year in range(base_year, end_year):
        pi = next(i for i, p in enumerate(periods) if p['year'] <= year < p['end_year'])
        capex = sum(r['capex_yuan'] for r in selected if r['commission_year'] == year)
        candidate_om = sum(r['annual_maintenance_yuan'] for r in selected if r['commission_year'] <= year < r['retirement_year'])
        existing_om = sum(cost for asset_id, cost in req.existing_annual_maintenance_yuan.items() if year < req.existing_retirement_year.get(asset_id, end_year))
        om = candidate_om+existing_om+inv.economics.annual_maintenance_yuan
        salvage = sum(r['capex_yuan']*max(0, r['retirement_year']-end_year)/by_id[r['asset_id']].lifetime_years for r in selected) if year == end_year-1 and req.salvage_policy == 'linear_remaining_life' else 0
        operating = period_cost[pi]
        cashflows.append({'year': year, 'capex_yuan': capex, 'annual_maintenance_yuan': om, 'expected_operating_yuan': float(operating),
                          'fixed_maintenance_yuan': inv.economics.annual_maintenance_yuan, 'existing_asset_maintenance_yuan': existing_om, 'candidate_maintenance_yuan': candidate_om,
                          'terminal_salvage_yuan': salvage, 'investment_discount_factor': df(year), 'operating_discount_factor': df(year+1),
                          'discounted_total_yuan': float(capex*df(year)+(om+operating-salvage)*df(year+1))})
    objective_value = sum(v*x[i] for i, v in objective.items())+constant
    if solver['dual_bound_yuan'] is not None:
        if solver['dual_bound_yuan'] > objective_value+max(1e-4, abs(objective_value)*1e-8):
            raise ValueError('求解下界超过已校核投资可行解')
        solver['verified_relative_gap'] = max(0, objective_value-solver['dual_bound_yuan'])/max(1e-9, abs(objective_value))
    if abs(sum(c['discounted_total_yuan'] for c in cashflows)-objective_value) > max(1e-4, abs(objective_value)*1e-8):
        raise ValueError('现金流与MILP目标不一致')
    # Rounded investment budgets are checked again without relying on solver row scaling.
    for stage in req.stages:
        if stage.budget_yuan is not None and sum(r['capex_yuan'] for r in selected if r['commission_year']==stage.year) > stage.budget_yuan+1e-5:
            raise ValueError('舍入后的建设投资超过阶段预算')
    if budget is not None and sum(r['capex_yuan'] for r in selected) > budget+1e-5:
        raise ValueError('舍入后的建设投资超过总预算')
    validation = validate_portfolio(req, inv, network, periods, selected, remaining, progress, cancelled, solver_runner)
    unknown = any(v['unknown_probability'] > 1e-9 for v in validation)
    validation_joint = None
    if validation:
        statuses = {}
        for case in req.validation_scenarios:
            states = [s['status'] for period in validation for s in period['samples'] if s['scenario_id'] == case.id]
            statuses[case.id] = 'failed' if 'failed' in states else 'unknown' if 'unknown' in states else 'passed'
        lower = sum(c.weight for c in req.validation_scenarios if statuses[c.id] == 'passed')
        untested = sum(c.weight for c in req.validation_scenarios if statuses[c.id] == 'unknown')
        validation_joint = {'success_probability_lower': lower, 'success_probability_upper': lower+untested, 'unknown_probability': untested}
    validation_check = 'not_checked'
    if validation:
        tested = [validation_joint] if req.risk_scope == 'all_periods' else validation
        validation_check = 'passed' if all(v['success_probability_lower']+1e-8 >= req.required_probability for v in tested) else 'failed' if any(v['success_probability_upper']+1e-8 < req.required_probability for v in tested) else 'not_checked'
    gap_ok = solver.get('verified_relative_gap') is not None and solver['verified_relative_gap'] <= req.relative_gap+1e-7
    final_state = 'complete' if solved.status == 0 and gap_ok and not unknown else 'incomplete_validation' if unknown else 'incomplete_solve'
    if progress:
        progress({'phase': final_state, 'fraction': 1, 'selected_assets': len(selected)})
    return {'method': METHOD, 'status': final_state, 'solver': solver, 'certificate': certificate,
            'objective_yuan': float(objective_value), 'selected_assets': selected, 'cashflows': cashflows,
            'training': training, 'compliance': compliance, 'all_periods_actual_probability': all_period_probability,
            'validation': validation, 'validation_all_periods': validation_joint, 'scenario_results': traces,
            'recommendation_status': 'not_recommended_validation_failed' if validation_check == 'failed' else 'pending_validation' if validation_check == 'not_checked' else 'static_validated_dynamic_pending',
            'checks': [{'name': '共享投资/预算/投运寿命/加权机会约束', 'status': 'passed'},
                       {'name': '全模型原始约束和舍入整数校核', 'status': 'passed'},
                       {'name': '独立输入样本外加权达标验证', 'status': validation_check},
                       {'name': '交流网损/动态稳定/黑启动/一二次联合规划', 'status': 'not_checked'}],
            'runtime_seconds': time.monotonic()-started, 'environment': {'scipy': scipy.__version__, 'numpy': np.__version__},
            'target_policy': req.target_policy,
            'scope': ['目标判据可选每步达标或按台账最大连续中断预算；默认每步，预算模式仍在一个成功指标内同时约束所有保护负荷/时段。主动削减不豁免最低供电目标，累计中断另报。',
                      '候选可按固定设备块或有界连续设计混合配置；台账额定值为参考上限，比例在0—1内，正的最小比例至少万分之一。每ID最多建设一次，分期扩容/替换使用不同ID。',
                      '连续电源按功率比缩放曲线、最小出力、无功/视在功率及爬坡；可运行小时数不缩放。燃料默认使用安装后的台账固定库存，也可显式选择随功率比缩放。属同一参考技术的线性设计假设，需厂家确认。',
                      '连续储能功率/能量独立决策，投资与维护分项由用户提供，SOC/构网储备按实际能量计，功率/无功上限按实际功率计；可设最短/最长额定储能时长。效率、温度系数和启动参数保持参考技术值。',
                      '固定建设费/固定年维护费按安装0/1计，不随容量降低；线性寿命残值政策对全部资本分项使用同一设备寿命，不代表真实回收报价。',
                      '投资在所有训练轨迹间共享，运行按场景后验调度；未来投资没有按样本偷看选址，尚未建立自适应情景树投资。',
                      '各时期联合负荷/时段机会约束或跨全部时期联合机会约束可选，保留样本权重，不将边际概率相乘。',
                      '每步模式强于允许短时中断的目标；预算模式按台账连续中断小时及目标窗口交集计时。未经概率校准的SAA不代表真实地区风险保证。',
                      '自动按所有可能退役年拆分运营期，后期资产不提前使用，退役后不继续贡献能力。',
                      '投资期初、运营/维护期末计现值，残值政策显式可选；代表事件频次明确录入，不自动按8760外推灾害。',
                      '运营成本仅覆盖给定代表事件与频次；若缺正常运行场景，不能当作完整全寿命成本。',
                      '台账全局年维护费视为固定开销，已有逐台维护费随退役停止，候选维护费另列；输入时须避免重复计价。',
                      '阶段负荷系数相对基准，阶段内运行剖面保持不变；需逐年增长时应分年建阶段或提供对应剖面。',
                      '场景储能温度系数同时降额功率和能量，表示事件初始温度条件；阶段覆盖按设备键合并，不会因覆盖另一设备而清除已有故障。',
                      '每个代表事件独立初始SOC与燃料，不跨事件或跨年结转能量；单次事件内启停/燃料/SOC/线路/电压严格约束。',
                      '样本外优先检验受保护目标的物理可行性，再降低费用；未知样本保留在概率上下界，不提供未获依据的置信保证。',
                      '当前无损LinDistFlow及理想变比1变压器；动态判稳、恢复路径及一二次联合投资尚未在本模型中校核。']}


def validate_portfolio(req, inv, network, periods, selected, remaining, progress, cancelled, solver_runner=None):
    if not req.validation_scenarios:
        return []
    results = []
    by_id = {r['asset_id']: r for r in selected}
    for pi, period in enumerate(periods):
        samples = []
        for case in req.validation_scenarios:
            if cancelled and cancelled():
                raise StudyCancelled('样本外验证取消')
            state, trace = 'unknown', None
            if remaining() >= 1:
                params, actual = scenario_model(req, inv, period['stage'], case)
                m = SparseModel()
                active, sizing = {}, {}
                for c in req.candidates:
                    selected_asset = by_id.get(c.asset_id)
                    value = int(selected_asset is not None and selected_asset['commission_year'] <= period['year'] < selected_asset['retirement_year'])
                    active[c.asset_id] = m.var(value, value)
                    if c.sizing_mode == 'continuous':
                        pf = selected_asset['power_fraction'] if value else 0
                        ef = (selected_asset['energy_fraction'] if selected_asset['energy_kwh'] is not None else selected_asset['fuel_fraction']) if value else 0
                        sizing[c.asset_id] = (m.var(pf, pf), m.var(ef, ef))
                for asset_id, year in req.existing_retirement_year.items():
                    value = int(period['year'] < year)
                    active[asset_id] = m.var(value, value)
                built = build_dispatch_model(params, actual, network, cancelled=cancelled, model=m, activation=active, sizing=sizing)
                goals, targets = target_terms(req, built)
                if req.target_policy == 'interruption_budget':
                    good = m.var(0, 1, binary=True)
                    add_target_constraints(built, req.protected_classes, good, req.target_policy)
                    goals = {good: -1}  # prove existence of a schedule satisfying the actual budget
                local_end = time.monotonic()+min(params.time_limit_seconds, max(0, remaining()))
                solution, goal_optimized, logs, goal_feasible = None, False, [], None
                for index, terms in enumerate([goals, economic_terms(req, actual, built)]):
                    seconds = min(remaining(), local_end-time.monotonic())
                    if seconds < .01:
                        break
                    solved = (solver_runner or run_milp)(m, terms, seconds, 1e-7)
                    logs.append({'objective': '受保护目标' if index == 0 else '费用', 'status': int(solved.status)})
                    if solved.x is None:
                        break
                    solution = solved.x
                    if index == 0:
                        goal_optimized = solved.status == 0 and (req.target_policy != 'interruption_budget' or solution[good] < .5)
                        if target_success(built, solution, req.protected_classes, req.target_policy):
                            goal_feasible = solution.copy()
                    if solved.status != 0:
                        break
                    m.add(terms, upper=float(solved.fun)+max(1e-7, abs(float(solved.fun))*1e-8))
                if solution is not None:
                    if goal_feasible is not None and not target_success(built, solution, req.protected_classes, req.target_policy):
                        solution = goal_feasible
                        logs.append({'objective': '使用已验证目标可行解，避免费用层容差改变目标判定', 'status': 0})
                    certificate = validate_solution(m, solution)
                    passed = target_success(built, solution, req.protected_classes, req.target_policy)
                    state = 'passed' if passed else 'failed' if goal_optimized else 'unknown'
                    trace = decode_dispatch(built, solution, logs, certificate=certificate, joint=True)
                    trace['runtime_seconds'] = None
            samples.append({'scenario_id': case.id, 'weight': case.weight, 'status': state, 'result': trace})
            if progress:
                progress({'phase': 'validating_investment', 'fraction': .8+.19*(pi+len(samples)/len(req.validation_scenarios))/len(periods),
                          'period': pi, 'scenario_id': case.id})
        passed = sum(s['weight'] for s in samples if s['status'] == 'passed')
        unknown = sum(s['weight'] for s in samples if s['status'] == 'unknown')
        results.append({'period': pi, 'year': period['year'], 'end_year': period['end_year'], 'success_probability_lower': passed,
                        'success_probability_upper': passed+unknown, 'unknown_probability': unknown, 'samples': samples})
    return results
