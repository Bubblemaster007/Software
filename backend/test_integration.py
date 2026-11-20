import unittest
import numpy as np
from fastapi.testclient import TestClient
from backend.app import app
class Integration(unittest.TestCase):
 def test_compute_save_export_and_conservation(self):
  c=TestClient(app);csv=c.get('/api/demo').json()['csv'];r=c.post('/api/balance',json={'csv':csv,'parameters':{}});self.assertEqual(r.status_code,200,r.text);d=r.json()
  self.assertEqual(len(d['rows']),48);self.assertEqual(len(d['strategies']),8)
  for x in d['rows']:
   supply=x['renewable_used_kw']+x['firm_grid_dispatch_kw']+x['emergency_gen_kw']+x['storage_discharge_kw']
   self.assertAlmostEqual(supply+x['power_deficit_kw'],x['load_kw'],places=6)
   self.assertTrue(.1-1e-8<=x['soc']<=.95+1e-8)
  self.assertAlmostEqual(sum(x['power_deficit_kw'] for x in d['rows']),d['metrics']['expected_energy_deficit_kwh'],places=5)
  self.assertEqual(c.get('/api/runs/'+d['id']).json()['id'],d['id']);self.assertEqual(c.get('/api/runs/'+d['id']+'/csv').status_code,200)
 def test_reject_invalid_time_and_negative(self):
  c=TestClient(app)
  for csv in ['timestamp,load_kw,wind_kw,pv_kw\n2026-01-01,100,0,0\n2026-01-01 00:15,100,0,0','timestamp,load_kw,wind_kw,pv_kw\n2026-01-01,-1,0,0\n2026-01-01 01:00,100,0,0']:
   self.assertEqual(c.post('/api/balance',json={'csv':csv,'parameters':{}}).status_code,422)
if __name__=='__main__':unittest.main()
