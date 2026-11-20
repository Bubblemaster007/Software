import unittest
from fastapi.testclient import TestClient
from backend.app import app

class StrategyFlow(unittest.TestCase):
 def test_adjustment_reuses_baseline_without_overwriting(self):
  c=TestClient(app);csv=c.get('/api/demo').json()['csv']
  source=c.post('/api/balance',json={'csv':csv,'parameters':{}}).json()
  parameters={**source['parameters'],'grid_channel_kw':4000}
  response=c.post('/api/strategy-evaluation',json={'source_run_id':source['id'],'parameters':parameters,'wind_scale':1.2})
  self.assertEqual(response.status_code,200,response.text)
  result=response.json()
  self.assertGreater(result['baseline']['expected_energy_deficit_kwh'],0)
  self.assertEqual(result['verified']['expected_energy_deficit_kwh'],0)
  saved=c.get('/api/runs/'+result['run_id']).json()
  self.assertEqual(saved['baseline_run_id'],source['id'])
  self.assertEqual(saved['stages'],source['stages'])
  self.assertEqual(c.get('/api/runs/'+source['id']).json()['parameters']['grid_channel_kw'],0)
  self.assertIn('策略调整参数',c.get('/api/runs/'+result['run_id']+'/report').text)
  self.assertEqual(c.post('/api/strategy-evaluation',json={'source_run_id':source['id'],'parameters':parameters,'wind_scale':-1}).status_code,422)

if __name__=='__main__':unittest.main()
