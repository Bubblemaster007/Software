"""Read original collection files without changing their XML or units."""
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import hashlib, io
import pandas as pd
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'SourceData'
router=APIRouter(prefix='/api/alashankou')
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
def files():
 # macOS archive metadata (._*) is not a source document and must not appear
 # as an import/download choice in the engineering workspace.
 return sorted(p for p in BASE.rglob('*') if p.is_file() and not p.name.startswith('._') and ('阿拉山口' in p.name or p.name=='典型日曲线.doc'))
def key(p):return hashlib.sha256(str(p.relative_to(BASE)).encode()).hexdigest()[:16]
def read_rows(p):
 with ZipFile(p) as z:
  strings=[]
  if 'xl/sharedStrings.xml' in z.namelist():
   strings=[''.join(si.itertext()) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)]
  rows=[]
  for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//m:sheetData/m:row',NS):
   values={}
   for cell in row:
    v=cell.find('m:v',NS);text=v.text if v is not None else ''.join(cell.itertext())
    if cell.get('t')=='s':text=strings[int(text)]
    values[''.join(c for c in cell.get('r') if c.isalpha())]=text
   rows.append(values)
  return rows
@router.get('')
def catalog():
 result=[]
 for p in files():
  kind='load' if '典型负荷曲线' in p.name and p.suffix=='.xlsx' else 'wind_monthly' if '风场' in p.name and p.suffix=='.xlsx' else 'reference'
  result.append({'id':key(p),'name':p.name,'path':str(p.relative_to(BASE)),'kind':kind,'bytes':p.stat().st_size})
 return {'files':result,'notes':['典型负荷为5分钟总有功，原表未标功率单位；应用前请选择并核实单位。','风场为月发电量，不能作为逐小时风电；装机列标题为兆瓦但数值疑似千瓦，保留原值待核实。','PDF/DWG/DOC为原始参考资料；未自动推断实际线路阻抗和连接关系。']}
def find(file_id):
 p=next((p for p in files() if key(p)==file_id),None)
 if p is None:raise HTTPException(404,'原始资料不存在')
 return p
@router.get('/{file_id}/file')
def download(file_id:str):
 p=find(file_id);return FileResponse(p,filename=p.name)
@router.get('/{file_id}/preview')
def preview(file_id:str,unit:str=Query('MW',pattern='^(MW|kW)$')):
 p=find(file_id)
 if p.suffix!='.xlsx':raise HTTPException(422,'请选择典型负荷或风场Excel')
 try:
  rows=read_rows(p)
  if '典型负荷曲线' not in p.name:return {'kind':'wind_monthly','rows':rows,'note':'月发电量单位万千瓦时；保留装机原值，单位矛盾待核实，不生成逐时出力。'}
  df=pd.DataFrame([{'timestamp':r.get('B'),'value':r.get('C')} for r in rows[2:]])
  df.timestamp=pd.to_datetime(df.timestamp,errors='raise');df.value=pd.to_numeric(df.value,errors='raise')
  if not np.isfinite(df.value).all() or (df.value<0).any():raise ValueError('原始负荷包含非法数值')
  if not df.timestamp.diff().iloc[1:].eq(pd.Timedelta(minutes=5)).all():raise ValueError('原始5分钟时序不连续')
  start=df.timestamp.iloc[0].normalize()
  day=df[(df.timestamp>=start)&(df.timestamp<start+pd.Timedelta(days=1))]
  if len(day)!=288:raise ValueError('典型日必须包含完整288个5分钟样本')
  hourly=day.set_index('timestamp').value.resample('h').mean().mul(1000 if unit=='MW' else 1).rename('load_kw').to_frame()
  hourly['wind_kw']=0;hourly['pv_kw']=0
  csv=hourly.to_csv(index=True)
  provenance={'file':str(p.relative_to(BASE)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'unit_assumption':unit,'method':'每小时12个5分钟采样点算术平均；次日零点为边界点，不计入当日；风光缺测填0，仅代表未配置出力。','raw_samples':len(df),'hours':len(hourly)}
  return {'kind':'load','csv':csv,'rows':hourly.reset_index().to_dict('records'),'source_import':provenance}
 except (ValueError,KeyError) as e:raise HTTPException(422,str(e))
