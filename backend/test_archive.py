import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import backend.app as service

class ArchiveTests(unittest.TestCase):
 def test_paging_filtering_and_project_isolation(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(service,'DATA',Path(folder)):
   with service.db() as connection:
    for i in range(125):
     record={'id':str(i),'created':'2026-01-01T00:00:00','project_id':'A' if i<124 else 'B','model':'aggregate'}
     if i%3==1:record['baseline_run_id']='baseline'
     if i%3==2:record.update(baseline_run_id='baseline',random_batch_id='batch')
     connection.execute('INSERT INTO runs VALUES(?,?,?)',(record['id'],record['created'],json.dumps(record)))
   connection.close()
   client=TestClient(service.app)
   first=client.get('/api/run-archive',params={'project_id':'A','limit':20}).json()
   self.assertEqual(first['total'],124);self.assertEqual(first['items'][0]['id'],'123')
   pages=[client.get('/api/run-archive',params={'project_id':'A','limit':20,'offset':i}).json()['items'] for i in range(0,124,20)]
   ids=[item['id'] for page in pages for item in page]
   self.assertEqual(len(ids),124);self.assertEqual(len(set(ids)),124);self.assertNotIn('124',ids)
   for kind,key in [('random','random_batch_id'),('adjustment','baseline_run_id')]:
    items=client.get('/api/run-archive',params={'project_id':'A','kind':kind,'limit':100}).json()['items']
    self.assertTrue(items);self.assertTrue(all(item[key] for item in items))
    if kind=='adjustment':self.assertTrue(all(not item['random_batch_id'] for item in items))
   items=client.get('/api/run-archive',params={'project_id':'A','kind':'baseline','limit':100}).json()['items']
   self.assertTrue(all(not item['baseline_run_id'] and not item['random_batch_id'] for item in items))
   self.assertEqual(client.get('/api/run-archive?project_id=A&limit=101').status_code,422)
   self.assertEqual(len(client.get('/api/runs?project_id=A').json()),100)
   self.assertEqual(len(client.get('/api/runs?project_id=A&offset=100').json()),24)
if __name__=='__main__':unittest.main()
