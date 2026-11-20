import unittest, copy, io
import pandas as pd
from fastapi.testclient import TestClient
from backend.app import app

class EditableNetworkTests(unittest.TestCase):
 def setUp(self):
  self.c=TestClient(app)
  self.network={'name':'三节点验证','source':'测试参数','base_voltage_kv':10,'nodes':[{'node':1,'pd_kw':0},{'node':7,'pd_kw':50},{'node':42,'pd_kw':50}], 'lines':[{'line':100,'from_node':7,'to_node':1,'r_ohm':.1,'x_ohm':.1},{'line':300,'from_node':42,'to_node':7,'r_ohm':.1,'x_ohm':.1}]}
  self.payload={'model':'case33','network':self.network,'network_parameters':{'wind_node':7,'pv_node':42},'parameters':{'grid_channel_kw':1000,'storage_power_kw':0,'storage_energy_kwh':0,'emergency_gen_kw':0},'csv':'timestamp,load_kw,wind_kw,pv_kw\n2026-01-01 00:00,100,0,0\n2026-01-01 01:00,100,0,0\n'}
 def test_custom_topology_fault_recovery_and_archive(self):
  self.payload['stages']=[{'name':'故障','end_hour':1,'failed_lines':[300]},{'name':'恢复','end_hour':2}]
  r=self.c.post('/api/balance',json=self.payload);self.assertEqual(r.status_code,200,r.text);d=r.json()
  self.assertAlmostEqual(d['rows'][0]['power_deficit_kw'],50,places=4)
  self.assertAlmostEqual(d['rows'][1]['power_deficit_kw'],0,places=4)
  self.assertEqual(d['network']['lines'][0]['from_node'],1)
  for row in d['rows']:
   self.assertAlmostEqual(row['firm_grid_dispatch_kw'],row['load_served_kw']+row['estimated_line_loss_kw'],places=4)
  saved=self.c.get('/api/runs/'+d['id']).json();self.assertEqual(saved['network'],d['network'])
  self.assertIn('三节点验证',self.c.get('/api/runs/'+d['id']+'/report').text)
  adjusted=self.c.post('/api/strategy-evaluation',json={'source_run_id':d['id'],'parameters':d['parameters']})
  self.assertEqual(adjusted.status_code,200,adjusted.text)
  self.assertEqual(self.c.get('/api/runs/'+adjusted.json()['run_id']).json()['network'],d['network'])
 def test_invalid_topology_and_fault_ids(self):
  for change in ['duplicate','cycle','missing','negative','zero_load']:
   n=copy.deepcopy(self.network)
   if change=='duplicate':n['lines'][1]['line']=100
   if change=='cycle':n['lines'].append({'line':400,'from_node':1,'to_node':42,'r_ohm':.1,'x_ohm':.1})
   if change=='missing':n['lines'][0]['to_node']=999
   if change=='negative':n['lines'][0]['r_ohm']=-1
   if change=='zero_load':
    for node in n['nodes']:node['pd_kw']=0
   self.assertEqual(self.c.post('/api/network/validate',json=n).status_code,422,change)
  for ids in [[1],[100,100],[999]]:
   self.payload['failed_lines']=ids
   self.assertEqual(self.c.post('/api/balance',json=self.payload).status_code,422)
 def test_source_data_conversion(self):
  files=self.c.get('/api/alashankou').json()['files'];loads=[f for f in files if f['kind']=='load'];self.assertEqual(len(loads),2)
  for f in loads:
   mw=self.c.get('/api/alashankou/'+f['id']+'/preview?unit=MW');self.assertEqual(mw.status_code,200,mw.text)
   kw=self.c.get('/api/alashankou/'+f['id']+'/preview?unit=kW').json()
   d=mw.json();self.assertEqual(len(d['rows']),24);self.assertEqual(d['source_import']['raw_samples'],289)
   self.assertAlmostEqual(d['rows'][0]['load_kw'],1000*kw['rows'][0]['load_kw'])
   df=pd.read_csv(io.StringIO(d['csv']));self.assertTrue((df.wind_kw==0).all())
   self.assertEqual(self.c.get('/api/alashankou/'+f['id']+'/file').status_code,200)
   run=self.c.post('/api/balance',json={'csv':d['csv'],'parameters':{'grid_channel_kw':50000},'source_import':d['source_import']})
   self.assertEqual(run.status_code,200,run.text)
   self.assertEqual(run.json()['source_import'],d['source_import'])
   self.assertAlmostEqual(run.json()['metrics']['expected_energy_deficit_kwh'],0)
   self.assertIn('阿拉山口源荷来源',self.c.get('/api/runs/'+run.json()['id']+'/report').text)
  wind=next(f for f in files if f['kind']=='wind_monthly')
  d=self.c.get('/api/alashankou/'+wind['id']+'/preview').json();self.assertEqual(d['kind'],'wind_monthly');self.assertNotIn('csv',d)
if __name__=='__main__':unittest.main()
