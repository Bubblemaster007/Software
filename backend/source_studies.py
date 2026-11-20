"""Versioned source/load studies using the original topic 2 implementations."""
from contextlib import closing
from datetime import datetime
import hashlib,io,json,sqlite3,uuid
from typing import Literal
import numpy as np
import pandas as pd
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field,model_validator
from backend.workspace import ROOT,project_record

router=APIRouter(prefix='/api/source-studies',tags=['源荷多水平年研究'])
def connection():
 c=sqlite3.connect(ROOT/'data/platform.db')
 c.execute('CREATE TABLE IF NOT EXISTS source_studies(id TEXT PRIMARY KEY,project_id TEXT,created TEXT,payload TEXT)')
 return c

class Horizon(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 name:str=Field(min_length=1,max_length=30)
 year:int=Field(ge=2000,le=2100)
 growth:float=Field(.05,ge=-.9,le=5)
 wind_scale:float=Field(1.05,ge=0,le=10)
 pv_scale:float=Field(1.05,ge=0,le=10)
 noise:float=Field(.03,ge=0,le=.5)
class StudyInput(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 project_id:str
 csv:str=Field(min_length=10,max_length=2000000)
 seed:int=Field(42,ge=0,le=2147483647)
 horizons:list[Horizon]=Field(min_length=1,max_length=3)
 critical_ratio:float=Field(.2,ge=0,le=1)
 important_ratio:float=Field(.35,ge=0,le=1)
 @model_validator(mode='after')
 def validate_horizons(self):
  if self.critical_ratio+self.important_ratio>1:raise ValueError('关键和重要负荷占比之和不能超过1')
  names=[h.name.strip() for h in self.horizons]
  if any(not n for n in names) or len(names)!=len(set(names)):raise ValueError('水平年名称不能为空或重复')
  if len({h.year for h in self.horizons})!=len(self.horizons):raise ValueError('水平年年份不能重复')
  return self

def read_study(study_id):
 with closing(connection()) as c:row=c.execute('SELECT payload FROM source_studies WHERE id=?',(study_id,)).fetchone()
 if not row:raise HTTPException(404,'源荷研究不存在')
 return json.loads(row[0])
def summary(record):
 return {k:v for k,v in record.items() if k not in ('input_csv','artifacts')}

@router.post('')
def generate(req:StudyInput):
 project=project_record(req.project_id)
 from annual_background_generator import generate_annual_background
 from data_schema import Chapter2Config,StageScenarioConfig
 from load_uncertainty_model import multi_scale_load_decompose,forecast_load_stage,build_classified_load_boundary,build_load_probability_boundary
 from renewable_uncertainty_model import build_renewable_probability_boundary
 try:
  frame=pd.read_csv(io.StringIO(req.csv));cols=['timestamp','load_kw','wind_kw','pv_kw']
  if list(frame.columns)!=cols:raise ValueError('表头需为timestamp,load_kw,wind_kw,pv_kw')
  if not 2<=len(frame)<=8760:raise ValueError('历史时序需2至8760小时')
  frame.timestamp=pd.to_datetime(frame.timestamp,errors='raise')
  if frame.timestamp.isna().any() or not frame.timestamp.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():raise ValueError('历史时间须连续逐小时')
  for col in cols[1:]:
   frame[col]=pd.to_numeric(frame[col],errors='raise')
   if not np.isfinite(frame[col]).all() or frame[col].lt(0).any():raise ValueError('功率必须为非负有限值')
  cfg=Chapter2Config(random_seed=req.seed)
  artifacts={'decomposition':multi_scale_load_decompose(frame,cfg).to_csv(index=False)};horizons=[]
  for index,h in enumerate(req.horizons):
   stage=StageScenarioConfig(h.name.strip(),h.growth,h.wind_scale,h.pv_scale,h.noise)
   annual=generate_annual_background(frame,stage,cfg,h.year)
   forecast=forecast_load_stage(frame,stage,cfg)
   classified=build_classified_load_boundary(forecast,req.critical_ratio,req.important_ratio,1-req.critical_ratio-req.important_ratio)
   for key,table in {'annual':annual[cols],'classified':classified,'load_boundary':build_load_probability_boundary(frame,stage,cfg),'renewable_boundary':build_renewable_probability_boundary(frame,stage,cfg)}.items():
    artifacts[f'{index}_{key}']=table.to_csv(index=False)
   horizons.append({**h.model_dump(),'hours':len(annual),'first_timestamp':str(annual.timestamp.iloc[0]),'last_timestamp':str(annual.timestamp.iloc[-1]),'load_energy_kwh':float(annual.load_kw.sum()),'peak_load_kw':float(annual.load_kw.max()),'preview':json.loads(annual[cols].head(24).to_json(orient='records',date_format='iso'))})
  record={'id':uuid.uuid4().hex,'project_id':req.project_id,'project_revision':project['revision'],'created':datetime.now().isoformat(timespec='seconds'),'parameters':req.model_dump(exclude={'csv','project_id'}),'input_csv':req.csv,'input_sha256':hashlib.sha256(req.csv.encode()).hexdigest(),'algorithm':'topic2.original.source-study.v1','horizons':horizons,'artifacts':artifacts,'scope':'原代码滚动均值分解、经验分位边界、月份小时独立重采样；非VMD或深度学习模型，非校准风险概率。缺少历史月份时回退全样本。每水平年固定8760小时，闰年截断末24小时。'}
  with closing(connection()) as c,c:c.execute('INSERT INTO source_studies VALUES(?,?,?,?)',(record['id'],req.project_id,record['created'],json.dumps(record,ensure_ascii=False,allow_nan=False)))
  return summary(record)
 except (ValueError,TypeError,KeyError) as e:raise HTTPException(422,str(e))

@router.get('')
def list_studies(project_id:str):
 project_record(project_id)
 with closing(connection()) as c:rows=c.execute('SELECT payload FROM source_studies WHERE project_id=? ORDER BY created DESC,rowid DESC',(project_id,)).fetchall()
 return [summary(json.loads(row[0])) for row in rows]

@router.get('/{study_id}/csv')
def download(study_id:str,kind:Literal['annual','classified','load_boundary','renewable_boundary','decomposition']='annual',horizon:int=0):
 record=read_study(study_id)
 key='decomposition' if kind=='decomposition' else f'{horizon}_{kind}'
 if key not in record['artifacts']:raise HTTPException(422,'水平年索引不存在')
 return Response('\ufeff'+record['artifacts'][key],media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="source-{study_id[:8]}-{key}.csv"'})
