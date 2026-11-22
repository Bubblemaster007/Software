import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import pandas as pd
from fastapi import HTTPException
from backend import input_datasets as datasets

class HistoricalInputTests(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory();self.path=Path(self.temp.name)/'history.csv'
  pd.DataFrame({'time':pd.date_range('2024-02-28',periods=72,freq='h'),'load':[10.,20.,30.]*24,
   'wind_power':[2.,4.,6.]*24,'solar_power':[0.,1.,2.]*24,'load_imputed':[False,True,False]*24}).to_csv(self.path,index=False)
 def tearDown(self):self.temp.cleanup()
 def entry(self,kind):return patch.object(datasets,'entries',return_value={'chosen':(self.path,'history',kind)})
 def test_physical_units_and_provenance(self):
  with self.entry('alashankou'),patch.object(datasets,'alash_network',return_value={'nodes':[]}):r=datasets.preview('chosen',24,48)
  self.assertEqual(r['rows'][0]['load_kw'],10.)
  self.assertEqual(r['source_import']['sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())
  self.assertEqual(r['source_import']['quality_counts']['load_imputed'],16)
  self.assertEqual(r['source_import']['first_timestamp'],'2024-02-29 00:00:00')
  self.assertEqual(r['network_parameters'],{'wind_node':1,'pv_node':1})
 def test_example_preserves_joint_ratios_and_uses_full_year_scale(self):
  with self.entry('extreme'):r=datasets.preview('chosen',0,2)
  self.assertAlmostEqual(r['source_import']['scale_factor'],3715/30)
  self.assertAlmostEqual(r['rows'][0]['wind_kw']/r['rows'][0]['load_kw'],.2)
  self.assertIsNone(r['network'])
 def test_no_silent_time_axis_repair(self):
  frame=pd.read_csv(self.path);frame=frame.drop(25);frame.to_csv(self.path,index=False)
  with self.entry('extreme'),self.assertRaises(HTTPException) as error:datasets.preview('chosen',24,2)
  self.assertIn('不连续',str(error.exception.detail))
 def test_missing_file_never_falls_back_to_demo(self):
  with patch.object(datasets,'entries',return_value={'chosen':(self.path.parent/'absent.csv','history','extreme')}),self.assertRaises(HTTPException) as error:datasets.preview('chosen',0,2)
  self.assertEqual(error.exception.status_code,404)
 def test_range_exceeding_source_rejected(self):
  with self.entry('extreme'),self.assertRaises(HTTPException):datasets.preview('chosen',71,2)
 def test_no_arbitrary_path_access(self):
  with self.entry('extreme'),self.assertRaises(HTTPException) as error:datasets.preview('../secret',0,2)
  self.assertEqual(error.exception.status_code,404)
 def test_api_preview_and_input_limits(self):
  from fastapi.testclient import TestClient
  from backend.app import app
  client=TestClient(app)
  with self.entry('extreme'):
   response=client.get('/api/input-datasets/chosen/preview?start=0&hours=24')
   self.assertEqual(response.status_code,200,response.text)
   self.assertEqual(response.json()['source_import']['hours'],24)
   self.assertEqual(client.get('/api/input-datasets/chosen/preview?hours=8784').status_code,422)
 def test_old_typical_day_cannot_submit_new_balance(self):
  from fastapi.testclient import TestClient
  from backend.app import app
  response=TestClient(app).post('/api/balance',json={'csv':'timestamp,load_kw,wind_kw,pv_kw\n2023-01-01 00:00,10,2,0\n2023-01-01 01:00,10,2,0',
   'parameters':{},'source_import':{'file':'阿拉山口市典型负荷曲线（6.22）.xlsx'}})
  self.assertEqual(response.status_code,422)
  self.assertIn('6.22',response.text)
 @unittest.skipUnless((datasets.ALASH/'01_风光荷数据/风光荷_2023.csv').is_file(),'本机阿拉山口资料未安装')
 def test_installed_history_network_balance_and_provenance(self):
  import importlib
  from fastapi.testclient import TestClient
  module=importlib.import_module('backend.app')
  data=datasets.preview('alashankou-2023',0,2)
  self.assertEqual(len(data['network']['nodes']),51)
  self.assertEqual(sum(x['status'] for x in data['network']['lines']),50)
  with patch.object(module,'DATA',Path(self.temp.name)):
   response=TestClient(module.app).post('/api/balance',json={'csv':data['csv'],'parameters':{'grid_channel_kw':30000},
    'network':data['network'],'network_parameters':data['network_parameters'],'branch_limit_kw':data['branch_limit_kw'],
    'source_import':data['source_import'],'model':'case33'})
   self.assertEqual(response.status_code,200,response.text)
   self.assertEqual(response.json()['source_import'],data['source_import'])
   self.assertEqual(len(response.json()['rows']),2)

if __name__=='__main__':unittest.main()
