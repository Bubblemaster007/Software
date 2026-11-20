"""Derive evaluation inputs from frozen engineering results and retain the proof."""
from contextlib import closing
from datetime import datetime, timedelta
import json
import math
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field, model_validator
from backend.engineering import StrictModel, Inventory, canonical_sha
from backend.workspace import project_record
from backend.effect_evaluation import EvaluationInput, evaluation_result, save_evaluation

router = APIRouter(prefix='/api/effect-evaluations', tags=['档案指标与质效评价'])
METHOD = 'frozen-archive.evaluation-indicators.v1'
DYNAMIC_CHECKS = ['电压稳定', '频率稳定', '黑启动可行性']
# The registry distinguishes energy delivery from time-based reliability and stability.
METRICS = [
    ('served_energy_kwh', '已覆盖区间供电量', 'benefit', 'kWh', 'Σ供电功率×时间步长'),
    ('unsupplied_energy_kwh', '已覆盖区间未供电量', 'cost', 'kWh', 'Σ(负荷功率−供电功率)×时间步长'),
    ('energy_supply_ratio', '已覆盖区间电量供给比例', 'benefit', '比例', '供电量/负荷电量，零需求时不可用'),
    ('maximum_unsupplied_kw', '已覆盖区间最大未供功率', 'cost', 'kW', 'max(负荷功率−供电功率)'),
    ('study_dispatch_cost_yuan', '已覆盖区间研究运行费用', 'cost', '元', '冻结价格下的购电、燃料、启动、储能吞吐和主动削减费用'),
    ('capex_yuan', '新增设备名义投资', 'cost', '元', 'Σ所选设备资本支出；与逐年现金流资本支出核对'),
    ('discounted_cost_yuan', '规划折现净成本', 'cost', '元', 'Σ逐年discounted_total_yuan；覆盖冻结代表场景及频次'),
    ('training_target_success_probability', '训练场景目标达标权重', 'benefit', '比例', '跨期联合或各期最低实际达标权重，沿用冻结风险范围'),
    ('validation_target_success_lower', '样本外目标达标权重下界', 'benefit', '比例', '冻结验证集的已证明通过权重，未知权重保留'),
    ('validation_unknown_probability', '样本外未知权重', 'cost', '比例', '跨期联合或各期最大未知权重'),
    ('worst_period_event_unsupplied_kwh', '最不利运营期加权事件未供电量', 'cost', 'kWh/次', '每期Σ训练场景权重×事件未供电量，再取期内最大值'),
]
DEFINITIONS = {key: {'id': key, 'name': name, 'direction': direction, 'unit': unit, 'formula': formula}
               for key, name, direction, unit, formula in METRICS}


class ArchiveReference(StrictModel):
    kind: Literal['device_dispatch', 'study_job', 'investment_case']
    id: str = Field(min_length=1, max_length=64)
    case_id: str | None = Field(None, min_length=1, max_length=64)
    expected_sha256: str | None = Field(None, pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def case_reference(self):
        if (self.kind == 'investment_case') != (self.case_id is not None):
            raise ValueError('配置比较单例须提供case_id，其他类型省略该字段')
        return self


class ArchiveEvaluationInput(StrictModel):
    project_id: str
    project_revision: int = Field(ge=1)
    name: str = Field('档案指标质效评价', min_length=1, max_length=100)
    references: list[ArchiveReference] = Field(min_length=2, max_length=100)
    metric_ids: list[str] = Field(min_length=1, max_length=30)
    safety_limits: dict[str, Annotated[float, Field(ge=-1e15, le=1e15)]] = Field(default_factory=dict)
    entropy_share: float = Field(.5, ge=0, le=1)
    entropy_sweep: list[Annotated[float, Field(ge=0, le=1)]] = Field(default_factory=lambda: [0, .25, .5, .75, 1], max_length=21)
    comparison_note: str = Field('', max_length=2000)

    @model_validator(mode='after')
    def selection(self):
        identities = [(ref.kind, ref.id, ref.case_id) for ref in self.references]
        if len(set(identities)) != len(identities):
            raise ValueError('不能重复选择同一档案')
        if len(set(self.metric_ids)) != len(self.metric_ids) or not set(self.metric_ids) <= DEFINITIONS.keys():
            raise ValueError('指标须为唯一的受支持指标ID')
        if not self.safety_limits.keys() <= set(self.metric_ids):
            raise ValueError('硬阈值须引用本次选定指标')
        return self


def finite(value):
    if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError('归档指标包含缺失或无效数值')
    return float(value)


def consistent(actual, expected):
    return abs(finite(actual)-finite(expected)) <= max(1e-5, abs(expected)*1e-7)


def inventory_for_case(snapshot, artifact):
    values = json.loads(json.dumps(snapshot['engineering']['inventory']))
    overrides = artifact.get('inventory_overrides', {})
    if 'economics' in overrides:
        values['economics'] = overrides['economics']
    for asset in values.get('storage', []):
        if asset['id'] in overrides.get('storage_temperature_factor', {}):
            asset['temperature_factor'] = overrides['storage_temperature_factor'][asset['id']]
    inventory = Inventory.model_validate(values)
    if canonical_sha(inventory.model_dump(mode='json')) != artifact['inventory_sha256']:
        raise ValueError('配置单例库存摘要与冻结覆盖不一致')
    return inventory


def read_source(ref, project_id):
    from backend import resource_dispatch, study_jobs
    if ref.kind == 'device_dispatch':
        record = resource_dispatch.read(ref.id)
        snapshot, result = record['input'], record['result']
        family, artifact = 'dispatch', None
    else:
        record = study_jobs.get(ref.id, include_input=True, include_result=True)
        snapshot, result = record['input'], record['result']
        family, artifact = record['module'], None
        if ref.kind == 'investment_case':
            if family != 'investment_experiments':
                raise ValueError('单例引用须来自配置比较任务')
            with closing(study_jobs.connection()) as connection:
                row = connection.execute('SELECT payload FROM study_case_results WHERE job_id=? AND case_id=?',
                                         (ref.id, ref.case_id)).fetchone()
            if row is None:
                raise HTTPException(404, '配置单例证据尚未归档')
            artifact = json.loads(row[0])
            result, family = artifact['result'], 'investment'
        elif family not in ('device_dispatch', 'annual_dispatch', 'investment'):
            raise ValueError('请选择逐设备调度、年度滚动、联合配置或配置比较完整单例')
        elif record['status'] not in ('succeeded', 'incomplete') or result is None:
            raise ValueError('所选任务尚无可用汇总结果')
        if family == 'device_dispatch':
            family = 'dispatch'
    if record['project_id'] != project_id:
        raise ValueError('评价引用的档案须属于当前工程')
    if canonical_sha(snapshot) != record['input_sha256']:
        raise ValueError('来源冻结输入摘要校验失败')
    if result is None or result.get('status') == 'infeasible':
        raise ValueError('该档案没有可用于评价的物理可行结果')
    signature = canonical_sha({'input': snapshot, 'result': result, 'case': artifact})
    if ref.expected_sha256 and ref.expected_sha256 != signature:
        raise HTTPException(409, '来源档案已变化，请重新提取指标')
    parameters = artifact['parameters'] if artifact else snapshot['parameters']
    inventory = inventory_for_case(snapshot, artifact) if artifact else Inventory.model_validate(snapshot['engineering']['inventory'])
    if artifact and canonical_sha({'parameters': parameters, 'inventory': inventory.model_dump(mode='json'),
                                   'network': snapshot['network']}) != artifact['derived_input_sha256']:
        raise ValueError('配置单例输入摘要校验失败')
    return {'reference': ref.model_dump(exclude={'expected_sha256'}), 'sha256': signature,
            'source_input_sha256': record['input_sha256'], 'source_result_sha256': canonical_sha(result),
            'name': record['name'] + (' · '+artifact['definition']['name'] if artifact else ''),
            'family': family, 'snapshot': snapshot, 'parameters': parameters, 'inventory': inventory,
            'result': result, 'artifact': artifact}


def trace_metrics(rows, parameters, inventory):
    from backend.annual_dispatch import committed_metrics
    from backend.resource_dispatch import DispatchInput
    if not rows:
        raise ValueError('来源没有已提交轨迹')
    req = DispatchInput.model_validate(parameters)
    load = served = 0.
    maximum = 0.
    demand_trace = []
    start = datetime.fromisoformat(parameters['start'])
    for index, row in enumerate(rows):
        if datetime.fromisoformat(row['timestamp']) != start+timedelta(hours=index*req.step_hours):
            raise ValueError('来源轨迹的时间轴不连续')
        if not consistent(row.get('step_hours', req.step_hours), req.step_hours):
            raise ValueError('来源轨迹步长与冻结输入不一致')
        demand, supply = finite(row['load_kw']), finite(row['served_kw'])
        if demand < -1e-6 or supply < -1e-6 or supply > demand+1e-5:
            raise ValueError('来源负荷或供电轨迹越界')
        load += demand*req.step_hours
        served += supply*req.step_hours
        maximum = max(maximum, demand-supply)
        demand_trace.append([row['timestamp'], sorted((a['id'], a['demand_kw']) for a in row['loads'])])
    values = {'served_energy_kwh': served, 'unsupplied_energy_kwh': max(0, load-served),
              'maximum_unsupplied_kw': maximum}
    if load > 0:
        values['energy_supply_ratio'] = served/load
    try:
        values['study_dispatch_cost_yuan'] = committed_metrics(rows, req, inventory)['study_dispatch_cost_yuan']
    except KeyError:
        pass  # Older archives may retain energy traces without every cost component.
    proof = {'load_energy_kwh': load, 'served_energy_kwh': served, 'steps': len(rows),
             'step_hours': req.step_hours, 'start': parameters['start'],
             'demand_trace_sha256': canonical_sha(demand_trace), 'trajectory_sha256': canonical_sha(rows)}
    return values, proof


def annual_rows(source):
    from backend import study_jobs
    rows, hashes = [], []
    summaries = source['result']['windows']
    with closing(study_jobs.connection()) as connection:
        for summary in summaries:
            saved = connection.execute('SELECT payload FROM study_case_results WHERE job_id=? AND case_id=?',
                                       (source['reference']['id'], summary['id'])).fetchone()
            if saved is None:
                raise ValueError('年度提交窗口证据缺失')
            artifact = json.loads(saved[0])
            if canonical_sha(artifact['summary']) != canonical_sha(summary):
                raise ValueError('年度窗口摘要与汇总不一致')
            if len(artifact['committed_rows']) != summary['committed_steps']:
                raise ValueError('年度窗口提交行数与摘要不一致')
            for row in artifact['committed_rows']:
                if row['global_step'] != len(rows):
                    raise ValueError('年度提交轨迹存在重叠或缺步')
                rows.append(row)
            hashes.append({'id': summary['id'], 'sha256': canonical_sha(artifact)})
    if len(rows) != source['result']['coverage']['completed_steps']:
        raise ValueError('年度轨迹行数与实际覆盖不一致')
    return rows, hashes


def investment_metrics(source):
    result, parameters = source['result'], source['parameters']
    values, proof = {}, {'cashflows': result.get('cashflows', []), 'periods': result.get('compliance', [])}
    if result.get('cashflows'):
        capex = sum(finite(row['capex_yuan']) for row in result['cashflows'])
        selected_capex = sum(finite(row['capex_yuan']) for row in result['selected_assets'])
        discounted = sum(finite(row['discounted_total_yuan']) for row in result['cashflows'])
        if not consistent(capex, selected_capex) or not consistent(discounted, result['objective_yuan']):
            raise ValueError('配置现金流与所选投资或折现目标不一致')
        values.update(capex_yuan=capex, discounted_cost_yuan=discounted)
    if parameters.get('risk_scope') == 'all_periods':
        probability = result.get('all_periods_actual_probability')
        validation = [result['validation_all_periods']] if result.get('validation_all_periods') else []
    else:
        probability = min((row['actual_probability'] for row in result.get('compliance', [])), default=None)
        validation = result.get('validation', [])
    if probability is not None:
        values['training_target_success_probability'] = finite(probability)
    if validation:
        values['validation_target_success_lower'] = min(finite(row['success_probability_lower']) for row in validation)
        values['validation_unknown_probability'] = max(finite(row['unknown_probability']) for row in validation)
    proof['validation'] = validation
    expected = []
    weights = {row['id']: row['weight'] for row in parameters.get('scenarios', [])}
    for period in result.get('compliance', []):
        traces = [row for row in result.get('scenario_results', []) if row['period'] == period['period']]
        if {row['scenario_id'] for row in traces} != weights.keys():
            continue
        total = 0.
        for trace in traces:
            # Scenario curves and scale are already realized in each result row.
            total += weights[trace['scenario_id']]*sum(
                (finite(row['load_kw'])-finite(row['served_kw']))*finite(row['step_hours'])
                for row in trace['result']['rows'])
        expected.append({'period': period['period'], 'expected_unsupplied_kwh': total})
    if expected and len(expected) == len(result.get('compliance', [])):
        values['worst_period_event_unsupplied_kwh'] = max(row['expected_unsupplied_kwh'] for row in expected)
    proof['expected_event_by_period'] = expected
    return values, proof


def derive_source(source):
    result, parameters = source['result'], source['parameters']
    checks = {row['name']: {'name': row['name'], 'status': row['status'],
                           'evidence': '来源 '+source['sha256']+' / result.checks'} for row in result.get('checks', [])}
    if source['family'] == 'investment':
        values, proof = investment_metrics(source)
        basis = {key: parameters.get(key) for key in ('stages', 'scenarios', 'validation_scenarios',
                  'risk_scope', 'target_policy', 'protected_classes', 'discount_rate', 'salvage_policy')}
    else:
        base = parameters if source['family'] == 'dispatch' else parameters['base']
        hashes = []
        if source['family'] == 'dispatch':
            rows = result['rows']
        else:
            rows, hashes = annual_rows(source)
        values, proof = trace_metrics(rows, base, source['inventory'])
        if source['family'] == 'annual_dispatch':
            proof['window_hashes'] = hashes
            proof['coverage'] = result['coverage']
        audit = {'served_energy_kwh': 'served_energy_kwh', 'unsupplied_energy_kwh': 'total_unsupplied_energy_kwh',
                 'study_dispatch_cost_yuan': 'study_dispatch_cost_yuan'}
        matched = all(consistent(values[key], result['metrics'][target]) for key, target in audit.items()
                      if key in values and target in result['metrics'])
        checks['归档指标一致性'] = {'name': '归档指标一致性', 'status': 'passed' if matched else 'failed',
                               'evidence': '提交轨迹回算与冻结汇总核对 '+source['sha256']}
        target = result.get('metrics', {}).get('all_load_targets')
        if target is None:
            targets = [row['target_status'] for row in result.get('load_metrics', [])]
            target = 'failed' if 'failed' in targets else 'passed' if targets and all(t == 'passed' for t in targets) else 'not_checked'
        checks['保供目标'] = {'name': '保供目标', 'status': target, 'evidence': '来源逐负荷目标判据 '+source['sha256']}
        basis = {key: proof[key] for key in ('steps', 'step_hours', 'start', 'demand_trace_sha256')}
        basis['elapsed_hours'] = base.get('elapsed_hours', 0)
    checks['求解完整性'] = {'name': '求解完整性', 'status': 'passed' if result['status'] in ('optimal', 'complete') else 'not_checked',
                        'evidence': '来源求解状态 '+result['status']+' / '+source['sha256']}
    for key, value in values.items():
        values[key] = finite(value)
    basis['family'] = source['family']
    basis['network_sha256'] = canonical_sha(source['snapshot']['network'])
    proof.update(source_input_sha256=source['source_input_sha256'], source_result_sha256=source['source_result_sha256'],
                 engineering_revision=source['snapshot']['engineering']['revision'], formulas={key: DEFINITIONS[key]['formula'] for key in values})
    return values, proof, list(checks.values()), basis


def prepare(req):
    project = project_record(req.project_id)
    if project['revision'] != req.project_revision:
        raise HTTPException(409, '工程版本已变化，请刷新后重新提取')
    alternatives, evidence, bases = [], [], []
    for index, ref in enumerate(req.references):
        source = read_source(ref, req.project_id)
        values, proof, checks, basis = derive_source(source)
        missing = [key for key in req.metric_ids if key not in values]
        if missing:
            raise ValueError(source['name']+'缺少可提取指标 '+ '、'.join(DEFINITIONS[key]['name'] for key in missing))
        identity = 'archive-'+str(index+1)
        alternatives.append({'id': identity, 'name': source['name'], 'values': [values[key] for key in req.metric_ids],
                             'provenance': '冻结档案 '+source['sha256'], 'checks': checks})
        evidence.append({'alternative_id': identity, 'reference': source['reference'], 'sha256': source['sha256'],
                         'family': source['family'], 'available_metrics': values, 'derivation': proof})
        bases.append(basis)
    fields = sorted(set().union(*(basis.keys() for basis in bases)))
    differences = [{'field': field, 'values': [{'alternative_id': alternatives[i]['id'], 'value': basis.get(field)}
                    for i, basis in enumerate(bases)]} for field in fields
                   if len({canonical_sha(basis.get(field)) for basis in bases}) > 1]
    required = DYNAMIC_CHECKS + sorted({check['name'] for alt in alternatives for check in alt['checks']} - set(DYNAMIC_CHECKS))
    evaluation = EvaluationInput.model_validate({'project_id': req.project_id, 'project_revision': req.project_revision,
        'name': req.name, 'criteria': [{**{key: DEFINITIONS[metric][key] for key in ('id', 'name', 'direction', 'unit')},
                                      'safety_limit': req.safety_limits.get(metric)} for metric in req.metric_ids],
        'alternatives': alternatives, 'entropy_share': req.entropy_share, 'entropy_sweep': req.entropy_sweep,
        'required_checks': required})
    return evaluation, {'method': METHOD, 'sources': evidence,
        'comparability': {'status': 'differences_present' if differences else 'same_recorded_basis', 'differences': differences,
                          'note': req.comparison_note,
                          'scope': '对照冻结网络、已覆盖时间及需求轨迹或规划阶段/场景/折现条件；设备设计、费用和调度策略可不同，来源输入摘要保留全部研究假设。'},
        'definitions': [DEFINITIONS[key] for key in req.metric_ids]}


@router.post('/archive-preview')
def preview_archive_evaluation(req: ArchiveEvaluationInput):
    try:
        evaluation, evidence = prepare(req)
    except (ValueError, KeyError) as error:
        raise HTTPException(422, str(error))
    return {'input': evaluation.model_dump(), 'source_evidence': evidence}


@router.post('/archive-evaluate')
def evaluate_archives(req: ArchiveEvaluationInput):
    try:
        evaluation, evidence = prepare(req)
        result = evaluation_result(evaluation)
    except (ValueError, KeyError) as error:
        raise HTTPException(422, str(error))
    result['notes'][-1] = '指标由冻结档案按已登记公式提取或回算；必要校核沿用来源证据，动态和实证仍随各自验证状态登记。'
    result['notes'].append('电量供给比例按电量计；时间可靠率、N-1、动态裕度、收益及投资回报期继续使用各自模型或实测依据。')
    if evidence['comparability']['differences']:
        result['notes'].append('本次来源存在时间、需求或规划等对照条件差异，详情保存在可比条件表中。')
    return save_evaluation(evaluation, result, 'frozen_archive_indicators', evidence)


@router.get('/archive-sources')
def archive_sources(project_id: str):
    from backend import resource_dispatch, study_jobs
    project_record(project_id)
    sources = []
    for row in resource_dispatch.history(project_id):
        sources.append({**row, 'reference': {'kind': 'device_dispatch', 'id': row['id']}, 'family': 'dispatch'})
    with closing(study_jobs.connection()) as connection:
        rows = connection.execute('SELECT id,status,meta,result FROM study_jobs WHERE project_id=? ORDER BY created DESC',
                                  (project_id,)).fetchall()
        for identity, status, meta_text, result_text in rows:
            meta = json.loads(meta_text)
            module = meta['module']
            if module in ('device_dispatch', 'annual_dispatch', 'investment'):
                sources.append({'id': identity, 'name': meta['name'], 'status': status,
                                'reference': {'kind': 'study_job', 'id': identity}, 'family': module,
                                'result_available': result_text is not None})
            elif module == 'investment_experiments':
                cases = connection.execute('SELECT case_id,payload FROM study_case_results WHERE job_id=? ORDER BY case_id',
                                           (identity,)).fetchall()
                for case_id, payload in cases:
                    case = json.loads(payload)
                    sources.append({'id': identity+'/'+case_id, 'name': meta['name']+' · '+case['definition']['name'],
                                    'status': case['result']['status'], 'family': 'investment_case',
                                    'reference': {'kind': 'investment_case', 'id': identity, 'case_id': case_id}})
    return {'sources': sources, 'metrics': list(DEFINITIONS.values())}
