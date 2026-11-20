"""Durable, frozen-input study queue. Fixed workers; cooperative cancellation only."""
from contextlib import closing
from pathlib import Path
from datetime import datetime, timedelta, timezone
import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
import traceback
import uuid
import html

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from fastapi.responses import StreamingResponse
from pydantic import Field, ValidationError
from backend.engineering import StrictModel, Inventory, canonical_sha, inventory_snapshot, validate_nodes
from backend.network_data import Network
from backend.workspace import project_record, case33
from backend.resource_dispatch import DispatchInput, DispatchIncomplete, dispatch
from backend.disaster_studies import DisasterInput, scan, validate_targets
from backend.restoration import RestorationInput, plan_restoration, validate_restoration
from backend.investment_planning import InvestmentInput, investment_plan, validate_investment
from backend.investment_experiments import InvestmentExperimentInput, run_experiments, validate_experiments
from backend.annual_dispatch import AnnualDispatchInput, run_annual, validate_annual
from backend.native_jobs import process_identity
from backend.study_control import StudyCancelled

ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix='/api/study-jobs', tags=['统一研究任务'])
TERMINAL = {'succeeded', 'incomplete', 'failed', 'cancelled', 'interrupted'}


class Submission(StrictModel):
    module: str = Field(pattern='^(device_dispatch|disaster_scan|restoration|investment|investment_experiments|annual_dispatch)$')
    parameters: dict


def connection():
    (ROOT/'data').mkdir(exist_ok=True)
    c = sqlite3.connect(ROOT/'data/platform.db', timeout=30)
    c.execute('CREATE TABLE IF NOT EXISTS study_jobs(id TEXT PRIMARY KEY, project_id TEXT, created REAL, status TEXT, meta TEXT, input TEXT, result TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS study_case_results(job_id TEXT, case_id TEXT, payload TEXT, PRIMARY KEY(job_id,case_id))')
    return c


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def record(row, include_input=False, include_result=False):
    result = {'id': row[0], 'project_id': row[1], 'created': row[2], 'status': row[3], **json.loads(row[4])}
    if include_input:
        result['input'] = json.loads(row[5])
    if include_result:
        result['result'] = json.loads(row[6]) if row[6] else None
    return result


def get(job_id, include_input=False, include_result=False):
    with closing(connection()) as c:
        row = c.execute('SELECT * FROM study_jobs WHERE id=?', (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, '研究任务不存在')
    return record(row, include_input, include_result)


def update(job_id, allowed, status=None, result=None, **fields):
    """Compare-and-set status and meta; terminal records are never overwritten."""
    with closing(connection()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM study_jobs WHERE id=?', (job_id,)).fetchone()
        if not row or row[3] in TERMINAL or row[3] not in allowed:
            return False
        meta = json.loads(row[4])
        meta.update(fields)
        c.execute('UPDATE study_jobs SET status=?,meta=?,result=COALESCE(?,result) WHERE id=?',
                  (status or row[3], encode(meta), encode(result) if result is not None else None, job_id))
    return True


def audit():
    with closing(connection()) as c:
        rows = c.execute("SELECT * FROM study_jobs WHERE status IN ('queued','running','cancel_requested')").fetchall()
    for row in rows:
        job = record(row)
        if job.get('pid') and job.get('process_identity'):
            if process_identity(job['pid']) != job['process_identity']:
                update(job['id'], {'queued', 'running', 'cancel_requested'}, status='interrupted',
                       error='已确认工作进程退出，未提交成功结果；可重试冻结输入', finished=time.time())
        elif job.get('launch_token') and time.time()-job.get('launch_time', time.time()) > 60:
            # Revoke the token: a delayed child can no longer claim or commit this task.
            update(job['id'], {'queued'}, status='interrupted', error='工作进程启动未确认，启动令牌已撤销', finished=time.time())


def schedule():
    """Atomically reserve slots across API/worker processes, then launch known code."""
    audit()
    launches = []
    with closing(connection()) as c, c:
        c.execute('BEGIN IMMEDIATE')
        active = c.execute("SELECT status,meta FROM study_jobs WHERE status IN ('queued','running','cancel_requested')").fetchall()
        count = sum(status != 'queued' or bool(json.loads(meta).get('launch_token')) for status, meta in active)
        rows = c.execute("SELECT * FROM study_jobs WHERE status='queued' ORDER BY created,rowid").fetchall()
        for row in rows:
            meta = json.loads(row[4])
            if count >= 2:
                break
            if meta.get('launch_token'):
                continue
            token = uuid.uuid4().hex
            meta.update(launch_token=token, launch_time=time.time())
            c.execute('UPDATE study_jobs SET meta=? WHERE id=? AND status=\'queued\'', (encode(meta), row[0]))
            launches.append((row[0], token))
            count += 1
    for job_id, token in launches:
        folder = ROOT/'data/study_jobs'/job_id
        folder.mkdir(parents=True, exist_ok=True)
        try:
            with (folder/'worker.log').open('ab') as log:
                child = subprocess.Popen([sys.executable, '-m', 'backend.study_worker', job_id, token], cwd=ROOT,
                                         stdout=log, stderr=subprocess.STDOUT,
                                         env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'},
                                         creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            identity = process_identity(child.pid)
            # The child may have already completed; do not overwrite its terminal state.
            if identity:
                update(job_id, {'queued'}, pid=child.pid, process_identity=identity)
        except OSError as e:
            update(job_id, {'queued'}, status='failed', error=str(e), finished=time.time())


def freeze(submission):
    schemas = {'device_dispatch': DispatchInput, 'disaster_scan': DisasterInput, 'restoration': RestorationInput, 'investment': InvestmentInput, 'investment_experiments': InvestmentExperimentInput, 'annual_dispatch': AnnualDispatchInput}
    params = schemas[submission.module].model_validate(submission.parameters)
    base = params if submission.module == 'device_dispatch' else params.base
    project = project_record(base.project_id)
    if project['revision'] != base.project_revision:
        raise HTTPException(409, '工程版本变化，请重新读取')
    engineering = inventory_snapshot(base.project_id, base.engineering_revision)
    inventory = Inventory.model_validate(engineering['inventory'])
    validate_nodes(inventory, project)
    network = Network.model_validate(project['state']['network']) if project['state'].get('network') else Network.model_validate({'name': 'IEEE33示例', 'base_voltage_kv': 12.66, **case33()})
    if submission.module == 'disaster_scan':
        validate_targets(params, inventory, network)
    elif submission.module == 'restoration':
        validate_restoration(params, inventory, network)
    elif submission.module == 'investment':
        validate_investment(params, inventory, network)
    elif submission.module == 'investment_experiments':
        validate_experiments(params, inventory, network)
    elif submission.module == 'annual_dispatch':
        validate_annual(params, inventory, network)
    from backend.app import RUNTIME_ID
    return {'module': submission.module, 'parameters': params.model_dump(mode='json'), 'project': project,
            'engineering': engineering, 'network': network.model_dump(mode='json'), 'runtime': RUNTIME_ID}


def enqueue(snapshot, retry_from=None):
    job_id, now = uuid.uuid4().hex, time.time()
    params = snapshot['parameters']
    base = params if snapshot['module'] == 'device_dispatch' else params['base']
    meta = {'module': snapshot['module'], 'name': params['name'], 'input_sha256': canonical_sha(snapshot),
            'runtime': snapshot['runtime'], 'progress': {'phase': 'queued', 'fraction': 0}, 'retry_from': retry_from}
    with closing(connection()) as c, c:
        c.execute('INSERT INTO study_jobs VALUES(?,?,?,?,?,?,NULL)', (job_id, base['project_id'], now, 'queued', encode(meta), encode(snapshot)))
    schedule()
    return get(job_id)


@router.post('')
def submit(req: Submission):
    try:
        snapshot = freeze(req)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_context=False, include_url=False))
    except (ValueError, KeyError) as e:
        raise HTTPException(422, str(e))
    return enqueue(snapshot)


@router.get('')
def history(project_id: str):
    project_record(project_id)
    schedule()
    with closing(connection()) as c:
        rows = c.execute('SELECT * FROM study_jobs WHERE project_id=? ORDER BY created DESC,rowid DESC LIMIT 100', (project_id,)).fetchall()
    return [record(r) for r in rows]


@router.get('/{job_id}')
def detail(job_id: str, include_input: bool = False, include_result: bool = False):
    schedule()
    return get(job_id, include_input, include_result)


@router.post('/{job_id}/cancel')
def cancel(job_id: str):
    get(job_id)
    if not update(job_id, {'queued'}, status='cancelled', finished=time.time()):
        update(job_id, {'running'}, status='cancel_requested')
    schedule()
    return get(job_id)


@router.post('/{job_id}/retry')
def retry(job_id: str):
    previous = get(job_id, True)
    if previous['status'] not in TERMINAL:
        raise HTTPException(409, '任务未结束，不能重试')
    snapshot = previous['input']
    from backend.app import RUNTIME_ID
    snapshot['runtime'] = RUNTIME_ID
    # Original project, inventory and schedules remain frozen. Only code identity changes.
    return enqueue(snapshot, job_id)


@router.get('/{job_id}/download')
def download(job_id: str):
    return Response(encode(get(job_id, True, True)), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename=study-{job_id}.json'})


@router.get('/{job_id}/csv')
def export_csv(job_id: str, dataset: str = 'default'):
    job = get(job_id, include_result=True)
    if job['module'] == 'annual_dispatch':
        if dataset != 'default':
            raise HTTPException(422, '年度出口提供已提交逐时数据集')
        return annual_csv(job)
    if not job['result']:
        raise HTTPException(409, '任务尚无可导出结果')
    datasets = {'disaster_scan': 'samples', 'restoration': 'actions', 'investment': 'selected_assets', 'investment_experiments': 'cases'}
    rows = job['result'].get(datasets.get(job['module'], 'rows'), [])
    if dataset != 'default':
        if job['module'] != 'investment' or dataset not in ('cashflows', 'compliance', 'training'):
            raise HTTPException(422, '不支持的结果数据集')
        rows = job['result'].get(dataset, [])
    stream = io.StringIO()
    keys = list(rows[0]) if rows else ['intensity', 'duration_hours', 'sample', 'success']
    if job['module'] == 'device_dispatch':
        keys = ['timestamp', 'step_hours', 'load_kw', 'served_kw', 'shortage_kw', 'total_unsupplied_kw', 'grid_kw']
    elif job['module'] == 'restoration':
        keys = ['kind', 'target_id', 'target_name', 'start_step', 'command_end_step', 'end_step', 'start_minutes', 'end_minutes', 'line_id', 'control', 'synchronization', 'inrush_screen']
        rows = [{k: encode(v) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in rows]
    elif job['module'] == 'investment':
        keys = ['asset_id', 'name', 'node', 'commission_year', 'retirement_year', 'capex_yuan', 'power_kw', 'energy_kwh', 'sizing_mode', 'power_fraction', 'energy_fraction', 'reference_power_kw', 'reference_energy_kwh', 'annual_maintenance_yuan', 'fuel_fraction', 'fuel_budget_mode'] if dataset == 'default' else list(rows[0]) if rows else ['year']
        rows = [{k: encode(v) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in rows]
    elif job['module'] == 'investment_experiments':
        keys = ['id', 'name', 'kind', 'parameter', 'value', 'status', 'requested_probability', 'objective_yuan', 'delta_objective_yuan', 'relative_objective_change', 'training_success_probability', 'all_periods_training_probability', 'worst_period_expected_event_unsupplied_kwh', 'validation_status', 'validation_success_probability_lower', 'validation_success_probability_upper', 'recommendation_status', 'derived_input_sha256']
    writer = csv.DictWriter(stream, fieldnames=keys, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return Response('\ufeff'+stream.getvalue(), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename=study-{job_id}.csv'})


@router.get('/{job_id}/report')
def investment_report(job_id: str):
    job = get(job_id, True, True)
    if job['module'] == 'annual_dispatch':
        return annual_report(job)
    if job['module'] == 'investment_experiments':
        return experiment_report(job)
    if job['module'] != 'investment' or not job['result']:
        raise HTTPException(409, '该任务尚无联合配置报告')
    result, snapshot = job['result'], job['input']
    params = snapshot['parameters']
    esc = lambda value: html.escape(str(value if value is not None else '—'))
    def table(rows, columns):
        head = ''.join('<th>'+esc(title)+'</th>' for key, title in columns)
        body = ''.join('<tr>'+''.join('<td>'+esc(row.get(key))+'</td>' for key, title in columns)+'</tr>' for row in rows)
        return '<table><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table>'
    created = datetime.fromtimestamp(job['created'], timezone(timedelta(hours=8))).isoformat()
    text = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+esc(job['name'])+'</title>'
    text += '<style>body{font:15px/1.7 sans-serif;max-width:1150px;margin:40px auto;padding:0 24px;color:#183c40}table{border-collapse:collapse;width:100%;margin:18px 0}th,td{border:1px solid #c5d6d8;padding:8px;text-align:left}th{background:#edf5f5}pre{white-space:pre-wrap;overflow-wrap:anywhere}.notice{padding:16px;background:#f6eee1}@media print{body{margin:0}tr{break-inside:avoid}}</style>'
    text += '<h1>'+esc(job['name'])+'</h1><p>任务：'+esc(job_id)+'；北京时间：'+esc(created)+'</p>'
    text += '<p>结果状态：'+esc(result['status'])+'；折现目标成本：'+esc(result.get('objective_yuan'))+' 元；建议状态：'+esc(result.get('recommendation_status'))+'</p>'
    text += '<p class="notice">本报告为给定候选、样本与静态近似下的工程研究结果。课题3动态方程、训练权重及验证数据按用户要求暂留空；动态稳定、实际黑启动及一二次联合配置未校核，不能作为安全执行许可。</p>'
    if result.get('recommendation_status') == 'not_recommended_validation_failed':
        text += '<p class="notice">样本外验证失败：本方案不能作为已验证可靠方案，不以训练集达标替代验证。</p>'
    if result['status'] == 'infeasible':
        text += '<p>当前约束无投资可行解，不能解释为零投资、零缺供方案。</p>'
    text += '<h2>冻结输入与判据</h2><p>工程版本 '+esc(snapshot['project']['revision'])+'；台账版本 '+esc(snapshot['engineering']['revision'])+'；方法 '+esc(result['method'])+'</p>'
    text += '<p>联合范围：'+esc(params['risk_scope'])+'；概率要求：'+esc(params['required_probability'])+'；保护类别：'+esc(' / '.join(params['protected_classes']))+'；概率来源：'+esc(params['probability_provenance'])+'</p>'
    text += '<p>输入SHA256：'+esc(job['input_sha256'])+'；运行构建：'+esc(snapshot['runtime']['build_id'])+'</p>'
    text += '<p>保供目标判据：'+esc(params.get('target_policy', 'every_step'))+'</p>'
    text += '<h2>选址与建设</h2>'+table(result['selected_assets'], [('asset_id','设备'),('node','节点'),('sizing_mode','容量方式'),('power_fraction','功率比例'),('energy_fraction','能量比例'),('power_kw','kW'),('energy_kwh','kWh'),('commission_year','投运年'),('retirement_year','退役年'),('capex_yuan','投资元')])
    text += '<h2>逐年现金流</h2>'+table(result['cashflows'], [('year','年份'),('capex_yuan','投资元'),('annual_maintenance_yuan','维护元'),('expected_operating_yuan','期望运营元'),('terminal_salvage_yuan','期末残值元'),('discounted_total_yuan','折现净成本元')])
    text += '<h2>训练样本实际机会约束</h2>'+table(result.get('compliance',[]), [('year','开始年'),('end_year','结束年（不含）'),('assigned_probability','承诺概率'),('actual_probability','实际概率'),('required_probability','要求')])
    text += '<h2>样本外验证</h2>'
    text += table(result['validation'], [('year','开始年'),('end_year','结束年（不含）'),('success_probability_lower','成功下界'),('success_probability_upper','成功上界'),('unknown_probability','未知权重')]) if result['validation'] else '<p>未提供或未执行样本外验证，不能视为已通过。</p>'
    text += '<h2>校核状态</h2>'+table(result['checks'], [('name','项目'),('status','状态')])
    text += '<h2>求解界限与原始证据</h2><pre>'+esc(encode(result['solver']))+'</pre>'
    text += '<h2>方法边界</h2><ul>'+''.join('<li>'+esc(line)+'</li>' for line in result['scope'])+'</ul></html>'
    text = text.replace('</html>', '<details><summary>冻结配置参数与计算环境</summary><pre>'+esc(json.dumps({'parameters': params, 'environment': result.get('environment')}, ensure_ascii=False, indent=2))+'</pre></details></html>')
    return Response(text, media_type='text/html; charset=utf-8', headers={'Content-Disposition': f'attachment; filename=investment-{job_id}.html'})


@router.get('/{job_id}/log')
def worker_log(job_id: str):
    job = get(job_id)
    path = ROOT/'data/study_jobs'/job['id']/'worker.log'
    content = ''
    if path.exists():
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size-200000))
            content = stream.read().decode('utf-8', errors='replace')
    return Response(content or '尚无工作进程日志', media_type='text/plain; charset=utf-8')


@router.get('/{job_id}/experiment-cases/{case_id}')
def experiment_case(job_id: str, case_id: str):
    job = get(job_id, include_result=True)
    if job['module'] != 'investment_experiments' or not job['result']:
        raise HTTPException(409, '本任务尚无对比研究结果')
    if not any(c['id'] == case_id and c.get('detail_archived') for c in job['result']['cases']):
        raise HTTPException(404, '该算例没有归档结果')
    with closing(connection()) as c:
        row = c.execute('SELECT payload FROM study_case_results WHERE job_id=? AND case_id=?', (job_id, case_id)).fetchone()
    if not row:
        raise HTTPException(404, '算例归档缺失')
    return Response(encode({'experiment_job_id': job_id, 'frozen_experiment_input_sha256': job['input_sha256'],
                            **json.loads(row[0])}), media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename=experiment-{job_id}-{case_id}.json'})


def experiment_report(job):
    if not job['result']:
        raise HTTPException(409, '本研究尚无结果')
    esc = lambda v: html.escape(str(v if v is not None else '—'))
    result = job['result']
    keys = [('name', '算例'), ('status', '解状态'), ('value', '参数值'), ('objective_yuan', '折现成本 元'),
            ('training_success_probability', '实际训练概率'), ('delta_objective_yuan', '较基准 元'),
            ('validation_status', '样本外'), ('validation_success_probability_lower', '样本外概率下界'), ('recommendation_status', '建议状态')]
    head = ''.join('<th>'+esc(title)+'</th>' for _, title in keys)
    body = ''.join('<tr>'+''.join('<td>'+esc(row.get(key))+'</td>' for key, _ in keys)+'</tr>' for row in result['cases'])
    text = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+esc(job['name'])+'</title>'
    text += '<style>body{font:14px/1.7 sans-serif;max-width:1400px;margin:35px auto;padding:0 20px;color:#183c40}table{width:100%;border-collapse:collapse}th,td{padding:8px;border:1px solid #ccdadd;overflow-wrap:anywhere}th{background:#eef6f6}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
    text += '<h1>配置风险—成本与敏感性研究</h1><p>'+esc(job['name'])+' · '+esc(result['status'])+'</p>'
    text += '<p>输入SHA256：'+esc(job['input_sha256'])+'；运行构建：'+esc(job['runtime']['build_id'])+'</p>'
    text += '<p>训练非支配算例：'+esc('、'.join(result['training_non_dominated']))+'；已验证非支配算例：'+esc('、'.join(result['validated_non_dominated']) or '无')+'</p>'
    text += '<table><tr>'+head+'</tr>'+body+'</table><h2>单例完整证据</h2><ul>'
    for row in result['cases']:
        if row.get('detail_archived'):
            text += '<li>'+esc(row['id'])+' / '+esc(row['derived_input_sha256'])+'（软件档案中下载完整单例JSON）</li>'
    text += '</ul><h2>方法范围</h2><ul>'+''.join('<li>'+esc(s)+'</li>' for s in result['scope'])+'</ul>'
    text += '<details><summary>冻结研究参数</summary><pre>'+esc(encode(job['input']['parameters']))+'</pre></details></html>'
    return Response(text, media_type='text/html; charset=utf-8', headers={'Content-Disposition': f'attachment; filename=investment-experiments-{job["id"]}.html'})


@router.get('/{job_id}/annual-windows')
def annual_windows(job_id: str):
    job = get(job_id)
    if job['module'] != 'annual_dispatch':
        raise HTTPException(409, '该任务属于其他研究类型')
    with closing(connection()) as c:
        rows = c.execute('SELECT case_id,payload FROM study_case_results WHERE job_id=? ORDER BY case_id', (job_id,))
        return [json.loads(payload)['summary'] for _, payload in rows]


@router.get('/{job_id}/annual-windows/{window_id}')
def annual_window(job_id: str, window_id: str):
    job = get(job_id)
    if job['module'] != 'annual_dispatch':
        raise HTTPException(409, '该任务属于其他研究类型')
    with closing(connection()) as c:
        row = c.execute('SELECT payload FROM study_case_results WHERE job_id=? AND case_id=?', (job_id, window_id)).fetchone()
    if not row:
        raise HTTPException(404, '窗口尚未提交或不存在')
    return Response(row[0], media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename=annual-{job_id}-{window_id}.json'})


def annual_csv(job):
    keys = ['global_step', 'timestamp', 'step_hours', 'load_kw', 'served_kw', 'total_unsupplied_kw',
            'controlled_curtailment_kw', 'shortage_kw', 'grid_kw', 'power_balance_residual_kw']
    def chunks():
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        yield '\ufeff'+output.getvalue()
        # StreamingResponse may resume this iterator on another worker thread.
        # Close each connection before yielding or waiting on the client.
        previous = ''
        while True:
            with closing(connection()) as c:
                row = c.execute('SELECT case_id,payload FROM study_case_results '
                                'WHERE job_id=? AND case_id>? ORDER BY case_id LIMIT 1',
                                (job['id'], previous)).fetchone()
            if row is None:
                break
            previous, payload = row
            output.seek(0)
            output.truncate(0)
            writer.writerows(json.loads(payload)['committed_rows'])
            yield output.getvalue()
    return StreamingResponse(chunks(), media_type='text/csv; charset=utf-8',
                             headers={'Content-Disposition': f'attachment; filename=annual-committed-{job["id"]}.csv'})


def annual_report(job):
    if not job['result']:
        raise HTTPException(409, '年度报告等待任务产生汇总结果')
    esc = lambda value: html.escape(str(value if value is not None else '—'))
    result = job['result']
    text = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>年度滚动计算</title><style>body{font:15px/1.7 sans-serif;max-width:1100px;margin:35px auto;padding:20px;color:#183c40}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccdadd;padding:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
    text += '<h1>逐设备年度滚动计算</h1><p>'+esc(job['name'])+'</p><p>输入摘要 '+esc(job['input_sha256'])+'</p>'
    text += '<h2>覆盖范围</h2><pre>'+esc(encode(result['coverage']))+'</pre><h2>已提交区间指标</h2><table>'
    text += ''.join('<tr><th>'+esc(key)+'</th><td>'+esc(value)+'</td></tr>' for key,value in result['metrics'].items())+'</table>'
    text += '<h2>窗口与停止记录</h2><p>'+esc(result['status'])+' / '+esc(result['stop_reason'])+'</p>'
    text += '<p>已提交窗口 '+esc(len(result['windows']))+'</p><h2>逐负荷目标</h2><pre>'+esc(encode(result['load_metrics']))+'</pre>'
    text += '<h2>方法范围</h2><ul>'+''.join('<li>'+esc(value)+'</li>' for value in result['scope'])+'</ul></html>'
    return Response(text, media_type='text/html; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename=annual-{job["id"]}.html'})


def execute(job_id, token):
    """Worker entry point. Source changes while queued are rejected, not misattributed."""
    job = get(job_id, True)
    if job['status'] != 'queued' or job.get('launch_token') != token:
        return
    # Claim under the same database lock used by cancellation and slot reservation.
    if not update(job_id, {'queued'}, status='running', started=time.time(), pid=os.getpid(), process_identity=process_identity(os.getpid())):
        return
    try:
        snapshot = job['input']
        if canonical_sha(snapshot) != job['input_sha256']:
            raise ValueError('冻结输入摘要不匹配')
        from backend.app import RUNTIME_ID
        if RUNTIME_ID['build_id'] != snapshot['runtime']['build_id']:
            raise ValueError('排队后代码构建已变化，请通过启动脚本打开当前软件并重试')
        inventory = Inventory.model_validate(snapshot['engineering']['inventory'])
        network = Network.model_validate(snapshot['network'])
        def cancelled():
            return get(job_id)['status'] != 'running'
        def progress(value):
            if not update(job_id, {'running'}, progress=value):
                raise StudyCancelled('取消或任务状态变化')
        if job['module'] == 'device_dispatch':
            result = dispatch(DispatchInput.model_validate(snapshot['parameters']), inventory, network, progress, cancelled)
        elif job['module'] == 'disaster_scan':
            result = scan(DisasterInput.model_validate(snapshot['parameters']), inventory, network, progress, cancelled)
        elif job['module'] == 'restoration':
            result = plan_restoration(RestorationInput.model_validate(snapshot['parameters']), inventory, network, progress, cancelled)
        elif job['module'] == 'annual_dispatch':
            def window_sink(window_id, value):
                payload = encode(value)
                with closing(connection()) as c, c:
                    c.execute('BEGIN IMMEDIATE')
                    state = c.execute('SELECT status FROM study_jobs WHERE id=?', (job_id,)).fetchone()
                    if not state or state[0] != 'running':
                        raise StudyCancelled('年度窗口提交前取消')
                    c.execute('INSERT INTO study_case_results VALUES(?,?,?)', (job_id, window_id, payload))
            result = run_annual(AnnualDispatchInput.model_validate(snapshot['parameters']), inventory, network,
                                progress, cancelled, window_sink)
        elif job['module'] in ('investment', 'investment_experiments'):
            from backend.milp_execution import native_milp
            def solver_runner(model, terms, seconds, gap):
                return native_milp(model, terms, seconds, gap, cancelled=cancelled,
                                   log_dir=ROOT/'data/study_jobs'/job_id, expected_build_id=snapshot['runtime']['build_id'])
            if job['module'] == 'investment':
                result = investment_plan(InvestmentInput.model_validate(snapshot['parameters']), inventory, network, progress, cancelled, solver_runner)
            else:
                def case_sink(case_id, value):
                    payload = encode(value)
                    with closing(connection()) as c, c:
                        c.execute('BEGIN IMMEDIATE')
                        state = c.execute('SELECT status FROM study_jobs WHERE id=?', (job_id,)).fetchone()
                        if not state or state[0] != 'running':
                            raise StudyCancelled('单例结果提交前已取消')
                        c.execute('INSERT INTO study_case_results VALUES(?,?,?)', (job_id, case_id, payload))
                result = run_experiments(InvestmentExperimentInput.model_validate(snapshot['parameters']), inventory, network, progress, cancelled, solver_runner, case_sink)
        else:
            raise ValueError('未注册研究模块')
        if cancelled():
            raise StudyCancelled('取消请求优先于结果提交')
        status = 'succeeded' if result['status'] in ('optimal', 'complete', 'infeasible') else 'incomplete'
        if not update(job_id, {'running'}, status=status, result=result, finished=time.time()):
            raise StudyCancelled('结果提交前收到取消请求')
    except DispatchIncomplete as e:
        if not update(job_id, {'running'}, status='incomplete', error=str(e), finished=time.time()):
            update(job_id, {'cancel_requested'}, status='cancelled', finished=time.time(), error='取消期间达到计算时限')
    except StudyCancelled:
        update(job_id, {'running', 'cancel_requested'}, status='cancelled', finished=time.time(), error='已取消，未保存成功结果')
    except Exception as e:
        traceback.print_exc()
        if not update(job_id, {'running'}, status='failed', error=str(e), finished=time.time()):
            update(job_id, {'cancel_requested'}, status='cancelled', finished=time.time(), error='取消期间计算退出')
    finally:
        schedule()
