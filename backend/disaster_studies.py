"""Conditional hazard experiments using the actual device MILP, not score formulas.

Reference event failure probabilities are converted to constant per-hour hazards.
Paired experiments use keyed PCG64 draws; no return-period to probability shortcut.
"""
import hashlib
import math
import time
from statistics import NormalDist
from typing import Literal

import numpy as np
from pydantic import Field, model_validator
from backend.engineering import StrictModel, Inventory, canonical_sha
from backend.network_data import Network
from backend.resource_dispatch import DispatchInput, DispatchIncomplete, dispatch, repeated
from backend.study_control import StudyCancelled

METHOD = 'hazard.device-milp.paired.v1'


class Fragility(StrictModel):
    kind: Literal['source', 'storage', 'line', 'transformer', 'switch', 'grid']
    target_id: str = Field(min_length=1, max_length=64)
    reference_intensity: float = Field(1, gt=0, le=1000000)
    reference_duration_hours: float = Field(1, gt=0, le=8760)
    failure_probability: float = Field(.1, ge=0, le=1)
    shape: float = Field(2, gt=0, le=10)
    repair_hours: float = Field(4, gt=0, le=8760)
    failed_availability: float = Field(0, ge=0, le=1)
    common_group: str = Field('', max_length=64)
    provenance: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def target(self):
        if self.kind == 'line':
            try:
                self.target_id = str(int(self.target_id))
            except ValueError:
                raise ValueError('线路目标须为线路编号')
        if self.kind == 'grid' and self.target_id != 'grid':
            raise ValueError('外部供电目标编号须为grid')
        if self.kind in ('line', 'switch') and self.failed_availability not in (0, 1):
            raise ValueError('线路/开关仅支持0或1状态，不支持连续降额')
        return self

    @property
    def key(self):
        return f'{self.kind}:{self.target_id}'


class DisasterInput(StrictModel):
    base: DispatchInput
    name: str = Field('承灾强度与时长扫描', min_length=1, max_length=100)
    intensities: list[float] = Field(default_factory=lambda: [0, 1, 2], min_length=1, max_length=50)
    durations_hours: list[float] = Field(default_factory=lambda: [1, 4], min_length=1, max_length=20)
    event_start_step: int = Field(0, ge=0, le=671)
    samples: int = Field(20, ge=1, le=1000)
    seed: int = Field(2026, ge=0, le=2**32-1)
    fragilities: list[Fragility] = Field(min_length=1, max_length=100)
    criterion: Literal['load_targets', 'energy_budget'] = 'load_targets'
    maximum_unsupplied_kwh: float = Field(0, ge=0, le=1000000000)
    required_success_probability: float = Field(.95, gt=0, le=1)
    confidence: float = Field(.95, gt=.5, lt=1)
    judgement: Literal['wilson_lower', 'empirical'] = 'wilson_lower'
    weakness_targets: list[str] = Field(default_factory=list, max_length=30)
    weakness_intensity: float | None = Field(None, ge=0, le=1000000)
    weakness_duration_hours: float | None = Field(None, gt=0, le=168)
    wall_time_seconds: float = Field(600, ge=1, le=3600)

    @model_validator(mode='after')
    def limits(self):
        if self.base.enforce_load_targets:
            raise ValueError('承灾扫描须保留缺供轨迹，不能启用基础调度硬保供；请使用扫描的负荷目标判据')
        if len(set(self.intensities)) != len(self.intensities) or any(not 0 <= x <= 1000000 for x in self.intensities):
            raise ValueError('强度须为不重复的非负有限数')
        if len(set(self.durations_hours)) != len(self.durations_hours):
            raise ValueError('持续时长不得重复')
        for hours in self.durations_hours:
            steps = hours / self.base.step_hours
            if not 0 < hours <= 168 or abs(steps-round(steps)) > 1e-8 or self.event_start_step + round(steps) > self.base.steps:
                raise ValueError('事件时长须对齐时间步且完整处于基准计算时域内')
        keys = {f.key for f in self.fragilities}
        if len(keys) != len(self.fragilities):
            raise ValueError('同一目标不得重复设置脆弱性')
        if len(set(self.weakness_targets)) != len(self.weakness_targets) or not set(self.weakness_targets) <= keys:
            raise ValueError('薄弱性对照目标须为不重复的已配置脆弱性目标')
        if self.weakness_intensity is not None and self.weakness_intensity not in self.intensities:
            raise ValueError('薄弱性对照强度须属于扫描强度')
        if self.weakness_duration_hours is not None and self.weakness_duration_hours not in self.durations_hours:
            raise ValueError('薄弱性对照时长须属于扫描时长')
        if self.samples * (len(self.intensities)*len(self.durations_hours) + len(self.weakness_targets)) > 5000:
            raise ValueError('扫描与设备对照总计不得超过5000次调度')
        return self


def validate_targets(req: DisasterInput, inventory: Inventory, network: Network):
    groups = {'source': inventory.sources, 'storage': inventory.storage,
              'transformer': inventory.transformers, 'switch': inventory.switches}
    targets = {f'{kind}:{a.id}' for kind, assets in groups.items() for a in assets if a.existing or req.base.include_candidates}
    targets |= {f'line:{e.line}' for e in network.lines} | {'grid:grid'}
    if not {f.key for f in req.fragilities} <= targets:
        raise ValueError('脆弱性目标不存在或不参与本次计算')


def step_probability(f: Fragility, intensity, dt):
    if intensity == 0 or f.failure_probability == 0:
        return 0.0
    if f.failure_probability == 1:
        return 1.0
    log_exposure = (math.log(-math.log1p(-f.failure_probability))
                    + f.shape*(math.log(intensity)-math.log(f.reference_intensity))
                    - math.log(f.reference_duration_hours)+math.log(dt))
    # Work in log space for valid but extreme positive reference values.
    if log_exposure > 6:
        return 1.0
    return -math.expm1(-math.exp(log_exposure))


def draws(seed, sample, group, steps):
    # Explicit bit generator and byte order: target ordering does not change draws.
    digest = hashlib.sha256(group.encode('utf-8')).digest()
    words = [int.from_bytes(digest[i:i+4], 'little') for i in range(0, 16, 4)]
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, sample, *words]))).random(steps)


def materialize(req, intensity, duration, sample, network, inventory, remove=None):
    """Intersect with baseline ceilings; mitigation removes only the selected mechanism."""
    base = req.base.model_dump(mode='json')
    n, dt = req.base.steps, req.base.step_hours
    device = dict(base['device_availability'])
    lines = {int(k): v for k, v in base['line_status'].items()}
    grid = repeated(base['grid_available_kw'], n, 0, 'grid').copy()
    events, traces = [], {}
    end = req.event_start_step + round(duration/dt)
    for f in req.fragilities:
        if f.key == remove:
            continue
        u = draws(req.seed, sample, 'group:'+f.common_group if f.common_group else 'target:'+f.key, n)
        factor = np.ones(n)
        down_until = -1
        p = step_probability(f, intensity, dt)
        for t in range(n):
            if req.event_start_step <= t < end and t >= down_until and u[t] < p:
                down_until = t + max(1, math.ceil(f.repair_hours/dt))
                events.append({'target': f.key, 'start_step': t, 'recover_step': down_until})
            if t < down_until:
                factor[t] = f.failed_availability
        traces[f.key] = factor.tolist()
        if f.kind == 'line':
            line_id = int(f.target_id)
            # A perturbation must not turn a normally-open or spare line on.
            fallback = next(e.status for e in network.lines if e.line == line_id)
            if line_id not in req.base.line_status:
                # Switch state is applied by dispatch; only insert an override when a failure occurs.
                fallback *= int(not any(s.line_id == line_id and not s.normally_closed
                                        for s in inventory.switches if s.existing or req.base.include_candidates))
            if line_id in lines or np.any(factor < 1):
                lines[line_id] = np.minimum(repeated(lines.get(line_id, []), n, fallback, f.key), factor).astype(int).tolist()
        elif f.kind == 'grid':
            grid *= factor
        else:
            device[f.target_id] = np.minimum(repeated(device.get(f.target_id, []), n, 1, f.key), factor).tolist()
    base.update(device_availability=device, line_status=lines, grid_available_kw=grid.tolist())
    return DispatchInput.model_validate(base), {'events': events, 'availability': traces}


def wilson(success, total, confidence):
    if total <= 0:
        return [0.0, 1.0]
    z = NormalDist().inv_cdf((1+confidence)/2)
    p, q = success/total, z*z/total
    center = (p+q/2)/(1+q)
    half = z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/(1+q)
    return [max(0, center-half), min(1, center+half)]


def success_status(req, result):
    if req.criterion == 'energy_budget':
        passed = result['metrics']['total_unsupplied_energy_kwh'] <= req.maximum_unsupplied_kwh + 1e-5
    else:
        status = result['metrics']['all_load_targets']
        if status == 'not_checked':
            return 'unknown'
        passed = status == 'passed'
    # A feasible incumbent demonstrates a passing schedule, but cannot prove failure.
    return 'passed' if passed else 'failed' if result['status'] == 'optimal' else 'unknown'


def summarize_case(req, intensity, duration, samples):
    successes = sum(s['success'] == 'passed' for s in samples)
    failures = sum(s['success'] == 'failed' for s in samples)
    unknown = req.samples - successes - failures
    interval = wilson(successes, req.samples, req.confidence)
    optimistic_interval = wilson(successes+unknown, req.samples, req.confidence)
    score = interval[0] if req.judgement == 'wilson_lower' else successes/req.samples
    upper = optimistic_interval[1] if req.judgement == 'wilson_lower' else (successes+unknown)/req.samples
    # An upper confidence bound below the required probability supports rejection.
    state = 'passed' if score+1e-12 >= req.required_success_probability else 'failed' if upper+1e-12 < req.required_success_probability else 'uncertain'
    return {'intensity': intensity, 'duration_hours': duration, 'successes': successes, 'failures': failures,
            'unknown': unknown, 'completed': len(samples), 'requested': req.samples,
            'success_fraction_lower': successes/req.samples, 'success_fraction_upper': (successes+unknown)/req.samples,
            'wilson_conservative': interval, 'wilson_optimistic': optimistic_interval, 'judgement': state,
            'measured_samples': sum(s['unsupplied_kwh'] is not None for s in samples),
            'mean_unsupplied_kwh': float(np.mean([s['unsupplied_kwh'] for s in samples if s['unsupplied_kwh'] is not None]))
            if any(s['unsupplied_kwh'] is not None for s in samples) else None}


def boundaries(cases):
    """Return tested cells; never extrapolate or assume monotone damage/recovery."""
    result = []
    for duration in sorted({c['duration_hours'] for c in cases}):
        cells = sorted([c for c in cases if c['duration_hours'] == duration], key=lambda c: c['intensity'])
        feasible = [c['intensity'] for c in cells if c['judgement'] == 'passed']
        nonmonotone = any(a['judgement'] == 'failed' and any(b['judgement'] == 'passed' for b in cells[i+1:]) for i, a in enumerate(cells))
        result.append({'duration_hours': duration, 'tested_feasible_intensities': feasible,
                       'maximum_tested_feasible_intensity': max(feasible) if feasible else None,
                       'right_censored': bool(cells and cells[-1]['judgement'] == 'passed'),
                       'nonmonotone': nonmonotone,
                       'cells': [{'intensity': c['intensity'], 'judgement': c['judgement']} for c in cells]})
    return result


def scan(req: DisasterInput, inventory: Inventory, network: Network, progress=None, cancelled=None):
    validate_targets(req, inventory, network)
    started = time.monotonic()
    total = req.samples*(len(req.intensities)*len(req.durations_hours)+len(req.weakness_targets))
    ledger, case_rows, paired, comparisons = [], [], {}, []
    worst = None
    done, expired = 0, False
    selected_i = req.weakness_intensity if req.weakness_intensity is not None else max(req.intensities)
    selected_d = req.weakness_duration_hours if req.weakness_duration_hours is not None else max(req.durations_hours)

    def check():
        if cancelled and cancelled():
            raise StudyCancelled('用户请求取消')

    def solve(intensity, duration, sample, remove=None):
        nonlocal done, worst, expired
        check()
        remaining = req.wall_time_seconds-(time.monotonic()-started)
        if remaining < 1:
            expired = True
            return None
        params, perturbation = materialize(req, intensity, duration, sample, network, inventory, remove)
        params.time_limit_seconds = min(params.time_limit_seconds, remaining)
        if progress:
            progress({'phase': 'weakness' if remove else 'scanning', 'completed': done, 'total': total,
                      'fraction': done/total, 'intensity': intensity, 'duration_hours': duration,
                      'sample': sample, 'target': remove})
        try:
            result = dispatch(params, inventory, network, cancelled=cancelled)
        except DispatchIncomplete as e:
            check()
            done += 1
            return {'intensity': intensity, 'duration_hours': duration, 'sample': sample,
                    'removed_target': remove, 'success': 'unknown', 'solver_status': 'no_incumbent_time_limit',
                    'unsupplied_kwh': None, 'shortage_kwh': None, 'maximum_shortage_kw': None,
                    'event_count': len(perturbation['events']), 'perturbation_sha256': canonical_sha(perturbation),
                    'runtime_seconds': None, 'reason': str(e)}
        check()
        done += 1
        summary = {'intensity': intensity, 'duration_hours': duration, 'sample': sample,
                   'removed_target': remove, 'success': success_status(req, result), 'solver_status': result['status'],
                   'unsupplied_kwh': result['metrics']['total_unsupplied_energy_kwh'],
                   'shortage_kwh': result['metrics']['shortage_energy_kwh'],
                   'maximum_shortage_kw': result['metrics']['maximum_total_unsupplied_kw'],
                   'event_count': len(perturbation['events']), 'perturbation_sha256': canonical_sha(perturbation),
                   'runtime_seconds': result['runtime_seconds']}
        if remove is None and (worst is None or summary['unsupplied_kwh'] > worst['sample']['unsupplied_kwh']):
            keys = ('timestamp', 'step_hours', 'load_kw', 'served_kw', 'shortage_kw', 'total_unsupplied_kw', 'grid_kw')
            worst = {'sample': summary, 'perturbation': perturbation,
                     'rows': [{k: row[k] for k in keys} for row in result['rows']],
                     'load_metrics': result['load_metrics'], 'checks': result['checks']}
        return summary

    for duration in sorted(req.durations_hours):
        for intensity in sorted(req.intensities):
            samples = []
            if not expired:
                for sample in range(req.samples):
                    row = solve(intensity, duration, sample)
                    if row is None:
                        break
                    samples.append(row)
                    ledger.append(row)
                    if intensity == selected_i and duration == selected_d:
                        paired[sample] = row
            case_rows.append(summarize_case(req, intensity, duration, samples))
    for target in req.weakness_targets:
        if not expired:
            for sample, base in paired.items():
                row = solve(selected_i, selected_d, sample, target)
                if row is None:
                    break
                ledger.append(row)
                # Do not rank differences between unoptimized schedules as causal capacity effects.
                reliable = base['solver_status'] == row['solver_status'] == 'optimal'
                comparisons.append({'target': target, 'sample': sample, 'baseline_unsupplied_kwh': base['unsupplied_kwh'],
                                    'mitigated_unsupplied_kwh': row['unsupplied_kwh'], 'reliable_pair': reliable})
        # Every requested target remains visible, including untested/limited pairs.
        if progress:
            progress({'phase': 'weakness_summary', 'completed': done, 'total': total, 'fraction': done/total, 'target': target})
    ranking = []
    for target in req.weakness_targets:
        pairs = [p for p in comparisons if p['target'] == target and p['reliable_pair']]
        deltas = [p['baseline_unsupplied_kwh']-p['mitigated_unsupplied_kwh'] for p in pairs]
        ranking.append({'target': target, 'intensity': selected_i, 'duration_hours': selected_d,
                        'reliable_pairs': len(pairs), 'requested_pairs': req.samples,
                        'mean_avoided_unsupplied_kwh': float(np.mean(deltas)) if deltas else None,
                        'standard_error_kwh': float(np.std(deltas, ddof=1)/math.sqrt(len(deltas))) if len(deltas)>1 else None,
                        'status': 'complete' if len(pairs) == req.samples else 'incomplete'})
    ranking.sort(key=lambda r: (r['mean_avoided_unsupplied_kwh'] is None, -(r['mean_avoided_unsupplied_kwh'] or 0)))
    check()
    incomplete = expired or any(s['success'] == 'unknown' or s['solver_status'] != 'optimal' for s in ledger)
    state = 'incomplete_time_limit' if expired else 'incomplete_evaluation' if incomplete else 'complete'
    if progress:
        progress({'phase': state, 'completed': done, 'total': total, 'fraction': done/total})
    return {'method': METHOD, 'status': state,
            'cases': case_rows, 'boundaries': boundaries(case_rows), 'samples': ledger,
            'weakness': ranking, 'paired_comparisons': comparisons, 'worst_trace': worst,
            'completed_solves': done, 'requested_solves': total, 'runtime_seconds': time.monotonic()-started,
            'environment': {'numpy': np.__version__, 'random_generator': 'PCG64/SeedSequence/keyed-sha256.v1'},
            'scope': ['指定脆弱性、确定性全时域调度与成功判据下的条件抽样结果，非真实系统全局承灾极限。',
                      '参考事件失效概率按恒定风险率转换逐步概率；重现期不直接作为设备失效概率。',
                      '共因组共享均匀冲击；组间独立。这是显式研究相关结构，尚未自动地区校准。',
                      '故障在步首发生；修复向上对齐网格，事件结束不立即清除未修复故障，修复后可再次失效。',
                      '扰动与基准可用率取最小值，外部供电按比例降额；储能故障只限制功率，未模拟能量损毁。',
                      '薄弱性试验仅移除目标脆弱性机制，保留原有故障/检修及其他随机冲击，负值不截断。',
                      '未知与未完成样本不剔除：保守视为失败、乐观视为成功，分别给出区间。Wilson为逐点区间，非整张边界同时置信保证。',
                      '交流网损、动态稳定、涌流及通信仍未校核；达标仅指选定的保供判据。']}
