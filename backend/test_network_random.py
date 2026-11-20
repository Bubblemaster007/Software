import time
import unittest
from fastapi.testclient import TestClient
from backend.app import app

class NetworkRandomFlow(unittest.TestCase):
 def test_network_samples_preserve_faults_recovery_and_ac_ledger(self):
  c=TestClient(app);csv='\n'.join(c.get('/api/demo').json()['csv'].splitlines()[:13])
  project=c.post('/api/projects',json={'name':'网络随机平衡验证','state':{'csv':csv}}).json()
  source=c.post('/api/balance',json={'project_id':project['id'],'project_revision':1,'csv':csv,'parameters':{'grid_channel_kw':4000},'model':'case33','branch_limit_kw':3000,'stages':[{'name':'根支路失电','end_hour':6,'failed_lines':[1]},{'name':'支路恢复','end_hour':12}]}).json()
  self.assertIn('id',source,source)
  started=time.perf_counter()
  response=c.post('/api/random-balance',json={'source_run_id':source['id'],'samples':2,'rate_per_hour':0})
  self.assertEqual(response.status_code,200,response.text)
  batch=response.json();self.assertEqual(batch['model'],'case33')
  self.assertEqual(batch['phase_summary'][0]['shortage_sample_probability'],1)
  self.assertEqual(batch['phase_summary'][1]['shortage_sample_probability'],0)
  for sample in batch['samples']:
   result=c.get('/api/runs/'+sample['run_id']).json()
   self.assertEqual(result['model'],'case33')
   self.assertEqual(result['stages'],source['stages'])
   self.assertEqual(result['branch_limit_kw'],3000)
   self.assertEqual(result['random_batch_id'],batch['id'])
   self.assertEqual(result['baseline_run_id'],source['id'])
   self.assertEqual(sample['voltage_violation_hours'],sum(not row['ac_voltage_within_bounds'] for row in result['rows']))
   for row in result['rows']:
    supply=row['renewable_used_kw']+row['firm_grid_dispatch_kw']+row['emergency_gen_kw']+row['storage_discharge_kw']
    demand=row['load_served_kw']+row['storage_charge_kw']+row['estimated_line_loss_kw']
    self.assertAlmostEqual(supply,demand,places=4)
   self.assertTrue(all(abs(row['power_deficit_kw']-row['load_kw'])<1e-6 for row in result['rows'][:6]))
  print(f'IEEE33 2 samples x 12 hours: {time.perf_counter()-started:.3f}s')

if __name__=='__main__':unittest.main()
