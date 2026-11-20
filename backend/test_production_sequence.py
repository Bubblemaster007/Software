import io
import unittest
import pandas as pd
from fastapi.testclient import TestClient
from backend.app import app

class ProductionSequenceFlow(unittest.TestCase):
 def test_exact_interval_relocation_save_and_balance(self):
  c=TestClient(app);background=c.get('/api/demo').json()['csv']
  project=c.post('/api/projects',json={'name':'生产序列嵌入验证','state':{'csv':background}}).json()
  event='timestamp,load_kw,wind_kw,pv_kw\n2025-01-01 00:00,5000,0,0\n2025-01-01 01:00,6000,0,0'
  payload={'project_id':project['id'],'background_csv':background,'event_csv':event,'start_hour':12}
  response=c.post('/api/production-sequences',json=payload)
  self.assertEqual(response.status_code,200,response.text)
  result=response.json();rows=result['rows']
  self.assertEqual(len(rows),48)
  self.assertEqual(sum(row['is_extreme_condition'] for row in rows),2)
  self.assertEqual(rows[12]['load_kw'],5000)
  self.assertEqual(rows[13]['load_kw'],6000)
  original=pd.read_csv(io.StringIO(background));produced=pd.read_csv(io.StringIO(result['csv']))
  pd.testing.assert_frame_equal(produced.iloc[:12],original.iloc[:12])
  pd.testing.assert_frame_equal(produced.iloc[14:],original.iloc[14:])
  self.assertEqual(list(produced.columns),list(original.columns))
  self.assertEqual(produced.timestamp.tolist(),original.timestamp.tolist())
  self.assertIn(result['id'],[r['id'] for r in c.get('/api/production-sequences',params={'project_id':project['id']}).json()])
  balance_input={'project_id':project['id'],'project_revision':1,'production_sequence_id':result['id'],'csv':result['csv'],'parameters':{}}
  checked=c.post('/api/balance',json=balance_input)
  self.assertEqual(checked.status_code,200,checked.text)
  calculation=checked.json()
  self.assertEqual(calculation['production_snapshot']['event_start'],result['event_start'])
  self.assertEqual(calculation['production_snapshot']['parameters']['start_hour'],12)
  self.assertEqual(len(calculation['production_snapshot']['event_sha256']),64)
  self.assertIn('生产序列来源与嵌入参数',c.get('/api/runs/'+calculation['id']+'/report').text)
  self.assertEqual(c.post('/api/balance',json={**balance_input,'csv':result['csv'].replace('5000.0','5001.0')}).status_code,422)
  other=c.post('/api/projects',json={'name':'序列隔离验证','state':{}}).json()
  self.assertEqual(c.post('/api/balance',json={**balance_input,'project_id':other['id']}).status_code,422)
  random=c.post('/api/random-balance',json={'source_run_id':calculation['id'],'samples':2,'rate_per_hour':0}).json()
  for sample in random['samples']:
   self.assertEqual(c.get('/api/runs/'+sample['run_id']).json()['production_sequence_id'],result['id'])
  adjustment=c.post('/api/strategy-evaluation',json={'source_run_id':calculation['id'],'parameters':calculation['parameters']}).json()
  self.assertEqual(c.get('/api/runs/'+adjustment['run_id']).json()['production_sequence_id'],result['id'])
  scaled=c.post('/api/strategy-evaluation',json={'source_run_id':calculation['id'],'parameters':calculation['parameters'],'wind_scale':2}).json()
  self.assertIsNone(c.get('/api/runs/'+scaled['run_id']).json()['production_sequence_id'])
  plan=c.post('/api/planning',json={'run_id':calculation['id'],'max_storage_units':0,'max_emergency_units':0,'max_mobile_units':0}).json()
  verification=c.post('/api/plans/'+plan['id']+'/verify').json()
  self.assertEqual(c.get('/api/runs/'+verification['run_id']).json()['production_sequence_id'],result['id'])
  self.assertEqual(c.post('/api/production-sequences',json={**payload,'start_hour':47}).status_code,422)
  smoothed=c.post('/api/production-sequences',json={**payload,'smooth':True}).json()
  self.assertNotEqual(smoothed['rows'][11]['load_kw'],rows[11]['load_kw'])
  self.assertEqual(smoothed['rows'][12]['load_kw'],5000)

if __name__=='__main__':unittest.main()
