import io,unittest
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from backend.app import app

class Studies(unittest.TestCase):
 def test_original_outputs_reproducible_and_classified_load_conserved(self):
  c=TestClient(app);csv=c.get('/api/demo').json()['csv'];p=c.post('/api/projects',json={'name':'多水平年源荷验证','state':{'csv':csv}}).json()
  body={'project_id':p['id'],'csv':csv,'seed':17,'critical_ratio':.25,'important_ratio':.3,'horizons':[{'name':'近期','year':2028},{'name':'远期','year':2035,'growth':.35}]}
  response=c.post('/api/source-studies',json=body);self.assertEqual(response.status_code,200,response.text);study=response.json()
  self.assertEqual(len(study['horizons']),2)
  repeat=c.post('/api/source-studies',json=body).json()
  def table(id,kind,horizon=0):
   r=c.get(f'/api/source-studies/{id}/csv',params={'kind':kind,'horizon':horizon});self.assertEqual(r.status_code,200,r.text[:100]);return pd.read_csv(io.StringIO(r.text))
  for horizon in range(2):
   annual=table(study['id'],'annual',horizon);pd.testing.assert_frame_equal(annual,table(repeat['id'],'annual',horizon))
   self.assertEqual(len(annual),8760);self.assertTrue(pd.to_datetime(annual.timestamp).diff().iloc[1:].eq(pd.Timedelta(hours=1)).all())
   self.assertTrue(np.isfinite(annual.iloc[:,1:]).all().all());self.assertTrue(annual.iloc[:,1:].ge(0).all().all())
   classified=table(study['id'],'classified',horizon)
   np.testing.assert_allclose(classified.forecast_load_kw,classified.critical_load_kw+classified.important_load_kw+classified.general_load_kw)
   self.assertFalse(table(study['id'],'load_boundary',horizon).empty);self.assertFalse(table(study['id'],'renewable_boundary',horizon).empty)
  decomposition=table(study['id'],'decomposition')
  np.testing.assert_allclose(decomposition.load_kw,decomposition.load_trend_kw+decomposition.load_daily_component_kw+decomposition.load_high_frequency_kw)
  self.assertEqual(c.get('/api/projects/'+p['id']).json()['state']['csv'],csv)
  self.assertEqual(len(c.get('/api/source-studies',params={'project_id':p['id']}).json()),2)
  self.assertEqual(c.get(f"/api/source-studies/{study['id']}/csv?horizon=8").status_code,422)
  for invalid in [{'critical_ratio':.9,'important_ratio':.9},{'csv':csv.replace(',700',',-700')+'\ninvalid'}, {'horizons':[{'name':'a','year':2028},{'name':'a','year':2030}]}]:
   self.assertEqual(c.post('/api/source-studies',json={**body,**invalid}).status_code,422)

if __name__=='__main__':unittest.main()
