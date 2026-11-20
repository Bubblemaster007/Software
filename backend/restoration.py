"""Bounded beam search over primary/secondary restoration operations.

Every retained prefix is replayed over the entire fixed horizon by the device MILP.
This plans engineering operations; it cannot certify transient safety without the
missing dynamic models. Numeric external synchronization and inrush envelopes are
explicitly distinguished from independently verified transient calculations.
"""
from dataclasses import dataclass, field
import copy
import heapq
import math
import time
from typing import Literal
import numpy as np
from pydantic import Field, model_validator
from backend.engineering import Inventory, StrictModel, canonical_sha
from backend.network_data import Network
from backend.resource_dispatch import (DispatchInput, dispatch, repeated, components,
                                       DispatchIncomplete, DispatchInfeasible)
from backend.study_control import StudyCancelled

METHOD = 'restoration.primary-secondary.beam-milp.v1'
CLASSES = ('基本保障', '居民生活', '一般负荷')


class SyncEvidence(StrictModel):
    target: str = Field(min_length=1, max_length=100)
    valid_from_step: int = Field(ge=0)
    valid_to_step: int = Field(ge=0)
    voltage_difference_pu: float = Field(ge=0, le=2)
    frequency_difference_hz: float = Field(ge=0, le=100)
    angle_difference_degrees: float = Field(ge=0, le=180)
    provenance: str = Field(min_length=1, max_length=1000)


class RestorationInput(StrictModel):
    base: DispatchInput
    name: str = Field('黑启动恢复操作规划', min_length=1, max_length=100)
    mode: Literal['serial', 'parallel'] = 'parallel'
    initial_closed_lines: list[int] = Field(default_factory=list, max_length=200)
    line_ready_step: dict[int, int] = Field(default_factory=dict)
    equipment_ready_step: dict[str, int] = Field(default_factory=dict)
    manual_resource_ids: list[str] = Field(default_factory=list, max_length=1000)
    manual_switch_ids: list[str] = Field(default_factory=list, max_length=1000)
    manual_load_ids: list[str] = Field(default_factory=list, max_length=1000)
    resource_terminals: dict[str, str] = Field(default_factory=dict)
    load_terminals: dict[str, str] = Field(default_factory=dict)
    backup_powered_devices: list[str] = Field(default_factory=list, max_length=1500)
    manual_crews: int = Field(1, ge=1, le=16)
    manual_operation_minutes: float = Field(1, gt=0, le=10000)
    maximum_communication_latency_ms: float = Field(1000, ge=0, le=1000000)
    control_provenance: str = Field('用户研究操作与控制假设，需工程确认', min_length=1, max_length=1000)
    synchronization: list[SyncEvidence] = Field(default_factory=list, max_length=200)
    sync_voltage_limit_pu: float = Field(.05, gt=0, le=.2)
    sync_frequency_limit_hz: float = Field(.1, gt=0, le=1)
    sync_angle_limit_degrees: float = Field(10, gt=0, le=30)
    energizing_current_limits_a: dict[str, float] = Field(default_factory=dict)
    transient_parameter_provenance: str = Field('', max_length=1000)
    require_inrush_parameters: bool = False
    beam_width: int = Field(4, ge=1, le=8)
    maximum_operations: int = Field(40, ge=1, le=64)
    maximum_evaluations: int = Field(200, ge=1, le=1000)
    wall_time_seconds: float = Field(600, ge=1, le=3600)

    @model_validator(mode='after')
    def semantics(self):
        if (self.base.elapsed_hours > 0 or any(self.base.initial_source_on.values())
                or any(self.base.initial_source_power_kw.values()) or self.base.initial_source_startup_remaining_steps):
            raise ValueError('全停电恢复入口按新事件冷启动生成操作序列，延续调度状态请使用逐设备入口')
        if any(self.base.grid_available_kw) or self.base.initial_energized_nodes:
            raise ValueError('本版黑启动从全停电、外部供电为0开始')
        if self.base.line_status or self.base.source_commitment or self.base.required_energized_nodes or self.base.minimum_load_when_energized:
            raise ValueError('黑启动由操作序列生成线路/启停/带电约束，请勿在base重复设置')
        if self.base.allow_demand_response:
            raise ValueError('恢复规划使用实际负荷投入，不将缺供或未投入负荷当主动响应')
        for values in [self.initial_closed_lines, self.manual_resource_ids, self.manual_switch_ids,
                       self.manual_load_ids, self.backup_powered_devices]:
            if len(values) != len(set(values)):
                raise ValueError('初始线路、操作授权和备用供电编号不得重复')
        if set(self.manual_resource_ids) & self.resource_terminals.keys() or set(self.manual_load_ids) & self.load_terminals.keys():
            raise ValueError('同一资源/负荷不能同时指定手动和遥控，需明确本次操作方式')
        if any(not 0 <= s < self.base.steps for s in [*self.line_ready_step.values(), *self.equipment_ready_step.values()]):
            raise ValueError('可用/修复步须在计算时域内')
        for evidence in self.synchronization:
            if not 0 <= evidence.valid_from_step <= evidence.valid_to_step < self.base.steps:
                raise ValueError('同步证据有效窗口不在计算时域内')
        if any(not 0 < a <= 1000000 for a in self.energizing_current_limits_a.values()):
            raise ValueError('励磁容量包络电流上限须为正有限数')
        if self.energizing_current_limits_a and not self.transient_parameter_provenance:
            raise ValueError('励磁容量参数须填写来源')
        return self


def study_assets(req, inventory):
    return {a.id: a for a in inventory.sources+inventory.storage+inventory.loads+inventory.transformers+
            inventory.switches+inventory.controllers+inventory.terminals if a.existing or req.base.include_candidates}


def validate_restoration(req, inventory, network):
    assets = study_assets(req, inventory)
    resources = {a.id for a in inventory.sources+inventory.storage if a.id in assets}
    loads = {a.id for a in inventory.loads if a.id in assets}
    terminals = {a.id for a in inventory.terminals if a.id in assets}
    secondary = terminals | {a.id for a in inventory.controllers if a.id in assets}
    switches = {a.id for a in inventory.switches if a.id in assets}
    lines = {a.line: a for a in network.lines}
    if not set(req.initial_closed_lines) <= lines.keys() or not req.line_ready_step.keys() <= lines.keys():
        raise ValueError('初始/可用线路引用不存在的线路')
    if any(req.line_ready_step.get(i, 0) > 0 or not lines[i].status and i not in req.line_ready_step for i in req.initial_closed_lines):
        raise ValueError('初始闭合线路必须在第0步可用；备用线路需显式声明可用步')
    for values, allowed, label in [(req.manual_resource_ids, resources, '手动资源'), (req.resource_terminals, resources, '遥控资源'),
                                    (req.manual_switch_ids, switches, '手动开关'), (req.manual_load_ids, loads, '手动负荷'),
                                    (req.load_terminals, loads, '遥控负荷'), (req.backup_powered_devices, secondary, '备用电源设备'),
                                    (req.energizing_current_limits_a, resources, '励磁支撑电源')]:
        if not set(values) <= allowed:
            raise ValueError(label+'引用不存在或未参与设备')
    if not (set(req.resource_terminals.values()) | set(req.load_terminals.values())) <= terminals:
        raise ValueError('资源/负荷控制终端不存在或未参与')
    comm_ids = {a.id for a in inventory.communication}
    if not req.equipment_ready_step.keys() <= assets.keys() | comm_ids:
        raise ValueError('修复设备不存在或未参与')
    for asset_id, tid in {**req.resource_terminals, **req.load_terminals}.items():
        if assets[asset_id].node != assets[tid].node:
            raise ValueError('控制终端须与资源/负荷同节点：'+asset_id)
    for switch in inventory.switches:
        if switch.id not in assets:
            continue
        if switch.line_id not in lines or switch.node not in (lines[switch.line_id].from_node, lines[switch.line_id].to_node):
            raise ValueError('开关须位于关联线路的一个端点：'+switch.id)
        if switch.terminal_id and assets.get(switch.terminal_id) and assets[switch.terminal_id].node != switch.node:
            raise ValueError('开关与其终端须同节点：'+switch.id)
    switch_lines = [s.line_id for s in inventory.switches if s.id in assets]
    if len(set(switch_lines)) != len(switch_lines):
        raise ValueError('当前恢复操作按一支路一开关建模，多开关串联须拆分支路')
    for a in inventory.switches+inventory.transformers:
        if a.id not in assets:
            continue
        values = req.base.device_availability.get(a.id, [1])
        if any(v > w for v, w in zip(values, values[1:])):
            raise ValueError('本版恢复过程不允许开关/变压器二次故障，需另建灾害工况')
        line_id = a.line_id if hasattr(a, 'line_id') else next((e.line for e in network.lines if {e.from_node, e.to_node} == {a.node, a.to_node}), None)
        if line_id in req.initial_closed_lines and not equipment_available(req, a, 0):
            raise ValueError('初始闭合线路上的开关/变压器第0步不可用，请先隔离：'+a.id)
    components([n.node for n in network.nodes], [lines[i] for i in req.initial_closed_lines])


def ceil_steps(minutes, dt):
    return max(0, math.ceil(minutes/(dt*60)-1e-10))


@dataclass
class State:
    actions: list = field(default_factory=list)
    # Resource ID -> command completion / ready step; each switch can close once.
    resources: dict = field(default_factory=dict)
    closed: dict = field(default_factory=dict)
    picked: dict = field(default_factory=dict)
    crew_free: list = field(default_factory=list)
    node_busy: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)
    node_ready: dict = field(default_factory=dict)
    score: tuple = ()


def equipment_available(req, item, step):
    if item.id in req.equipment_ready_step:
        available = step >= req.equipment_ready_step[item.id]
    else:
        available = item.available
    if item.id in req.base.device_availability:
        values = req.base.device_availability[item.id]
        available = available and values[0 if len(values) == 1 else step] > 0
    return available


def communication_route(req, inventory, state, terminal_id, node, step):
    assets = study_assets(req, inventory)
    terminal = assets.get(terminal_id)
    if terminal is None or not hasattr(terminal, 'controller_id'):
        return None
    controller = assets.get(terminal.controller_id)
    if controller is None or not hasattr(controller, 'covered_nodes') or node not in set(controller.covered_nodes) | {controller.node}:
        return None
    powered = lambda a: a.id in req.backup_powered_devices or state.node_ready.get(a.node, req.base.steps) <= step
    online = {a.id for a in inventory.controllers+inventory.terminals
              if a.id in assets and equipment_available(req, a, step) and powered(a)}
    if not {terminal_id, controller.id} <= online:
        return None
    graph = {a: [] for a in online}
    for link in inventory.communication:
        if link.from_device in online and link.to_device in online and equipment_available(req, link, step):
            graph[link.from_device].append((link.to_device, link.latency_ms, link.id))
            graph[link.to_device].append((link.from_device, link.latency_ms, link.id))
    queue, seen = [(0.0, controller.id, ())], set()
    while queue:
        latency, current, path = heapq.heappop(queue)
        if current in seen:
            continue
        seen.add(current)
        if current == terminal_id:
            return {'status': 'passed', 'controller': controller.id, 'terminal': terminal_id,
                    'route': list(path), 'latency_ms': latency} if latency <= req.maximum_communication_latency_ms else None
        for target, delay, lid in graph[current]:
            if target not in seen:
                heapq.heappush(queue, (latency+delay, target, path+(lid,)))
    return None


def sync_check(req, target, step):
    for e in req.synchronization:
        if e.target == target and e.valid_from_step <= step <= e.valid_to_step:
            ok = (e.voltage_difference_pu <= req.sync_voltage_limit_pu
                  and e.frequency_difference_hz <= req.sync_frequency_limit_hz
                  and e.angle_difference_degrees <= req.sync_angle_limit_degrees)
            if ok:
                return {'name': '预同步外部数值校验', 'status': 'external_passed', 'evidence': e.model_dump()}
    return None


def materialize(req, inventory, network, state):
    """Generate command schedules. Original curves, demand, SOC and fuel stay unchanged."""
    inv = inventory.model_copy(deep=True)
    n = req.base.steps
    assets = study_assets(req, inv)
    for a in assets.values():
        if a.id in req.equipment_ready_step:
            a.available = True
    data = req.base.model_dump(mode='json')
    factors = {a.id: repeated(data['device_availability'].get(a.id, []), n, 1, a.id).copy()
               for a in inv.sources+inv.storage+inv.loads+inv.transformers+inv.switches}
    for asset_id, ready in req.equipment_ready_step.items():
        if asset_id in factors:
            factors[asset_id][:ready] = 0
    commitment, energize = {}, {}
    controlled = set(req.manual_load_ids) | req.load_terminals.keys()
    for a in inv.sources+inv.storage:
        if a.id not in assets:
            continue
        command, ready = state.resources.get(a.id, (n, n))
        factors[a.id][:command] = 0
        if a in inv.sources:
            commitment[a.id] = [int(t >= ready) for t in range(n)]
        if ready < n:
            energize.setdefault(a.node, [0]*n)[ready:] = [1]*(n-ready)
    for a in inv.loads:
        if a.id in controlled:
            ready = state.picked.get(a.id, n)
            factors[a.id][:ready] = 0
            if ready < n:
                energize.setdefault(a.node, [0]*n)[ready:] = [1]*(n-ready)
    # Retained prefixes may not silently de-energize previously live nodes.
    for node, ready in state.node_ready.items():
        energize.setdefault(node, [0]*n)[ready:] = [1]*(n-ready)
    line_states = {}
    for edge in network.lines:
        closed = 0 if edge.line in req.initial_closed_lines else state.closed.get(edge.line, n)
        line_states[edge.line] = [int(t >= closed) for t in range(n)]
    data.update(device_availability={k: v.tolist() for k, v in factors.items()}, source_commitment=commitment,
                required_energized_nodes=energize, line_status=line_states,
                minimum_load_when_energized={a.id: 1 for a in inv.loads if a.id in assets})
    return DispatchInput.model_validate(data), inv


def update_state(state, result, req):
    state.result = result
    state.node_ready = {}
    for t, row in enumerate(result['rows']):
        for node in row['nodes']:
            if node['energized']:
                state.node_ready.setdefault(node['node'], t)
    energies = tuple(sum(l['served_kwh'] for l in result['load_metrics'] if l['class'] == cls) for cls in CLASSES)
    # Quantize only search tie-breaking, never output trajectories/metrics.
    state.score = (*[round(e, 5) for e in energies], len(state.node_ready), len(state.picked), -len(state.actions),
                   -max((a['end_step'] for a in state.actions), default=0))


def preallocate(req, inventory, network):
    """Priority and electrical-distance seed matching; final feasibility comes from MILP."""
    assets = study_assets(req, inventory)
    def eligible(a):
        if not (a.id in assets and a.grid_forming and a.black_start):
            return False
        ready = max(req.equipment_ready_step.get(a.id, 0), ceil_steps(a.arrival_minutes, req.base.step_hours))
        if ready >= req.base.steps or not equipment_available(req, a, ready):
            return False
        if hasattr(a, 'rated_kw'):
            return a.rated_kw > 0 and (a.fuel_kwh is None or a.fuel_kwh > 1e-9)
        return a.power_kw*a.temperature_factor > 0 and a.energy_kwh*a.temperature_factor*(a.initial_soc-a.minimum_soc-req.base.forming_reserve_ratio) > 1e-8
    seeds = [a for a in inventory.sources+inventory.storage if eligible(a)]
    graph = {n.node: [] for n in network.nodes}
    for edge in network.lines:
        if edge.status or edge.line in req.line_ready_step:
            distance = math.hypot(edge.r_ohm, edge.x_ohm)
            graph[edge.from_node].append((edge.to_node, distance, edge.line))
            graph[edge.to_node].append((edge.from_node, distance, edge.line))
    distances = {}
    for a in seeds:
        queue, found = [(0.0, 0, a.node, ())], {}
        while queue:
            distance, hops, node, path = heapq.heappop(queue)
            if node in found:
                continue
            found[node] = (distance, hops, path)
            for other, weight, line in graph[node]:
                if other not in found:
                    heapq.heappush(queue, (distance+weight, hops+1, other, path+(line,)))
        distances[a.id] = found
    ordered = sorted((a for a in inventory.loads if a.id in assets), key=lambda a: (CLASSES.index(a.load_class), a.priority, a.id))
    rows, allocated_kw = [], {a.id: 0 for a in seeds}
    for load in ordered:
        choices = [(distances[a.id][load.node][0], distances[a.id][load.node][1], a.id,
                    distances[a.id][load.node][2]) for a in seeds if load.node in distances[a.id]]
        demand_kw = max(repeated(load.curve_kw, req.base.steps, load.peak_kw, load.id))
        adequate = [c for c in choices if allocated_kw[c[2]]+demand_kw <=
                    (assets[c[2]].rated_kw if hasattr(assets[c[2]], 'rated_kw') else assets[c[2]].power_kw*assets[c[2]].temperature_factor)+1e-8]
        choice = min(adequate or choices) if choices else None
        if choice:
            allocated_kw[choice[2]] += demand_kw
        rows.append({'load_id': load.id, 'class': load.load_class, 'priority': load.priority,
                     'seed_id': choice[2] if choice else None, 'distance_ohm': choice[0] if choice else None,
                     'path_lines': list(choice[3]) if choice else [], 'capacity_match': bool(adequate),
                     'status': 'heuristic_match' if adequate else 'insufficient_initial_capacity' if choice else 'no_eligible_seed'})
    return rows


def candidate_actions(req, inventory, network, state):
    assets = study_assets(req, inventory)
    used = {(a['kind'], str(a['target_id'])) for a in state.actions}
    result = []
    for a in inventory.sources+inventory.storage:
        if a.id not in assets or ('start', a.id) in used:
            continue
        if a.grid_forming and a.black_start or a.node in state.node_ready:
            result.append(('start', a.id))
    for a in inventory.switches:
        if a.id not in assets or a.line_id in req.initial_closed_lines or a.line_id in state.closed:
            continue
        edge = next(e for e in network.lines if e.line == a.line_id)
        if edge.from_node in state.node_ready or edge.to_node in state.node_ready:
            result.append(('close', a.id))
    for a in inventory.loads:
        if a.id in assets and a.id not in state.picked and a.node in state.node_ready and (a.id in req.manual_load_ids or a.id in req.load_terminals):
            result.append(('pickup', a.id))
    return result


def schedule_action(req, inventory, network, state, kind, asset_id):
    """Schedule parallel commands only in independent current electrical partitions."""
    assets = study_assets(req, inventory)
    asset = assets[asset_id]
    n, dt = req.base.steps, req.base.step_hours
    closed_ids = set(req.initial_closed_lines) | state.closed.keys()
    groups, lookup = components([a.node for a in network.nodes], [e for e in network.lines if e.line in closed_ids])
    touched = set(groups[lookup[asset.node]])
    minimum, sync_target = req.equipment_ready_step.get(asset_id, 0), None
    if kind == 'start':
        minimum = max(minimum, ceil_steps(asset.arrival_minutes, dt))
        if not (asset.grid_forming and asset.black_start):
            minimum = max(minimum, state.node_ready.get(asset.node, n))
        elif asset.node in state.node_ready:
            sync_target = 'resource:'+asset_id
        manual, terminal = asset_id in req.manual_resource_ids, req.resource_terminals.get(asset_id)
        minutes = req.manual_operation_minutes
    elif kind == 'close':
        edge = next(e for e in network.lines if e.line == asset.line_id)
        minimum = max(minimum, req.line_ready_step.get(edge.line, 0 if edge.status else n))
        ready = [state.node_ready[node] for node in (edge.from_node, edge.to_node) if node in state.node_ready]
        minimum = max(minimum, min(ready, default=n))
        touched |= set(groups[lookup[edge.from_node]]) | set(groups[lookup[edge.to_node]])
        for transformer in inventory.transformers:
            if transformer.id in assets and {transformer.node, transformer.to_node} == {edge.from_node, edge.to_node}:
                minimum = max(minimum, req.equipment_ready_step.get(transformer.id, 0))
                if not equipment_available(req, transformer, minimum):
                    raise ValueError('变压器未可用：'+transformer.id)
        if len(ready) == 2:
            minimum = max(minimum, max(ready))
            sync_target = 'line:'+str(edge.line)
        manual = asset_id in req.manual_switch_ids
        terminal = asset.terminal_id if asset.remote_control and not manual else None
        minutes = asset.operation_minutes
    else:
        minimum = max(minimum, state.node_ready.get(asset.node, n))
        manual, terminal = asset_id in req.manual_load_ids, req.load_terminals.get(asset_id)
        minutes = req.manual_operation_minutes
    if not manual and not terminal:
        raise ValueError('缺少明确的人工操作授权或遥控终端')
    minimum = max(minimum, max((state.node_busy.get(node, 0) for node in touched), default=0))
    if req.mode == 'serial':
        minimum = max(minimum, max((a['end_step'] for a in state.actions), default=0))
    crew = min(range(req.manual_crews), key=lambda i: (state.crew_free[i], i)) if manual else None
    if crew is not None:
        minimum = max(minimum, state.crew_free[crew])
    control, command_end, start = None, None, minimum
    # A remote device may acquire station power after an earlier planned action.
    while start < n:
        if not equipment_available(req, asset, start):
            start += 1
            continue
        if manual:
            control = {'status': 'passed', 'mode': 'manual', 'crew': crew+1, 'provenance': req.control_provenance}
        else:
            control = communication_route(req, inventory, state, terminal, asset.node, start)
        if control:
            duration = max(1, ceil_steps(minutes+(control.get('latency_ms', 0)/60000), dt))
            command_end = start+duration
            if command_end >= n:
                break
            if all(equipment_available(req, asset, t) and (manual or communication_route(req, inventory, state, terminal, asset.node, t))
                   for t in range(start, command_end+1)):
                break
        control = None
        start += 1
    if not control or command_end is None or command_end >= n:
        raise ValueError('时域内无可用操作窗口、供电或控制通信路径')
    ready = command_end + (ceil_steps(asset.startup_minutes, dt) if kind == 'start' and hasattr(asset, 'startup_minutes') else 0)
    if kind == 'close':
        ready += max((ceil_steps(a.energization_minutes, dt) for a in inventory.transformers if a.id in assets
                      and {a.node, a.to_node} == {edge.from_node, edge.to_node}), default=0)
    if ready >= n:
        raise ValueError('启动/合闸等待完成超出时域')
    synchronization = None
    if sync_target:
        synchronization = sync_check(req, sync_target, command_end if kind == 'close' else ready)
        if synchronization is None:
            raise ValueError('带电合区/构网源并入缺有效的电压频率相角预同步证据：'+sync_target)
    new = State(actions=copy.deepcopy(state.actions), resources=dict(state.resources), closed=dict(state.closed),
                picked=dict(state.picked), crew_free=list(state.crew_free), node_busy=dict(state.node_busy),
                node_ready=dict(state.node_ready))
    if kind == 'start':
        new.resources[asset_id] = (command_end, ready)
    elif kind == 'close':
        new.closed[asset.line_id] = command_end
    else:
        new.picked[asset_id] = command_end
    if crew is not None:
        new.crew_free[crew] = command_end
    for node in touched:
        new.node_busy[node] = ready
    action = {'kind': kind, 'target_id': asset_id, 'target_name': asset.name, 'start_step': start,
              'command_end_step': command_end, 'end_step': ready, 'start_minutes': start*dt*60,
              'end_minutes': ready*dt*60, 'control': control, 'synchronization': synchronization}
    if kind == 'close':
        action['line_id'] = asset.line_id
    new.actions.append(action)
    return new


def inrush_screen(req, inventory, network, before, after):
    """Conservative supplied-current envelope, explicitly not an EMT waveform model."""
    transformers = []
    for a in inventory.transformers:
        if not (a.existing or req.base.include_candidates):
            continue
        now = max(after.node_ready.get(a.node, req.base.steps), after.node_ready.get(a.to_node, req.base.steps))
        prior = max(before.node_ready.get(a.node, req.base.steps), before.node_ready.get(a.to_node, req.base.steps))
        if now < req.base.steps and prior >= req.base.steps:
            transformers.append((a, now))
    if not transformers:
        return {'name': '新增变压器励磁容量包络', 'status': 'not_applicable', 'details': []}
    details = []
    for transformer, step in transformers:
        row = after.result['rows'][step]
        live_edges = [e for e in network.lines if next(v for v in row['lines'] if v['line'] == e.line)['closed']]
        groups, lookup = components([a.node for a in network.nodes], live_edges)
        group = set(groups[lookup[transformer.node]])
        supporters = [a.id for a in inventory.sources if a.grid_forming and a.node in group and
                      any(s['id'] == a.id and s['on'] and (s['fuel_remaining_kwh'] is None or s['fuel_remaining_kwh']+1e-7 >= (a.fuel_kwh or 0)*req.base.forming_reserve_ratio) for s in row['sources'])]
        for a in inventory.storage:
            if not (a.grid_forming and a.node in group and a.id in after.resources
                    and after.resources[a.id][1] <= step and equipment_available(req, a, step) and a.power_kw*a.temperature_factor > 0):
                continue
            actual = next(v for v in row['storage'] if v['id'] == a.id)
            minimum = a.energy_kwh*a.temperature_factor*(a.minimum_soc+req.base.forming_reserve_ratio)
            if min(actual['energy_begin_kwh'], actual['energy_end_kwh'])+1e-7 >= minimum:
                supporters.append(a.id)
        simultaneous = [a for a, t in transformers if t == step and a.node in group]
        missing = transformer.inrush_multiple is None or any(a.inrush_multiple is None for a in simultaneous) or not supporters or any(i not in req.energizing_current_limits_a for i in supporters)
        if missing:
            details.append({'transformer': transformer.id, 'step': step, 'status': 'not_checked', 'reason': '缺励磁倍数或在线构网支撑电源短时电流参数'})
            continue
        impulse = sum(a.rated_kva*a.inrush_multiple for a in simultaneous)/(math.sqrt(3)*network.base_voltage_kv)
        loads = {a.id: a for a in inventory.loads}
        steady_kva = sum(v['served_kw']*math.hypot(1, loads[v['id']].reactive_kvar/loads[v['id']].peak_kw if loads[v['id']].peak_kw else 0)
                         for v in row['loads'] if loads[v['id']].node in group)
        required = impulse+steady_kva/(math.sqrt(3)*network.base_voltage_kv)
        limit = sum(req.energizing_current_limits_a[a] for a in supporters)
        details.append({'transformer': transformer.id, 'step': step, 'estimated_required_a': required,
                        'supplied_limit_a': limit, 'status': 'passed' if required <= limit+1e-7 else 'failed'})
    status = 'failed' if any(d['status'] == 'failed' for d in details) else 'not_checked' if any(d['status'] == 'not_checked' for d in details) else 'passed'
    return {'name': '新增变压器励磁容量包络', 'status': status, 'details': details,
            'scope': '同电压基准的电流容量筛查，未计算饱和波形、保护配合或动态电压跌落'}


def plan_restoration(req: RestorationInput, inventory: Inventory, network: Network, progress=None, cancelled=None):
    validate_restoration(req, inventory, network)
    started = time.monotonic()
    rejected, seen, evaluations = [], set(), 0
    stop_reason = 'search_exhausted'
    def check():
        if cancelled and cancelled():
            raise StudyCancelled('恢复规划取消')
    def evaluate(state):
        nonlocal evaluations
        check()
        remaining = req.wall_time_seconds-(time.monotonic()-started)
        if remaining < 1:
            raise TimeoutError('总时限达到')
        parameters, actual_inventory = materialize(req, inventory, network, state)
        parameters.time_limit_seconds = min(parameters.time_limit_seconds, remaining)
        evaluations += 1
        result = dispatch(parameters, actual_inventory, network, cancelled=cancelled)
        if result['status'] != 'optimal':
            raise DispatchIncomplete('候选调度未完成分层优化，不用于排序或否定路径')
        update_state(state, result, req)
        return state
    empty = State(crew_free=[0]*req.manual_crews)
    best = evaluate(empty)
    beam = [best]
    for depth in range(req.maximum_operations):
        candidates = []
        for old in beam:
            for kind, asset_id in candidate_actions(req, inventory, network, old):
                check()
                if evaluations >= req.maximum_evaluations or time.monotonic()-started >= req.wall_time_seconds:
                    stop_reason = 'evaluation_limit' if evaluations >= req.maximum_evaluations else 'time_limit'
                    break
                try:
                    state = schedule_action(req, inventory, network, old, kind, asset_id)
                    key = canonical_sha({'resources': state.resources, 'closed': state.closed, 'picked': state.picked,
                                         'crew_free': state.crew_free, 'node_busy': state.node_busy})
                    if key in seen:
                        continue
                    seen.add(key)
                    state = evaluate(state)
                    screen = inrush_screen(req, inventory, network, old, state)
                    if screen['status'] == 'failed' or req.require_inrush_parameters and screen['status'] == 'not_checked':
                        raise ValueError('励磁容量包络失败或缺少必要参数')
                    state.actions[-1]['inrush_screen'] = screen
                    state.actions[-1]['new_energized_nodes'] = sorted(set(state.node_ready)-set(old.node_ready))
                    candidates.append(state)
                    if state.score > best.score:
                        best = state
                except DispatchIncomplete as e:
                    rejected.append({'depth': depth, 'kind': kind, 'target_id': asset_id, 'status': 'unknown', 'reason': str(e)})
                except (DispatchInfeasible, ValueError) as e:
                    rejected.append({'depth': depth, 'kind': kind, 'target_id': asset_id, 'status': 'rejected', 'reason': str(e)})
                except TimeoutError:
                    stop_reason = 'time_limit'
                    break
                if progress:
                    progress({'phase': 'restoration_search', 'fraction': min(.99, evaluations/req.maximum_evaluations),
                              'evaluations': evaluations, 'depth': depth+1, 'best_operations': len(best.actions)})
            if stop_reason != 'search_exhausted':
                break
        if stop_reason != 'search_exhausted' or not candidates:
            break
        candidates.sort(key=lambda s: s.score, reverse=True)
        beam = candidates[:req.beam_width]
        if depth+1 == req.maximum_operations:
            stop_reason = 'operation_limit'
    check()
    last = best.result['rows'][-1]
    connected = {r['line'] for r in last['lines'] if r['closed']}
    groups, _ = components([n.node for n in network.nodes], [e for e in network.lines if e.line in connected])
    partitions = []
    assets = study_assets(req, inventory)
    for index, nodes in enumerate(groups):
        if not any(node in best.node_ready for node in nodes):
            continue
        partitions.append({'id': index+1, 'nodes': nodes, 'resources': [a.id for a in inventory.sources+inventory.storage if a.id in best.resources and a.node in nodes],
                           'loads': [a.id for a in inventory.loads if a.id in assets and a.node in nodes],
                           'first_energized_minutes': min(best.node_ready.get(node, req.base.steps) for node in nodes)*req.base.step_hours*60})
    recovery = []
    for a in inventory.loads:
        if a.id not in assets:
            continue
        flags = []
        for row in best.result['rows']:
            value = next(v for v in row['loads'] if v['id'] == a.id)
            flags.append(value['demand_kw'] <= 1e-8 or value['served_kw']+1e-5 >= value['demand_kw'])
        # A zero-demand prefix is not proof that the load was energized or connected.
        eligible = best.picked.get(a.id, req.base.steps) if a.id in set(req.manual_load_ids) | req.load_terminals.keys() else best.node_ready.get(a.node, req.base.steps)
        restoration_step = next((t for t in range(eligible, req.base.steps) if all(flags[t:])), None)
        recovery.append({'load_id': a.id, 'class': a.load_class, 'first_sustained_full_supply_minutes': restoration_step*req.base.step_hours*60 if restoration_step is not None else None,
                         'restored_to_horizon': restoration_step is not None})
    parameter_snapshot, actual_inventory = materialize(req, inventory, network, best)
    checks = [{'name': '逐步辐射拓扑/容量/燃料/SOC/静态电压', 'status': 'passed'},
              {'name': '操作设备/终端/控制通信及前置关系', 'status': 'passed'},
              {'name': '完整交流网损与多电压模型', 'status': 'not_checked'},
              {'name': '频率/电压暂态稳定', 'status': 'not_checked'},
              {'name': '励磁饱和波形/保护与实际预同步', 'status': 'not_checked'},
              {'name': 'MRSCR分级与动态控制策略', 'status': 'not_checked'}]
    if progress:
        progress({'phase': stop_reason, 'fraction': 1 if stop_reason == 'search_exhausted' else min(.99, evaluations/req.maximum_evaluations), 'evaluations': evaluations})
    return {'method': METHOD, 'status': 'complete' if stop_reason == 'search_exhausted' else 'incomplete_search',
            'stop_reason': stop_reason, 'mode': req.mode, 'actions': best.actions, 'partitions': partitions,
            'preallocation': preallocate(req, inventory, network), 'load_recovery': recovery,
            'dispatch': best.result, 'replay_parameters': parameter_snapshot.model_dump(mode='json'),
            'replay_inventory': actual_inventory.model_dump(mode='json'), 'checks': checks,
            'operational_clearance': 'not_cleared', 'evaluations': evaluations, 'rejected_candidates': rejected,
            'goal_status': 'restored_to_horizon' if all(r['restored_to_horizon'] for r in recovery) else 'partially_restored' if any(r['restored_to_horizon'] for r in recovery) else 'unrestored',
            'runtime_seconds': time.monotonic()-started,
            'scope': ['有限束搜索按基本保障/居民/一般已供电量分层排序，非全局最优证明。',
                      '全停电初态；线路初始状态显式输入，未建控制的负荷随带电分区全量投入。',
                      '只有显式手动授权或同节点终端映射的负荷可分步投入；命令后要求全量供电到时域末。',
                      '序列中已恢复节点不得静默失电，电源命令后强制在线，全部前缀经全时域调度复算。',
                      '人工队伍之间及电气独立分区可并行，同一分区串行；人工操作时间须含实际行程/接线，未自动求车辆路径。',
                      '开关只能合闸一次，故障须到可用步后处理；尚不搜索打开现有线路的预隔离/重构操作。',
                      '通信链路按双向、串行延时相加建模；终端与控制器须已供电或声明备用供电，失联不自动降为手动。',
                      '启动/到位/操作/励磁等待向后对齐时间网格；变压器等待期间未隔离的负荷仍随线路带电，暂态未认证。',
                      '带电合区与构网源并入须有覆盖该步的外部V/f/相角数值证据，通过只表示输入数值满足阈值。',
                      '励磁包络仅比较输入倍数估计电流加稳态负荷电流与已给短时限额，不代替EMT、饱和与保护计算。',
                      '当前无损LinDistFlow与统一电压基准，缺动态与MRSCR模型；即使静态通过也不生成安全执行许可。']}
