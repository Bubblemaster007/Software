import unittest
from fastapi.testclient import TestClient
from backend.app import app


class SequentialFlow(unittest.TestCase):
 def test_repair_capacity_and_report_snapshot(self):
  c=TestClient(app)
  csv=c.get('/api/demo').json()['csv']
  project=c.post('/api/projects',json={'name':'连续故障闭环验证','state':{'csv':csv}}).json()
  body={'project_id':project['id'],'name':'六小时修复场景','csv':csv,'resource':'grid_channel','rated_kw':4000,'rate_per_hour':10,'repair_hours':6,'seed':42}
  response=c.post('/api/scenarios/sequential',json=body)
  self.assertEqual(response.status_code,200,response.text)
  scene=response.json()
  self.assertEqual(len(scene['failures']),8)
  self.assertTrue(all(row['state']=='failed' for row in scene['states']))
  self.assertEqual(scene['states'],c.post('/api/scenarios/sequential',json=body).json()['states'])
  response=c.post('/api/balance',json={'project_id':project['id'],'project_revision':1,'scenario_id':scene['id'],'csv':csv,'parameters':{'grid_channel_kw':4000}})
  self.assertEqual(response.status_code,200,response.text)
  result=response.json()
  self.assertTrue(all(row['firm_grid_dispatch_kw']==0 for row in result['rows']))
  self.assertEqual(result['scenario_snapshot']['repair_hours'],6)
  report=c.get('/api/runs/'+result['id']+'/report').text
  self.assertIn('故障场景快照与复现参数',report)
  self.assertIn('六小时修复场景',report)
  self.assertIn('repair_hours',report)

 def test_zero_capacity_is_not_equipment_failure(self):
  c=TestClient(app)
  csv=c.get('/api/demo').json()['csv']
  project=c.post('/api/projects',json={'name':'零容量状态验证','state':{}}).json()
  response=c.post('/api/scenarios/sequential',json={'project_id':project['id'],'name':'未配置资源','csv':csv,'resource':'grid_channel','rated_kw':0,'rate_per_hour':0,'repair_hours':6,'seed':42})
  self.assertEqual(response.status_code,200,response.text)
  self.assertEqual(response.json()['failures'],[])
  self.assertTrue(all(row['state']=='normal' and row['available_kw']==0 for row in response.json()['states']))


if __name__=='__main__':unittest.main()

