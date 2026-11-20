import unittest
from fastapi.testclient import TestClient
from backend.app import app

class ResourceParameters(unittest.TestCase):
 def test_load_tiers_are_used_in_both_models(self):
  c=TestClient(app)
  csv='timestamp,load_kw,wind_kw,pv_kw\n2026-01-01 00:00,100,0,0\n2026-01-01 01:00,100,0,0'
  parameters={'storage_power_kw':0,'storage_energy_kwh':0,'emergency_gen_kw':0,'grid_channel_kw':50,'critical_load_ratio':.8,'important_load_ratio':.1}
  for model in ['aggregate','case33']:
   response=c.post('/api/balance',json={'csv':csv,'parameters':parameters,'model':model})
   self.assertEqual(response.status_code,200,response.text)
   result=response.json()
   self.assertEqual(result['parameters']['critical_load_ratio'],.8)
   self.assertLessEqual(result['metrics']['critical_load_supply_ratio'],.625+1e-6)
   self.assertEqual(result['metrics']['important_load_restoration_ratio'],0)
   for row in result['rows']:
    self.assertEqual(row['critical_load_kw'],80)
    self.assertEqual(row['important_load_kw'],10)
   default=c.post('/api/balance',json={'csv':csv,'parameters':{**parameters,'critical_load_ratio':.2,'important_load_ratio':.35},'model':model}).json()
   self.assertAlmostEqual(default['metrics']['critical_load_supply_ratio'],1)
  for invalid in [{'critical_load_ratio':.8,'important_load_ratio':.3},{'soc_min_ratio':.9},{'eta_charge':0},{'eta_discharge':1.1}]:
   self.assertEqual(c.post('/api/balance',json={'csv':csv,'parameters':{**parameters,**invalid}}).status_code,422)

 def test_storage_efficiency_and_reserve_limit(self):
  c=TestClient(app)
  csv='timestamp,load_kw,wind_kw,pv_kw\n2026-01-01 00:00,100,0,0\n2026-01-01 01:00,100,0,0'
  parameters={'storage_power_kw':100,'storage_energy_kwh':100,'emergency_gen_kw':0,'grid_channel_kw':0,'soc_initial_ratio':.8,'soc_min_ratio':.4,'eta_discharge':.5}
  for model in ['aggregate','case33']:
   response=c.post('/api/balance',json={'csv':csv,'parameters':parameters,'model':model})
   self.assertEqual(response.status_code,200,response.text)
   result=response.json()
   self.assertAlmostEqual(sum(row['storage_discharge_kw'] for row in result['rows']),20,places=5)
   self.assertTrue(all(row['soc']>=.4-1e-6 for row in result['rows']))

if __name__=='__main__':unittest.main()
