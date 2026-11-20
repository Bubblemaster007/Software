import unittest
import numpy as np
from fastapi.testclient import TestClient
from backend.app import app

class RandomBalanceFlow(unittest.TestCase):
 def test_samples_reproducibility_statistics_and_archival(self):
  c=TestClient(app);csv=c.get('/api/demo').json()['csv']
  project=c.post('/api/projects',json={'name':'随机平衡闭环验证','state':{'csv':csv}}).json()
  source=c.post('/api/balance',json={'project_id':project['id'],'project_revision':1,'csv':csv,'parameters':{'grid_channel_kw':4000},'stages':[{'name':'前半段','end_hour':24},{'name':'后半段','end_hour':48}]}).json()
  body={'source_run_id':source['id'],'samples':4,'seed':42,'rate_per_hour':.1,'repair_hours':6}
  response=c.post('/api/random-balance',json=body)
  self.assertEqual(response.status_code,200,response.text)
  batch=response.json();samples=batch['samples'];summary=batch['summary']
  self.assertEqual([s['seed'] for s in samples],[42,43,44,45])
  energy=[s['expected_energy_deficit_kwh'] for s in samples]
  self.assertEqual([p['stage'] for p in batch['phase_summary']],['前半段','后半段'])
  self.assertAlmostEqual(sum(p['mean_energy_deficit_mwh'] for p in batch['phase_summary'])*1000,summary['mean_energy_deficit_kwh'],places=5)
  self.assertAlmostEqual(summary['mean_energy_deficit_kwh'],float(np.mean(energy)))
  self.assertAlmostEqual(summary['p95_energy_deficit_kwh'],float(np.quantile(energy,.95)))
  self.assertLessEqual(summary['shortage_probability_wilson95_lower'],summary['shortage_sample_probability'])
  self.assertGreaterEqual(summary['shortage_probability_wilson95_upper'],summary['shortage_sample_probability'])
  repeated=c.post('/api/random-balance',json=body).json()
  self.assertEqual(energy,[s['expected_energy_deficit_kwh'] for s in repeated['samples']])
  self.assertIn(batch['id'],[b['id'] for b in c.get('/api/random-balance',params={'project_id':project['id']}).json()])
  self.assertEqual(c.get('/api/random-balance/'+batch['id']+'/csv').status_code,200)
  no_failure=c.post('/api/random-balance',json={**body,'rate_per_hour':0}).json()
  self.assertEqual(no_failure['summary']['mean_energy_deficit_kwh'],0)
  self.assertTrue(all(s['failure_events']==0 for s in no_failure['samples']))
  self.assertEqual(c.post('/api/random-balance',json={**body,'source_run_id':samples[0]['run_id']}).status_code,422)
  self.assertEqual(c.post('/api/random-balance',json={**body,'samples':21}).status_code,422)

if __name__=='__main__':unittest.main()
