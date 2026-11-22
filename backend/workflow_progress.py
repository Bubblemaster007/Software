"""Read-only workflow evidence; opening navigation never schedules a task."""
from contextlib import closing
from pathlib import Path
from datetime import datetime
import json
import sqlite3
from fastapi import APIRouter, HTTPException

ROOT=Path(__file__).resolve().parents[1]
router=APIRouter(prefix='/api/workflow-progress')

def task_time(value):
 try:return float(value)
 except (ValueError,TypeError):
  try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
  except (ValueError,TypeError):return 0

def signature(state):
 keys=('csv','network','parameters','stages','model','networkParameters','failedLines','branchLimit','scenarioId','productionSequenceId')
 return json.dumps({k:state.get(k) for k in keys},sort_keys=True,ensure_ascii=False)

@router.get('/{project_id}')
def snapshot(project_id:str):
 path=ROOT/'data/platform.db'
 if not path.exists():raise HTTPException(404,'工程不存在')
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)) as c:
  c.execute('BEGIN')
  tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  row=c.execute('SELECT payload FROM projects WHERE id=?',(project_id,)).fetchone() if 'projects' in tables else None
  if not row:raise HTTPException(404,'工程不存在')
  project=json.loads(row[0]);state=project.get('state',{})
  def count(table):
   return c.execute(f'SELECT COUNT(*) FROM {table} WHERE project_id=?',(project_id,)).fetchone()[0] if table in tables else 0
  jobs=[]
  if 'study_jobs' in tables:
   records=c.execute('SELECT id,status,meta,input,created FROM study_jobs WHERE project_id=? ORDER BY created DESC,rowid DESC LIMIT 100',(project_id,))
   for id,status,meta,raw,created in records:
    meta=json.loads(meta);frozen=json.loads(raw).get('project',{})
    jobs.append({'id':id,'module':meta.get('module'),'status':status,'progress':meta.get('progress'),'created':created,'created_epoch':task_time(created),
     'project_revision':frozen.get('revision'),'matches_saved_input':signature(frozen.get('state',{}))==signature(state)})
  if 'native_jobs' in tables:
   for (raw,) in c.execute('SELECT payload FROM native_jobs WHERE project_id=? ORDER BY created DESC,rowid DESC',(project_id,)):
    job=json.loads(raw);config=job.get('config',{});network=config.get('case33_network',{})
    matches=job.get('csv')==state.get('csv') and not state.get('network') and config.get('chapter4')==state.get('parameters')
    matches=matches and all(network.get(k)==v for k,v in state.get('networkParameters',{}).items()) and network.get('branch_limit_kw')==state.get('branchLimit',5000)
    jobs.append({'id':job['id'],'module':'native','status':job['status'],'created':job.get('created'),'created_epoch':task_time(job.get('created')),
     'project_revision':job.get('project_revision'),'matches_saved_input':matches})
  jobs.sort(key=lambda j:(j['created_epoch'],j['id']),reverse=True)
  scenario_evidence={'state':'pending','scenario_id':state.get('scenarioId'),'production_id':state.get('productionSequenceId')}
  if scenario_evidence['scenario_id'] or scenario_evidence['production_id']:
   valid=True
   for key,table in [('scenario_id','scenarios'),('production_id','production_sequences')]:
    id=scenario_evidence[key]
    if not id:continue
    if table not in tables:valid=False;continue
    cols={r[1] for r in c.execute(f'PRAGMA table_info({table})')}
    if 'payload' not in cols:valid=False;continue
    row=c.execute(f'SELECT payload FROM {table} WHERE id=? AND project_id=?',(id,project_id)).fetchone()
    if not row:valid=False;continue
    artifact=json.loads(row[0])
    if key=='production_id':valid=valid and artifact.get('csv')==state.get('csv')
    else:
     source_times=[line.split(',')[0].replace('T',' ')[:19] for line in state.get('csv','').strip().splitlines()[1:]]
     capacity_times=[str(r.get('timestamp','')).replace('T',' ')[:19] for r in artifact.get('capacity',[])]
     valid=valid and bool(source_times) and source_times==capacity_times
   scenario_evidence['state']='applied' if valid else 'stale'
  elif count('scenarios')+count('source_studies')+count('production_sequences'):
   scenario_evidence['state']='generated'
  if state.get('scenarioConfiguration'):
   from backend.scenario_configuration import configuration_matches
   try:valid=configuration_matches(state['scenarioConfiguration'],state) and scenario_evidence['state']!='stale'
   except (ValueError,TypeError,AttributeError):valid=False
   scenario_evidence['state']='applied' if valid else 'stale'
  run_count=adjustment_count=0;latest=None
  if 'runs' in tables:
   run_count=c.execute("SELECT COUNT(*) FROM runs WHERE json_extract(payload,'$.project_id')=?",(project_id,)).fetchone()[0]
   adjustment_count=c.execute("SELECT COUNT(*) FROM runs WHERE json_extract(payload,'$.project_id')=? AND json_extract(payload,'$.baseline_run_id') IS NOT NULL",(project_id,)).fetchone()[0]
   keys=['id','project_revision','input_csv','parameters','model','network','network_parameters','scenario_id','production_sequence_id','failed_lines','branch_limit_kw','stages','created']
   columns=','.join("json_extract(payload,'$."+key+"')" for key in keys)
   row=c.execute('SELECT '+columns+" FROM runs WHERE json_extract(payload,'$.project_id')=? ORDER BY created DESC,rowid DESC LIMIT 1",(project_id,)).fetchone()
   if row:
    record=dict(zip(keys,row));matches=record['input_csv']==state.get('csv')
    for saved,field in [('parameters','parameters'),('model','model'),('network','network'),('networkParameters','network_parameters'),('scenarioId','scenario_id'),('productionSequenceId','production_sequence_id'),('branchLimit','branch_limit_kw')]:
     if saved not in state:continue
     value=record[field]
     if field in ('parameters','network','network_parameters') and value is not None:value=json.loads(value)
     matches=matches and value==state[saved]
    if 'failedLines' in state:matches=matches and ','.join(map(str,json.loads(record['failed_lines'] or '[]')))==state['failedLines']
    phases=json.loads(record['stages'] or '[]')
    if state.get('stages'):matches=matches and phases==state['stages']
    elif phases and not (len(phases)==1 and phases[0].get('name')=='全时域'):matches=False
    latest={'id':row[0],'project_revision':row[1],'matches_saved_input':matches,'created_epoch':task_time(record['created'])}
  return {'project_id':project_id,'revision':project['revision'],'scenario_count':count('scenarios'),
   'source_study_count':count('source_studies'),'production_count':count('production_sequences'),
   'run_count':run_count,'adjustment_count':adjustment_count,'latest_run':latest,'jobs':jobs,'scenario_evidence':scenario_evidence}
