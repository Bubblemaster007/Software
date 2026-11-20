import io
import unittest
import pandas as pd
from fastapi.testclient import TestClient
from backend.app import app


class ExtremeWindowFlow(unittest.TestCase):
 def test_window_source_alignment_reproducibility_and_balance(self):
  c=TestClient(app)
  csv=c.get('/api/demo').json()['csv']
  project=c.post('/api/projects',json={'name':'极端窗口闭环验证','state':{'csv':csv}}).json()
  payload={'project_id':project['id'],'csv':csv,'window':36,'seed':42}
  response=c.post('/api/source-analysis',json=payload)
  self.assertEqual(response.status_code,200,response.text)
  data=response.json();window=data['extreme_window']
  self.assertEqual(len(window['rows']),36)
  self.assertEqual(window['rows'][0]['timestamp'],data['windows'][0]['window_start'])
  self.assertEqual(window['hazard'],c.post('/api/source-analysis',json=payload).json()['extreme_window']['hazard'])
  original=pd.read_csv(io.StringIO(csv));selected=pd.read_csv(io.StringIO(window['csv']))
  self.assertEqual(list(selected.columns),list(original.columns))
  pd.testing.assert_frame_equal(selected,original[original.timestamp.isin(selected.timestamp)].reset_index(drop=True))
  result=c.post('/api/balance',json={'csv':window['csv'],'parameters':{}})
  self.assertEqual(result.status_code,200,result.text)
  self.assertEqual(len(result.json()['rows']),36)
  self.assertEqual(c.post('/api/source-analysis',json={**payload,'window':49}).status_code,422)


if __name__=='__main__':unittest.main()
