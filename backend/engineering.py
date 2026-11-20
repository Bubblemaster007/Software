"""Typed engineering inventory and the PPT's scenario/priority calculations.

Inventory revisions are independent from the editable project state. No inventory
is silently converted to the legacy aggregate dispatch parameters.
"""
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal
import hashlib
import json
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.workspace import project_record

ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix='/api/engineering', tags=['工程台账与分类保供目标'])
REGIONS = ('东部', '中部', '西部')
KINDS = ('县域级', '乡镇级', '村级')
LOAD_CLASSES = ('基本保障', '居民生活', '一般负荷')


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=True)


class Asset(StrictModel):
    id: str = Field(min_length=1, max_length=64, pattern=r'^[\w.-]+$')
    name: str = Field(min_length=1, max_length=100)
    node: int = Field(ge=1, le=99999)
    existing: bool = True
    available: bool = True
    longitude: float | None = Field(None, ge=-180, le=180)
    latitude: float | None = Field(None, ge=-90, le=90)
    provenance: str = Field('', max_length=1000)

    @model_validator(mode='after')
    def coordinates(self):
        if (self.longitude is None) != (self.latitude is None):
            raise ValueError('经纬度须同时填写或同时留空')
        return self


class Source(Asset):
    kind: Literal['光伏', '风电', '小水电', '柴油机', '移动发电车']
    rated_kw: float = Field(ge=0, le=1000000)
    minimum_kw: float = Field(0, ge=0)
    reactive_limit_kvar: float = Field(0, ge=0, le=1000000)
    apparent_limit_kva: float | None = Field(None, gt=0, le=1000000)
    startup_minutes: float = Field(0, ge=0, le=100000)
    ramp_kw_per_minute: float | None = Field(None, gt=0)
    available_hours: float | None = Field(None, gt=0, le=8760)
    grid_forming: bool = False
    black_start: bool = False
    arrival_minutes: float = Field(0, ge=0, le=100000)
    fuel_kwh: float | None = Field(None, ge=0)
    curve_kw: list[float] = Field(default_factory=list, max_length=35136)

    @model_validator(mode='after')
    def capacity(self):
        if self.minimum_kw > self.rated_kw:
            raise ValueError('电源最小出力不得超过额定功率')
        if any(not 0 <= x <= self.rated_kw for x in self.curve_kw):
            raise ValueError('电源曲线须为0至额定功率之间的有限值')
        if self.black_start and not self.grid_forming:
            raise ValueError('自启动电源必须具备建压建频能力')
        return self


class Storage(Asset):
    reactive_limit_kvar: float = Field(0, ge=0, le=1000000)
    apparent_limit_kva: float | None = Field(None, gt=0, le=1000000)
    mobile: bool = False
    power_kw: float = Field(ge=0, le=1000000)
    energy_kwh: float = Field(ge=0, le=10000000)
    initial_soc: float = Field(.8, ge=0, le=1)
    minimum_soc: float = Field(.1, ge=0, le=1)
    maximum_soc: float = Field(.95, ge=0, le=1)
    charge_efficiency: float = Field(.95, gt=0, le=1)
    discharge_efficiency: float = Field(.95, gt=0, le=1)
    arrival_minutes: float = Field(0, ge=0, le=100000)
    grid_forming: bool = False
    black_start: bool = False
    temperature_factor: float = Field(1, ge=0, le=1)

    @model_validator(mode='after')
    def energy(self):
        if not self.minimum_soc <= self.initial_soc <= self.maximum_soc:
            raise ValueError('储能须满足SOC下限≤初始值≤上限')
        if self.black_start and not self.grid_forming:
            raise ValueError('黑启动储能必须具备构网能力')
        return self


class Load(Asset):
    load_class: Literal['基本保障', '居民生活', '一般负荷'] = '居民生活'
    peak_kw: float = Field(ge=0, le=1000000)
    reactive_kvar: float = Field(0, ge=0, le=1000000)
    minimum_supply_ratio: float = Field(1, ge=0, le=1)
    target_hours: float = Field(48, ge=0, le=8760)
    maximum_curtailment_ratio: float = Field(0, ge=0, le=1)
    interruption_allowed: bool = False
    maximum_interruption_hours: float = Field(0, ge=0, le=8760)
    priority: int = Field(1, ge=1, le=1000)
    cti: float | None = Field(None, ge=0, le=1)
    curve_kw: list[float] = Field(default_factory=list, max_length=35136)

    @model_validator(mode='after')
    def demand(self):
        if any(not 0 <= x <= self.peak_kw for x in self.curve_kw):
            raise ValueError('负荷曲线须为0至峰值之间的有限值')
        if not self.interruption_allowed and self.maximum_interruption_hours:
            raise ValueError('不允许中断的负荷不能设置允许中断时长')
        return self


class Transformer(Asset):
    to_node: int = Field(ge=1)
    rated_kva: float = Field(gt=0)
    ratio: float = Field(1, gt=0)
    inrush_multiple: float | None = Field(None, ge=0)
    energization_minutes: float = Field(0, ge=0)


class Switch(Asset):
    line_id: int = Field(ge=1)
    normally_closed: bool = True
    remote_control: bool = False
    operation_minutes: float = Field(1, ge=0)
    terminal_id: str | None = None


class Controller(Asset):
    covered_nodes: list[int] = Field(default_factory=list, max_length=1000)
    local_autonomy: bool = True


class Terminal(Asset):
    controller_id: str
    local_control: bool = True


class CommunicationLink(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    from_device: str
    to_device: str
    available: bool = True
    latency_ms: float = Field(0, ge=0)
    cost_yuan: float = Field(0, ge=0)


class Economics(StrictModel):
    discount_rate: float = Field(.06, ge=0, le=1)
    lifetime_years: int = Field(15, ge=1, le=100)
    investment_limit_yuan: float | None = Field(None, ge=0)
    pv_yuan_per_kw: float = Field(3200, ge=0)
    wind_yuan_per_kw: float = Field(4200, ge=0)
    storage_power_yuan_per_kw: float = Field(750, ge=0)
    storage_energy_yuan_per_kwh: float = Field(1100, ge=0)
    fuel_yuan_per_kwh: float = Field(1.15, ge=0)
    shortage_yuan_per_kwh: float = Field(20, ge=0)
    curtailment_yuan_per_kwh: float = Field(6, ge=0)
    annual_maintenance_yuan: float = Field(0, ge=0)
    provenance: str = Field('界面设计PPT示例成本，需按工程核实', max_length=1000)


class Inventory(StrictModel):
    sources: list[Source] = Field(default_factory=list, max_length=500)
    storage: list[Storage] = Field(default_factory=list, max_length=500)
    loads: list[Load] = Field(default_factory=list, max_length=1000)
    transformers: list[Transformer] = Field(default_factory=list, max_length=500)
    switches: list[Switch] = Field(default_factory=list, max_length=1000)
    controllers: list[Controller] = Field(default_factory=list, max_length=500)
    terminals: list[Terminal] = Field(default_factory=list, max_length=1000)
    communication: list[CommunicationLink] = Field(default_factory=list, max_length=2000)
    economics: Economics = Field(default_factory=Economics)
    scenario_template_id: str | None = Field(None, max_length=100)
    coordinate_system: str = Field('WGS84', min_length=1, max_length=80)

    @model_validator(mode='after')
    def references(self):
        assets = self.sources + self.storage + self.loads + self.transformers + self.switches + self.controllers + self.terminals
        ids = [a.id for a in assets] + [a.id for a in self.communication]
        if len(ids) != len(set(ids)):
            raise ValueError('设备、负荷及通信链路编号在工程台账内须全局唯一')
        controllers = {a.id for a in self.controllers}
        terminals = {a.id for a in self.terminals}
        for terminal in self.terminals:
            if terminal.controller_id not in controllers:
                raise ValueError('终端引用的协调控制器不存在：' + terminal.id)
        for switch in self.switches:
            if switch.terminal_id and switch.terminal_id not in terminals:
                raise ValueError('开关引用的终端不存在：' + switch.id)
            if switch.remote_control and not switch.terminal_id:
                raise ValueError('遥控开关须关联自动化终端：' + switch.id)
        devices = controllers | terminals
        for link in self.communication:
            if link.from_device == link.to_device or not {link.from_device, link.to_device} <= devices:
                raise ValueError('通信链路端点须为已存在的两个不同控制器/终端：' + link.id)
        return self


class InventoryWrite(StrictModel):
    project_revision: int = Field(ge=1)
    expected_revision: int = Field(ge=0)
    inventory: Inventory


def connection():
    c = sqlite3.connect(ROOT / 'data/platform.db')
    c.execute('CREATE TABLE IF NOT EXISTS engineering_inventory(project_id TEXT PRIMARY KEY, revision INTEGER, payload TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS engineering_versions(project_id TEXT, revision INTEGER, payload TEXT, PRIMARY KEY(project_id,revision))')
    return c


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def inventory_record(project_id: str):
    project_record(project_id)
    with closing(connection()) as c:
        row = c.execute('SELECT payload FROM engineering_inventory WHERE project_id=?', (project_id,)).fetchone()
    if row:
        return json.loads(row[0])
    inventory = Inventory().model_dump()
    return {'project_id': project_id, 'revision': 0, 'inventory': inventory, 'sha256': canonical_sha(inventory)}


def inventory_snapshot(project_id: str, revision: int | None = None):
    if revision is None:
        return inventory_record(project_id)
    if revision == 0:
        project_record(project_id)
        inventory = Inventory().model_dump()
        return {'project_id': project_id, 'revision': 0, 'inventory': inventory, 'sha256': canonical_sha(inventory)}
    return read_version(project_id, revision)


def validate_nodes(inventory: Inventory, project):
    if inventory.scenario_template_id and inventory.scenario_template_id not in {r['id'] for r in scenario_templates()}:
        raise ValueError('典型场景模板编号不存在')
    network = project['state'].get('network')
    nodes = {n['node'] for n in network['nodes']} if network else set(range(1, 34))
    lines = {l['line'] for l in network['lines']} if network else set(range(1, 38))
    for asset in inventory.sources + inventory.storage + inventory.loads + inventory.transformers + inventory.switches + inventory.controllers + inventory.terminals:
        if asset.node not in nodes:
            raise ValueError(f'{asset.id}接入节点不存在，请先保存工程网络')
    for t in inventory.transformers:
        if t.to_node not in nodes or t.node == t.to_node:
            raise ValueError('变压器端点须为两个不同的已存节点：' + t.id)
    for switch in inventory.switches:
        if switch.line_id not in lines:
            raise ValueError('开关关联线路不存在：' + switch.id)
    for controller in inventory.controllers:
        if len(controller.covered_nodes) != len(set(controller.covered_nodes)) or not set(controller.covered_nodes) <= nodes:
            raise ValueError('控制器覆盖范围存在无效或重复节点：' + controller.id)


@router.get('/projects/{project_id}')
def read_inventory(project_id: str):
    return inventory_record(project_id)


@router.put('/projects/{project_id}')
def save_inventory(project_id: str, req: InventoryWrite):
    project = project_record(project_id)
    try:
        validate_nodes(req.inventory, project)
    except ValueError as e:
        raise HTTPException(422, str(e))
    payload = req.inventory.model_dump()
    if len(json.dumps(payload)) > 6000000:
        raise HTTPException(422, '工程台账超过6MB，请分离长曲线')
    with closing(connection()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        project_row = c.execute('SELECT revision FROM projects WHERE id=?', (project_id,)).fetchone()
        if not project_row or project_row[0] != req.project_revision:
            raise HTTPException(409, '工程版本已变化，请刷新后重新校验台账')
        row = c.execute('SELECT revision FROM engineering_inventory WHERE project_id=?', (project_id,)).fetchone()
        current = row[0] if row else 0
        if req.expected_revision != current:
            raise HTTPException(409, '工程台账已在其他窗口修改，请重新读取')
        record = {'project_id': project_id, 'project_revision': req.project_revision, 'revision': current + 1,
                  'updated': datetime.now().isoformat(timespec='seconds'), 'inventory': payload, 'sha256': canonical_sha(payload)}
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
        c.execute('INSERT OR REPLACE INTO engineering_inventory VALUES(?,?,?)', (project_id, record['revision'], encoded))
        c.execute('INSERT INTO engineering_versions VALUES(?,?,?)', (project_id, record['revision'], encoded))
    return record


@router.get('/projects/{project_id}/versions')
def list_versions(project_id: str):
    project_record(project_id)
    with closing(connection()) as c:
        rows = c.execute('SELECT payload FROM engineering_versions WHERE project_id=? ORDER BY revision DESC', (project_id,)).fetchall()
    result=[]
    for row in rows:
        record=json.loads(row[0]); state=record.get('inventory', {})
        result.append({'project_id': project_id, 'revision': record['revision'],
                       'updated': record.get('updated'), 'name': state.get('project_name') or state.get('name') or '工程台账',
                       'region': state.get('region') or ''})
    return result


@router.get('/projects/{project_id}/versions/{revision}')
def read_version(project_id: str, revision: int):
    project_record(project_id)
    with closing(connection()) as c:
        row = c.execute('SELECT payload FROM engineering_versions WHERE project_id=? AND revision=?', (project_id, revision)).fetchone()
    if not row:
        raise HTTPException(404, '台账版本不存在')
    return json.loads(row[0])


def regional_targets(region: str):
    return [
        {'load_class': '基本保障', 'minimum_supply_ratio': 1, 'target_hours': 72 if region == '西部' else 48,
         'interruption_allowed': False, 'maximum_curtailment_ratio': 0, 'priority': 1},
        {'load_class': '居民生活', 'minimum_supply_ratio': .6 if region == '西部' else .8,
         'target_hours': 72 if region == '西部' else 48, 'interruption_allowed': True, 'maximum_curtailment_ratio': .4 if region == '西部' else .2, 'priority': 2},
        {'load_class': '一般负荷', 'minimum_supply_ratio': 0, 'target_hours': 0, 'interruption_allowed': True, 'maximum_curtailment_ratio': 1, 'priority': 3},
    ]


def scenario_templates():
    rows = []
    for kind in KINDS:
        for region in (('西部',) if kind == '县域级' else REGIONS):
            for period in ((20,) if kind == '村级' else (20, 50)):
                rows.append({'id': f'{kind}-{region}-{period}', 'kind': kind, 'region': region, 'return_period_years': period,
                             'name': f'{region}{kind}·{period}年一遇', 'targets': regional_targets(region),
                             'hazard_examples': {'西部': ['雨雪冰冻', '覆冰'], '东部': ['台风', '洪涝'], '中部': ['暴雨', '内涝']}[region],
                             'calibrated': False, 'probability': None,
                             'provenance': '完整中期PPT第14—15、19页；模板须按示范区确认，不自动生成设备故障概率'})
    return rows


@router.get('/scenario-templates')
def templates():
    return {'templates': scenario_templates(), 'types': KINDS, 'source': '完整65页中期PPT，课题1',
            'note': '重现期为灾害等级标签，不能直接作为逐时设备故障概率；模板目标未经示范区核实。'}


class PriorityInput(StrictModel):
    cti: float = Field(ge=0, le=1)
    historical_consequence: float = Field(ge=0, le=1)
    repair_hours: float = Field(ge=0)
    repair_reference_hours: float = Field(gt=0)
    disaster_hours: float = Field(ge=0)
    disaster_reference_hours: float = Field(gt=0)
    supply_kw: float = Field(ge=0)
    supply_reference_kw: float = Field(gt=0)
    interruptibility: float = Field(ge=0, le=1)
    curtailability: float = Field(ge=0, le=1)
    weights: list[float] = Field(min_length=6, max_length=6)
    beta: float = Field(.6, ge=0, le=1)
    importance: float | None = Field(None, ge=0, le=1)

    @model_validator(mode='after')
    def normalization(self):
        if any(w < 0 for w in self.weights) or abs(sum(self.weights) - 1) > 1e-8:
            raise ValueError('六项权重须非负且合计为1')
        if self.repair_hours > self.repair_reference_hours or self.supply_kw > self.supply_reference_kw:
            raise ValueError('抢修时长及供电能力不得大于其归一化参考上限')
        return self


@router.post('/priority')
def priority(req: PriorityInput):
    cls = '基本保障' if req.cti >= .75 else '居民生活' if req.cti >= .30 else '一般负荷'
    importance = req.importance if req.importance is not None else {'基本保障': .93, '居民生活': .70, '一般负荷': .56}[cls]
    values = [req.historical_consequence, 1 - req.repair_hours / req.repair_reference_hours,
              req.disaster_hours / req.disaster_reference_hours, 1 - req.supply_kw / req.supply_reference_kw,
              1 - req.interruptibility, 1 - req.curtailability]
    terms = [w * x for w, x in zip(req.weights, values)]
    demand = sum(terms)
    return {'load_class': cls, 'cti': req.cti, 'demand_index': demand, 'importance': importance,
            'priority_score': req.beta * demand + (1 - req.beta) * importance,
            'components': [{'name': name, 'value': value, 'weight': weight, 'contribution': term}
                           for name, value, weight, term in zip(['历史后果', '1-抢修/上限', '灾害/参考时长', '1-供电/上限', '1-可中断', '1-可削减'], values, req.weights, terms)],
            'parameters': req.model_dump(), 'method': 'ppt.topic1.priority.v1', 'source': '完整中期PPT第16—18页',
            'notes': ['CTI采用录入的已评审综合特性值，不擅自推定CTI指标权重。',
                      '保留PPT原公式1-R/Tmax的方向，未静默改写；灾害时长超过参考值时需求指数可能大于1，不强行截断。']}


@router.get('/schema')
def inventory_schema():
    return {'inventory': Inventory.model_json_schema(), 'priority': PriorityInput.model_json_schema(),
            'units': {'power': 'kW', 'energy': 'kWh', 'reactive_power': 'kvar', 'cost': '元', 'time': 'h', 'startup': 'min'},
            'scope': '逐设备台账及分类目标已可保存校验；尚未自动替换旧汇总平衡输入。'}
