import unittest
import pandas as pd
from fastapi.testclient import TestClient
from backend.app import app

class EventMetrics(unittest.TestCase):
 def test_island_support_uses_capacity_not_actual_grid_dispatch(self):
  c=TestClient(app)
  background=pd.DataFrame({'timestamp':pd.date_range('2026-01-01',periods=12,freq='h'),'load_kw':100,'wind_kw':200,'pv_kw':0}).to_csv(index=False)
  project=c.post('/api/projects',json={'name':'事件策略指标验证','state':{'csv':background}}).json()
  event='\n'.join(background.splitlines()[:5])
  scene=c.post('/api/scenarios/sequential',json={'project_id':project['id'],'name':'事件四小时失电','csv':event,'resource':'grid_channel','rated_kw':4000,'rate_per_hour':10,'repair_hours':4,'seed':42}).json()
  sequence=c.post('/api/production-sequences',json={'project_id':project['id'],'background_csv':background,'event_csv':event,'start_hour':4,'scenario_id':scene['id'],'resource_capacities':{'grid_channel_kw':4000}}).json()
  for model in ['aggregate','case33']:
   response=c.post('/api/balance',json={'project_id':project['id'],'project_revision':1,'csv':sequence['csv'],'production_sequence_id':sequence['id'],'parameters':{'grid_channel_kw':4000},'model':model})
   self.assertEqual(response.status_code,200,response.text)
   result=response.json()
   self.assertEqual(result['metrics']['extreme_event_hours'],4)
   self.assertEqual(result['metrics']['island_required_hours'],4)
   self.assertEqual(sum(row['is_extreme_condition'] for row in result['rows']),4)
   self.assertEqual(sum(row['island_support_required'] for row in result['rows']),4)
   self.assertTrue(next(row['triggered'] for row in result['strategies'] if row['strategy']=='源储荷孤岛协同运行策略'))
   self.assertTrue(result['algorithm'].endswith('.v2'))
   baseline=c.post('/api/balance',json={'csv':background,'parameters':{'grid_channel_kw':4000},'model':model}).json()
   self.assertEqual(baseline['metrics']['island_required_hours'],0)
   self.assertEqual(baseline['metrics']['extreme_event_hours'],0)
   self.assertIn('research_island_required_hours',result['metrics'])

 def test_network_renewable_curve_respects_fault_capacity(self):
  c=TestClient(app);csv='timestamp,load_kw,wind_kw,pv_kw\n2026-01-01 00:00,100,200,0\n2026-01-01 01:00,100,200,0'
  project=c.post('/api/projects',json={'name':'网络风光限额验证','state':{}}).json()
  scene=c.post('/api/scenarios/sequential',json={'project_id':project['id'],'name':'风光停运','csv':csv,'resource':'renewable','rated_kw':200,'rate_per_hour':10,'repair_hours':2,'seed':42}).json()
  result=c.post('/api/balance',json={'project_id':project['id'],'project_revision':1,'csv':csv,'scenario_id':scene['id'],'parameters':{'grid_channel_kw':4000},'model':'case33'}).json()
  self.assertTrue(all(row['available_re_kw']==0 for row in result['rows']))
  self.assertTrue(all(row['renewable_used_kw']==0 for row in result['rows']))

if __name__=='__main__':unittest.main()
