import unittest
import pandas as pd
from fastapi.testclient import TestClient
from backend.app import app

class CoupledEmbeddingFlow(unittest.TestCase):
 def test_event_fault_relocation_and_background_recovery(self):
  c=TestClient(app)
  background=pd.DataFrame({'timestamp':pd.date_range('2026-01-01',periods=24,freq='h'),'load_kw':100,'wind_kw':0,'pv_kw':0}).to_csv(index=False)
  event='\n'.join(background.splitlines()[:3])
  project=c.post('/api/projects',json={'name':'源荷故障耦合验证','state':{'csv':background}}).json()
  fault=c.post('/api/scenarios/sequential',json={'project_id':project['id'],'name':'事件电网失电','csv':event,'resource':'grid_channel','rated_kw':4000,'rate_per_hour':10,'repair_hours':2,'seed':42}).json()
  payload={'project_id':project['id'],'background_csv':background,'event_csv':event,'start_hour':12,'scenario_id':fault['id'],'resource_capacities':{'grid_channel_kw':4000,'emergency_gen_kw':0,'storage_power_kw':0}}
  response=c.post('/api/production-sequences',json=payload)
  self.assertEqual(response.status_code,200,response.text)
  sequence=response.json();self.assertIn('embedded_scenario_id',sequence)
  self.assertEqual(len(sequence['coupled_event_rows']),2)
  scene=c.get('/api/scenarios/'+sequence['embedded_scenario_id']).json()
  self.assertEqual(len(scene['capacity']),24)
  self.assertEqual(scene['capacity'][11]['available_kw_grid_channel'],4000)
  self.assertEqual(scene['capacity'][12]['available_kw_grid_channel'],0)
  self.assertEqual(scene['capacity'][13]['available_kw_grid_channel'],0)
  self.assertEqual(scene['capacity'][14]['available_kw_grid_channel'],4000)
  self.assertEqual(scene['states'][0]['timestamp'],sequence['rows'][12]['timestamp'])
  for model in ['aggregate','case33']:
   response=c.post('/api/balance',json={'project_id':project['id'],'project_revision':1,'production_sequence_id':sequence['id'],'csv':sequence['csv'],'parameters':{'grid_channel_kw':4000,'emergency_gen_kw':0,'storage_power_kw':0,'storage_energy_kwh':0},'model':model})
   self.assertEqual(response.status_code,200,response.text)
   result=response.json()
   self.assertEqual(result['scenario_id'],scene['id'])
   self.assertAlmostEqual(result['metrics']['expected_energy_deficit_kwh'],200,places=4)
   self.assertEqual(result['rows'][12]['firm_grid_dispatch_kw'],0)
   self.assertAlmostEqual(result['rows'][14]['power_deficit_kw'],0,places=5)
  self.assertEqual(c.post('/api/production-sequences',json={**payload,'event_csv':event.replace('2026-01-01','2025-01-01')}).status_code,422)
  self.assertEqual(c.post('/api/balance',json={'project_id':project['id'],'project_revision':1,'production_sequence_id':sequence['id'],'scenario_id':fault['id'],'csv':sequence['csv'],'parameters':{}}).status_code,422)

if __name__=='__main__':unittest.main()
