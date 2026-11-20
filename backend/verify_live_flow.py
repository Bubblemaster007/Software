"""Run the complete local HTTP workflow and retain a reviewable demo project."""
import json
from pathlib import Path
import httpx

def main():
 root=Path(__file__).resolve().parents[1]
 with httpx.Client(base_url='http://127.0.0.1:8765',timeout=120) as client:
  def request(method,url,**kwargs):
   response=client.request(method,url,**kwargs);response.raise_for_status();return response.json()
  csv='\n'.join(request('GET','/api/demo')['csv'].splitlines()[:25])
  parameters={'grid_channel_kw':0,'emergency_gen_kw':300,'storage_power_kw':500,'storage_energy_kwh':2000}
  state={'csv':csv,'parameters':parameters,'model':'case33','stages':[],'failedLines':'','branchLimit':5000}
  project=request('POST','/api/projects',json={'name':'功能联调示范工程','state':state})
  base=request('POST','/api/balance',json={'project_id':project['id'],'project_revision':1,'csv':csv,'parameters':parameters,'model':'case33'})
  adjusted=request('POST','/api/strategy-evaluation',json={'source_run_id':base['id'],'parameters':{**base['parameters'],'grid_channel_kw':4000}})
  assert adjusted['verified']['expected_energy_deficit_kwh']<base['metrics']['expected_energy_deficit_kwh']
  batch=request('POST','/api/random-balance',json={'source_run_id':adjusted['run_id'],'samples':2,'seed':42,'rate_per_hour':.1,'repair_hours':3})
  plan=request('POST','/api/planning',json={'run_id':base['id'],'max_storage_units':1,'max_emergency_units':1,'max_mobile_units':0})
  verified=request('POST','/api/plans/'+plan['id']+'/verify')
  stages=[{'name':'支路故障','end_hour':6,'failed_lines':[1]},{'name':'修复供电','end_hour':24}]
  fault=request('POST','/api/balance',json={'project_id':project['id'],'project_revision':1,'csv':csv,'parameters':{**base['parameters'],'grid_channel_kw':4000},'model':'case33','stages':stages})
  assert fault['network_details'][5]['lines'][0]['failed'] and not fault['network_details'][6]['lines'][0]['failed']
  assert all(row['power_deficit_kw']<1e-6 for row in fault['rows'][6:])
  for suffix,name in [('csv','功能联调逐时结果.csv'),('report','功能联调计算报告.html')]:
   response=client.get('/api/runs/'+fault['id']+'/'+suffix);response.raise_for_status();(root/'docs'/name).write_bytes(response.content)
  response=client.get('/api/comparison-report',params={'baseline_id':base['id'],'comparison_id':adjusted['run_id']});response.raise_for_status();(root/'docs/功能联调策略对比.html').write_bytes(response.content)
  state.update(parameters=fault['parameters'],stages=stages,networkParameters=fault['network_parameters'])
  request('PUT','/api/projects/'+project['id'],json={'name':project['name'],'expected_revision':1,'state':state})
  record={'project_id':project['id'],'baseline_run_id':base['id'],'adjusted_run_id':adjusted['run_id'],'baseline_eens_kwh':base['metrics']['expected_energy_deficit_kwh'],'adjusted_eens_kwh':adjusted['verified']['expected_energy_deficit_kwh'],'random_batch_id':batch['id'],'planning_id':plan['id'],'planning_verification':verified,'fault_run_id':fault['id'],'network_snapshot_hours':len(fault['network_details']),'verified_steps':['工程保存','网络平衡','策略调整复算','随机故障样本','源储配置试算及复核','故障与修复拓扑','结果归档','CSV与HTML报告','策略对比报告']}
  (root/'docs/功能联调记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps({k:v for k,v in record.items() if k!='planning_verification'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
