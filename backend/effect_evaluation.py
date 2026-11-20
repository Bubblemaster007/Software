"""Topic4: min/max normalization, entropy–CRITIC weights and TOPSIS.

The PPT names the weighting families without prescribing their mixing ratio.
The explicit alpha here is therefore a saved study assumption, not a claimed
reproduction of unpublished numerical results.
"""
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Literal, Annotated
import json
import sqlite3
import uuid
import csv
import io
import html
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import Field, model_validator
from backend.engineering import StrictModel, canonical_sha
from backend.workspace import project_record

ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix='/api/effect-evaluations', tags=['经济安全质效评价'])


class Criterion(StrictModel):
    id: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=100)
    direction: Literal['benefit', 'cost']
    unit: str = Field('', max_length=40)
    safety_limit: float | None = Field(None, ge=-1e15, le=1e15)


class Evidence(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    status: Literal['passed', 'failed', 'not_checked']
    evidence: str = Field('', max_length=3000)

    @model_validator(mode='after')
    def checked(self):
        if self.status != 'not_checked' and not self.evidence:
            raise ValueError('已校核项必须给出证据依据')
        return self


class Alternative(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    values: list[Annotated[float, Field(ge=-1e15, le=1e15)]] = Field(min_length=1, max_length=30)
    provenance: str = Field(min_length=1, max_length=2000)
    source_run_id: str | None = None
    checks: list[Evidence] = Field(default_factory=list, max_length=30)


class EvaluationInput(StrictModel):
    project_id: str
    project_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    criteria: list[Criterion] = Field(min_length=1, max_length=30)
    alternatives: list[Alternative] = Field(min_length=2, max_length=100)
    entropy_share: float = Field(.5, ge=0, le=1)
    entropy_sweep: list[Annotated[float, Field(ge=0, le=1)]] = Field(default_factory=list, max_length=21)
    required_checks: list[str] = Field(default_factory=lambda: ['电压稳定', '频率稳定', '黑启动可行性'], max_length=30)

    @model_validator(mode='after')
    def matrix(self):
        if len(set(self.entropy_sweep)) != len(self.entropy_sweep):
            raise ValueError('组合权重敏感性水平须唯一')
        if len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError('指标编号不得重复')
        if len({a.id for a in self.alternatives}) != len(self.alternatives):
            raise ValueError('方案编号不得重复')
        if len(set(self.required_checks)) != len(self.required_checks) or any(not s.strip() for s in self.required_checks):
            raise ValueError('必要校核名称须非空且不重复')
        for alternative in self.alternatives:
            if len(alternative.values) != len(self.criteria):
                raise ValueError('每个方案的指标数量必须与评价指标一致')
            if len({c.name for c in alternative.checks}) != len(alternative.checks):
                raise ValueError('同一方案的校核名称不得重复')
        return self


def topsis(req: EvaluationInput):
    x = np.asarray([a.values for a in req.alternatives], dtype=float)
    low, high = x.min(axis=0), x.max(axis=0)
    spread = high - low
    active = spread > 0
    z = np.divide(x - low, spread, out=np.zeros_like(x), where=active)
    for j, criterion in enumerate(req.criteria):
        if criterion.direction == 'cost' and active[j]:
            z[:, j] = 1 - z[:, j]
    probabilities = np.divide(z, z.sum(axis=0), out=np.zeros_like(z), where=z.sum(axis=0) > 0)
    plog = np.zeros_like(probabilities)
    positive = probabilities > 0
    plog[positive] = probabilities[positive] * np.log(probabilities[positive])
    divergence = np.where(active, np.maximum(0, 1 + plog.sum(axis=0) / np.log(len(x))), 0)
    entropy = divergence / divergence.sum() if divergence.sum() else np.zeros(len(spread))
    std = z.std(axis=0, ddof=1)
    correlation = np.zeros((len(spread), len(spread)))
    indices = np.flatnonzero(active)
    if len(indices) == 1:
        correlation[indices[0], indices[0]] = 1
    elif len(indices) > 1:
        correlation[np.ix_(indices, indices)] = np.corrcoef(z[:, indices], rowvar=False)
    information = np.zeros(len(spread))
    for j in indices:
        information[j] = std[j] * np.sum(1 - correlation[j, indices])
    # Perfectly redundant benefit indicators have zero CRITIC conflict.
    # Fall back explicitly to the entropy distribution, not invented new information.
    fallback = bool(len(indices) and information.sum() <= 1e-12)
    critic = information / information.sum() if not fallback and information.sum() else entropy.copy()
    weights = req.entropy_share * entropy + (1 - req.entropy_share) * critic
    weighted = z * weights
    ideal = weighted.max(axis=0)
    anti_ideal = weighted.min(axis=0)
    best_distance = np.linalg.norm(weighted - ideal, axis=1)
    worst_distance = np.linalg.norm(weighted - anti_ideal, axis=1)
    scores = np.divide(worst_distance, best_distance + worst_distance, out=np.full(len(x), .5),
                       where=(best_distance + worst_distance) > 1e-15)
    rows = []
    for i, alternative in enumerate(req.alternatives):
        hard = [{'criterion': c.id, 'name': c.name, 'value': alternative.values[j], 'threshold': c.safety_limit,
                 'status': 'passed' if (alternative.values[j] >= c.safety_limit if c.direction == 'benefit' else alternative.values[j] <= c.safety_limit) else 'failed'}
                for j, c in enumerate(req.criteria) if c.safety_limit is not None]
        by_name = {c.name: c.model_dump() for c in alternative.checks}
        checks = [by_name.get(name, {'name': name, 'status': 'not_checked', 'evidence': '未提供该项校核结果'}) for name in req.required_checks]
        failed = any(c['status'] == 'failed' for c in hard + checks)
        incomplete = any(c['status'] == 'not_checked' for c in checks)
        rows.append({'id': alternative.id, 'name': alternative.name, 'score': float(scores[i]),
                     'distance_to_ideal': float(best_distance[i]), 'distance_to_anti_ideal': float(worst_distance[i]),
                     'hard_constraints': hard, 'checks': checks,
                     'gate': 'failed' if failed else 'not_checked' if incomplete else 'passed_as_supplied',
                     'engineering_recommendation': False})
    for row in rows:
        row['rank'] = 1 + sum(bool(s > row['score'] + 1e-12) for s in scores)
    rows.sort(key=lambda r: (r['rank'], r['id']))
    return {'method': 'topic4.minmax.entropy-critic.topsis.v1', 'source': '完整中期PPT第54—57页',
            'normalized': z.tolist(), 'weighted': weighted.tolist(), 'correlation': correlation.tolist(),
            'ideal': ideal.tolist(), 'anti_ideal': anti_ideal.tolist(),
            'weights': [{'id': c.id, 'name': c.name, 'active': bool(active[j]), 'entropy': float(entropy[j]),
                         'critic': float(critic[j]), 'combined': float(weights[j])} for j, c in enumerate(req.criteria)],
            'ranking': rows, 'critic_fallback_to_entropy': fallback,
            'notes': ['指标先按效益/成本方向极值标准化，常量指标权重为0；完全相同方案贴近度为0.5并列。',
                      '组合权重为α×熵权+(1-α)×CRITIC；α为显式研究参数，PPT未给出固定混合公式。',
                      '排名是输入指标下的数学比较，硬约束失败和未校核不会被高分覆盖。',
                      '输入指标及外部校核由用户提供，尚未独立验证；不据此直接形成工程安全推荐。']}


def connection():
    c = sqlite3.connect(ROOT / 'data/platform.db')
    c.execute('CREATE TABLE IF NOT EXISTS effect_evaluations(id TEXT PRIMARY KEY, project_id TEXT, created TEXT, payload TEXT)')
    return c


def evaluation_result(req):
    result = topsis(req)
    if not req.entropy_sweep:
        return result
    levels = sorted(set(req.entropy_sweep + [req.entropy_share]))
    cases = []
    for alpha in levels:
        point = topsis(req.model_copy(update={'entropy_share': alpha}))
        cases.append({'entropy_share': alpha, 'weights': point['weights'],
                      'ranking': point['ranking']})
    ranges = []
    for alternative in req.alternatives:
        rows = [next(row for row in case['ranking'] if row['id'] == alternative.id) for case in cases]
        ranges.append({'id': alternative.id, 'name': alternative.name,
                       'best_rank': min(row['rank'] for row in rows),
                       'worst_rank': max(row['rank'] for row in rows),
                       'minimum_score': min(row['score'] for row in rows),
                       'maximum_score': max(row['score'] for row in rows)})
    result['weight_sensitivity'] = {'method': 'fixed-matrix.entropy-share-sweep.v1',
        'cases': cases, 'rank_ranges': ranges,
        'note': '固定指标矩阵和安全门槛，仅改变组合权重α；结果覆盖给定水平及基准α。'}
    return result


def save_evaluation(req, result, origin='user_supplied_indicators_unverified', source_evidence=None):
    record = {'id': uuid.uuid4().hex, 'project_id': req.project_id, 'created': datetime.now().isoformat(timespec='seconds'),
              'input': req.model_dump(), 'input_sha256': canonical_sha(req.model_dump()), 'result': result,
              'origin': origin}
    if source_evidence is not None:
        record['source_evidence'] = source_evidence
    with closing(connection()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        revision = c.execute('SELECT revision FROM projects WHERE id=?', (req.project_id,)).fetchone()
        if not revision or revision[0] != req.project_revision:
            raise HTTPException(409, '工程版本已变化，请刷新后重新评价')
        c.execute('INSERT INTO effect_evaluations VALUES(?,?,?,?)',
                  (record['id'], record['project_id'], record['created'], json.dumps(record, ensure_ascii=False, allow_nan=False)))
    return record


@router.post('')
def evaluate(req: EvaluationInput):
    project_record(req.project_id)
    for alternative in req.alternatives:
        if alternative.source_run_id:
            from backend.app import get_run
            if get_run(alternative.source_run_id).get('project_id') != req.project_id:
                raise HTTPException(422, '评价引用的计算须属于当前工程')
    return save_evaluation(req, evaluation_result(req))


@router.get('')
def list_evaluations(project_id: str):
    project_record(project_id)
    with closing(connection()) as c:
        rows = c.execute('SELECT payload FROM effect_evaluations WHERE project_id=? ORDER BY created DESC,rowid DESC', (project_id,)).fetchall()
    return [{'id': r['id'], 'created': r['created'], 'name': r['input']['name']} for (payload,) in rows if (r := json.loads(payload))]


@router.get('/{evaluation_id}')
def read_evaluation(evaluation_id: str):
    with closing(connection()) as c:
        row = c.execute('SELECT payload FROM effect_evaluations WHERE id=?', (evaluation_id,)).fetchone()
    if not row:
        raise HTTPException(404, '评价结果不存在')
    return json.loads(row[0])


@router.get('/{evaluation_id}/csv')
def export_evaluation_csv(evaluation_id: str, dataset: Literal['ranking', 'weights', 'sensitivity'] = 'ranking'):
    record = read_evaluation(evaluation_id)
    result = record['result']
    if dataset == 'sensitivity':
        rows = [{'entropy_share': case['entropy_share'], **row}
                for case in result.get('weight_sensitivity', {}).get('cases', []) for row in case['ranking']]
        columns = ['entropy_share', 'id', 'name', 'rank', 'score', 'gate', 'engineering_recommendation']
    elif dataset == 'weights':
        rows = result['weights']
        columns = ['id', 'name', 'active', 'entropy', 'critic', 'combined']
    else:
        rows = result['ranking']
        columns = ['id', 'name', 'rank', 'score', 'distance_to_ideal', 'distance_to_anti_ideal', 'gate', 'engineering_recommendation']
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return Response('\ufeff'+output.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename=effect-{evaluation_id}-{dataset}.csv'})


@router.get('/{evaluation_id}/report')
def export_evaluation_report(evaluation_id: str):
    record = read_evaluation(evaluation_id)
    esc = lambda value: html.escape(str(value))
    def table(rows, keys):
        return '<table><tr>'+''.join('<th>'+esc(key)+'</th>' for key in keys)+'</tr>'+''.join(
            '<tr>'+''.join('<td>'+esc(row.get(key, ''))+'</td>' for key in keys)+'</tr>' for row in rows)+'</table>'
    result = record['result']
    text = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>质效评价报告</title><style>body{font:15px/1.7 sans-serif;max-width:1100px;margin:30px auto;padding:20px;color:#183c40}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccdadd;padding:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
    text += '<h1>'+esc(record['input']['name'])+'</h1><p>档案 '+esc(record['id'])+'</p><p>输入摘要 '+esc(record['input_sha256'])+'</p>'
    text += '<h2>数学排序与安全门槛</h2>'+table(result['ranking'], ['name', 'rank', 'score', 'gate', 'engineering_recommendation'])
    text += '<h2>指标权重</h2>'+table(result['weights'], ['name', 'active', 'entropy', 'critic', 'combined'])
    if result.get('weight_sensitivity'):
        text += '<h2>组合权重敏感性</h2><p>'+esc(result['weight_sensitivity']['note'])+'</p>'
        text += table(result['weight_sensitivity']['rank_ranges'], ['name', 'best_rank', 'worst_rank', 'minimum_score', 'maximum_score'])
    text += '<h2>计量口径</h2><ul>'+''.join('<li>'+esc(note)+'</li>' for note in result['notes'])+'</ul>'
    text += '<h2>冻结指标、来源及校核</h2><pre>'+esc(json.dumps(record['input'], ensure_ascii=False, indent=2))+'</pre>'
    if record.get('source_evidence'):
        text += '<h2>档案提取证据与可比条件</h2><pre>'+esc(json.dumps(record['source_evidence'], ensure_ascii=False, indent=2))+'</pre>'
    return Response(text+'</html>', media_type='text/html; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename=effect-{evaluation_id}.html'})
