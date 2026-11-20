import unittest
from fastapi.testclient import TestClient
from backend.app import app
class VoltageTests(unittest.TestCase):
 def test_voltage_guard_changes_dispatch_and_is_saved(self):
  c=TestClient(app);payload={'csv':'timestamp,load_kw,wind_kw,pv_kw\n2026-01-01 00:00,1000,0,0\n2026-01-01 01:00,1000,0,0\n','parameters':{'grid_channel_kw':4000,'storage_power_kw':0,'storage_energy_kwh':0,'emergency_gen_kw':0},'model':'case33'}
  r=c.post('/api/balance',json=payload);self.assertEqual(r.status_code,200,r.text);baseline=r.json()
  payload['network_parameters']={'voltage_min_pu':.999,'linear_voltage_guard_pu':.9995,'voltage_max_pu':1.02}
  r=c.post('/api/balance',json=payload);self.assertEqual(r.status_code,200,r.text);strict=r.json()
  self.assertGreater(strict['metrics']['expected_energy_deficit_kwh'],baseline['metrics']['expected_energy_deficit_kwh'])
  self.assertEqual(strict['network_parameters']['linear_voltage_guard_pu'],.9995)
  for row in strict['rows']:
   self.assertGreaterEqual(row['ac_max_voltage_pu'],row['ac_min_voltage_pu'])
   self.assertEqual(row['ac_voltage_within_bounds'],row['ac_min_voltage_pu']>=.999-1e-8 and row['ac_max_voltage_pu']<=1.02+1e-8)
  self.assertIn('0.9995',c.get('/api/runs/'+strict['id']+'/report').text)
  for invalid in ({'voltage_min_pu':.98,'linear_voltage_guard_pu':.95},{'voltage_min_pu':1,'voltage_max_pu':1,'linear_voltage_guard_pu':1},{'voltage_max_pu':.99}):
   payload['network_parameters']=invalid;self.assertEqual(c.post('/api/balance',json=payload).status_code,422)
if __name__=='__main__':unittest.main()
