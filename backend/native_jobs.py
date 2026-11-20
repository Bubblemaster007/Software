"""Durable, isolated execution of the original topic 2 network pipeline."""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import hashlib,io,json,os,sqlite3,subprocess,sys,uuid,zipfile
import numpy as np
import pandas as pd
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response,FileResponse
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from backend.workspace import ROOT,project_record

router=APIRouter(prefix='/api/native-jobs',tags=['课题2原生年度流水线'])
JOBS=ROOT/'data/native_jobs'
def connection():
 c=sqlite3.connect(ROOT/'data/platform.db');c.execute('CREATE TABLE IF NOT EXISTS native_jobs(id TEXT PRIMARY KEY,project_id TEXT,created TEXT,payload TEXT)');return c
from backend.process_identity import process_identity

def read_job(id):
 with closing(connection()) as c:row=c.execute('SELECT payload FROM native_jobs WHERE id=?',(id,)).fetchone()
 if not row:raise HTTPException(404,'原生任务不存在')
 record=json.loads(row[0])
 if record['status'] in ('queued','running') and record.get('process_identity'):
  if process_identity(record['pid'])!=record['process_identity']:
   return update_job(id,status='interrupted',error='后台计算进程已退出，未保存成功结论；可新建任务重跑')
 return record
def update_job(id,**fields):
 with closing(connection()) as c,c:
  c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT payload FROM native_jobs WHERE id=?',(id,)).fetchone()
  if not row:raise ValueError('原生任务不存在')
  record=json.loads(row[0]);record.update(fields);c.execute('UPDATE native_jobs SET payload=? WHERE id=?',(json.dumps(record,ensure_ascii=False,allow_nan=False),id));return record
def summary(record):return {k:v for k,v in record.items() if k not in ('csv','config')}

class NativeInput(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 project_id:str
 project_revision:int=Field(ge=1)
 csv:str=Field(min_length=10,max_length=8000000)
 parameters:dict=Field(default_factory=dict)
 network_parameters:dict=Field(default_factory=dict)
 branch_limit_kw:float=Field(5000,gt=0,le=100000)
 seed:int=Field(42,ge=0,le=2147483600)
 event_samples:int=Field(2,ge=1,le=20)
def parse_input(csv):
 frame=pd.read_csv(io.StringIO(csv));required=['timestamp','load_kw','wind_kw','pv_kw','event_id','wind_speed']
 resources=['grid_channel','transformer','emergency_gen','storage','renewable']
 optional=['random_sequence_id','sequence_weight']+[f'{prefix}{r}' for prefix in ['available_kw_','failure_rate_per_hour_','repair_hours_'] for r in resources]
 if not set(required)<=set(frame):raise ValueError('原生CSV须含timestamp,load_kw,wind_kw,pv_kw,event_id,wind_speed')
 if set(frame)-set(required+optional):raise ValueError('包含不支持的字段：'+','.join(sorted(set(frame)-set(required+optional))))
 if not 2<=len(frame)<=8760:raise ValueError('原生流水线支持2至8760小时')
 frame.timestamp=pd.to_datetime(frame.timestamp,errors='raise')
 if frame.timestamp.isna().any() or not frame.timestamp.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():raise ValueError('时序须连续逐小时')
 for col in frame:
  if col in ('timestamp','random_sequence_id'):continue
  frame[col]=pd.to_numeric(frame[col],errors='raise')
  if not np.isfinite(frame[col]).all():raise ValueError(col+'必须为有限值')
  if col=='event_id':
   if frame[col].lt(-1).any() or frame[col].ne(np.floor(frame[col])).any():raise ValueError('event_id须为-1或非负整数')
  elif frame[col].lt(0).any():raise ValueError(col+'不能为负数')
 if frame.wind_speed.gt(100).any():raise ValueError('风速不能超过100m/s')
 for resource in resources:
  rate='failure_rate_per_hour_'+resource;repair='repair_hours_'+resource
  if (rate in frame)!=(repair in frame):raise ValueError('失效率和修复时长必须成对提供：'+resource)
  if rate in frame and (frame[rate].gt(10).any() or frame[repair].lt(1).any() or frame[repair].gt(8760).any() or frame[repair].ne(np.floor(frame[repair])).any()):raise ValueError('失效率须在0至10，修复时长须为1至8760整数小时')
 # Native stage aggregation is defined only for contiguous 36-hour events.
 for event,group in frame[frame.event_id.ge(0)].groupby('event_id'):
  indices=group.index.to_numpy()
  if len(indices)!=36 or not np.array_equal(indices,np.arange(indices[0],indices[0]+36)):raise ValueError(f'事件{event:g}必须是连续36小时；常规时段使用-1')
 if 'sequence_weight' in frame and not frame.sequence_weight.eq(1).all():raise ValueError('单任务为一条轨迹，sequence_weight必须为1；多轨迹加权另行集成')
 if 'random_sequence_id' in frame and (frame.random_sequence_id.isna().any() or frame.random_sequence_id.nunique()!=1):raise ValueError('单任务只接收一个非空序列编号')
 return frame

def launch(id):
 folder=JOBS/id;folder.mkdir(parents=True,exist_ok=True)
 with (folder/'worker.log').open('ab') as stream:
  worker=subprocess.Popen([sys.executable,'-m','backend.native_worker',id],cwd=ROOT,stdout=stream,stderr=stream,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
 # Worker also records its identity; do not overwrite completed state on a fast run.
 update_job(id,pid=worker.pid,process_identity=process_identity(worker.pid))

@router.post('')
def create(req:NativeInput):
 project=project_record(req.project_id)
 if project['revision']!=req.project_revision:raise HTTPException(409,'工程版本已变化，请重新打开工程')
 from backend.app import Parameters,NetworkParameters
 try:
  parse_input(req.csv)
  params=Parameters(**req.parameters).model_dump();network=NetworkParameters(**req.network_parameters).model_dump()
 except (ValueError,TypeError,KeyError,ValidationError) as e:raise HTTPException(422,str(e))
 config={'topology':{'type':'case33','case33_dir':str(ROOT/'vendor/topic2/data/case33')},'chapter4':params,'case33_network':{**network,'branch_limit_kw':req.branch_limit_kw},'paper_method':{'seed':req.seed,'event_samples':req.event_samples},'planning':{'max_mobile_units':0},'random_seed':req.seed}
 record={'id':uuid.uuid4().hex,'project_id':req.project_id,'project_revision':req.project_revision,'created':datetime.now().isoformat(timespec='seconds'),'status':'queued','algorithm':'topic2.original.native-downstream.v1','csv':req.csv,'config':config,'input_sha256':hashlib.sha256(req.csv.encode()).hexdigest(),'seed':req.seed,'event_samples':req.event_samples,'hours':len(parse_input(req.csv)),'scope':'原生论文下游入口；不生成或认证SC-RCRB。支路失效率沿用原代码风速条件测试公式，事件阶段固定6/6/12/12小时；不等于实测风险。规划仍为简化枚举。'}
 # Reconcile dead workers before enforcing the one-worker limit.
 with closing(connection()) as c:ids=[row[0] for row in c.execute('SELECT id FROM native_jobs')]
 for id in ids:read_job(id)
 with closing(connection()) as c,c:
  c.execute('BEGIN IMMEDIATE')
  if any(json.loads(row[0])['status'] in ('queued','running') for row in c.execute('SELECT payload FROM native_jobs')):raise HTTPException(409,'已有原生后台任务运行，请等待完成')
  c.execute('INSERT INTO native_jobs VALUES(?,?,?,?)',(record['id'],req.project_id,record['created'],json.dumps(record,ensure_ascii=False,allow_nan=False)))
 try:launch(record['id'])
 except OSError as e:update_job(record['id'],status='failed',error=str(e));raise HTTPException(500,'后台任务启动失败')
 return summary(read_job(record['id']))
@router.get('')
def list_jobs(project_id:str):
 project_record(project_id)
 with closing(connection()) as c:ids=[r[0] for r in c.execute('SELECT id FROM native_jobs WHERE project_id=? ORDER BY created DESC,rowid DESC',(project_id,))]
 return [summary(read_job(id)) for id in ids]
@router.get('/{id}')
def detail(id:str):return summary(read_job(id))
@router.get('/{id}/input')
def frozen_input(id:str):return read_job(id)
@router.get('/{id}/files')
def files(id:str):
 read_job(id);folder=JOBS/id/'outputs'
 return [{'path':p.relative_to(folder).as_posix(),'bytes':p.stat().st_size} for p in sorted(folder.rglob('*')) if p.is_file()]
@router.get('/{id}/file')
def download(id:str,path:str):
 read_job(id);folder=(JOBS/id/'outputs').resolve();target=(folder/path).resolve()
 if not target.is_relative_to(folder) or not target.is_file():raise HTTPException(404,'产物文件不存在')
 return FileResponse(target,filename=target.name)
@router.get('/{id}/archive')
def archive(id:str):
 record=read_job(id)
 if record['status'] in ('queued','running'):raise HTTPException(409,'任务仍在计算，请等待产物写入完成')
 folder=JOBS/id;out=io.BytesIO()
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr('input.json',json.dumps(record,ensure_ascii=False,indent=2))
  for p in folder.rglob('*'):
   if p.is_file():z.write(p,p.relative_to(folder).as_posix())
 return Response(out.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="native-{id[:8]}.zip"'})
