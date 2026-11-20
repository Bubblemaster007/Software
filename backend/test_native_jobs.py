import io,unittest,zipfile
from unittest.mock import patch
import pandas as pd
from fastapi.testclient import TestClient
from backend.app import app
from backend.native_worker import run

class NativeJobs(unittest.TestCase):
 def test_real_native_dispatch_and_archive(self):
  c=TestClient(app);demo=c.get('/api/demo').json()['csv'];p=c.post('/api/projects',json={'name':'原生流水线验证'}).json()
  frame=pd.read_csv(io.StringIO(demo)).iloc[:36].copy();frame['event_id']=0;frame['wind_speed']=0
  request={'project_id':p['id'],'project_revision':1,'csv':frame.to_csv(index=False),'parameters':{'grid_channel_kw':4000},'event_samples':2}
  with patch('backend.native_jobs.launch'):
   response=c.post('/api/native-jobs',json=request)
  self.assertEqual(response.status_code,200,response.text);id=response.json()['id']
  # Real original IEEE33 dispatch, stage statistics and planning; no fixture metrics.
  run(id);detail=c.get('/api/native-jobs/'+id).json();self.assertEqual(detail['status'],'succeeded',detail.get('error'))
  self.assertEqual(detail['result']['valid_event_count'],1)
  self.assertEqual(c.get('/api/native-jobs/'+id+'/input').json()['csv'],request['csv'])
  hourly=pd.read_csv(io.StringIO(c.get('/api/native-jobs/'+id+'/file',params={'path':'balance/hourly_balance.csv'}).text))
  self.assertEqual(len(hourly),36)
  self.assertAlmostEqual(hourly.power_deficit_kw.sum(),detail['result']['metrics']['expected_energy_deficit_kwh'])
  self.assertTrue(any(f['path']=='events/event_0000/event_phase_samples.csv' for f in c.get('/api/native-jobs/'+id+'/files').json()))
  archive=c.get('/api/native-jobs/'+id+'/archive');self.assertEqual(archive.status_code,200)
  with zipfile.ZipFile(io.BytesIO(archive.content)) as z:self.assertIn('outputs/run_summary.json',z.namelist());self.assertIn('input.json',z.namelist())
  self.assertEqual(c.get('/api/native-jobs/'+id+'/file',params={'path':'../../platform.db'}).status_code,404)
 def test_bad_event_and_resource_rate_columns_rejected(self):
  c=TestClient(app);p=c.post('/api/projects',json={'name':'原生输入校验'}).json();frame=pd.read_csv(io.StringIO(c.get('/api/demo').json()['csv'])).iloc[:2].copy();frame['event_id']=0;frame['wind_speed']=0
  body={'project_id':p['id'],'project_revision':1,'csv':frame.to_csv(index=False)}
  self.assertEqual(c.post('/api/native-jobs',json=body).status_code,422)
  frame['event_id']=-1;frame['failure_rate_per_hour_storage']=.1
  self.assertEqual(c.post('/api/native-jobs',json={**body,'csv':frame.to_csv(index=False)}).status_code,422)

if __name__=='__main__':unittest.main()
