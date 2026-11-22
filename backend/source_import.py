"""Normalize external source/load files without repairing physical observations."""
import csv
import hashlib
import io
import re
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router=APIRouter(prefix='/api/source-import')
ALIASES={
 'timestamp':('timestamp','time','datetime','时间','日期时间'),
 'load_kw':('load_kw','load','负荷','负荷kw','负荷(kw)','负荷/kw'),
 'wind_kw':('wind_kw','wind_power','风电','风电kw','风电(kw)','风电/kw'),
 'pv_kw':('pv_kw','solar_power','pv_power','光伏','光伏kw','光伏(kw)','光伏/kw'),
}
def key(value):return re.sub(r'\s+','',value.lstrip('\ufeff').strip().lower()).replace('（','(').replace('）',')')

class ImportInput(BaseModel):
 text:str=Field(min_length=1,max_length=6000000)
 filename:str=Field(default='外部历史数据.csv',max_length=255)

def normalize(text,filename='外部历史数据.csv'):
 lines=text.lstrip('\ufeff').splitlines()
 if not lines:raise ValueError('文件为空')
 first=next((s for s in lines if s.strip()),'')
 delimiter=max((',', '\t',';'),key=lambda d:first.count(d))
 records=list(csv.reader(io.StringIO(text.lstrip('\ufeff')),delimiter=delimiter,strict=True))
 records=[r for r in records if any(v.strip() for v in r)]
 if not records:raise ValueError('文件为空')
 headers=records[0];indices={}
 for field,aliases in ALIASES.items():
  found=[i for i,h in enumerate(headers) if key(h) in aliases]
  if len(found)!=1:raise ValueError(f'{field}列'+('存在多个候选，不能自动判断' if found else '缺失；支持timestamp/time、load/load_kw、wind_power/wind_kw、solar_power/pv_kw'))
  indices[field]=found[0]
 if not 2<=len(records)-1<=8760:raise ValueError(f'读取到{len(records)-1}行；请选择连续2–8760小时，闰年8784小时请明确选择时段，不自动删行')
 output=[];times=[]
 for rownum,row in enumerate(records[1:],2):
  if len(row)!=len(headers):raise ValueError(f'第{rownum}行列数与表头不一致')
  value=row[indices['timestamp']].strip()
  if not re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}',value):raise ValueError(f'第{rownum}行时间格式无效；需明确年月日及小时，不接受有歧义日期或Excel序号')
  try:time=pd.Timestamp(value)
  except (ValueError,TypeError):raise ValueError(f'第{rownum}行日期无效')
  if pd.isna(time) or time.tzinfo is not None:raise ValueError(f'第{rownum}行时间为空或含时区；请先明确本地时间基准')
  if times and time-times[-1]!=pd.Timedelta(hours=1):raise ValueError(f'第{rownum}行与上一行不相差1小时，可能存在缺失、重复或倒序；不自动补点')
  values=[]
  for field in ('load_kw','wind_kw','pv_kw'):
   raw=row[indices[field]].strip()
   try:number=float(raw)
   except ValueError:raise ValueError(f'第{rownum}行{field}不是数值或为空')
   if not np.isfinite(number) or number<0:raise ValueError(f'第{rownum}行{field}须为有限非负数')
   values.append(number)
  times.append(time);output.append([time.isoformat(sep=' '),*values])
 stream=io.StringIO();writer=csv.writer(stream,lineterminator='\n');writer.writerow(indices.keys());writer.writerows(output)
 result=stream.getvalue();extras=[h for i,h in enumerate(headers) if i not in indices.values()]
 return {'csv':result,'rows':len(output),'source_import':{'name':filename,'file':filename,'kind':'external','sha256':hashlib.sha256(text.encode()).hexdigest(),'input_sha256':hashlib.sha256(result.encode()).hexdigest(),'hours':len(output),'first_timestamp':str(times[0]),'last_timestamp':str(times[-1]),'output_unit':'kW','column_mapping':{k:headers[i] for k,i in indices.items()},'extra_columns':extras,'notes':['只映射列名、列顺序、分隔符和日期写法；未缩放功率、补值、排序或删除时段。','无单位的load/wind_power/solar_power按当前项目约定kW读取；MW须先明确转换。', '附加气象/质量列未作为四列平衡输入；原始文件请保留。']}}

@router.post('/preview')
def preview(req:ImportInput):
 try:return normalize(req.text,req.filename)
 except (ValueError,csv.Error) as e:raise HTTPException(422,str(e))
