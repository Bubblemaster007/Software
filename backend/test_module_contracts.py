import hashlib,json,unittest
from fastapi.testclient import TestClient
from backend.app import app
from backend.module_contracts import ADAPTERS,register_adapter

class ModuleContracts(unittest.TestCase):
 def test_snapshot_isolation_adapter_and_result_versioning(self):
  c=TestClient(app);csv=c.get('/api/demo').json()['csv'];p=c.post('/api/projects',json={'name':'模块接口验证','state':{'csv':csv,'model':'case33'}}).json()
  run=c.post('/api/balance',json={'csv':csv,'project_id':p['id'],'project_revision':1,'parameters':{}}).json()
  request={'module':'island_stability','project_id':p['id'],'project_revision':1,'source_run_id':run['id'],'parameters':{'island_nodes':[1,2],'frequency_min_hz':49.5}}
  r=c.post('/api/integration/requests',json=request);self.assertEqual(r.status_code,200,r.text);record=r.json();id=record['id']
  self.assertEqual(record['request_sha256'],hashlib.sha256(json.dumps(record['input'],ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest())
  self.assertEqual(record['input']['baseline_run']['metrics'],run['metrics'])
  self.assertEqual(c.post(f'/api/integration/requests/{id}/execute').status_code,409)
  c.put('/api/projects/'+p['id'],json={'name':'接口验证改名','expected_revision':1,'state':{'csv':'modified'}})
  self.assertEqual(c.get('/api/integration/requests/'+id).json()['input']['project']['state']['csv'],csv)
  result={'request_sha256':record['request_sha256'],'algorithm_version':'test-fixture.1','status':'succeeded','summary':'测试适配器连通性，无物理判别结论','checks':[{'name':'物理稳定性','status':'not_checked'}]}
  def handler(snapshot,digest):
   self.assertEqual(snapshot['parameters']['island_nodes'],[1,2]);self.assertEqual(digest,record['request_sha256']);return result
  register_adapter('island_stability','test-fixture.1',handler)
  try:
   response=c.post(f'/api/integration/requests/{id}/execute');self.assertEqual(response.status_code,200,response.text)
   self.assertEqual(response.json()['result_origin'],'registered_adapter')
   self.assertEqual(c.post(f'/api/integration/requests/{id}/result',json=result).status_code,409)
  finally:ADAPTERS.pop('island_stability',None)
  self.assertEqual(c.post('/api/integration/requests',json=request).status_code,409)
 def test_cross_project_and_digest_rejected(self):
  c=TestClient(app);p=c.post('/api/projects',json={'name':'交接隔离A'}).json();other=c.post('/api/projects',json={'name':'交接隔离B'}).json()
  run=c.post('/api/balance',json={'csv':c.get('/api/demo').json()['csv'],'project_id':other['id'],'project_revision':1,'parameters':{}}).json()
  body={'project_id':p['id'],'project_revision':1,'module':'black_start'}
  self.assertEqual(c.post('/api/integration/requests',json={**body,'source_run_id':run['id']}).status_code,422)
  record=c.post('/api/integration/requests',json=body).json()
  result={'request_sha256':'0'*64,'algorithm_version':'external1','status':'failed','summary':'输入不匹配'}
  self.assertEqual(c.post('/api/integration/requests/'+record['id']+'/result',json=result).status_code,422)
  result['request_sha256']=record['request_sha256']
  r=c.post('/api/integration/requests/'+record['id']+'/result',json=result);self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json()['result_origin'],'external_import_unverified')

if __name__=='__main__':unittest.main()
