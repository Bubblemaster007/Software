import copy,unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import app
from backend.comparison import comparison_report
class ComparisonTests(unittest.TestCase):
 def records(self):
  a={'id':'baseline','project_id':'A','created':'2026-01-01','project_revision':1,'model':'aggregate','algorithm':'topic2.aggregate.v2','scope':'<script>test</script>','input_csv':'timestamp,load_kw,wind_kw,pv_kw\n2026-01-01 00:00,1,0,0','parameters':{'storage_power_kw':0},'metrics':{'max_power_deficit_kw':100,'expected_energy_deficit_kwh':200,'critical_load_supply_ratio':.8,'loss_of_load_probability':.5},'stages':[],'failed_lines':[]}
  b=copy.deepcopy(a);b['id']='comparison';b['parameters']['storage_power_kw']=100;b['metrics']['expected_energy_deficit_kwh']=50
  return a,b
 def test_report_contains_snapshot_delta_and_escapes_text(self):
  a,b=self.records();text=comparison_report(a,b)
  self.assertIn('-150',text);self.assertIn('SHA256',text);self.assertIn('可结合资源参数差异',text)
  self.assertNotIn('<script>',text);self.assertIn('&lt;script&gt;',text)
  b['scenario_id']='fault';self.assertIn('不能直接归因',comparison_report(a,b))
  b['scenario_id']=None;b['production_sequence_id']='event';self.assertIn('条件不同：生产序列引用',comparison_report(a,b))
 def test_download_and_cross_project_rejection(self):
  a,b=self.records();records={a['id']:a,b['id']:b};client=TestClient(app)
  with patch('backend.app.get_run',side_effect=lambda key:records[key]):
   r=client.get('/api/comparison-report?baseline_id=baseline&comparison_id=comparison');self.assertEqual(r.status_code,200);self.assertIn('attachment',r.headers['content-disposition'])
   b['project_id']='B';self.assertEqual(client.get('/api/comparison-report?baseline_id=baseline&comparison_id=comparison').status_code,422)
if __name__=='__main__':unittest.main()
