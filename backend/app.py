from contextlib import closing, asynccontextmanager
from pathlib import Path
import sys,json,sqlite3,uuid,io
from typing import Literal,Any
from datetime import datetime
import numpy as np
import pandas as pd
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field,model_validator,ConfigDict
from backend.network_data import Network, router as network_router
from backend.workspace import router as workspace_router,project_record,scenario_record,production_sequence_record
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor/topic2'))
from src.chapter4.power_energy_balance import analyze_power_energy_balance
from topic2_remaining_code.strategy_trigger import trigger_strategies
@asynccontextmanager
async def lifespan(application):
 from backend.study_jobs import schedule
 schedule()
 yield

app=FastAPI(title='末端保供分析平台',lifespan=lifespan)
from backend.runtime_identity import build_identity
RUNTIME_ID=build_identity()
@app.get('/api/runtime')
def runtime_identity():return RUNTIME_ID
app.include_router(workspace_router)
app.include_router(network_router)
from backend.alashankou import router as alashankou_router
app.include_router(alashankou_router)
from backend.input_datasets import router as input_datasets_router
app.include_router(input_datasets_router)
from backend.source_import import router as source_import_router
app.include_router(source_import_router)
from backend.workflow_progress import router as workflow_progress_router
app.include_router(workflow_progress_router)
from backend.engineering import router as engineering_router
from backend.development_plan import router as development_plan_router
from backend.effect_evaluation import router as effect_evaluation_router
from backend.archive_evaluation import router as archive_evaluation_router
from backend.resource_dispatch import router as resource_dispatch_router
app.include_router(resource_dispatch_router)
from backend.study_jobs import router as study_jobs_router
app.include_router(study_jobs_router)
app.include_router(archive_evaluation_router)
app.include_router(effect_evaluation_router)
app.include_router(engineering_router)
app.include_router(development_plan_router)
from backend.source_studies import router as source_studies_router
from backend.module_contracts import router as module_contracts_router
app.include_router(source_studies_router)
app.include_router(module_contracts_router)
from backend.native_jobs import router as native_jobs_router
app.include_router(native_jobs_router)
DATA=ROOT/'data';DATA.mkdir(exist_ok=True)
def db():
 c=sqlite3.connect(DATA/'platform.db');c.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, created TEXT, payload TEXT)');return c
class Parameters(BaseModel):
 model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
 storage_power_kw:float=Field(500,ge=0,le=100000)
 storage_energy_kwh:float=Field(2000,ge=0,le=1000000)
 emergency_gen_kw:float=Field(300,ge=0,le=100000)
 grid_channel_kw:float=Field(0,ge=0,le=100000)
 soc_initial_ratio:float=Field(.8,ge=0,le=1)
 soc_min_ratio:float=Field(.1,ge=0,le=.95)
 soc_max_ratio:float=Field(.95,ge=.1,le=1)
 eta_charge:float=Field(.92,gt=0,le=1)
 eta_discharge:float=Field(.9,gt=0,le=1)
 critical_load_ratio:float=Field(.2,ge=0,le=1)
 important_load_ratio:float=Field(.35,ge=0,le=1)
 @model_validator(mode='after')
 def resource_consistency(self):
  if not self.soc_min_ratio<=self.soc_initial_ratio<=self.soc_max_ratio:raise ValueError('SOC须满足下限≤初始值≤上限')
  if self.critical_load_ratio+self.important_load_ratio>1:raise ValueError('关键与重要负荷比例之和不得超过1，剩余部分为一般负荷')
  return self
class Stage(BaseModel):
 model_config=ConfigDict(extra="forbid",allow_inf_nan=False,str_strip_whitespace=True)
 name:str=Field(min_length=1,max_length=40)
 end_hour:int=Field(gt=0,le=8760)
 grid_ratio:float=Field(1,ge=0,le=1)
 emergency_ratio:float=Field(1,ge=0,le=1)
 failed_lines:list[int]=Field(default_factory=list,max_length=200)
class NetworkParameters(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 wind_node:int=Field(18,ge=1,le=99999)
 pv_node:int=Field(30,ge=1,le=99999)
 voltage_min_pu:float=Field(.95,ge=.8,le=1)
 voltage_max_pu:float=Field(1.05,ge=1,le=1.2)
 linear_voltage_guard_pu:float=Field(.955,ge=.8,le=1)
 @model_validator(mode='after')
 def voltage_consistency(self):
  if self.voltage_min_pu>=self.voltage_max_pu:raise ValueError('电压下限须小于上限')
  if not self.voltage_min_pu<=self.linear_voltage_guard_pu<=self.voltage_max_pu:raise ValueError('线性调度电压保护阈值须位于电压上下限之间')
  return self
class Request(BaseModel):
 model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
 project_id:str|None=None
 project_revision:int|None=None
 engineering_revision:int|None=Field(None,ge=0)
 scenario_id:str|None=None
 production_sequence_id:str|None=None
 operating_condition:Literal['normal','extreme']|None=None
 network:Network|None=None
 source_import:dict|None=None
 network_parameters:NetworkParameters=Field(default_factory=NetworkParameters)
 stages:list[Stage]=Field(default_factory=list,max_length=20)
 model:Literal["aggregate","case33"]="aggregate"
 failed_lines:list[int]=Field(default_factory=list,max_length=200)
 branch_limit_kw:float=Field(5000,gt=0,le=100000)
 csv:str=Field(min_length=10,max_length=2000000)
 parameters:Parameters
@app.get('/api/backup')
def download_backup():
 from backend.backup import create_backup
 try:content,manifest=create_backup(DATA/'platform.db')
 except FileNotFoundError as e:raise HTTPException(404,str(e))
 except (ValueError,sqlite3.DatabaseError) as e:raise HTTPException(503,'备份未完成：'+str(e))
 stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
 return Response(content,media_type='application/zip',headers={'Content-Disposition':f'attachment; filename=power-backup-{stamp}.zip'})
@app.get('/api/demo')
def demo():
 t=np.arange(48);df=pd.DataFrame({'timestamp':pd.date_range('2026-01-05',periods=48,freq='h'),'load_kw':np.round(900+200*np.sin((t-7)*np.pi/12),2),'wind_kw':np.round(180+90*np.cos(t*np.pi/8),2),'pv_kw':np.round(700*np.maximum(0,np.sin((t%24-6)*np.pi/12)),2)})
 return {'csv':df.to_csv(index=False),'label':'合成48小时联调数据，非实测灾害数据'}
@app.post('/api/balance')
def balance(req:Request):
 try:
  if req.source_import and any(x in str(req.source_import.get('file','')) for x in ('6.22','6．22','6月22')):raise ValueError('6.22典型日已退出计算输入，请重新选择历史风光荷数据')
  df=pd.read_csv(io.StringIO(req.csv));required=['timestamp','load_kw','wind_kw','pv_kw']
  if list(df.columns)!=required:raise ValueError('首版CSV列必须依次为 timestamp,load_kw,wind_kw,pv_kw')
  if not 2<=len(df)<=8760:raise ValueError('需提供2至8760条逐小时数据')
  ts=pd.to_datetime(df.timestamp,errors='raise')
  if not ts.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():raise ValueError('当前算法仅支持连续、升序、无重复的1小时间隔')
  for col in required[1:]:
   df[col]=pd.to_numeric(df[col],errors='raise')
   if not np.isfinite(df[col]).all() or (df[col]<0).any():raise ValueError(f'{col}必须是有限非负数')
  if req.project_id:
   project=project_record(req.project_id)
   if req.project_revision!=project['revision']:raise HTTPException(409,'计算引用的工程版本已过期，请保存当前工程后重试')
  engineering_ref=None
  if req.engineering_revision is not None and not req.project_id:raise ValueError('台账版本必须关联工程')
  if req.project_id:
   from backend.engineering import inventory_snapshot
   engineering_ref=inventory_snapshot(req.project_id,req.engineering_revision)
  params=req.parameters.model_dump()
  production=None
  if req.production_sequence_id:
   production=production_sequence_record(req.production_sequence_id)
   if production['project_id']!=req.project_id:raise ValueError('生产序列必须属于当前工程')
   if production['csv']!=req.csv:raise ValueError('源荷已修改，与引用生产序列不一致，请解除序列引用后计算')
   df['is_extreme_condition']=[int(row['is_extreme_condition']) for row in production['rows']]
  else:df['is_extreme_condition']=0
  effective_scenario_id=req.scenario_id
  if production and production.get('embedded_scenario_id'):
   if effective_scenario_id and effective_scenario_id!=production['embedded_scenario_id']:raise ValueError('耦合生产序列必须使用其绑定故障场景，请先解除序列引用再更换场景')
   effective_scenario_id=production['embedded_scenario_id']
  stages=req.stages or [Stage(name='全时域',end_hour=len(df),failed_lines=req.failed_lines)]
  names=[stage.name for stage in stages]
  if len(names)!=len(set(names)):raise ValueError('阶段名称不得重复，请为各阶段设置独立名称，以便分别统计指标')
  ends=[stage.end_hour for stage in stages]
  if ends!=sorted(set(ends)) or ends[-1]!=len(df):raise ValueError('阶段结束小时必须严格递增，最后阶段须覆盖全部输入时段')
  network=req.network.model_dump() if req.network else None
  if req.model=='aggregate' and req.failed_lines:raise ValueError('支路故障需要选择节点网络模型')
  active_ids={l['line'] for l in network['lines'] if l['status']} if network else set(range(1,33))
  for failures in [req.failed_lines]+[stage.failed_lines for stage in stages]:
   if len(failures)!=len(set(failures)) or not set(failures)<=active_ids:raise ValueError('故障支路须为当前投运线路编号，且不能重复')
  if req.model=='aggregate' and any(stage.failed_lines for stage in stages):raise ValueError('支路故障需要选择IEEE33网络模型')
  stage_indices=[next(i for i,end in enumerate(ends) if h<end) for h in range(len(df))]
  df['available_kw_grid_channel']=[params['grid_channel_kw']*stages[i].grid_ratio for i in stage_indices]
  df['available_kw_emergency_gen']=[params['emergency_gen_kw']*stages[i].emergency_ratio for i in stage_indices]
  if effective_scenario_id:
   scenario=scenario_record(effective_scenario_id)
   if not req.project_id or scenario['project_id']!=req.project_id:raise ValueError('故障场景必须属于当前工程')
   cap=pd.DataFrame(scenario['capacity'])
   if len(cap)!=len(df) or not pd.to_datetime(cap.timestamp).reset_index(drop=True).equals(ts.reset_index(drop=True)):raise ValueError('故障场景的时间轴必须与源荷数据完全一致')
   limits={'available_kw_storage':params['storage_power_kw'],'available_kw_renewable':None,'available_kw_transformer':None}
   for col in cap.columns:
    if col=='timestamp':continue
    if col in df:df[col]=np.minimum(df[col],cap[col])
    elif col in limits:df[col]=cap[col] if limits[col] is None else np.minimum(limits[col],cap[col])
   if 'available_kw_renewable' in df:df['available_re_kw']=np.minimum(df.wind_kw+df.pv_kw,df.available_kw_renewable)
  network_details=[]
  if req.model=='case33':
   from src.chapter4.case33_network_balance import Case33NetworkBalance,NetworkBalanceConfig,summarize_network_balance,resource_limits_from_row
   nodes=pd.DataFrame(network['nodes']) if network else pd.read_csv(ROOT/'vendor/topic2/data/case33/nodes.csv')
   lines=pd.DataFrame(network['lines']) if network else pd.read_csv(ROOT/'vendor/topic2/data/case33/lines.csv')
   if not {req.network_parameters.wind_node,req.network_parameters.pv_node}<=set(nodes.node):raise ValueError('风光接入节点必须存在于当前网络')
   if len(df)>168:raise ValueError('网络试算当前限制168小时，长序列待接入后台任务')
   cfg=NetworkBalanceConfig.from_project({'chapter4':params,'case33_network':{'branch_limit_kw':req.branch_limit_kw,'base_voltage_kv':network['base_voltage_kv'] if network else 12.66,**req.network_parameters.model_dump()}})
   model=Case33NetworkBalance(nodes,lines,cfg)
   energy=cfg.storage_energy_kwh*cfg.soc_initial_ratio;rows=[]
   for hour,item in enumerate(df.itertuples()):
    row,energy,state,ac=model.dispatch_hour_ac_balanced(item.timestamp,item.load_kw,item.wind_kw,item.pv_kw,set(stages[stage_indices[hour]].failed_lines),energy,**resource_limits_from_row(item))
    failed=set(stages[stage_indices[hour]].failed_lines);connected=model.connected(failed)
    network_details.append({'timestamp':str(item.timestamp),'nodes':[{'node':int(node),'connected':i in connected,'load_kw':float(item.load_kw*model.load_weights[i]/model.peak_kw),'served_kw':float(state['served_kw'][i]),'linear_voltage_pu':float(np.sqrt(state['voltage_squared'][i])) if i in connected else None} for i,node in enumerate(model.node_ids)],'lines':[{'line':int(line),'failed':int(line) in failed,'flow_kw':float(state['branch_flow_kw'][i])} for i,line in enumerate(model.line_ids)]})
    row['ac_max_voltage_pu']=ac['ac_max_voltage_pu'];row['ac_voltage_within_bounds']=ac['ac_voltage_within_bounds'];rows.append(row)
   hourly=pd.DataFrame(rows);metrics=summarize_network_balance(hourly)
  else:metrics,hourly=analyze_power_energy_balance(df,params)
  # The research implementations use different auxiliary island-hour proxies.
  # Preserve their value and supply a common, capacity-based strategy input.
  metrics['research_island_required_hours']=metrics.get('island_required_hours',0)
  hourly['is_extreme_condition']=df.is_extreme_condition.to_numpy()
  grid_available=df.available_kw_grid_channel.to_numpy().copy()
  if 'available_kw_transformer' in df:grid_available=np.minimum(grid_available,df.available_kw_transformer.to_numpy())
  disconnected=hourly.reachable_load_kw.to_numpy()<hourly.load_kw.to_numpy()-1e-6
  hourly['external_grid_available_kw']=grid_available
  hourly['island_support_required']=((grid_available<=1e-6)|disconnected)&(hourly.load_kw.to_numpy()>1e-6)
  metrics['island_required_hours']=float(hourly.island_support_required.sum())
  metrics['network_disconnected_load_hours']=float(disconnected.sum())
  metrics['extreme_event_hours']=float(hourly.is_extreme_condition.sum())
  from phase_balance_analysis.src.phase_metrics import compute_phase_metrics
  hourly['stage']=[stages[i].name for i in stage_indices]
  hourly['stage_order']=stage_indices
  phase_input=hourly.assign(simulation_id='single',event_id='configured',power_loss_mw=hourly.power_deficit_kw/1000,curtailment_mw=hourly.curtailment_kw/1000)
  phase_summary,_=compute_phase_metrics(phase_input,1,1e-9,'用户输入单轨迹；比例为缺供时段占比')
  result={'project_id':req.project_id,'project_revision':req.project_revision,'scenario_id':effective_scenario_id,'stages':[stage.model_dump() for stage in stages],'phase_metrics':json.loads(phase_summary.to_json(orient='records',force_ascii=False)),'id':uuid.uuid4().hex,'created':datetime.now().isoformat(timespec='seconds'),'parameters':params,'metrics':metrics,'rows':json.loads(hourly.to_json(orient='records',date_format='iso')),'strategies':json.loads(trigger_strategies(metrics).to_json(orient='records',force_ascii=False)),'input_csv':req.csv,'model':req.model,'failed_lines':req.failed_lines,'branch_limit_kw':req.branch_limit_kw,'algorithm':'topic2.'+req.model+'.v1','scope':('辐射网络节点线性调度与交流潮流复核；仅校核与根节点连通区域，不含孤岛动态稳定' if req.model=='case33' else '汇总逐小时调度；不含节点潮流与稳定校核')}
  result['operating_condition']=req.operating_condition
  result['scenario_snapshot']=scenario if effective_scenario_id else None
  if network_details:result['network_details']=network_details
  if engineering_ref is not None:
   result['engineering']=engineering_ref
   result['engineering_usage']='台账来源快照；本次旧汇总/IEEE33调度未使用逐设备台账约束'
  result['network']=network
  result['source_import']=req.source_import
  result['network_parameters']=req.network_parameters.model_dump()
  result['algorithm']='topic2.'+req.model+('.radial.v3' if network and req.model=='case33' else '.v2')
  result['metric_definitions']={'island_required_hours':'存在正负荷且外部供电容量为0，或部分负荷与根节点失联的时段数；是孤岛支撑需求提示，不代表可稳定离网。','research_island_required_hours':'原研究函数辅助指标，两个模型的代理口径不同，保留供追溯。','extreme_event_hours':'绑定生产序列中的事件标记小时数；未绑定序列时为0。'}
  result['production_sequence_id']=req.production_sequence_id
  if production:
   import hashlib
   result['production_snapshot']={k:v for k,v in production.items() if k not in ['rows','csv','input_background_csv','input_event_csv']}
   result['production_snapshot']['background_sha256']=hashlib.sha256(production['input_background_csv'].encode()).hexdigest()
   result['production_snapshot']['event_sha256']=hashlib.sha256(production['input_event_csv'].encode()).hexdigest()
  with closing(db()) as c,c:c.execute('INSERT INTO runs VALUES(?,?,?)',(result['id'],result['created'],json.dumps(result,ensure_ascii=False,allow_nan=False)))
  return result
 except (ValueError,KeyError,TypeError,RuntimeError) as e:raise HTTPException(422,str(e))
def run_archive_page(project_id,limit,offset,kind='all',operating_condition=None):
 conditions=[];arguments=[]
 if project_id is not None:conditions.append("json_extract(payload,'$.project_id')=?");arguments.append(project_id)
 if kind=='random':conditions.append("json_extract(payload,'$.random_batch_id') IS NOT NULL")
 elif kind=='adjustment':conditions.append("json_extract(payload,'$.baseline_run_id') IS NOT NULL AND json_extract(payload,'$.random_batch_id') IS NULL")
 elif kind=='baseline':conditions.append("json_extract(payload,'$.baseline_run_id') IS NULL AND json_extract(payload,'$.random_batch_id') IS NULL")
 if operating_condition in ('normal','extreme'):conditions.append("json_extract(payload,'$.operating_condition')=?");arguments.append(operating_condition)
 elif operating_condition=='unknown':conditions.append("json_extract(payload,'$.operating_condition') IS NULL")
 where=(' WHERE '+' AND '.join(conditions)) if conditions else ''
 keys=['id','created','project_id','project_revision','model','scenario_id','baseline_run_id','random_batch_id','plan_id','algorithm','operating_condition']
 columns=','.join("json_extract(payload,'$."+key+"')" for key in keys)
 with closing(db()) as c:
  total=c.execute('SELECT COUNT(*) FROM runs'+where,arguments).fetchone()[0]
  rows=c.execute('SELECT '+columns+' FROM runs'+where+' ORDER BY created DESC,rowid DESC LIMIT ? OFFSET ?',arguments+[limit,offset]).fetchall()
 return {'items':[dict(zip(keys,row)) for row in rows],'total':total,'offset':offset,'limit':limit}
@app.get('/api/runs')
def runs(project_id:str|None=None,limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0)):
 return run_archive_page(project_id,limit,offset)['items']
@app.get('/api/run-archive')
def run_archive(project_id:str,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),kind:Literal['all','baseline','adjustment','random']='all',operating_condition:Literal['all','normal','extreme','unknown']='all'):
 return run_archive_page(project_id,limit,offset,kind,operating_condition)
@app.get('/api/runs/{run_id}')
def get_run(run_id:str):
 with closing(db()) as c,c:r=c.execute('SELECT payload FROM runs WHERE id=?',(run_id,)).fetchone()
 if not r:raise HTTPException(404,'结果不存在')
 return json.loads(r[0])
@app.get('/api/runs/{run_id}/csv')
def export(run_id:str):
 r=get_run(run_id);return Response(pd.DataFrame(r['rows']).to_csv(index=False).encode('utf-8-sig'),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename=balance-{run_id}.csv'})
@app.get('/api/runs/{run_id}/report')
def report(run_id:str):
 from html import escape
 r=get_run(run_id)
 def table(rows):
  if not rows:return '<p>无记录</p>'
  keys=list(rows[0]);return '<table><tr>'+''.join('<th>'+escape(str(k))+'</th>' for k in keys)+'</tr>'+''.join('<tr>'+''.join('<td>'+escape(str(row.get(k,'')))+'</td>' for k in keys)+'</tr>' for row in rows)+'</table>'
 html='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>末端保供计算报告</title><style>body{font:14px sans-serif;max-width:1200px;margin:40px auto;color:#234}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #bcd;padding:8px;text-align:left}th{background:#eaf3f3}pre{white-space:pre-wrap}@media print{body{margin:10px}}</style><h1>末端保供电力电量分析报告</h1>'
 html+='<p>计算编号：'+escape(r['id'])+'　时间：'+escape(r['created'])+'</p><p>算法：'+escape(r['algorithm'])+'</p><p>'+escape(r['scope'])+'</p>'
 html+='<p>输入为用户提交的单轨迹；示例数据不代表实测灾害。缺供时段比例不能解释为经校准的灾害发生概率。</p>'
 html+='<h2>资源参数（功率kW，能量kWh，SOC为比例）</h2>'+table([r['parameters']])
 html+='<p>负荷分类口径：关键与重要负荷按总负荷占比分组，剩余为一般负荷，并按关键、重要、一般顺序保障；不代表逐户分类数据库。无某类负荷时，原算法将该类电量满足率记为1。储能能量受SOC上下限及充放电效率约束。</p>'
 if r.get('baseline_run_id'):
  html+='<p>基准计算编号：'+escape(r['baseline_run_id'])+'</p><p>'+escape(r.get('interpretation',''))+'</p>'
 if r.get('strategy_adjustments'):
  html+='<h2>策略调整参数</h2><pre>'+escape(json.dumps(r['strategy_adjustments'],ensure_ascii=False,indent=2))+'</pre>'
 html+='<h2>网络接入与电压约束</h2>'+table([r.get('network_parameters',{'wind_node':18,'pv_node':30})]) if r.get('model')=='case33' else ''
 if r.get('source_import'):html+='<h2>风光荷输入来源与转换</h2>'+table([r['source_import']])
 if r.get('network'):
  html+='<h2>计算网络快照</h2>'+table([{k:v for k,v in r['network'].items() if k not in ('nodes','lines')}])+table(r['network']['nodes'])+table(r['network']['lines'])
 html+='<h2>阶段与故障设置</h2>'+table(r.get('stages',[]))
 if r.get('production_snapshot'):
  html+='<h2>生产序列来源与嵌入参数</h2><pre>'+escape(json.dumps(r['production_snapshot'],ensure_ascii=False,indent=2))+'</pre>'
 html+='<p>工程：'+escape(str(r.get('project_id') or '未关联'))+'；版本：'+escape(str(r.get('project_revision') or '未记录'))+'；固定故障支路：'+escape(str(r.get('failed_lines',[])))+'；支路限额：'+escape(str(r.get('branch_limit_kw','未记录')))+' kW</p>'
 scenario=r.get('scenario_snapshot')
 if scenario:
  metadata={k:v for k,v in scenario.items() if k not in ['states','capacity','failures','hazard_csv']}
  html+='<h2>故障场景快照与复现参数</h2><pre>'+escape(json.dumps(metadata,ensure_ascii=False,indent=2))+'</pre>'
  html+='<h3>连续故障起始事件</h3>'+table(scenario.get('failures',[]))
  html+='<h3>逐时可用容量</h3>'+table(scenario.get('capacity',[]))
 elif r.get('scenario_id'):
  html+='<p>场景编号：'+escape(r['scenario_id'])+'（历史记录未保存内嵌场景快照）</p>'
 html+='<h2>汇总指标（字段后缀标注单位）</h2>'+table([{'指标':k,'计算值':v} for k,v in r['metrics'].items()])
 if r.get('metric_definitions'):html+='<h3>辅助指标口径</h3>'+table([{'指标':k,'口径':v} for k,v in r['metric_definitions'].items()])
 html+='<h2>阶段指标（MW、MWh、%）</h2>'+table(r.get('phase_metrics',[]))
 html+='<h2>策略触发（默认研究阈值）</h2>'+table(r['strategies'])
 html+='<h2>完整逐时结果</h2>'+table(r['rows'])+'</html>'
 return Response(html,media_type='text/html',headers={'Content-Disposition':f'attachment; filename=report-{run_id}.html'})
@app.get('/api/comparison-report')
def export_comparison(baseline_id:str,comparison_id:str):
 from backend.comparison import comparison_report
 a=get_run(baseline_id);b=get_run(comparison_id)
 if a.get('project_id')!=b.get('project_id'):raise HTTPException(422,'对比计算必须属于同一工程')
 return Response(comparison_report(a,b),media_type='text/html',headers={'Content-Disposition':f'attachment; filename=comparison-{a["id"]}-{b["id"]}.html'})
class DraftRequest(BaseModel):
 values:dict[str,Any]

def validate_geography_disaster(values:dict[str,Any]):
    geography=values.get('geography') or {}; disaster=values.get('disaster') or {}
    for key,low,high in [('longitude',-180,180),('latitude',-90,90)]:
        value=geography.get(key)
        if value is not None and (not isinstance(value,(int,float)) or not low<=value<=high):
            raise HTTPException(422,f'{key}超出有效范围')
    start, end = disaster.get('start_time'), disaster.get('end_time')
    if start and end:
        try:
            if datetime.fromisoformat(start) > datetime.fromisoformat(end):
                raise HTTPException(422,'灾害结束时间必须不早于开始时间')
        except ValueError:
            raise HTTPException(422,'灾害时间必须为ISO日期时间')
    if disaster.get('verified') and not str(disaster.get('source') or '').strip():
        raise HTTPException(422,'已核实灾害记录必须填写来源')
    devices=disaster.get('affected_devices','')
    if isinstance(devices,list):
        if any(not str(x).strip() for x in devices): raise HTTPException(422,'受影响设备ID不能包含空值')
    elif not isinstance(devices,str):
        raise HTTPException(422,'受影响设备ID须为逗号分隔文本')

def validate_planning_draft(module:str,values:dict[str,Any]):
    required = {'一二次协同规划': ['primary_candidates','switches','terminals','controllers','communication_links'],
                '灵活组网': ['zones','tie_lines','normally_open_switches','islanding_rules','source_priority','communication_dependencies']}[module]
    for key in required:
        if not isinstance(values.get(key),list):
            raise HTTPException(422,f'{module}字段 {key} 必须为数组')
    if not str(values.get('objective') or '').strip(): raise HTTPException(422,f'{module}必须填写objective')
    if not str(values.get('provenance') or '').strip(): raise HTTPException(422,f'{module}必须填写provenance')
    budget=values.get('budget_yuan')
    if budget is not None and (not isinstance(budget,(int,float)) or budget<0): raise HTTPException(422,'budget_yuan必须为非负数或空值')

def validate_deliverables(values:dict[str,Any]):
    rows=values.get('rows')
    if not isinstance(rows,list): raise HTTPException(422,'成果与交付rows必须为数组')
    allowed={'待补','部分具备','已具备','已验收'}
    ids=set()
    for row in rows:
        if not isinstance(row,dict) or not str(row.get('id') or '').strip() or not str(row.get('name') or '').strip():
            raise HTTPException(422,'每个交付项必须包含id和name')
        if row['id'] in ids: raise HTTPException(422,'交付项id不能重复')
        ids.add(row['id'])
        if row.get('status') not in allowed: raise HTTPException(422,'交付项状态无效')
        if not isinstance(row.get('source',''),str) or not isinstance(row.get('note',''),str): raise HTTPException(422,'证据来源和备注必须为文本')

def validate_demonstration(values:dict[str,Any]):
    e=values.get('evidence')
    if not isinstance(e,dict): raise HTTPException(422,'示范区实证必须包含evidence对象')
    for key in ('region','project_level','basis','measurement_period','measured_metrics','conclusion','source'):
        if not isinstance(e.get(key,''),str): raise HTTPException(422,f'实证字段 {key} 必须为文本')
    if e.get('status') not in {'待补','部分具备','已具备','已验收'}: raise HTTPException(422,'实证状态无效')
    if e.get('status') in {'已具备','已验收'} and not e.get('source','').strip(): raise HTTPException(422,'已具备或已验收的实证记录必须填写证据来源')
@app.get('/api/drafts/{module}')
def read_draft(module:str,project_id:str="legacy"):
 module=project_id+":"+module
 with closing(db()) as c,c:
  c.execute('CREATE TABLE IF NOT EXISTS drafts(module TEXT PRIMARY KEY,payload TEXT,updated TEXT)')
  row=c.execute('SELECT payload,updated FROM drafts WHERE module=?',(module,)).fetchone()
 return {'values':json.loads(row[0]),'updated':row[1]} if row else {'values':None}
@app.put('/api/drafts/{module}')
def save_draft(module:str,req:DraftRequest,project_id:str="legacy"):
 key=project_id+":"+module
 if len(module)>80 or len(json.dumps(req.values))>100000:raise HTTPException(422,'草稿过大')
 if module=='地理与灾害':validate_geography_disaster(req.values)
 if module in ('一二次协同规划','灵活组网'):validate_planning_draft(module,req.values)
 if module=='成果与交付':validate_deliverables(req.values)
 if module=='示范区实证':validate_demonstration(req.values)
 read_draft(module,project_id)
 now=datetime.now().isoformat(timespec='seconds')
 with closing(db()) as c,c:c.execute('INSERT OR REPLACE INTO drafts VALUES(?,?,?)',(key,json.dumps(req.values,ensure_ascii=False),now))
 return {'updated':now}
class PlanningRequest(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 run_id:str
 storage_power_unit_kw:float=Field(100,gt=0,le=10000)
 storage_energy_unit_kwh:float=Field(200,gt=0,le=100000)
 max_storage_units:int=Field(10,ge=0,le=20)
 max_emergency_units:int=Field(10,ge=0,le=20)
 max_mobile_units:int=Field(5,ge=0,le=10)
 emergency_gen_unit_kw:float=Field(100,gt=0,le=10000)
 mobile_unit_kw:float=Field(100,gt=0,le=10000)
 storage_power_cost:float=Field(600,ge=0,le=1000000)
 storage_energy_cost:float=Field(900,ge=0,le=1000000)
 emergency_gen_cost:float=Field(450,ge=0,le=1000000)
 mobile_resource_cost:float=Field(200000,ge=0,le=100000000)
 penalty_energy_deficit:float=Field(20,ge=0,le=1000000)
 penalty_power_deficit:float=Field(100,ge=0,le=1000000)
 penalty_curtailment:float=Field(2,ge=0,le=1000000)
 default_soc_reserve_ratio:float=Field(.35,ge=.1,le=.95)
@app.post('/api/planning')
def planning(req:PlanningRequest):
 from topic2_remaining_code.resilience_reliability_planner import PlanningConfig,run_simple_planning
 source=get_run(req.run_id)
 config=PlanningConfig(**req.model_dump(exclude={'run_id'}))
 result=run_simple_planning(source['metrics'],pd.DataFrame(source['strategies']),config)
 result['source_run_id']=req.run_id
 result['method']='研究代码简化枚举与经验残余缺额估计，非机会约束优化'
 result['config']=__import__('dataclasses').asdict(config)
 result['id']=uuid.uuid4().hex
 with closing(db()) as c,c:
  c.execute('CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY,payload TEXT)')
  c.execute('INSERT INTO plans VALUES(?,?)',(result['id'],json.dumps(result,ensure_ascii=False,allow_nan=False)))
 return result
@app.get('/api/plans/{plan_id}')
def get_plan(plan_id:str):
 with closing(db()) as c,c:
  c.execute('CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY,payload TEXT)')
  row=c.execute('SELECT payload FROM plans WHERE id=?',(plan_id,)).fetchone()
 if not row:raise HTTPException(404,'规划结果不存在')
 return json.loads(row[0])
@app.post('/api/plans/{plan_id}/verify')
def verify_plan(plan_id:str):
 plan=get_plan(plan_id);source=get_run(plan['source_run_id'])
 if plan['recommended_plan']['mobile_units']:
  raise HTTPException(422,'该建议包含移动资源，尚缺接入时序与位置，不能自动复核')
 params=dict(source['parameters'])
 for key in ['storage_power_kw','storage_energy_kwh','emergency_gen_kw']:params[key]+=plan['recommended_plan'][key]
 req=Request(csv=source['input_csv'],parameters=Parameters(**params),model=source.get('model','aggregate'),operating_condition=source.get('operating_condition'),engineering_revision=source.get('engineering',{}).get('revision'),network=source.get('network'),source_import=source.get('source_import'),network_parameters=source.get('network_parameters',{}),stages=source.get('stages',[]),failed_lines=source.get('failed_lines',[]),branch_limit_kw=source.get('branch_limit_kw',5000),scenario_id=source.get('scenario_id'),production_sequence_id=source.get('production_sequence_id'),project_id=source.get('project_id'),project_revision=(project_record(source['project_id'])['revision'] if source.get('project_id') else None))
 checked=balance(req)
 checked['verification_of_plan']=plan_id
 checked['baseline_run_id']=source['id']
 checked['interpretation']='建议量按新增资源计入，沿用基准接入位置与时序；故障场景容量上限继续生效'
 with closing(db()) as c,c:c.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(checked,ensure_ascii=False,allow_nan=False),checked['id']))
 return {'plan_id':plan_id,'baseline':source['metrics'],'verified':checked['metrics'],'run_id':checked['id'],'interpretation':checked['interpretation']}
@app.get('/api/plans')
def list_plans(project_id:str):
 with closing(db()) as c,c:source_rows=c.execute('SELECT payload FROM runs').fetchall()
 ids={d['id'] for d in [json.loads(row[0]) for row in source_rows] if d.get('project_id')==project_id}
 with closing(db()) as c,c:
  c.execute('CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY,payload TEXT)')
  saved=c.execute('SELECT payload FROM plans ORDER BY rowid DESC').fetchall()
 return [p for p in [json.loads(r[0]) for r in saved] if p['source_run_id'] in ids]
class StrategyEvaluation(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 source_run_id:str
 parameters:Parameters
 wind_scale:float=Field(1,ge=0,le=10)
 pv_scale:float=Field(1,ge=0,le=10)

@app.post('/api/strategy-evaluation')
def evaluate_strategy(req:StrategyEvaluation):
 source=get_run(req.source_run_id)
 frame=pd.read_csv(io.StringIO(source['input_csv']))
 frame['wind_kw']*=req.wind_scale
 frame['pv_kw']*=req.pv_scale
 checked=balance(Request(csv=(source['input_csv'] if req.wind_scale==1 and req.pv_scale==1 else frame.to_csv(index=False)),parameters=req.parameters,model=source.get('model','aggregate'),operating_condition=source.get('operating_condition'),engineering_revision=source.get('engineering',{}).get('revision'),network=source.get('network'),source_import=source.get('source_import'),network_parameters=source.get('network_parameters',{}),stages=source.get('stages',[]),failed_lines=source.get('failed_lines',[]),branch_limit_kw=source.get('branch_limit_kw',5000),scenario_id=source.get('scenario_id'),production_sequence_id=(source.get('production_sequence_id') if req.wind_scale==1 and req.pv_scale==1 else None),project_id=source.get('project_id'),project_revision=(project_record(source['project_id'])['revision'] if source.get('project_id') else None)))
 checked['baseline_run_id']=source['id']
 checked['strategy_adjustments']=req.model_dump(exclude={'source_run_id'})
 checked['interpretation']='同一时间轴、阶段、拓扑与故障场景下复算；资源沿用基准接入位置，故障场景容量上限仍生效；风光系数调整出力，不等同装机优化。'
 with closing(db()) as c,c:c.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(checked,ensure_ascii=False,allow_nan=False),checked['id']))
 return {'baseline':source['metrics'],'verified':checked['metrics'],'run_id':checked['id'],'interpretation':checked['interpretation']}

class RandomBalanceRequest(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 source_run_id:str
 samples:int=Field(10,ge=2,le=20)
 seed:int=Field(42,ge=0,le=2147483600)
 resource:Literal['grid_channel','emergency_gen','storage','transformer','renewable']='grid_channel'
 rated_kw:float=Field(4000,ge=0,le=100000)
 rate_per_hour:float=Field(.02,ge=0,le=10)
 repair_hours:int=Field(6,ge=1,le=168)

def batch_db():
 c=db();c.execute('CREATE TABLE IF NOT EXISTS random_batches(id TEXT PRIMARY KEY,project_id TEXT,created TEXT,payload TEXT)');return c

@app.post('/api/random-balance')
def random_balance(req:RandomBalanceRequest):
 from backend.workspace import SequentialInput,sequential_scenario
 source=get_run(req.source_run_id)
 if not source.get('project_id'):raise HTTPException(422,'基准计算必须关联工程')
 if source.get('scenario_id'):raise HTTPException(422,'请使用未应用故障场景的基准；随机样本自行生成故障，避免覆盖原场景')
 if not 2<=len(source['rows'])<=168:raise HTTPException(422,'随机样本时域需为2至168小时')
 revision=project_record(source['project_id'])['revision']
 batch_id=uuid.uuid4().hex;items=[];phase_samples=[]
 for index in range(req.samples):
  seed=req.seed+index
  scene=sequential_scenario(SequentialInput(project_id=source['project_id'],name=f'随机平衡{batch_id[:8]}-样本{index+1}',csv=source['input_csv'],resource=req.resource,rated_kw=req.rated_kw,rate_per_hour=req.rate_per_hour,repair_hours=req.repair_hours,seed=seed))
  result=balance(Request(csv=source['input_csv'],parameters=Parameters(**source['parameters']),project_id=source['project_id'],project_revision=revision,scenario_id=scene['id'],production_sequence_id=source.get('production_sequence_id'),model=source.get('model','aggregate'),operating_condition=source.get('operating_condition'),engineering_revision=source.get('engineering',{}).get('revision'),network=source.get('network'),source_import=source.get('source_import'),network_parameters=source.get('network_parameters',{}),stages=source.get('stages',[]),failed_lines=source.get('failed_lines',[]),branch_limit_kw=source.get('branch_limit_kw',5000)))
  result['random_batch_id']=batch_id;result['baseline_run_id']=source['id']
  with closing(db()) as c,c:c.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(result,ensure_ascii=False,allow_nan=False),result['id']))
  items.append({'sample':index+1,'seed':seed,'scenario_id':scene['id'],'run_id':result['id'],'failure_events':len(scene['failures']),**result['metrics']})
  if source.get('model')=='case33':
   items[-1].update({'ac_min_voltage_pu':min(row['ac_min_voltage_pu'] for row in result['rows']),'voltage_violation_hours':sum(not row['ac_voltage_within_bounds'] for row in result['rows']),'line_loss_energy_kwh':sum(row['estimated_line_loss_kw'] for row in result['rows'])})
  phase_samples.extend(result['phase_metrics'])
 energy=np.array([row['expected_energy_deficit_kwh'] for row in items]);events=int((energy>1e-6).sum());n=req.samples;p=events/n;z=1.959963984540054
 center=(p+z*z/(2*n))/(1+z*z/n);half=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
 summary={'sample_count':n,'samples_with_shortage':events,'shortage_sample_probability':p,'shortage_probability_wilson95_lower':max(0.,center-half),'shortage_probability_wilson95_upper':min(1.,center+half),'mean_energy_deficit_kwh':float(energy.mean()),'p95_energy_deficit_kwh':float(np.quantile(energy,.95)),'mean_shortage_hour_ratio':float(np.mean([row['loss_of_load_probability'] for row in items]))}
 if source.get('model')=='case33':
  summary.update({'ac_min_voltage_pu':min(row['ac_min_voltage_pu'] for row in items),'mean_voltage_violation_hours':float(np.mean([row['voltage_violation_hours'] for row in items])),'mean_line_loss_energy_kwh':float(np.mean([row['line_loss_energy_kwh'] for row in items]))})
 phase_summary=[]
 for name,group in pd.DataFrame(phase_samples).groupby('stage',sort=False):
  phase_summary.append({'stage':name,'shortage_sample_probability':float((group.maximum_electricity_shortage_mw>1e-9).mean()),'mean_shortage_hour_pct':float(group.electricity_shortage_probability_pct.mean()),'mean_energy_deficit_mwh':float(group.expected_energy_not_served_mwh.mean())})
 result={'id':batch_id,'project_id':source['project_id'],'created':datetime.now().isoformat(timespec='seconds'),'source_run_id':source['id'],'parameters':req.model_dump(),'summary':summary,'phase_summary':phase_summary,'samples':items,'scope':'等权连续故障样本；种子为起始种子加样本序号。仅抽样指定资源故障，源荷与运行阶段固定。Wilson95%区间仅表示有限样本的不确定性，未校准灾害模型或源荷联合分布。'}
 result['operating_condition']=source.get('operating_condition')
 result['model']=source.get('model','aggregate')
 if result['model']=='case33':result['scope']+='IEEE33模型逐时调度并交流潮流复核，仅处理根节点连通区域；电压统计不能代替孤岛动态稳定判别。'
 with closing(batch_db()) as c,c:c.execute('INSERT INTO random_batches VALUES(?,?,?,?)',(batch_id,result['project_id'],result['created'],json.dumps(result,ensure_ascii=False,allow_nan=False)))
 return result

@app.get('/api/random-balance')
def random_batches(project_id:str):
 with closing(batch_db()) as c,c:rows=c.execute('SELECT payload FROM random_batches WHERE project_id=? ORDER BY created DESC',(project_id,)).fetchall()
 return [json.loads(row[0]) for row in rows]

@app.get('/api/random-balance/{batch_id}/csv')
def random_batch_csv(batch_id:str):
 with closing(batch_db()) as c,c:row=c.execute('SELECT payload FROM random_batches WHERE id=?',(batch_id,)).fetchone()
 if not row:raise HTTPException(404,'随机平衡批次不存在')
 return Response(pd.DataFrame(json.loads(row[0])['samples']).to_csv(index=False).encode('utf-8-sig'),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename=random-balance-{batch_id}.csv'})

if (ROOT/'frontend/dist').exists():app.mount('/',StaticFiles(directory=ROOT/'frontend/dist',html=True),name='frontend')
