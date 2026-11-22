import copy,importlib,sqlite3,json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from fastapi.testclient import TestClient
from backend.scenario_configuration import configuration_matches,csv_signature

class ScenarioConfigurationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'data').mkdir()
  self.platform=importlib.import_module('backend.app');self.workspace=importlib.import_module('backend.workspace');self.progress=importlib.import_module('backend.workflow_progress')
  self.patches=[patch.object(self.platform,'DATA',self.root/'data'),patch.object(self.workspace,'ROOT',self.root),patch.object(self.progress,'ROOT',self.root)]
  for p in self.patches:p.start()
  self.client=TestClient(self.platform.app)
  self.network={'name':'隔离三节点验证','source':'仅测试','base_voltage_kv':10,'nodes':[{'node':1,'pd_kw':0},{'node':7,'pd_kw':50},{'node':42,'pd_kw':50}],'lines':[{'line':100,'from_node':1,'to_node':7,'r_ohm':.1,'x_ohm':.1,'status':1},{'line':300,'from_node':7,'to_node':42,'r_ohm':.1,'x_ohm':.1,'status':1}]}
  self.csv='timestamp,load_kw,wind_kw,pv_kw\n2023-01-01 00:00,100,0,0\n2023-01-01 01:00,100,0,0\n'
  self.parameters={'grid_channel_kw':1000,'storage_power_kw':0,'storage_energy_kwh':0,'emergency_gen_kw':0}
 def tearDown(self):
  for p in self.patches:p.stop()
  self.tmp.cleanup()
 def calculate(self,**extra):
  response=self.client.post('/api/balance',json={'csv':self.csv,'parameters':self.parameters,'network':self.network,'network_parameters':{'wind_node':7,'pv_node':42},**extra});self.assertEqual(response.status_code,200,response.text);return response.json()
 def test_a_regular_without_fault_records(self):
  result=self.calculate(operating_condition='normal');self.assertEqual(result['scenario_id'],None);self.assertAlmostEqual(result['metrics']['expected_energy_deficit_kwh'],0)
 def test_c_manual_fault_reaches_solver(self):
  result=self.calculate(model='case33',failed_lines=[300],operating_condition='extreme');self.assertTrue(all(next(l for l in hour['lines'] if l['line']==300)['failed'] for hour in result['network_details']));self.assertAlmostEqual(result['rows'][0]['power_deficit_kw'],50,places=3)
 def test_staged_fault_and_recovery(self):
  result=self.calculate(model='case33',failed_lines=[],stages=[{'name':'故障','end_hour':1,'failed_lines':[300]},{'name':'恢复','end_hour':2,'failed_lines':[]}]);self.assertAlmostEqual(result['rows'][0]['power_deficit_kw'],50,places=3);self.assertAlmostEqual(result['rows'][1]['power_deficit_kw'],0,places=3);self.assertFalse(next(l for l in result['network_details'][1]['lines'] if l['line']==300)['failed'])
 def test_b_extreme_source_without_devices(self):
  self.csv=self.csv.replace(',100,0,0',',150,0,0');result=self.calculate(operating_condition='extreme');self.assertEqual(result['operating_condition'],'extreme');self.assertIsNone(result['scenario_id'])
 def test_e_random_and_embedding_actual_apis(self):
  project=self.client.post('/api/projects',json={'name':'隔离嵌入','state':{}}).json()
  scene=self.client.post('/api/scenarios/sequential',json={'project_id':project['id'],'name':'验证随机','csv':self.csv,'resource':'grid_channel','rated_kw':1000,'rate_per_hour':0,'repair_hours':1,'seed':42});self.assertEqual(scene.status_code,200,scene.text)
  embedded=self.client.post('/api/production-sequences',json={'project_id':project['id'],'background_csv':self.csv,'event_csv':self.csv.replace(',100,0,0',',120,0,0'),'start_hour':0,'smooth':False,'ramp_hours':1,'scenario_id':scene.json()['id'],'resource_capacities':{k:v for k,v in self.parameters.items() if k!='storage_energy_kwh'}});self.assertEqual(embedded.status_code,200,embedded.text)
  value=embedded.json();result=self.calculate(project_id=project['id'],project_revision=project['revision'],production_sequence_id=value['id'],scenario_id=value['embedded_scenario_id'],csv=value['csv'],operating_condition='extreme');self.assertEqual(result['production_sequence_id'],value['id'])
 def test_history_read_does_not_change_project(self):
  project=self.client.post('/api/projects',json={'name':'历史只读','state':{'csv':self.csv}}).json();result=self.calculate(project_id=project['id'],project_revision=1);before=self.client.get('/api/projects/'+project['id']).json();self.client.get('/api/runs/'+result['id']);self.assertEqual(before,self.client.get('/api/projects/'+project['id']).json())
 def test_progress_explicit_regular_confirmation_and_freshness(self):
  state={'csv':self.csv,'network':None,'operatingCondition':'常规运行','scenarioId':None,'productionSequenceId':None,'failedLines':'','stages':[]}
  state['scenarioConfiguration']={'name':'常规','snapshot':{'csvSignature':csv_signature(self.csv),'network':None,'condition':'常规运行','scenarioId':None,'productionId':None,'failedLines':[],'stages':[]}}
  self.assertTrue(configuration_matches(state['scenarioConfiguration'],state));project=self.client.post('/api/projects',json={'name':'无故障场景确认','state':state}).json();evidence=self.client.get('/api/workflow-progress/'+project['id']).json();self.assertEqual(evidence['scenario_evidence']['state'],'applied');state['csv']=self.csv.replace('100','120');self.assertFalse(configuration_matches(state['scenarioConfiguration'],state))

if __name__=='__main__':unittest.main()

