"""Local projects and immutable fault-scenario snapshots."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import io,json,sqlite3,uuid
import numpy as np
import pandas as pd
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field,ConfigDict,model_validator
from typing import Literal

ROOT=Path(__file__).resolve().parents[1]
router=APIRouter(prefix='/api')
def connection():
 c=sqlite3.connect(ROOT/'data/platform.db')
 c.execute('CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT,revision INTEGER,payload TEXT,updated TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS scenarios(id TEXT PRIMARY KEY,project_id TEXT,payload TEXT,created TEXT)')
 return c
class ProjectInput(BaseModel):
 name:str=Field(min_length=1,max_length=80)
 region:str=Field('',max_length=100)
 kind:Literal['县域级','乡镇级','村级','村镇级']='村镇级'
 state:dict=Field(default_factory=dict)
 expected_revision:int|None=None
 @model_validator(mode='after')
 def size(self):
  if len(json.dumps(self.state,allow_nan=False))>3000000:raise ValueError('工程数据过大')
  if not self.name.strip():raise ValueError('工程名称不能为空')
  return self

def project_record(project_id):
 with closing(connection()) as c,c:r=c.execute('SELECT payload FROM projects WHERE id=?',(project_id,)).fetchone()
 if not r:raise HTTPException(404,'工程不存在')
 return json.loads(r[0])
@router.get('/projects')
def list_projects():
 with closing(connection()) as c,c:return [{'id':r[0],'name':r[1],'revision':r[2],'updated':r[3]} for r in c.execute('SELECT id,name,revision,updated FROM projects ORDER BY updated DESC')]
@router.get('/projects/{project_id}')
def read_project(project_id:str):return project_record(project_id)
@router.post('/projects')
def create_project(req:ProjectInput):
 p={**req.model_dump(exclude={'expected_revision'}),'id':uuid.uuid4().hex,'revision':1,'updated':datetime.now().isoformat(timespec='seconds')}
 with closing(connection()) as c,c:c.execute('INSERT INTO projects VALUES(?,?,?,?,?)',(p['id'],p['name'],p['revision'],json.dumps(p,ensure_ascii=False,allow_nan=False),p['updated']))
 return p
@router.put('/projects/{project_id}')
def save_project(project_id:str,req:ProjectInput):
 with closing(connection()) as c,c:
  c.execute('BEGIN IMMEDIATE')
  r=c.execute('SELECT payload FROM projects WHERE id=?',(project_id,)).fetchone()
  if not r:raise HTTPException(404,'工程不存在')
  old=json.loads(r[0])
  if req.expected_revision!=old['revision']:raise HTTPException(409,'工程已在其他窗口修改，请重新打开后再保存')
  p={**req.model_dump(exclude={'expected_revision'}),'id':project_id,'revision':old['revision']+1,'updated':datetime.now().isoformat(timespec='seconds')}
  c.execute('UPDATE projects SET name=?,revision=?,payload=?,updated=? WHERE id=?',(p['name'],p['revision'],json.dumps(p,ensure_ascii=False,allow_nan=False),p['updated'],project_id))
 return p

@router.get('/network/case33')
def case33():
 base=ROOT/'vendor/topic2/data/case33'
 return {'nodes':pd.read_csv(base/'nodes.csv').to_dict('records'),'lines':pd.read_csv(base/'lines.csv').to_dict('records'),'source':'MATPOWER case33bw；固定联调网络，非示范区实测拓扑'}

class Device(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 device_id:str=Field(min_length=1,max_length=40)
 device_type:Literal['grid_channel','emergency_gen','storage','renewable','transformer']
 rated_kw:float=Field(ge=0,le=100000)
 a_wind:float=Field(.5,gt=0,le=10)
 b_wind:float=Field(25,ge=0,le=100)
 derate_factor:float=Field(.5,ge=0,le=1)
 recovery_factor:float=Field(.8,ge=0,le=1)
class FaultInput(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 project_id:str
 name:str=Field(min_length=1,max_length=80)
 hazard_csv:str=Field(min_length=10,max_length=100000)
 seed:int=Field(42,ge=0,le=2147483647)
 devices:list[Device]=Field(min_length=1,max_length=50)

@router.post('/scenarios/faults')
def generate_faults(req:FaultInput):
 project_record(req.project_id)
 from topic2_remaining_code.fault_probability_model import build_device_state_sequence,FaultModelConfig
 try:
  hazard=pd.read_csv(io.StringIO(req.hazard_csv))
  if list(hazard.columns)!=['timestamp','wind_speed']:raise ValueError('灾害CSV必须包含timestamp,wind_speed两列')
  if not 2<=len(hazard)<=168:raise ValueError('故障场景需2至168小时')
  hazard['timestamp']=pd.to_datetime(hazard.timestamp,errors='raise')
  if hazard.timestamp.isna().any() or not hazard.timestamp.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():raise ValueError('灾害时间必须连续逐小时且无缺失')
  hazard['wind_speed']=pd.to_numeric(hazard.wind_speed,errors='raise')
  if not np.isfinite(hazard.wind_speed).all() or not hazard.wind_speed.between(0,100).all():raise ValueError('风速须为0至100m/s有限值')
  ids=[d.device_id for d in req.devices]
  if len(ids)!=len(set(ids)):raise ValueError('设备编号不能重复')
  states,capacity=build_device_state_sequence(hazard,pd.DataFrame([d.model_dump() for d in req.devices]),FaultModelConfig(random_seed=req.seed))
  result={**req.model_dump(),'id':uuid.uuid4().hex,'created':datetime.now().isoformat(timespec='seconds'),'states':json.loads(states.to_json(orient='records',date_format='iso',force_ascii=False)),'capacity':json.loads(capacity.to_json(orient='records',date_format='iso',force_ascii=False)),'scope':'研究代码逐时独立状态抽样，非连续故障修复模型；脆弱性参数为用户假设，需实测校准'}
  with closing(connection()) as c,c:c.execute('INSERT INTO scenarios VALUES(?,?,?,?)',(result['id'],req.project_id,json.dumps(result,ensure_ascii=False,allow_nan=False),result['created']))
  return result
 except (ValueError,TypeError,KeyError) as e:raise HTTPException(422,str(e))
@router.get('/scenarios')
def list_scenarios(project_id:str):
 with closing(connection()) as c,c:
  rows=c.execute('SELECT payload FROM scenarios WHERE project_id=? ORDER BY created DESC',(project_id,)).fetchall()
 return [{k:d[k] for k in ['id','name','created','seed','scope']} for d in [json.loads(r[0]) for r in rows]]
@router.get('/scenarios/{scenario_id}')
def scenario_record(scenario_id:str):
 with closing(connection()) as c,c:r=c.execute('SELECT payload FROM scenarios WHERE id=?',(scenario_id,)).fetchone()
 if not r:raise HTTPException(404,'场景不存在')
 return json.loads(r[0])
class SourceAnalysisInput(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 project_id:str
 csv:str=Field(min_length=10,max_length=2000000)
 growth:float=Field(.05,ge=-.9,le=5)
 wind_scale:float=Field(1.05,ge=0,le=10)
 pv_scale:float=Field(1.05,ge=0,le=10)
 window:int=Field(36,ge=2,le=168)
 seed:int=Field(42,ge=0,le=2147483647)
@router.post('/source-analysis')
def source_analysis(req:SourceAnalysisInput):
 project_record(req.project_id)
 from data_schema import Chapter2Config,StageScenarioConfig
 from source_load_coupling import compute_source_load_features,score_extreme_windows
 from load_uncertainty_model import forecast_load_stage,build_load_probability_boundary
 from renewable_uncertainty_model import scale_renewable_stage,build_renewable_probability_boundary
 try:
  df=pd.read_csv(io.StringIO(req.csv))
  if list(df.columns)!=['timestamp','load_kw','wind_kw','pv_kw']:raise ValueError('源荷CSV表头不正确')
  if not req.window<=len(df)<=8760:raise ValueError('数据长度必须不小于窗口长度且不超过8760小时')
  df['timestamp']=pd.to_datetime(df.timestamp,errors='raise')
  if df.timestamp.isna().any() or not df.timestamp.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():raise ValueError('时间必须连续逐小时')
  for col in ['load_kw','wind_kw','pv_kw']:
   df[col]=pd.to_numeric(df[col],errors='raise')
   if not np.isfinite(df[col]).all() or (df[col]<0).any():raise ValueError('功率必须有限且非负')
  cfg=Chapter2Config(extreme_window_hours=req.window)
  stage=StageScenarioConfig('用户水平年',req.growth,req.wind_scale,req.pv_scale)
  features=compute_source_load_features(df,cfg)
  windows=score_extreme_windows(features,cfg).head(10)
  from src.chapter3.extreme_generator_adapter import build_extreme_scene
  extreme,hazard,origin=build_extreme_scene(features,windows,{'window_hours':req.window,'random_seed':req.seed})
  load=forecast_load_stage(df,stage,cfg);renewable=scale_renewable_stage(df,stage,cfg)
  projected=pd.DataFrame({'timestamp':df.timestamp,'load_kw':load.forecast_load_kw,'wind_kw':renewable.forecast_wind_kw,'pv_kw':renewable.forecast_pv_kw})
  serialize=lambda frame:json.loads(frame.to_json(orient='records',date_format='iso',force_ascii=False))
  return {'features':serialize(features),'windows':serialize(windows),'extreme_window':{'rows':serialize(extreme),'hazard':serialize(hazard),'origin':origin,'csv':extreme[['timestamp','load_kw','wind_kw','pv_kw']].to_csv(index=False),'seed':req.seed,'scope':'最高评分窗口，沿用原始源荷功率；天气由研究适配器合成，非实测。extreme_probability为评分映射，不是校准的发生概率。'},'load_boundary':serialize(build_load_probability_boundary(df,stage,cfg)),'renewable_boundary':serialize(build_renewable_probability_boundary(df,stage,cfg)),'projected_csv':projected.to_csv(index=False),'parameters':req.model_dump(exclude={'csv'}),'scope':'研究代码简化增长预测、月份小时经验分位数与窗口评分；短样本仅用于联调，未训练深度学习模型'}
 except (ValueError,TypeError,KeyError) as e:raise HTTPException(422,str(e))
class EmbedResources(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 storage_power_kw:float=Field(500,ge=0,le=100000)
 emergency_gen_kw:float=Field(300,ge=0,le=100000)
 grid_channel_kw:float=Field(0,ge=0,le=100000)

class EmbedInput(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 project_id:str
 background_csv:str=Field(min_length=10,max_length=2000000)
 event_csv:str=Field(min_length=10,max_length=2000000)
 start_hour:int=Field(0,ge=0,le=8759)
 smooth:bool=False
 ramp_hours:int=Field(2,ge=1,le=24)
 scenario_id:str|None=None
 resource_capacities:EmbedResources=Field(default_factory=EmbedResources)

def production_db():
 c=connection();c.execute('CREATE TABLE IF NOT EXISTS production_sequences(id TEXT PRIMARY KEY,project_id TEXT,created TEXT,payload TEXT)');return c

@router.post('/production-sequences')
def embed_sequence(req:EmbedInput):
 project=project_record(req.project_id)
 from topic2_remaining_code.annual_sequence_embedder import embed_extreme_condition
 def parse(csv,label):
  frame=pd.read_csv(io.StringIO(csv))
  if list(frame.columns)!=['timestamp','load_kw','wind_kw','pv_kw']:raise ValueError(label+'表头需为timestamp,load_kw,wind_kw,pv_kw')
  if not 2<=len(frame)<=8760:raise ValueError(label+'需2至8760小时')
  frame.timestamp=pd.to_datetime(frame.timestamp,errors='raise')
  if frame.timestamp.isna().any() or not frame.timestamp.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():raise ValueError(label+'时间须连续逐小时')
  for col in ['load_kw','wind_kw','pv_kw']:
   frame[col]=pd.to_numeric(frame[col],errors='raise')
   if not np.isfinite(frame[col]).all() or (frame[col]<0).any():raise ValueError(label+'功率须有限且非负')
  return frame
 try:
  background=parse(req.background_csv,'背景序列');event=parse(req.event_csv,'事件序列')
  if req.start_hour+len(event)>len(background):raise ValueError('事件嵌入区间超出背景序列')
  embedded_scenario=None;coupled_event=None
  if req.scenario_id:
   from topic2_remaining_code.coupled_condition_builder import build_coupled_condition
   source_scenario=scenario_record(req.scenario_id)
   if source_scenario['project_id']!=req.project_id:raise ValueError('故障场景须属于当前工程')
   capacity=pd.DataFrame(source_scenario['capacity']);capacity.timestamp=pd.to_datetime(capacity.timestamp)
   if not capacity.timestamp.reset_index(drop=True).equals(event.timestamp.reset_index(drop=True)):raise ValueError('事件源荷与故障场景时间轴必须完全一致')
   original_columns=[col for col in capacity if col!='timestamp']
   defaults={'available_kw_storage':req.resource_capacities.storage_power_kw,'available_kw_emergency_gen':req.resource_capacities.emergency_gen_kw,'available_kw_grid_channel':req.resource_capacities.grid_channel_kw,'available_kw_transformer':req.resource_capacities.grid_channel_kw,'available_kw_line':req.resource_capacities.grid_channel_kw}
   full_capacity=capacity.copy()
   for col,default in defaults.items():
    if col not in full_capacity:full_capacity[col]=default
   if 'available_kw_renewable' not in full_capacity:full_capacity['available_kw_renewable']=event.wind_kw+event.pv_kw
   coupled_event=build_coupled_condition(event,full_capacity)
   embedded_capacity=pd.DataFrame({'timestamp':background.timestamp})
   for col in original_columns:
    if col not in defaults and col!='available_kw_renewable':raise ValueError('不支持嵌入容量字段：'+col)
    embedded_capacity[col]=background.wind_kw+background.pv_kw if col=='available_kw_renewable' else defaults[col]
    embedded_capacity.loc[req.start_hour:req.start_hour+len(event)-1,col]=capacity[col].to_numpy()
   delta=background.timestamp.iloc[req.start_hour]-event.timestamp.iloc[0]
   states=pd.DataFrame(source_scenario['states'])
   if not states.empty:states['timestamp']=pd.to_datetime(states.timestamp)+delta
   serialize=lambda frame:json.loads(frame.to_json(orient='records',date_format='iso',force_ascii=False))
   embedded_scenario={'id':uuid.uuid4().hex,'project_id':req.project_id,'name':'嵌入故障-'+source_scenario['name'],'created':datetime.now().isoformat(timespec='seconds'),'seed':source_scenario['seed'],'source_scenario_id':req.scenario_id,'states':serialize(states),'capacity':serialize(embedded_capacity),'scope':'嵌入事件故障容量；事件外按生成时资源容量恢复，事件内沿用源场景上限。状态表只列事件设备，容量覆盖完整背景；不改变支路故障或假设负荷不可达。'}
  sequence=embed_extreme_condition(background,coupled_event if coupled_event is not None else event,str(background.timestamp.iloc[req.start_hour]),smooth=req.smooth,ramp_hours=req.ramp_hours)
  # Keep only source/load in CSV. Explicit sampled capacity columns travel in
  # a separate scenario; helper-generated zero defaults must not leak to dispatch.
  result={'id':uuid.uuid4().hex,'project_id':req.project_id,'project_revision':project['revision'],'created':datetime.now().isoformat(timespec='seconds'),'parameters':req.model_dump(exclude={'background_csv','event_csv'}),'input_background_csv':req.background_csv,'input_event_csv':req.event_csv,'csv':sequence[['timestamp','load_kw','wind_kw','pv_kw']].to_csv(index=False),'rows':json.loads(sequence[['timestamp','load_kw','wind_kw','pv_kw','is_extreme_condition']].to_json(orient='records',date_format='iso')),'event_start':str(background.timestamp.iloc[req.start_hour]),'event_end':str(background.timestamp.iloc[req.start_hour+len(event)-1]),'scope':'课题2极端工况嵌入函数，仅使用源荷列与事件标记；按背景时间轴重定位事件。未嵌入设备故障和可达性，不自动赋予事件概率。边界平滑开启时修改相邻时段源荷。'}
  if embedded_scenario:
   result['embedded_scenario_id']=embedded_scenario['id']
   result['coupled_event_rows']=serialize(coupled_event)
   result['scope']='调用课题2源荷故障耦合与事件嵌入函数，保存独立的完整背景容量场景。事件源荷与故障容量同步重定位；容量不平滑。事件外按生成时资源额定容量恢复；负荷可达性假定为1，未生成联合概率。'
  with closing(production_db()) as c,c:
   if embedded_scenario:c.execute('INSERT INTO scenarios VALUES(?,?,?,?)',(embedded_scenario['id'],req.project_id,json.dumps(embedded_scenario,ensure_ascii=False,allow_nan=False),embedded_scenario['created']))
   c.execute('INSERT INTO production_sequences VALUES(?,?,?,?)',(result['id'],req.project_id,result['created'],json.dumps(result,ensure_ascii=False,allow_nan=False)))
  return result
 except (ValueError,TypeError,KeyError) as e:raise HTTPException(422,str(e))

@router.get('/production-sequences')
def production_sequences(project_id:str):
 with closing(production_db()) as c,c:rows=c.execute('SELECT payload FROM production_sequences WHERE project_id=? ORDER BY created DESC',(project_id,)).fetchall()
 return [json.loads(row[0]) for row in rows]

def production_sequence_record(sequence_id:str):
 with closing(production_db()) as c,c:row=c.execute('SELECT payload FROM production_sequences WHERE id=?',(sequence_id,)).fetchone()
 if not row:raise HTTPException(404,'生产序列不存在')
 return json.loads(row[0])

class SequentialInput(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 project_id:str
 name:str=Field(min_length=1,max_length=80)
 csv:str=Field(min_length=10,max_length=2000000)
 resource:Literal['grid_channel','emergency_gen','storage','transformer','renewable']
 rated_kw:float=Field(4000,ge=0,le=100000)
 rate_per_hour:float=Field(.02,ge=0,le=10)
 repair_hours:int=Field(6,ge=1,le=168)
 seed:int=Field(42,ge=0,le=2147483647)
@router.post('/scenarios/sequential')
def sequential_scenario(req:SequentialInput):
 project_record(req.project_id)
 from src.chapter3.sequential_resource_states import simulate_resource_states
 from src.chapter4.case33_network_balance import NetworkBalanceConfig
 try:
  df=pd.read_csv(io.StringIO(req.csv))
  if list(df.columns)!=['timestamp','load_kw','wind_kw','pv_kw']:raise ValueError('源荷CSV字段不正确')
  if not 2<=len(df)<=168:raise ValueError('连续故障场景需2至168小时')
  df.timestamp=pd.to_datetime(df.timestamp,errors='raise')
  if df.timestamp.isna().any() or not df.timestamp.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():raise ValueError('时间必须连续逐小时')
  for col in ['load_kw','wind_kw','pv_kw']:
   df[col]=pd.to_numeric(df[col],errors='raise')
   if not np.isfinite(df[col]).all() or (df[col]<0).any():raise ValueError('源荷功率须有限非负')
  df['failure_rate_per_hour_'+req.resource]=req.rate_per_hour
  df['repair_hours_'+req.resource]=req.repair_hours
  df['available_kw_'+req.resource]=req.rated_kw
  cfg=NetworkBalanceConfig(grid_limit_kw=req.rated_kw,emergency_limit_kw=req.rated_kw,storage_power_kw=req.rated_kw)
  sequence,failures=simulate_resource_states(df,cfg,req.seed)
  column='available_kw_'+req.resource
  capacity=sequence[['timestamp',column]]
  states=pd.DataFrame({'timestamp':df.timestamp,'device_id':req.resource,'fault_prob':1-np.exp(-req.rate_per_hour),'state':np.where(sequence[column]>0,'normal','failed'),'available_kw':sequence[column]})
  # Zero capacity alone does not imply an equipment failure.
  outage=np.zeros(len(df),dtype=bool)
  for event in failures.to_dict('records'):
   start=int(np.flatnonzero(df.timestamp.eq(event['timestamp']))[0])
   outage[start:start+int(event['repair_hours'])]=True
  states['state']=np.where(outage,'failed','normal')
  serialize=lambda frame:json.loads(frame.to_json(orient='records',date_format='iso',force_ascii=False))
  result={**req.model_dump(exclude={'csv'}),'id':uuid.uuid4().hex,'created':datetime.now().isoformat(timespec='seconds'),'states':serialize(states),'capacity':serialize(capacity),'failures':serialize(failures),'scope':'课题2连续故障修复模型；输入为每小时失效率λ，转移概率1-exp(-λ)，修复期间保持故障。参数为用户假设，非风速脆弱性概率'}
  with closing(connection()) as c,c:c.execute('INSERT INTO scenarios VALUES(?,?,?,?)',(result['id'],req.project_id,json.dumps(result,ensure_ascii=False,allow_nan=False),result['created']))
  return result
 except (ValueError,TypeError,KeyError) as e:raise HTTPException(422,str(e))
