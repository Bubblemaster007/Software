import unittest
from fastapi.testclient import TestClient
from backend.app import app
class NetworkPlacementTests(unittest.TestCase):
 def test_location_affects_fault_supply_and_is_inherited(self):
  c=TestClient(app);p=c.post('/api/projects',json={'name':'电源接入节点验证'}).json()
  payload={'project_id':p['id'],'project_revision':p['revision'],'csv':'timestamp,load_kw,wind_kw,pv_kw\n2026-01-01 00:00,100,200,0\n2026-01-01 01:00,100,200,0\n','model':'case33','failed_lines':[17],'parameters':{'storage_power_kw':0,'storage_energy_kwh':0,'emergency_gen_kw':0,'grid_channel_kw':0}}
  a=c.post('/api/balance',json=payload);self.assertEqual(a.status_code,200,a.text)
  self.assertAlmostEqual(a.json()['metrics']['expected_energy_deficit_kwh'],200)
  payload['network_parameters']={'wind_node':30,'pv_node':18}
  r=c.post('/api/balance',json=payload);self.assertEqual(r.status_code,200,r.text);b=r.json()
  self.assertLess(b['metrics']['expected_energy_deficit_kwh'],190)
  self.assertEqual(b['network_parameters']['wind_node'],30)
  adjusted=c.post('/api/strategy-evaluation',json={'source_run_id':b['id'],'parameters':b['parameters']}).json()
  self.assertEqual(c.get('/api/runs/'+adjusted['run_id']).json()['network_parameters'],b['network_parameters'])
  batch=c.post('/api/random-balance',json={'source_run_id':b['id'],'samples':2,'rate_per_hour':0}).json()
  for item in batch['samples']:self.assertEqual(c.get('/api/runs/'+item['run_id']).json()['network_parameters'],b['network_parameters'])
  report=c.get('/api/runs/'+b['id']+'/report').text;self.assertIn('网络接入与电压约束',report)
  payload['network_parameters']['wind_node']=34;self.assertEqual(c.post('/api/balance',json=payload).status_code,422)
if __name__=='__main__':unittest.main()
