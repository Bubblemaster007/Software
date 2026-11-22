"""Explicit local historical datasets; no synthetic fallback or implicit application."""
from pathlib import Path
import hashlib
import io
import json
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from backend.network_data import Network

ROOT = Path(__file__).resolve().parents[1]
ALASH = ROOT/'阿拉山口_重建风光荷与拓扑_20261121'/'阿拉山口_重建风光荷与拓扑_20261121'
EXTREME = ROOT.parent/'ExtremeScene'/'Paper'/'data'/'raw'/'ausgrid_annual'
router = APIRouter(prefix='/api/input-datasets')
ALASH_NOTES = ['负荷为站净有功小时需求代理，计量边界未独立核实；补值不是实测需求。',
 '风电、光伏含重建成分；供区风电为区域重建风电的1%，光伏5000kW为情景假设。',
 '2025风况使用2022年供体，不作为独立实测联合尾部样本。',
 '配套拓扑为51节点分段骨架，阻抗、容量和径向开关状态含未校准假设。']

def entries():
 result = {}
 for year in (2023, 2024, 2025):
  result[f'alashankou-{year}'] = (ALASH/'01_风光荷数据'/f'风光荷_{year}.csv', f'阿拉山口 {year} · 历史负荷与重建风光', 'alashankou')
 for area in ('muswellbrook','singleton','cessnock_south'):
  for year in (2019,2020,2021,2022):
   p=EXTREME/area/f'{area}_wind_solar_load_weather_hourly_8760_FY{year}.csv'
   if p.is_file():result[f'extreme-{area}-{year}']=(p,f'ExtremeScene {area} FY{year} · IEEE33示例','extreme')
 return result

@router.get('')
def catalog():
 return {'datasets':[{'id':key,'name':name,'kind':kind,'available':p.is_file()} for key,(p,name,kind) in entries().items()],
         'notes':ALASH_NOTES,'maximum_input_hours':8760}

def alash_network():
 folder=ALASH/'02_拓扑数据'
 nodes=pd.read_csv(folder/'nodes.csv').fillna('')
 lines=pd.read_csv(folder/'lines.csv').fillna('')
 # limit_kw is an active-power assumption; do not reinterpret it as a measured kVA rating.
 return Network.model_validate({'name':'阿拉山口51节点分段骨架','base_voltage_kv':10,
  'source':'20261121资料包；逻辑分段骨架，非现场完整拓扑；P/Q分配、R/X、6000kW段容量及开关状态均含假设',
  'nodes':[{k:r[k] for k in ('node','type','name','pd_kw','qd_kvar','vm_init_pu')} for r in nodes.to_dict('records')],
  'lines':[{k:r[k] for k in ('line','name','from_node','to_node','r_ohm','x_ohm','status')} for r in lines.to_dict('records')]}).model_dump()

@router.get('/{dataset_id}/preview')
def preview(dataset_id:str, start:int=Query(0,ge=0), hours:int=Query(168,ge=2,le=8760)):
 item=entries().get(dataset_id)
 if not item:raise HTTPException(404,'数据集不存在')
 path,name,kind=item
 if not path.is_file():raise HTTPException(404,'本机未安装指定历史数据包，不使用合成数据替代')
 try:
  raw=path.read_bytes();df=pd.read_csv(io.BytesIO(raw));required=['time','load','wind_power','solar_power']
  if not set(required)<=set(df):raise ValueError('历史数据缺少time/load/wind_power/solar_power')
  times=pd.to_datetime(df.time,errors='raise')
  source_breaks=int((times.diff().iloc[1:]!=pd.Timedelta(hours=1)).sum())
  if times.isna().any() or times.duplicated().any() or not times.is_monotonic_increasing:raise ValueError('历史时间轴无效或重复')
  if not times.iloc[start:start+hours].diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():raise ValueError('所选历史时间轴不连续，不自动补点或删除闰日；请另选连续时段')
  values=df[['load','wind_power','solar_power']].apply(pd.to_numeric,errors='raise')
  if not np.isfinite(values.to_numpy()).all() or (values<0).any().any():raise ValueError('历史功率存在负值或非有限值')
  if start+hours>len(df):raise ValueError(f'所选时段超过{len(df)}小时，请调整起点或长度')
  scale=1.0;notes=list(ALASH_NOTES);network=None
  if kind=='extreme':
   peak=float(values.load.max())
   if peak<=0:raise ValueError('示例负荷峰值必须大于0')
   scale=3715.0/peak
   notes=['来自ExtremeScene公开年度风光荷，风光已在源数据处理中按负荷规模适配，并非阿拉山口实测。',
    '三条功率使用相同系数，将完整年度负荷峰值映射至IEEE33基准3715kW；不改变时间戳或风光荷相对关系。',
    '该缩放仅用于IEEE33示例，不表示实际风光接入该网络。']
  else:network=alash_network()
  if source_breaks:notes.append(f'源文件存在{source_breaks}处非连续小时边界（例如闰日被源文件省略）；仅允许选择不跨越边界的连续时段，不自动修复。')
  output=values.iloc[start:start+hours].mul(scale).rename(columns={'load':'load_kw','wind_power':'wind_kw','solar_power':'pv_kw'})
  output.insert(0,'timestamp',times.iloc[start:start+hours].dt.strftime('%Y-%m-%d %H:%M:%S').to_numpy())
  csv=output.to_csv(index=False)
  quality={k:int(df.iloc[start:start+hours][k].astype(str).str.lower().isin(['true','1']).sum()) for k in ('load_imputed','weather_is_donor_year','sunshine_imputed') if k in df}
  provenance={'dataset_id':dataset_id,'name':name,'file':str(path),'sha256':hashlib.sha256(raw).hexdigest(),
   'input_sha256':hashlib.sha256(csv.encode()).hexdigest(),'source_rows':len(df),'start_row':start,'hours':hours,
   'first_timestamp':str(output.timestamp.iloc[0]),'last_timestamp':str(output.timestamp.iloc[-1]),'output_unit':'kW',
   'scale_factor':scale,'quality_counts':quality,'notes':notes,'kind':kind}
  return {'csv':csv,'source_import':provenance,'rows':output.head(8).to_dict('records'),'network':network,
   'network_parameters':{'wind_node':1,'pv_node':1} if kind=='alashankou' else {'wind_node':18,'pv_node':30},
   'branch_limit_kw':6000 if kind=='alashankou' else 5000,'model':'aggregate' if hours>168 else 'case33'}
 except (ValueError,KeyError,OSError) as e:raise HTTPException(422,str(e))
