"""Multi-device, multi-period radial electrical dispatch with explicit study limits.

Sparse MILP: nodal P/Q balance, squared-voltage LinDistFlow, conservative octagonal
branch ratings, commitment/start delay, fuel, storage direction/SOC, and formation
of electrically separated islands. This is a scheduling/steady-state model, not
a substitute for the dynamic stability or black-start transient studies.
"""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
import io
import json
import math
import sqlite3
import time
import uuid

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import Field, model_validator
from backend.engineering import Inventory, StrictModel, canonical_sha, inventory_snapshot, validate_nodes
from backend.network_data import Network
from backend.workspace import project_record, case33

ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix='/api/device-dispatch', tags=['逐设备时序调度'])


class DispatchIncomplete(ValueError):
    """Time budget ended without a feasible incumbent; not evidence of infeasibility."""


class DispatchInfeasible(ValueError):
    """The stated scheduling constraints have no feasible solution."""


class DispatchInput(StrictModel):
    project_id: str
    project_revision: int = Field(ge=1)
    engineering_revision: int = Field(ge=1)
    name: str = Field('逐设备时序调度', min_length=1, max_length=100)
    start: datetime = datetime(2026, 1, 1)
    elapsed_hours: float = Field(0, ge=0, le=1000000)
    prior_target_history_complete: bool = False
    initial_state_provenance: str = Field('用户声明的初态', min_length=1, max_length=2000)
    steps: int = Field(24, ge=1, le=672)
    step_hours: float = Field(1, gt=0, le=1)
    grid_available_kw: list[float] = Field(default_factory=lambda: [0], min_length=1, max_length=672)
    grid_energy_yuan_per_kwh: float = Field(.5, ge=0, le=100000)
    storage_cycle_yuan_per_kwh: float = Field(.002, ge=0, le=100000)
    source_start_cost_yuan: float = Field(.0001, ge=0, le=100000)
    grid_reactive_limit_kvar: float = Field(0, ge=0, le=1000000)
    branch_limit_kva: float = Field(5000, gt=0, le=1000000)
    voltage_min_pu: float = Field(.95, ge=.8, le=1)
    voltage_max_pu: float = Field(1.05, ge=1, le=1.2)
    forming_reserve_ratio: float = Field(.02, gt=0, le=.5)
    initial_energized_nodes: list[int] = Field(default_factory=list, max_length=100)
    device_availability: dict[str, list[float]] = Field(default_factory=dict)
    line_status: dict[int, list[Literal[0, 1]]] = Field(default_factory=dict)
    source_commitment: dict[str, list[Literal[0, 1]]] = Field(default_factory=dict)
    required_energized_nodes: dict[int, list[Literal[0, 1]]] = Field(default_factory=dict)
    minimum_load_when_energized: dict[str, float] = Field(default_factory=dict)
    initial_source_on: dict[str, Literal[0, 1]] = Field(default_factory=dict)
    initial_source_power_kw: dict[str, float] = Field(default_factory=dict)
    initial_source_startup_remaining_steps: dict[str, int] = Field(default_factory=dict)
    initial_source_fuel_kwh: dict[str, float] = Field(default_factory=dict)
    initial_source_used_hours: dict[str, float] = Field(default_factory=dict)
    initial_storage_energy_kwh: dict[str, float] = Field(default_factory=dict)
    initial_target_interruption_hours: dict[str, float] = Field(default_factory=dict)
    initial_max_target_interruption_hours: dict[str, float] = Field(default_factory=dict)
    initial_total_target_interruption_hours: dict[str, float] = Field(default_factory=dict)
    source_energy_additions_kwh: dict[str, list[float]] = Field(default_factory=dict)
    source_forming_reserve_kwh: dict[str, float] = Field(default_factory=dict)
    allow_demand_response: bool = False
    enforce_load_targets: bool = False
    require_complete_target_horizon: bool = True
    load_target_start_hours: dict[str, float] = Field(default_factory=dict)
    include_candidates: bool = False
    allow_zero_demand: bool = False
    time_limit_seconds: float = Field(60, ge=1, le=120)

    @model_validator(mode='after')
    def scope(self):
        supported_steps = (1/60, 5/60, .25, .5, 1)
        if not any(abs(self.step_hours-v) < 1e-10 for v in supported_steps):
            raise ValueError('时间步仅支持1/5/15/30/60分钟')
        self.step_hours = min(supported_steps, key=lambda v: abs(self.step_hours-v))
        if self.steps * self.step_hours > 168:
            raise ValueError('逐设备交互计算当前限168小时')
        if self.voltage_min_pu >= self.voltage_max_pu:
            raise ValueError('电压下限须小于上限')
        if len(self.initial_energized_nodes) != len(set(self.initial_energized_nodes)):
            raise ValueError('初始带电节点不得重复')
        for label, values in [('外部供电容量', self.grid_available_kw)] + list(self.device_availability.items()):
            if len(values) not in (1, self.steps):
                raise ValueError(label + '曲线须为1个常值或与步数一致')
            maximum = 1000000 if label == '外部供电容量' else 1
            if any(not 0 <= value <= maximum for value in values):
                raise ValueError(label + '超出允许范围或包含非有限数')
        for values in [*self.line_status.values(), *self.source_commitment.values(), *self.required_energized_nodes.values()]:
            if len(values) not in (1, self.steps):
                raise ValueError('线路/启停/带电状态须为1个常值或与步数一致')
        if any(not 0 <= v <= 1 for v in self.minimum_load_when_energized.values()):
            raise ValueError('带电时负荷最低供电比例须在0—1之间')
        if any(not 0 <= value <= 1000000 for value in self.load_target_start_hours.values()):
            raise ValueError('负荷目标起始小时须为有限非负数')
        scalar_states = [self.initial_source_power_kw, self.initial_source_fuel_kwh,
                         self.initial_source_used_hours, self.initial_storage_energy_kwh,
                         self.initial_target_interruption_hours, self.initial_max_target_interruption_hours,
                         self.initial_total_target_interruption_hours, self.source_forming_reserve_kwh]
        if any(not 0 <= value <= 1e12 for state in scalar_states for value in state.values()):
            raise ValueError('衔接状态须为0至1e12之间的有限非负数')
        if any(value <= 0 for value in self.source_forming_reserve_kwh.values()):
            raise ValueError('显式构网燃料储备须大于0')
        if any(not 0 <= value <= 100000 for value in self.initial_source_startup_remaining_steps.values()):
            raise ValueError('剩余启动步数须在0—100000之间，0表示本步完成')
        for asset_id, values in self.source_energy_additions_kwh.items():
            if len(values) not in (1, self.steps) or any(not 0 <= v <= 1e12 for v in values):
                raise ValueError('可发电量补给须为有限非负kWh，提供每步数组或每步常值：'+asset_id)
        for asset_id in set(self.initial_target_interruption_hours) | set(self.initial_max_target_interruption_hours) | set(self.initial_total_target_interruption_hours):
            tail = self.initial_target_interruption_hours.get(asset_id, 0)
            maximum = self.initial_max_target_interruption_hours.get(asset_id, tail)
            total = self.initial_total_target_interruption_hours.get(asset_id, maximum)
            if not tail <= maximum+1e-9 <= total+2e-9 or total > self.elapsed_hours+1e-8:
                raise ValueError('中断历史须满足尾段≤历史最大≤累计≤已逝事件时长：'+asset_id)
        return self


class SparseModel:
    def __init__(self):
        self.lower, self.upper, self.integral = [], [], []
        self.rows, self.cols, self.data, self.cl, self.cu = [], [], [], [], []

    def var(self, lower=0, upper=np.inf, binary=False):
        index = len(self.lower)
        self.lower.append(lower)
        self.upper.append(upper)
        self.integral.append(int(binary))
        return index

    def add(self, terms, lower=-np.inf, upper=np.inf):
        row = len(self.cl)
        for variable, coefficient in terms.items():
            if coefficient:
                self.rows.append(row)
                self.cols.append(variable)
                self.data.append(coefficient)
        self.cl.append(lower)
        self.cu.append(upper)

    def matrix(self):
        return coo_matrix((self.data, (self.rows, self.cols)), shape=(len(self.cl), len(self.lower))).tocsc()


def repeated(values, steps, fallback, name):
    if not values:
        return np.full(steps, fallback, dtype=float)
    if len(values) not in (1, steps):
        raise ValueError(name + '曲线长度须为1或等于计算步数，不隐式截断或重采样')
    return np.full(steps, values[0], dtype=float) if len(values) == 1 else np.asarray(values, dtype=float)


def components(node_ids, edges):
    adjacency = {n: [] for n in node_ids}
    for edge in edges:
        adjacency[edge.from_node].append(edge.to_node)
        adjacency[edge.to_node].append(edge.from_node)
    groups, lookup = [], {}
    for node in node_ids:
        if node in lookup:
            continue
        queue = [node]
        lookup[node] = len(groups)
        for current in queue:
            for other in adjacency[current]:
                if other not in lookup:
                    lookup[other] = len(groups)
                    queue.append(other)
        groups.append(queue)
    if len(edges) != len(node_ids) - len(groups):
        raise ValueError('当前线路状态构成环网，逐设备LinDistFlow仅支持辐射森林')
    return groups, lookup


def limit_apparent(model, p, q, limit, scale=None):
    for k in range(8):
        angle = math.pi / 8 + k * math.pi / 4
        terms = {p: math.cos(angle), q: math.sin(angle)}
        bound = limit * math.cos(math.pi / 8)
        if scale is not None:
            terms[scale] = -bound
        model.add(terms, upper=bound if scale is None else 0)


def longest_run(flags, dt):
    longest = current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        longest = max(current, longest)
    return longest * dt


def target_interruption(required, served, dt, target_hours, initial_hours=0., start_hours=0.):
    """Maximum consecutive target deficit; clip the last step to the target window."""
    longest = current = initial_hours
    total = 0.
    for t, (goal, actual) in enumerate(zip(required, served)):
        duration = max(0., min((t+1)*dt, target_hours)-max(t*dt, start_hours))
        missed = goal > 0 and actual+max(1e-7, abs(goal)*1e-8) < goal
        current = current+duration if missed else 0.
        total += duration if missed else 0.
        longest = max(longest, current)
    return longest, total


def target_bounds(req, asset):
    start = req.load_target_start_hours.get(asset.id, 0)-req.elapsed_hours
    return start, start+asset.target_hours


def target_success(built, x, classes=None, policy='interruption_budget'):
    for a in built.loads:
        if classes is not None and a.load_class not in classes:
            continue
        required = [f['loads'][a.id]['required_kw'] for f in built.frames]
        served = [float(x[f['loads'][a.id]['served']]) for f in built.frames]
        start, end = target_bounds(built.req, a)
        maximum, _ = target_interruption(required, served, built.dt, end,
                                          built.req.initial_target_interruption_hours.get(a.id, 0), start)
        maximum = max(maximum, built.req.initial_max_target_interruption_hours.get(a.id, 0))
        budget = a.maximum_interruption_hours if a.interruption_allowed and policy == 'interruption_budget' else 0
        if maximum > budget+1e-8 or (built.req.require_complete_target_horizon and a.minimum_supply_ratio > 0
                                   and built.steps*built.dt+1e-9 < end):
            return False
    return True


def add_target_constraints(built, classes=None, success=None, policy='interruption_budget'):
    """Linear-size exact consecutive-outage clock; optional joint success indicator."""
    m = built.m
    nv, nc = len(m.lower), len(m.cl)
    for a in built.loads:
        if classes is not None and a.load_class not in classes:
            continue
        if (built.req.elapsed_hours > 0 and a.minimum_supply_ratio > 0 and a.target_hours > 0
                and not built.req.prior_target_history_complete):
            raise ValueError('延续事件的硬保供判据须提供完整中断前史声明：'+a.id)
        start, end = target_bounds(built.req, a)
        remaining_target = max(0, end-max(0, start))
        if built.req.require_complete_target_horizon and a.minimum_supply_ratio > 0 and end > built.steps*built.dt+1e-9:
            raise ValueError('硬保供目标须覆盖参与负荷的完整目标时长：'+a.id)
        budget = a.maximum_interruption_hours if a.interruption_allowed and policy == 'interruption_budget' else 0
        history = built.req.initial_target_interruption_hours.get(a.id, 0)
        maximum_history = max(history, built.req.initial_max_target_interruption_hours.get(a.id, 0))
        if maximum_history > budget+1e-8:
            m.add({success: 1} if success is not None else {}, upper=0 if success is not None else -1)
            continue
        previous = None
        for t, f in enumerate(built.frames):
            v = f['loads'][a.id]
            goal = v['required_kw']
            if goal <= 0:
                previous = None  # zero demand terminates a target outage run
                continue
            if budget >= remaining_target+history-1e-9:
                continue
            terms = {v['served']: 1}
            if success is not None:
                terms[success] = -goal
            if budget <= 1e-9:
                m.add(terms, lower=goal if success is None else 0)
                continue
            bad = m.var(0, 1, binary=True)
            terms[bad] = goal
            m.add(terms, lower=goal if success is None else 0)
            if success is not None:
                m.add({bad: 1, success: -1}, upper=0)
            duration = max(0., min((t+1)*built.dt, end)-max(t*built.dt, start))
            bound = min(budget, remaining_target+history)
            clock = m.var(0, bound)
            m.add({clock: 1, bad: -bound}, upper=0)
            big_m = bound+duration
            # bad=1 => clock=previous+duration; bad=0 => clock=0.
            lower = {clock: 1, bad: -big_m}
            upper = {clock: 1, bad: big_m}
            if previous is not None:
                lower[previous] = upper[previous] = -1
            preceding = history if t == 0 else 0
            m.add(lower, lower=duration-big_m+preceding)
            m.add(upper, upper=duration+big_m+preceding)
            previous = clock
    built.variable_count += len(m.lower)-nv
    built.constraint_count += len(m.cl)-nc
    if built.variable_count > 200000:
        raise ValueError('硬目标加入后单场景模型超过20万变量，请调整规模')


@dataclass
class DispatchModel:
    req: DispatchInput
    network: Network
    m: SparseModel
    dt: float
    steps: int
    nodes: list
    sources: list
    storage: list
    loads: list
    energy: dict
    frames: list
    economics: dict
    objectives: list
    activation: dict
    sizing: dict
    started: float
    variable_count: int
    constraint_count: int


def source_energy_profile(req, asset, steps):
    initial = req.initial_source_fuel_kwh.get(asset.id, asset.fuel_kwh)
    if initial is None:
        return None, None, None
    additions = repeated(req.source_energy_additions_kwh.get(asset.id, []), steps, 0, asset.id+'可发电量补给')
    reference = max(asset.fuel_kwh or 0, initial, float(additions.max()))
    reserve = req.source_forming_reserve_kwh.get(asset.id, reference*req.forming_reserve_ratio)
    return initial+np.cumsum(additions), additions, reserve


def build_dispatch_model(req: DispatchInput, inventory: Inventory, network: Network, progress=None, cancelled=None, model=None, activation=None, sizing=None):
    from backend.study_control import StudyCancelled
    def check_cancel():
        if cancelled and cancelled():
            raise StudyCancelled('用户请求取消')
    check_cancel()
    started = time.monotonic()
    dt, steps = req.step_hours, req.steps
    nodes = sorted(n.node for n in network.nodes)
    sources = [a for a in inventory.sources if a.existing or req.include_candidates]
    storage = [a for a in inventory.storage if a.existing or req.include_candidates]
    loads = [a for a in inventory.loads if a.existing or req.include_candidates]
    if not loads:
        raise ValueError('请先保存至少一个参与计算的负荷台账')
    if not set(req.initial_energized_nodes) <= set(nodes):
        raise ValueError('初始带电节点不属于计算网络')
    if not set(req.required_energized_nodes) <= set(nodes):
        raise ValueError('强制带电节点不属于计算网络')
    if not set(req.source_commitment) <= {a.id for a in sources}:
        raise ValueError('强制启停电源不属于参与计算的台账')
    if not set(req.minimum_load_when_energized) <= {a.id for a in loads}:
        raise ValueError('带电负荷约束引用不存在的参与负荷')
    source_ids = {a.id for a in sources}
    source_states = [req.initial_source_on, req.initial_source_power_kw,
                     req.initial_source_startup_remaining_steps, req.initial_source_fuel_kwh,
                     req.initial_source_used_hours, req.source_energy_additions_kwh,
                     req.source_forming_reserve_kwh]
    if any(not set(state) <= source_ids for state in source_states):
        raise ValueError('电源衔接或补给引用未参与的电源')
    if not set(req.initial_storage_energy_kwh) <= {a.id for a in storage}:
        raise ValueError('储能初始电量引用未参与的储能')
    load_states = [req.initial_target_interruption_hours, req.initial_max_target_interruption_hours,
                   req.initial_total_target_interruption_hours, req.load_target_start_hours]
    if any(not set(state) <= {a.id for a in loads} for state in load_states):
        raise ValueError('中断前史引用未参与的负荷')
    for asset in sources:
        power = req.initial_source_power_kw.get(asset.id, 0)
        pending = req.initial_source_startup_remaining_steps.get(asset.id)
        if power > asset.rated_kw+1e-8 or (power > 1e-8 and not req.initial_source_on.get(asset.id, 0)):
            raise ValueError('初始有功须匹配运行状态且不超过参考额定功率：'+asset.id)
        if pending is not None and (req.initial_source_on.get(asset.id, 0) or pending > math.ceil(asset.startup_minutes/(60*dt)-1e-12)):
            raise ValueError('剩余启动时间与设备启动时长或运行状态不符：'+asset.id)
        if asset.available_hours is not None and req.initial_source_used_hours.get(asset.id, 0) > asset.available_hours+1e-8:
            raise ValueError('已用运行小时超过台账可运行时长：'+asset.id)
        if asset.fuel_kwh is None and any(asset.id in state for state in
                (req.initial_source_fuel_kwh, req.source_energy_additions_kwh, req.source_forming_reserve_kwh)):
            raise ValueError('电量状态和补给需要台账先声明可发电量预算：'+asset.id)
    transformers = [a for a in inventory.transformers if a.existing or req.include_candidates]
    switches = [a for a in inventory.switches if a.existing or req.include_candidates]
    devices = inventory.sources + inventory.storage + inventory.loads + inventory.transformers + inventory.switches
    if not set(req.device_availability) <= {a.id for a in devices}:
        raise ValueError('设备可用曲线包含不存在或不支持的设备编号')
    if not set(req.line_status) <= {line.line for line in network.lines}:
        raise ValueError('线路状态包含不存在的线路编号')
    if steps * (len(nodes) + 8 * len(sources) + 7 * len(storage) + 4 * len(loads)) > 200000:
        raise ValueError('本次逐设备模型超过20万变量规模，请缩短时域或精简设备')
    grid = repeated(req.grid_available_kw, steps, 0, '电网')
    factors = {a.id: repeated(req.device_availability.get(a.id, []), steps, 1, a.id) * float(a.available)
               for a in devices}
    source_caps, fuel_profiles = {}, {}
    for a in sources:
        if a.kind in ('风电', '光伏', '小水电') and not a.curve_kw:
            raise ValueError(a.id + '缺少风光水可用曲线，不能将额定容量自动当作逐时出力')
        if a.kind in ('柴油机','移动发电车') and a.fuel_kwh is None and a.available_hours is None:
            raise ValueError(a.id+'缺少燃料可发电量或可运行时长，不能假定无限燃料')
        source_caps[a.id] = repeated(a.curve_kw, steps, a.rated_kw, a.id) * factors[a.id]
        profile, _, _ = source_energy_profile(req, a, steps)
        fuel_profiles[a.id] = profile
        if profile is not None:
            source_caps[a.id][profile <= 1e-9] = 0
    demands = {a.id: repeated(a.curve_kw, steps, a.peak_kw, a.id) for a in loads}
    if not req.allow_zero_demand and sum(float(v.sum()) for v in demands.values()) <= 0:
        raise ValueError('计算负荷电量须大于0')
    if any(a.peak_kw == 0 and a.reactive_kvar > 0 for a in loads):
        raise ValueError('当前负荷无功随有功比例变化，有功峰值为0时不能单设无功')
    edge_by_pair = {frozenset((line.from_node, line.to_node)): line for line in network.lines}
    transformer_edges = {}
    for transformer in transformers:
        if abs(transformer.ratio - 1) > 1e-9:
            raise ValueError('当前逐设备模型只支持统一电压基准的理想变压器（变比1），多电压等级尚待接入')
        edge = edge_by_pair.get(frozenset((transformer.node, transformer.to_node)))
        if edge is None:
            raise ValueError('请先在网络中建立变压器对应的支路：' + transformer.id)
        transformer_edges[transformer.id] = edge.line
    line_states = {line.line: repeated(req.line_status.get(line.line, []), steps, line.status, str(line.line)).astype(bool)
                   for line in network.lines}
    for switch in switches:
        if switch.line_id not in line_states:
            raise ValueError('开关引用线路不存在：' + switch.id)
        line_states[switch.line_id] &= factors[switch.id] > 0
        if switch.line_id not in req.line_status:
            line_states[switch.line_id] &= switch.normally_closed
    for transformer in transformers:
        line_states[transformer_edges[transformer.id]] &= factors[transformer.id] > 0

    m = model if model is not None else SparseModel()
    activation = activation or {}
    sizing = sizing or {}  # asset -> (power fraction variable, storage energy/source fuel fraction variable)
    if not set(activation) <= {a.id for a in sources+storage}:
        raise ValueError('投资激活约束引用未知源储设备')
    variable_start, constraint_start = len(m.lower), len(m.cl)
    if any(not 0 <= z < variable_start or m.lower[z] < 0 or m.upper[z] > 1 for z in activation.values()):
        raise ValueError('投资激活变量须为已建立的0—1主问题变量')
    if not set(sizing) <= set(activation) or any(
            len(pair) != 2 or any(not 0 <= z < variable_start or m.lower[z] < 0 or m.upper[z] > 1 for z in pair)
            for pair in sizing.values()):
        raise ValueError('连续容量比例须引用已激活设备及已建立的0—1有界主问题变量')
    def scaled(terms, limit, index):
        m.add({**terms, index: -limit} if index is not None else terms,
              upper=0 if index is not None else limit)
    def power_index(asset_id):
        return sizing[asset_id][0] if asset_id in sizing else activation.get(asset_id)
    def energy_index(asset_id):
        return sizing[asset_id][1] if asset_id in sizing else activation.get(asset_id)
    def product_fraction(index, binary):
        # Exact McCormick hull for [0,1] capacity fraction times binary support.
        w = m.var(0, 1)
        m.add({w: 1, index: -1}, upper=0)
        m.add({w: 1, binary: -1}, upper=0)
        m.add({w: 1, index: -1, binary: -1}, lower=-1)
        return w
    def upper_active(terms, limit, asset_id):
        if asset_id in activation:
            m.add({**terms, activation[asset_id]: -limit}, upper=0)
        else:
            m.add(terms, upper=limit)
    energy = {}
    for a in storage:
        capacity = a.energy_kwh * a.temperature_factor
        initial_energy = req.initial_storage_energy_kwh.get(a.id, capacity*a.initial_soc)
        if not capacity*a.minimum_soc-1e-8 <= initial_energy <= capacity*a.maximum_soc+1e-8:
            raise ValueError('衔接储能初始电量超出有效SOC范围：'+a.id)
        if a.id not in activation:
            energy[a.id] = [m.var(capacity * a.minimum_soc, capacity * a.maximum_soc) for _ in range(steps + 1)]
            m.add({energy[a.id][0]: 1}, initial_energy, initial_energy)
        else:
            z = energy_index(a.id)
            energy[a.id] = [m.var(0, capacity * a.maximum_soc) for _ in range(steps + 1)]
            for slot in energy[a.id]:
                m.add({slot: 1, z: -capacity*a.minimum_soc}, lower=0)
                m.add({slot: 1, z: -capacity*a.maximum_soc}, upper=0)
            m.add({energy[a.id][0]: 1, z: -initial_energy}, 0, 0)
    source_energy = {}
    for asset in sources:
        if fuel_profiles[asset.id] is None:
            continue
        initial = req.initial_source_fuel_kwh.get(asset.id, asset.fuel_kwh)
        states = [m.var(0, initial)] + [m.var(0, float(limit)) for limit in fuel_profiles[asset.id]]
        scale = energy_index(asset.id)
        if scale is None:
            m.add({states[0]: 1}, initial, initial)
        else:
            m.add({states[0]: 1, scale: -initial}, 0, 0)
        source_energy[asset.id] = states
    frames, economics = [], {}
    target_objectives = {cls: {} for cls in ('基本保障', '居民生活', '一般负荷')}
    supply_objectives = {cls: {} for cls in target_objectives}
    for t in range(steps):
        check_cancel()
        if progress and t % max(1, steps // 20) == 0:
            progress({'phase': 'building', 'fraction': .1 * t / steps})
        live_edges = [line for line in network.lines if line_states[line.line][t]]
        groups, lookup = components(nodes, live_edges)
        energized = [m.var(0, 1, binary=True) for _ in groups]
        for node, values in req.required_energized_nodes.items():
            if values[0 if len(values) == 1 else t]:
                m.add({energized[lookup[node]]: 1}, 1, 1)
        f = {'groups': groups, 'lookup': lookup, 'energized': energized,
             'voltage': {}, 'sources': {}, 'storage': {}, 'loads': {}, 'lines': {}, 'grid': None}
        p_balance, q_balance = {n: {} for n in nodes}, {n: {} for n in nodes}
        supporters = [[] for _ in groups]
        for group_index, group in enumerate(groups):
            e = energized[group_index]
            if 1 in group and grid[t] > 0:
                m.add({e: 1}, 1, 1)
            reference = 1 if 1 in group else min(group)
            for n in group:
                v = m.var(0, req.voltage_max_pu ** 2)
                f['voltage'][n] = v
                m.add({v: 1, e: -req.voltage_min_pu ** 2}, lower=0)
                m.add({v: 1, e: -req.voltage_max_pu ** 2}, upper=0)
                if n == reference:
                    m.add({v: 1, e: -1}, 0, 0)
        grid_p = m.var(0, grid[t])
        grid_q = m.var(-req.grid_reactive_limit_kvar if grid[t] > 0 else 0,
                       req.grid_reactive_limit_kvar if grid[t] > 0 else 0)
        p_balance[1][grid_p] = 1
        q_balance[1][grid_q] = 1
        economics[grid_p] = req.grid_energy_yuan_per_kwh * dt
        f['grid'] = (grid_p, grid_q)
        for a in sources:
            cap = float(source_caps[a.id][t])
            arrived = (t * dt+req.elapsed_hours) * 60 >= a.arrival_minutes - 1e-8
            available = cap > 1e-9 and arrived
            u = m.var(0, int(available), binary=True)
            if a.id in req.source_commitment:
                schedule = req.source_commitment[a.id]
                commitment = schedule[0 if len(schedule) == 1 else t]
                m.add({u: 1}, commitment, commitment)
            start = m.var(0, int(available), binary=True)
            if a.id in activation:
                upper_active({u: 1}, 1, a.id)
                upper_active({start: 1}, 1, a.id)
            p = m.var(0, cap if available else 0)
            q_limit = a.reactive_limit_kvar if available else 0
            q = m.var(-q_limit, q_limit)
            e = energized[lookup[a.node]]
            m.add({u: 1, e: -1}, upper=0)
            m.add({p: 1, u: -cap}, upper=0)
            if a.id in sizing:
                ps = power_index(a.id)
                scaled({p: 1}, cap, ps)
                scaled({q: 1}, q_limit, ps)
                scaled({q: -1}, q_limit, ps)
                m.add({ps: 1, u: -1e-4}, lower=0)
                m.add({ps: 1, start: -1e-4}, lower=0)
                m.add({p: 1, ps: -a.minimum_kw, u: -a.minimum_kw}, lower=-a.minimum_kw)
            else:
                m.add({p: 1, u: -a.minimum_kw}, lower=0)
            m.add({q: 1, u: -q_limit}, upper=0)
            m.add({q: 1, u: q_limit}, lower=0)
            if a.apparent_limit_kva is not None:
                limit_apparent(m, p, q, a.apparent_limit_kva, power_index(a.id))
            lag = math.ceil(a.startup_minutes / (60 * dt) - 1e-12)
            if t + lag >= steps or any(source_caps[a.id][k] <= 1e-9 for k in range(t, min(t + lag + 1, steps))):
                m.add({start: 1}, 0, 0)
            if not a.black_start:
                m.add({start: 1, e: -1}, upper=0)
            previous_u = frames[t - 1]['sources'][a.id]['on'] if t else None
            prior_start = frames[t - lag]['sources'][a.id]['start'] if lag and t >= lag else start if not lag else None
            initial_on = req.initial_source_on.get(a.id, 0) if t == 0 else 0
            pending = req.initial_source_startup_remaining_steps.get(a.id)
            pending_valid = pending is not None and all(source_caps[a.id][k] > 1e-9 for k in range(min(steps, pending+1)))
            ready = int(pending_valid and t == pending)
            if pending_valid and t <= pending:
                m.add({start: 1}, 0, 0)
            terms = {u: 1}
            if previous_u is not None:
                terms[previous_u] = -1
                m.add({start: 1, previous_u: 1}, upper=1)
            elif initial_on:
                m.add({start: 1}, upper=0)
            if prior_start is not None:
                terms[prior_start] = -1
            m.add(terms, upper=initial_on+ready)
            support = None
            if a.grid_forming and available:
                support = m.var(0, 1, binary=True)
                m.add({support: 1, u: -1}, upper=0)
                if not a.black_start:
                    if t:
                        prev_e = frames[t - 1]['energized'][frames[t - 1]['lookup'][a.node]]
                        m.add({support: 1, prev_e: -1}, upper=0)
                    elif a.node not in req.initial_energized_nodes:
                        m.add({support: 1}, 0, 0)
                supporters[lookup[a.node]].append(support)
            if a.ramp_kw_per_minute is not None:
                ramp = a.ramp_kw_per_minute * dt * 60
                previous_p = frames[t - 1]['sources'][a.id]['p'] if t else None
                terms = {p: 1}
                if previous_p is not None:
                    terms[previous_p] = -1
                initial_power = req.initial_source_power_kw.get(a.id, 0) if t == 0 else 0
                scaled(terms, ramp+initial_power, power_index(a.id))
                if previous_p is not None:
                    down = {previous_p: 1, p: -1, u: a.rated_kw}
                    ps = power_index(a.id)
                    if ps is not None:
                        down[ps] = -ramp
                    m.add(down, upper=a.rated_kw if ps is not None else ramp+a.rated_kw)
                elif initial_power:
                    down = {p: -1, u: a.rated_kw}
                    ps = power_index(a.id)
                    if ps is not None:
                        down[ps] = initial_power-ramp
                    m.add(down, upper=a.rated_kw if ps is not None else a.rated_kw+ramp-initial_power)
            p_balance[a.node][p] = 1
            q_balance[a.node][q] = 1
            economics[p] = dt * (inventory.economics.fuel_yuan_per_kwh if a.kind in ('柴油机', '移动发电车') else 0)
            economics[start] = req.source_start_cost_yuan
            f['sources'][a.id] = {'p': p, 'q': q, 'on': u, 'start': start, 'forming_support': support,
                                  'available_kw': cap if arrived else 0,
                                  'energy_end': source_energy[a.id][t+1] if a.id in source_energy else None}
        for a in storage:
            available = a.available and (a.existing or req.include_candidates) and (t * dt+req.elapsed_hours) * 60 >= a.arrival_minutes - 1e-8
            cap = a.power_kw * a.temperature_factor * factors[a.id][t] if available else 0
            charge, discharge = m.var(0, cap), m.var(0, cap)
            direction = m.var(0, 1, binary=True)
            q = m.var(-a.reactive_limit_kvar if cap else 0, a.reactive_limit_kvar if cap else 0)
            e = energized[lookup[a.node]]
            if a.id in activation:
                upper_active({direction: 1}, 1, a.id)
                scaled({charge: 1}, cap, power_index(a.id))
                scaled({discharge: 1}, cap, power_index(a.id))
                scaled({q: 1}, a.reactive_limit_kvar, power_index(a.id))
                scaled({q: -1}, a.reactive_limit_kvar, power_index(a.id))
            m.add({charge: 1, direction: cap}, upper=cap)
            m.add({discharge: 1, direction: -cap}, upper=0)
            m.add({charge: 1, e: -cap}, upper=0)
            m.add({discharge: 1, e: -cap}, upper=0)
            m.add({q: 1, e: -a.reactive_limit_kvar}, upper=0)
            m.add({q: 1, e: a.reactive_limit_kvar}, lower=0)
            m.add({energy[a.id][t + 1]: 1, energy[a.id][t]: -1,
                   charge: -a.charge_efficiency * dt, discharge: dt / a.discharge_efficiency}, 0, 0)
            if a.apparent_limit_kva is not None:
                limit_apparent(m, discharge, q, a.apparent_limit_kva, power_index(a.id))
                limit_apparent(m, charge, q, a.apparent_limit_kva, power_index(a.id))
            if a.grid_forming and cap > 0 and a.energy_kwh > 0:
                support = m.var(0, 1, binary=True)
                m.add({support: 1, e: -1}, upper=0)
                capacity = a.energy_kwh * a.temperature_factor
                reserve = capacity * req.forming_reserve_ratio
                reserve_index = support
                if a.id in sizing:
                    ps, es = sizing[a.id]
                    m.add({ps: 1, support: -1e-4}, lower=0)
                    m.add({es: 1, support: -1e-4}, lower=0)
                    reserve_index = product_fraction(es, support)
                for slot in (t, t + 1):
                    if a.id in activation:
                        m.add({energy[a.id][slot]: 1, reserve_index: -reserve, energy_index(a.id): -capacity*a.minimum_soc}, lower=0)
                    else:
                        m.add({energy[a.id][slot]: 1, support: -reserve}, lower=capacity * a.minimum_soc)
                if a.id in activation:
                    upper_active({support: 1}, 1, a.id)
                if not a.black_start:
                    if t:
                        prev_e = frames[t - 1]['energized'][frames[t - 1]['lookup'][a.node]]
                        m.add({support: 1, prev_e: -1}, upper=0)
                    elif a.node not in req.initial_energized_nodes:
                        m.add({support: 1}, 0, 0)
                supporters[lookup[a.node]].append(support)
            p_balance[a.node][discharge] = 1
            p_balance[a.node][charge] = -1
            q_balance[a.node][q] = 1
            economics[charge] = economics[discharge] = req.storage_cycle_yuan_per_kwh * dt
            f['storage'][a.id] = {'charge': charge, 'discharge': discharge, 'q': q, 'direction': direction}
        for i, group in enumerate(groups):
            if 1 not in group or grid[t] <= 0:
                m.add({energized[i]: 1, **{s: -1 for s in supporters[i]}}, upper=0)
        for a in loads:
            demand = float(demands[a.id][t])
            served = m.var(0, demand * factors[a.id][t])
            curtailed = m.var(0, demand * a.maximum_curtailment_ratio if req.allow_demand_response else 0)
            shortage = m.var(0, demand)
            goal_shortage = m.var(0, demand)
            e = energized[lookup[a.node]]
            m.add({served: 1, e: -demand}, upper=0)
            if a.id in req.minimum_load_when_energized:
                minimum = demand * factors[a.id][t] * req.minimum_load_when_energized[a.id]
                m.add({served: 1, e: -minimum}, lower=0)
            m.add({served: 1, curtailed: 1, shortage: 1}, demand, demand)
            target_start, target_end = target_bounds(req, a)
            target_duration = max(0, min((t+1)*dt, target_end)-max(t*dt, target_start))
            required = demand*a.minimum_supply_ratio if target_duration > 1e-9 else 0
            m.add({served: 1, goal_shortage: 1}, lower=required)
            p_balance[a.node][served] = -1
            q_balance[a.node][served] = -a.reactive_kvar / a.peak_kw if a.peak_kw else 0
            if required > 0:
                target_objectives[a.load_class][goal_shortage] = target_duration / a.priority
            supply_objectives[a.load_class][shortage] = dt / a.priority
            economics[curtailed] = inventory.economics.curtailment_yuan_per_kwh * dt
            f['loads'][a.id] = {'served': served, 'curtailed': curtailed, 'shortage': shortage,
                                  'goal_shortage': goal_shortage, 'demand': demand, 'required_kw': required}
        voltage_factor = 2 / (network.base_voltage_kv * 1000) ** 2 * 1000
        for line in network.lines:
            live = bool(line_states[line.line][t])
            cap = line.capacity_kva if line.capacity_kva is not None else req.branch_limit_kva
            for transformer in transformers:
                if transformer_edges[transformer.id] == line.line:
                    cap = min(cap, transformer.rated_kva * factors[transformer.id][t])
            p, q = m.var(-cap if live else 0, cap if live else 0), m.var(-cap if live else 0, cap if live else 0)
            p_balance[line.from_node][p] = -1
            p_balance[line.to_node][p] = 1
            q_balance[line.from_node][q] = -1
            q_balance[line.to_node][q] = 1
            if live:
                m.add({f['voltage'][line.to_node]: 1, f['voltage'][line.from_node]: -1,
                       p: voltage_factor * line.r_ohm, q: voltage_factor * line.x_ohm}, 0, 0)
                limit_apparent(m, p, q, cap)
            f['lines'][line.line] = {'p': p, 'q': q, 'live': live, 'limit_kva': cap}
        for n in nodes:
            m.add(p_balance[n], 0, 0)
            m.add(q_balance[n], 0, 0)
        frames.append(f)
    for a in sources:
        if a.fuel_kwh is not None:
            _, additions, reserve = source_energy_profile(req, a, steps)
            for t,f in enumerate(frames):
                flow = {source_energy[a.id][t+1]: 1, source_energy[a.id][t]: -1,
                        f['sources'][a.id]['p']: dt}
                scale = energy_index(a.id)
                if scale is None:
                    m.add(flow, float(additions[t]), float(additions[t]))
                else:
                    flow[scale] = -float(additions[t])
                    m.add(flow, 0, 0)
                support=f['sources'][a.id]['forming_support']
                if support is not None:
                    reserve_index = product_fraction(energy_index(a.id), support) if a.id in sizing else support
                    m.add({source_energy[a.id][t+1]: 1, reserve_index: -reserve}, lower=0)
        if a.available_hours is not None:
            remaining_hours = max(0, a.available_hours-req.initial_source_used_hours.get(a.id, 0))
            upper_active({f['sources'][a.id]['on']: dt for f in frames}, remaining_hours, a.id)

    if len(m.lower)-variable_start > 200000:
        raise ValueError('逐设备模型超过20万变量，请缩短时域或精简设备')
    objectives = [(cls + '最低保供', terms) for cls, terms in target_objectives.items() if terms]
    objectives += [(cls + '未供电', terms) for cls, terms in supply_objectives.items() if terms]
    objectives.append(('运行成本与循环', economics))
    built = DispatchModel(req, network, m, dt, steps, nodes, sources, storage, loads, energy,
                         frames, economics, objectives, activation, sizing, started,
                         len(m.lower)-variable_start, len(m.cl)-constraint_start)
    if req.enforce_load_targets:
        add_target_constraints(built)
        if built.variable_count > 200000:
            raise ValueError('硬中断约束后逐设备模型超过20万变量，请缩短时域或精简设备')
    return built


def validate_solution(m, x):
    activity=m.matrix() @ x
    primal_violation=max(float(np.max(np.maximum(np.asarray(m.cl)-activity,0),initial=0)),float(np.max(np.maximum(activity-np.asarray(m.cu),0),initial=0)))
    bound_violation=max(float(np.max(np.maximum(np.asarray(m.lower)-x,0),initial=0)),float(np.max(np.maximum(x-np.asarray(m.upper),0),initial=0)))
    integer_indices=np.flatnonzero(np.asarray(m.integral))
    integer_violation=float(np.max(np.abs(x[integer_indices]-np.rint(x[integer_indices])),initial=0))
    if max(primal_violation,bound_violation)>1e-4 or integer_violation>1e-5:
        raise ValueError('求解结果未通过原始约束残差检查')
    return {'primal_violation': primal_violation, 'bound_violation': bound_violation,
            'integer_violation': integer_violation}


def decode_dispatch(built, x, solver_log=None, complete=True, certificate=None, joint=False):
    req, network, m = built.req, built.network, built.m
    dt, steps, nodes = built.dt, built.steps, built.nodes
    sources, storage, loads = built.sources, built.storage, built.loads
    frames, energy, economics, started = built.frames, built.energy, built.economics, built.started
    certificate = certificate or validate_solution(m, x)
    primal_violation = certificate['primal_violation']
    bound_violation = certificate['bound_violation']
    integer_violation = certificate['integer_violation']
    solver_log = solver_log or []
    if req.enforce_load_targets and not target_success(built, x):
        raise ValueError('求解轨迹未通过硬保供目标实际复核，拒绝保存达标结果')
    def value(index):
        v = float(x[index])
        return 0.0 if abs(v) < 1e-7 else v
    def installed(asset_id):
        return value(built.activation[asset_id]) if asset_id in built.activation else 1.0
    def fraction(asset_id, dimension):
        return float(x[built.sizing[asset_id][dimension]]) if asset_id in built.sizing else installed(asset_id)
    rows = []
    for t, f in enumerate(frames):
        row = {'timestamp': (req.start + timedelta(hours=t * dt)).isoformat(), 'step_hours': dt,
               'grid_kw': value(f['grid'][0]), 'grid_kvar': value(f['grid'][1]),
               'sources': [], 'storage': [], 'loads': [], 'nodes': [], 'lines': []}
        for a in sources:
            v = f['sources'][a.id]
            used = value(v['p'])
            fuel_remaining = value(v['energy_end']) if v['energy_end'] is not None else None
            available_kw = v['available_kw']*fraction(a.id, 0)
            row['sources'].append({'id': a.id, 'node': a.node, 'installed': installed(a.id)>.5, 'dispatch_kw': used, 'reactive_kvar': value(v['q']),
                                   'on': value(v['on']) > .5, 'startup_command': value(v['start']) > .5,
                                   'available_kw': available_kw, 'online_limit_kw':available_kw if value(v['on'])>.5 else 0, 'renewable_curtailment_kw': max(0, available_kw - used) if a.kind in ('风电', '光伏') else 0,
                                   'fuel_remaining_kwh': fuel_remaining})
        for a in storage:
            v = f['storage'][a.id]
            capacity = a.energy_kwh * a.temperature_factor * fraction(a.id, 1)
            row['storage'].append({'id': a.id, 'node': a.node, 'installed': installed(a.id)>.5, 'charge_kw': value(v['charge']),
                                   'discharge_kw': value(v['discharge']), 'reactive_kvar': value(v['q']),
                                   'effective_capacity_kwh':capacity, 'energy_begin_kwh': value(energy[a.id][t]), 'energy_end_kwh': value(energy[a.id][t + 1]),
                                   'soc': value(energy[a.id][t + 1]) / capacity if capacity else None})
        for a in loads:
            v = f['loads'][a.id]
            supplied = value(v['served'])
            row['loads'].append({'id': a.id, 'node': a.node, 'class': a.load_class, 'demand_kw': v['demand'], 'served_kw': supplied,
                                 'controlled_curtailment_kw': value(v['curtailed']), 'shortage_kw': value(v['shortage']),
                                 'target_kw': v['required_kw'], 'target_shortage_kw': max(0, v['required_kw'] - supplied)})
        for node in nodes:
            live = value(f['energized'][f['lookup'][node]]) > .5
            row['nodes'].append({'node': node, 'energized': live, 'linear_voltage_pu': math.sqrt(max(0, value(f['voltage'][node]))) if live else None})
        for line in network.lines:
            v = f['lines'][line.line]
            row['lines'].append({'line': line.line, 'closed': v['live'], 'p_kw': value(v['p']), 'q_kvar': value(v['q']), 'limit_kva': v['limit_kva']})
        row['load_kw'] = sum(v['demand_kw'] for v in row['loads'])
        row['served_kw'] = sum(v['served_kw'] for v in row['loads'])
        row['controlled_curtailment_kw'] = sum(v['controlled_curtailment_kw'] for v in row['loads'])
        row['shortage_kw'] = sum(v['shortage_kw'] for v in row['loads'])
        row['total_unsupplied_kw'] = row['load_kw'] - row['served_kw']
        row['power_balance_residual_kw'] = row['grid_kw'] + sum(v['dispatch_kw'] for v in row['sources']) + sum(v['discharge_kw'] - v['charge_kw'] for v in row['storage']) - row['served_kw']
        rows.append(row)
    load_metrics = []
    for a in loads:
        series = [next(v for v in row['loads'] if v['id'] == a.id) for row in rows]
        prefix = 0
        for v in series:
            if v['served_kw'] + 1e-5 < v['demand_kw'] * a.minimum_supply_ratio:
                break
            prefix += 1
        target_start, target_end = target_bounds(req, a)
        remaining_target = max(0, target_end-max(0, target_start))
        history = req.initial_target_interruption_hours.get(a.id, 0)
        maximum_interruption, current_interruption = target_interruption(
            [v['target_kw'] for v in series], [v['served_kw'] for v in series], dt, target_end, history, target_start)
        maximum_interruption = max(maximum_interruption, req.initial_max_target_interruption_hours.get(a.id, 0))
        total_interruption = current_interruption+req.initial_total_target_interruption_hours.get(
            a.id, req.initial_max_target_interruption_hours.get(a.id, history))
        tolerance = a.maximum_interruption_hours if a.interruption_allowed else 0
        failed = maximum_interruption > tolerance + 1e-8
        history_complete = req.elapsed_hours <= 1e-9 or req.prior_target_history_complete
        status = 'failed' if failed else 'not_checked' if steps*dt+1e-9 < target_end or not history_complete else 'passed'
        load_metrics.append({'id': a.id, 'name': a.name, 'class': a.load_class,
                             'demand_kwh': sum(v['demand_kw'] for v in series) * dt,
                             'served_kwh': sum(v['served_kw'] for v in series) * dt,
                             'shortage_kwh': sum(v['shortage_kw'] for v in series) * dt,
                             'controlled_curtailment_kwh': sum(v['controlled_curtailment_kw'] for v in series) * dt,
                             'continuous_target_supply_hours': prefix * dt,
                             'maximum_target_interruption_hours': maximum_interruption,
                             'total_target_interruption_hours': total_interruption,
                             'current_window_target_interruption_hours': current_interruption,
                             'remaining_target_hours_at_start': remaining_target,
                             'prior_target_history_complete': history_complete,
                             'allowed_consecutive_interruption_hours': tolerance,
                             'target_hours': a.target_hours, 'target_status': status})
    metrics = {'load_energy_kwh': sum(r['load_kw'] for r in rows) * dt,
               'served_energy_kwh': sum(r['served_kw'] for r in rows) * dt,
               'shortage_energy_kwh': sum(r['shortage_kw'] for r in rows) * dt,
               'controlled_curtailment_energy_kwh': sum(r['controlled_curtailment_kw'] for r in rows) * dt,
               'total_unsupplied_energy_kwh': sum(r['total_unsupplied_kw'] for r in rows) * dt,
               'maximum_shortage_kw': max(r['shortage_kw'] for r in rows),
               'maximum_total_unsupplied_kw': max(r['total_unsupplied_kw'] for r in rows),
               'maximum_balance_residual_kw': max(abs(r['power_balance_residual_kw']) for r in rows),
               'study_dispatch_cost_yuan':float(sum(coefficient*x[index] for index,coefficient in economics.items())),
               'all_load_targets': 'failed' if any(l['target_status'] == 'failed' for l in load_metrics) else 'not_checked' if any(l['target_status'] == 'not_checked' for l in load_metrics) else 'passed'}
    continued = (req.elapsed_hours > 0 or any([req.initial_source_on, req.initial_source_power_kw,
        req.initial_source_startup_remaining_steps, req.initial_source_fuel_kwh, req.initial_source_used_hours,
        req.initial_storage_energy_kwh, req.initial_target_interruption_hours, req.initial_max_target_interruption_hours,
        req.initial_total_target_interruption_hours, req.source_energy_additions_kwh, req.source_forming_reserve_kwh,
        req.load_target_start_hours])) or not req.require_complete_target_horizon
    method = 'devices.radial.horizon-milp.v5' if continued else 'devices.radial.horizon-milp.v4' if req.enforce_load_targets else 'devices.radial.horizon-milp.v3'
    return {'status': 'joint_feasible' if joint else 'optimal' if complete else 'feasible_limit', 'method': 'devices.radial.joint-recourse.v1' if joint else method,
            'elapsed_hours_at_start': req.elapsed_hours,
            'rows': rows, 'metrics': metrics, 'load_metrics': load_metrics, 'solver': solver_log,
            'runtime_seconds': time.monotonic() - started, 'maximum_integer_violation':integer_violation, 'maximum_constraint_violation': primal_violation, 'maximum_bound_violation':bound_violation, 'variables': built.variable_count, 'constraints': built.constraint_count if joint else len(m.cl),
            'checks': [{'name': '逐设备有功守恒', 'status': 'passed' if metrics['maximum_balance_residual_kw'] < 1e-4 else 'failed'},
                       {'name': '交流网损及非线性潮流', 'status': 'not_checked'},
                       {'name': '离网动态稳定与励磁涌流', 'status': 'not_checked'},
                       {'name': '通信与实际操作时序', 'status': 'not_checked'}],
            'scope': ['衔接输入包含事件已逝时间、机组前状态/有功/未完成启动、剩余可发电量、已用运行小时、储能实际电量及中断前史。到位和目标时长以同一事件起点计，曲线首项仍对应本次开始时间。',
                      '可发电量补给在指定步开始生效，单位kWh。燃料逐步状态守恒，构网绝对储备可固定，默认参考量取台账初始声明、窗口初始实际库存和最大单次补给量的最大值。空载耗油和启动辅助电量仍需设备数据支持。',
                      '延续事件的完整目标需要完整前史声明。中断最大值和累计值包含给出的已知前史，当前窗口累计另列。前史不足的软目标保留未校核状态。',
                      '硬保供开关默认关闭；启用后按逐负荷是否允许中断及最大连续中断小时建立精确时钟约束，时域须覆盖完整目标。主动削减低于最低供电比例也计目标中断。末步按目标窗口交集计时，不表示步内可以再调度。',
                      '最大连续中断和累计中断分别统计，零目标需求时段终止连续段。事件前史由衔接输入提供，默认初态按新事件起算。',
                      '外部购电、循环和启动成本为显式研究参数，非地区核定价格；非燃料源运行边际成本在本版忽略。',
                      '支持1/5/15/30/60分钟；恢复入口可强制电源启停、节点带电及带电负荷最低投入，旧请求默认不附加这些约束。',
                      '确定性全时域优化使用完整已知曲线，不代表实际灾害预测精度。',
                      '联合规划后验调度，服从共享投资/机会约束与折现经济目标，并非独立的分层缺供最小化。' if joint else '逐设备多时段MILP，按基本保障/居民/一般依次最小化目标缺额及非计划缺供，最后降低运行成本。',
                      '线路容量采用内接八边形保守近似；电压为无损LinDistFlow，不含交流网损和动态稳定结论。',
                      '每个失联分区须有可用构网资源，未初始带电时须有黑启动条件；储能构网预留能量为显式研究参数。',
                      '曲线为分段常值；到位和启动时间向后对齐计算网格，未隐式细分时段。',
                      '燃料按可转化电量kWh记，储能按有效额定能量比例预留，燃料构网采用显式绝对储备或默认参考量比例。储备量与时间步长独立。',
                      '电源停运可重新启动；未建候选默认不参与。负荷调节须显式开启，计划削减与非计划缺供分账。',
                      '当前变压器仅处理变比1的理想支路容量；未提供的风光水曲线不会按额定出力补造。']}



def dispatch(req: DispatchInput, inventory: Inventory, network: Network, progress=None, cancelled=None):
    from backend.study_control import StudyCancelled
    def check_cancel():
        if cancelled and cancelled():
            raise StudyCancelled('用户请求取消')
    built = build_dispatch_model(req, inventory, network, progress, cancelled)
    m, objectives, started = built.m, built.objectives, built.started
    solver_log, solution = [], None
    complete = True
    for oi, (label, terms) in enumerate(objectives):
        check_cancel()
        if progress:
            progress({'phase': 'solving', 'objective': label, 'fraction': .1 + .85 * oi / len(objectives)})
        remaining = req.time_limit_seconds - (time.monotonic() - started)
        if remaining <= 0:
            complete = False
            break
        c = np.zeros(len(m.lower))
        for index, coefficient in terms.items():
            c[index] = coefficient
        solved = milp(c, integrality=np.asarray(m.integral), bounds=Bounds(m.lower, m.upper),
                      constraints=LinearConstraint(m.matrix(), m.cl, m.cu),
                      options={'time_limit': remaining, 'mip_rel_gap': 1e-7})
        check_cancel()
        solver_log.append({'objective': label, 'status': int(solved.status), 'message': str(solved.message),
                           'value': float(solved.fun) if solved.fun is not None else None,
                           'gap': float(solved.mip_gap) if getattr(solved, 'mip_gap', None) is not None else None})
        if solved.x is None:
            if solution is None:
                if solved.status == 1:
                    raise DispatchIncomplete('逐设备调度达到时限，尚未获得可行解')
                if solved.status == 2:
                    raise DispatchInfeasible('给定逐设备调度约束不可行：' + solved.message)
                raise ValueError('逐设备调度未获得可行解：' + solved.message)
            complete = False
            break
        solution = solved.x
        if solved.status != 0:
            complete = False
            break
        m.add(terms, upper=float(solved.fun) + max(1e-7, abs(float(solved.fun)) * 1e-8))
    if solution is None:
        raise DispatchIncomplete('建模达到时限，尚未获得可行解')
    check_cancel()
    result = decode_dispatch(built, solution, solver_log, complete)
    if progress:
        progress({'phase': 'complete', 'fraction': 1})
    return result


def continuation_state(req, inventory, result, committed_steps=None):
    """Derive a concrete device state after a committed prefix of one dispatch."""
    if not result['method'].startswith('devices.radial.horizon-milp.'):
        raise ValueError('边界状态导出需要独立逐设备调度结果')
    count = len(result['rows']) if committed_steps is None else committed_steps
    if not 1 <= count <= len(result['rows']):
        raise ValueError('衔接位置须为结果范围内已执行的步数')
    rows = result['rows'][:count]
    last = rows[-1]
    source_rows = {item['id']: item for item in last['sources']}
    state = {
        'start': (req.start+timedelta(hours=count*req.step_hours)).isoformat(),
        'step_hours': req.step_hours,
        'include_candidates': req.include_candidates,
        'require_complete_target_horizon': req.require_complete_target_horizon,
        'load_target_start_hours': req.load_target_start_hours.copy(),
        'elapsed_hours': req.elapsed_hours+count*req.step_hours,
        'initial_source_on': {}, 'initial_source_power_kw': {},
        'initial_source_startup_remaining_steps': {}, 'initial_source_fuel_kwh': {},
        'initial_source_used_hours': {}, 'initial_storage_energy_kwh': {},
        'initial_target_interruption_hours': {}, 'initial_max_target_interruption_hours': {},
        'initial_total_target_interruption_hours': {},
        'initial_energized_nodes': [node['node'] for node in last['nodes'] if node['energized']],
        'prior_target_history_complete': req.elapsed_hours <= 1e-9 or req.prior_target_history_complete,
        'initial_state_provenance': '逐设备调度已提交前缀的末状态',
        'source_energy_additions_kwh': {}, 'source_forming_reserve_kwh': {},
    }
    for asset in inventory.sources:
        if asset.id not in source_rows:
            continue
        pending = req.initial_source_startup_remaining_steps.get(asset.id)
        used_hours = req.initial_source_used_hours.get(asset.id, 0)
        for row in rows:
            item = next(v for v in row['sources'] if v['id'] == asset.id)
            used_hours += req.step_hours if item['on'] else 0
            if item['available_kw'] <= 1e-9:
                pending = None
            elif item['startup_command']:
                pending = math.ceil(asset.startup_minutes/(60*req.step_hours)-1e-12)
            if item['on'] or pending == 0:
                pending = None
            elif pending is not None:
                pending -= 1
        item = source_rows[asset.id]
        state['initial_source_on'][asset.id] = int(item['on'])
        state['initial_source_power_kw'][asset.id] = item['dispatch_kw']
        state['initial_source_used_hours'][asset.id] = used_hours
        if pending is not None:
            state['initial_source_startup_remaining_steps'][asset.id] = pending
        if item['fuel_remaining_kwh'] is not None:
            state['initial_source_fuel_kwh'][asset.id] = max(0, item['fuel_remaining_kwh'])
            _, _, reserve = source_energy_profile(req, asset, req.steps)
            if reserve:
                state['source_forming_reserve_kwh'][asset.id] = reserve
    for item in last['storage']:
        state['initial_storage_energy_kwh'][item['id']] = item['energy_end_kwh']
    for asset in inventory.loads:
        if not any(item['id'] == asset.id for item in last['loads']):
            continue
        tail = req.initial_target_interruption_hours.get(asset.id, 0)
        maximum = req.initial_max_target_interruption_hours.get(asset.id, tail)
        total = req.initial_total_target_interruption_hours.get(asset.id, maximum)
        target_start, target_end = target_bounds(req, asset)
        for index, row in enumerate(rows):
            item = next(v for v in row['loads'] if v['id'] == asset.id)
            duration = max(0, min((index+1)*req.step_hours, target_end)-max(index*req.step_hours, target_start))
            missing = item['target_kw'] > 0 and item['served_kw']+max(1e-7, item['target_kw']*1e-8) < item['target_kw']
            tail = tail+duration if missing else 0
            maximum = max(maximum, tail)
            total += duration if missing else 0
        if count*req.step_hours >= target_end-1e-9:
            tail = 0
        state['initial_target_interruption_hours'][asset.id] = tail
        state['initial_max_target_interruption_hours'][asset.id] = maximum
        state['initial_total_target_interruption_hours'][asset.id] = total
    return state



def connection():
    c = sqlite3.connect(ROOT / 'data/platform.db')
    c.execute('CREATE TABLE IF NOT EXISTS device_dispatch(id TEXT PRIMARY KEY,project_id TEXT,created TEXT,payload TEXT)')
    return c


@router.post('')
def calculate(req: DispatchInput):
    project = project_record(req.project_id)
    if project['revision'] != req.project_revision:
        raise HTTPException(409, '工程版本已变化，请重新读取')
    engineering = inventory_snapshot(req.project_id, req.engineering_revision)
    try:
        inventory = Inventory.model_validate(engineering['inventory'])
        validate_nodes(inventory, project)
        network = Network.model_validate(project['state']['network']) if project['state'].get('network') else Network.model_validate(
            {'name': 'IEEE33示例', 'base_voltage_kv': 12.66, **case33()})
        result = dispatch(req, inventory, network)
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e))
    from backend.app import RUNTIME_ID
    snapshot = {'algorithm':result['method'],'runtime':RUNTIME_ID,'parameters': req.model_dump(mode='json'), 'engineering': engineering, 'network': network.model_dump(), 'project': project}
    record = {'id': uuid.uuid4().hex, 'project_id': req.project_id, 'created': datetime.now().isoformat(timespec='seconds'),
              'name': req.name, 'input': snapshot, 'input_sha256': canonical_sha(snapshot), 'result': result}
    with closing(connection()) as c, c:
        c.execute('INSERT INTO device_dispatch VALUES(?,?,?,?)', (record['id'], record['project_id'], record['created'], json.dumps(record, ensure_ascii=False, allow_nan=False)))
    return record


@router.get('')
def history(project_id: str):
    project_record(project_id)
    with closing(connection()) as c:
        rows = c.execute('SELECT payload FROM device_dispatch WHERE project_id=? ORDER BY created DESC,rowid DESC', (project_id,)).fetchall()
    return [{'id': r['id'], 'name': r['name'], 'created': r['created'], 'status': r['result']['status']} for (payload,) in rows if (r := json.loads(payload))]


@router.get('/{run_id}')
def read(run_id: str):
    with closing(connection()) as c:
        row = c.execute('SELECT payload FROM device_dispatch WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, '逐设备计算档案不存在')
    return json.loads(row[0])


@router.get('/{run_id}/continuation')
def export_continuation(run_id: str, committed_steps: int | None = None):
    record = read(run_id)
    req = DispatchInput.model_validate(record['input']['parameters'])
    inventory = Inventory.model_validate(record['input']['engineering']['inventory'])
    try:
        parameters = continuation_state(req, inventory, record['result'], committed_steps)
    except ValueError as error:
        raise HTTPException(422, str(error))
    source_sha = canonical_sha(record['input'])
    count = committed_steps or len(record['result']['rows'])
    parameters['initial_state_provenance'] = f'参考逐设备归档{run_id}前{count}步的末状态，原输入摘要{source_sha}'
    payload = {'source_record_id': run_id, 'source_snapshot_sha256': source_sha,
               'project_id': record['project_id'], 'project_revision': req.project_revision,
               'engineering_revision': req.engineering_revision,
               'committed_steps': committed_steps or len(record['result']['rows']), 'parameters': parameters,
               'instructions': ['参数中的start和elapsed_hours已推进到指定步之后。到位和目标时长继续按原事件起点计。',
                                '后续计算使用本次导出的实际状态，并按新的开始时刻提供源荷、网供、设备和线路曲线。',
                                '已执行补给已计入剩余可发电量，后续补给数组需按新窗口重新填写。']}
    return Response(json.dumps(payload, ensure_ascii=False, allow_nan=False), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename=dispatch-state-{run_id}.json'})


@router.get('/{run_id}/csv')
def export(run_id: str):
    import csv
    record = read(run_id)
    keys = ['timestamp', 'step_hours', 'load_kw', 'served_kw', 'controlled_curtailment_kw', 'shortage_kw', 'total_unsupplied_kw', 'grid_kw', 'power_balance_residual_kw']
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=keys, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(record['result']['rows'])
    return Response('\ufeff' + stream.getvalue(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename=device-dispatch-{run_id}.csv'})
