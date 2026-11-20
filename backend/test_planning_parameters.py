import unittest
from fastapi.testclient import TestClient
from backend.app import app

class PlanningParameters(unittest.TestCase):
 def test_limits_costs_and_saved_snapshot(self):
  c=TestClient(app)
  source=c.post('/api/balance',json={'csv':c.get('/api/demo').json()['csv'],'parameters':{}}).json()
  payload={'run_id':source['id'],'max_storage_units':0,'max_emergency_units':0,'max_mobile_units':0,'emergency_gen_unit_kw':250,'mobile_unit_kw':150,'storage_energy_cost':1250,'penalty_energy_deficit':50}
  response=c.post('/api/planning',json=payload)
  self.assertEqual(response.status_code,200,response.text)
  result=response.json()
  self.assertEqual(result['candidate_count'],1)
  for key in ['storage_power_kw','storage_energy_kwh','emergency_gen_kw','mobile_units']:
   self.assertEqual(result['recommended_plan'][key],0)
  saved=c.get('/api/plans/'+result['id']).json()
  self.assertEqual(saved['config']['storage_energy_cost'],1250)
  self.assertEqual(saved['config']['emergency_gen_unit_kw'],250)
  self.assertEqual(saved['config']['penalty_energy_deficit'],50)
  self.assertEqual(result['evaluation']['investment_cost'],0)
  for invalid in [{'emergency_gen_unit_kw':0},{'storage_power_cost':-1},{'max_mobile_units':11},{'unknown_setting':1}]:
   self.assertEqual(c.post('/api/planning',json={**payload,**invalid}).status_code,422)

if __name__=='__main__':unittest.main()
