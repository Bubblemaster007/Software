"""Versioned immutable exchanges and a Python adapter boundary for other topics."""
from contextlib import closing
from datetime import datetime
import hashlib,json,sqlite3,uuid
from typing import Literal,Callable
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from backend.workspace import ROOT,project_record,scenario_record
from backend.engineering import inventory_record

router=APIRouter(prefix='/api/integration',tags=['模块集成接口'])
Module=Literal['disaster_limit','island_stability','black_start','joint_planning']
ADAPTERS:dict[str,tuple[str,Callable]]={}
MODULES=[{'id':'disaster_limit','name':'承灾极限分析','topic':1,'input':['强度扫描','设备脆弱性','保供目标'],'output':['临界强度','临界时长','薄弱设备']}, {'id':'island_stability','name':'离网稳定判别','topic':3,'input':['孤岛范围','控制模型','扰动','频率电压阈值'],'output':['判别结论','风险节点','阈值校核','耗时']}, {'id':'black_start','name':'黑启动路径优化','topic':3,'input':['启动资源','恢复分区','开关终端','通信路由','涌流频率电压约束'],'output':['带时间恢复序列','路径','恢复负荷','逐步校核']}, {'id':'joint_planning','name':'一二次协同规划','topic':3,'input':['开关','自动化终端','通信链路','经济约束'],'output':['设备布局','通信方案','成本','可行性']}]
def register_adapter(module:str,version:str,handler:Callable):
 if module not in {m['id'] for m in MODULES} or not version or not callable(handler):raise ValueError('适配器注册无效')
 ADAPTERS[module]=(version,handler)
def connection():
 c=sqlite3.connect(ROOT/'data/platform.db');c.execute('CREATE TABLE IF NOT EXISTS module_exchanges(id TEXT PRIMARY KEY,project_id TEXT,module TEXT,created TEXT,payload TEXT)');return c
def read(exchange_id):
 with closing(connection()) as c:row=c.execute('SELECT payload FROM module_exchanges WHERE id=?',(exchange_id,)).fetchone()
 if not row:raise HTTPException(404,'模块交接任务不存在')
 return json.loads(row[0])
def write(record):
 with closing(connection()) as c,c:c.execute('INSERT OR REPLACE INTO module_exchanges VALUES(?,?,?,?,?)',(record['id'],record['project_id'],record['module'],record['created'],json.dumps(record,ensure_ascii=False,allow_nan=False)))
class ExchangeInput(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 module:Module
 project_id:str
 project_revision:int=Field(ge=1)
 source_run_id:str|None=None
 scenario_id:str|None=None
 parameters:dict=Field(default_factory=dict)
class Check(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 name:str=Field(min_length=1,max_length=100)
 status:Literal['passed','failed','not_checked']
 evidence:str=Field('',max_length=5000)
class Result(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 contract_version:Literal['1.0']='1.0'
 request_sha256:str=Field(min_length=64,max_length=64)
 algorithm_version:str=Field(min_length=1,max_length=120)
 status:Literal['succeeded','failed']
 summary:str=Field(min_length=1,max_length=5000)
 metrics:dict=Field(default_factory=dict)
 checks:list[Check]=Field(default_factory=list,max_length=1000)
 payload:dict=Field(default_factory=dict)

@router.get('/modules')
def modules():return [{**m,'contract_version':'1.0','adapter_version':ADAPTERS[m['id']][0] if m['id'] in ADAPTERS else None,'status':'available' if m['id'] in ADAPTERS else 'awaiting_adapter'} for m in MODULES]
@router.get('/topic2')
def topic2_catalog():
 from backend.topic2_catalog import catalog
 return catalog()
@router.get('/schema')
def schema():return {'input':ExchangeInput.model_json_schema(),'result':Result.model_json_schema(),'units':{'power':'kW','energy':'kWh','voltage':'pu','frequency':'Hz','duration':'h','cost':'元'},'rules':['请求保存后不可改写输入','结果必须回传request_sha256','外部导入结果不等于已独立验证','未校核项必须显式列出','运行阶段和建设年份分别传递']}

@router.post('/requests')
def create(req:ExchangeInput):
 project=project_record(req.project_id)
 if project['revision']!=req.project_revision:raise HTTPException(409,'工程版本已变化，请先刷新工程')
 source=None;scene=None
 if req.source_run_id:
  from backend.app import get_run
  source=get_run(req.source_run_id)
  if source.get('project_id')!=req.project_id:raise HTTPException(422,'基准结果不属于当前工程')
 if req.scenario_id:
  scene=scenario_record(req.scenario_id)
  if scene['project_id']!=req.project_id:raise HTTPException(422,'场景不属于当前工程')
 if source and (source.get('scenario_id') or None)!=(req.scenario_id or None):raise HTTPException(422,'交接场景须与基准计算一致')
 from backend.workspace import case33
 from backend.app import read_draft
 module_name=next(m['name'] for m in MODULES if m['id']==req.module)
 snapshot={'contract_version':'1.0','module':req.module,'project':project,'baseline_run':source,'scenario':scene,'module_draft':read_draft(module_name,req.project_id),'network':((source.get('network') or case33()) if source else (project['state'].get('network') or case33())) if (source or project.get('state',{})).get('model')=='case33' else None,'engineering':source['engineering'] if source and source.get('engineering') else inventory_record(req.project_id),'engineering_basis':'baseline_run' if source and source.get('engineering') else 'current_saved_inventory','parameters':req.parameters,'units':schema()['units'],'input_basis':'baseline_run为已归档计算快照；project.state为工程当前输入，两者可不同，适配器必须明确采用的依据。module_draft保留原字段单位，parameters按统一单位显式映射，不自动将草稿视为已校准模型。'}
 try:encoded=json.dumps(snapshot,ensure_ascii=False,sort_keys=True,allow_nan=False)
 except (ValueError,TypeError):raise HTTPException(422,'参数必须为有限JSON值')
 if len(encoded)>10000000:raise HTTPException(422,'交接输入超过10MB限制')
 record={'id':uuid.uuid4().hex,'project_id':req.project_id,'module':req.module,'created':datetime.now().isoformat(timespec='seconds'),'status':'prepared','request_sha256':hashlib.sha256(encoded.encode()).hexdigest(),'input':snapshot,'result':None}
 write(record);return record
@router.get('/requests')
def list_requests(project_id:str):
 project_record(project_id)
 with closing(connection()) as c:rows=c.execute('SELECT payload FROM module_exchanges WHERE project_id=? ORDER BY created DESC,rowid DESC',(project_id,)).fetchall()
 return [{k:v for k,v in json.loads(row[0]).items() if k not in ('input','result')} for row in rows]
@router.get('/requests/{exchange_id}')
def get_request(exchange_id:str):return read(exchange_id)
def save_result(record,result:Result,origin:str):
 if record['result'] is not None:raise HTTPException(409,'此任务已保存结果，请创建新任务保留版本')
 if record['request_sha256']!=result.request_sha256:raise HTTPException(422,'结果输入摘要与任务不匹配')
 try:
  if len(json.dumps(result.model_dump(),allow_nan=False))>5000000:raise HTTPException(422,'结果超过5MB限制')
 except ValueError:raise HTTPException(422,'结果必须为有限JSON值')
 with closing(connection()) as c,c:
  c.execute('BEGIN IMMEDIATE')
  latest=json.loads(c.execute('SELECT payload FROM module_exchanges WHERE id=?',(record['id'],)).fetchone()[0])
  if latest['result'] is not None:raise HTTPException(409,'此任务已保存结果，请创建新任务保留版本')
  latest.update(status=result.status,result=result.model_dump(),result_origin=origin,completed=datetime.now().isoformat(timespec='seconds'))
  c.execute('UPDATE module_exchanges SET payload=? WHERE id=?',(json.dumps(latest,ensure_ascii=False,allow_nan=False),record['id']))
 return latest
@router.post('/requests/{exchange_id}/result')
def import_result(exchange_id:str,result:Result):return save_result(read(exchange_id),result,'external_import_unverified')
@router.post('/requests/{exchange_id}/execute')
def execute(exchange_id:str):
 record=read(exchange_id)
 if record['result'] is not None:raise HTTPException(409,'此任务已有结果')
 adapter=ADAPTERS.get(record['module'])
 if not adapter:raise HTTPException(409,'本模块尚未注册计算适配器，可导出输入交接包；没有生成计算结论')
 version,handler=adapter
 result=Result.model_validate(handler(record['input'],record['request_sha256']))
 if result.algorithm_version!=version:raise HTTPException(422,'算法返回版本与注册版本不一致')
 return save_result(record,result,'registered_adapter')
