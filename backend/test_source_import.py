import unittest
from backend.source_import import normalize

class SourceImportTests(unittest.TestCase):
 def test_raw_history_columns_extra_fields_and_bom(self):
  text='\ufefftime,load,wind_power,solar_power,wind_speed,load_imputed\n2023-01-01 00:00:00,17322.75,298.806,0,12,false\n2023-01-01 01:00:00,16756,286,0,13,true\n'
  result=normalize(text,'history.csv')
  self.assertEqual(result['rows'],2);self.assertIn('17322.75,298.806,0.0',result['csv'])
  self.assertEqual(result['source_import']['extra_columns'],['wind_speed','load_imputed'])
  self.assertEqual(result['csv'].splitlines()[0],'timestamp,load_kw,wind_kw,pv_kw')
 def test_reordered_quoted_tab_and_millisecond_times(self):
  result=normalize('光伏(kW)\t时间\t风电(kW)\t负荷(kW)\n0\t2023/01/01 00:00:00.000\t2\t10\n1\t2023/01/01 01:00:00.000\t3\t20\n')
  self.assertIn('2023-01-01 00:00:00,10.0,2.0,0.0',result['csv'])
  self.assertEqual(normalize('"timestamp","load_kw","wind_kw","pv_kw"\n"2023-01-01 00:00:00",10,2,0\n"2023-01-01 01:00:00",20,3,1')['rows'],2)
 def test_no_guessing_or_filling(self):
  base='time,load,wind_power,solar_power\n2023-01-01 00:00:00,10,2,0\n2023-01-01 01:00:00,20,3,1'
  for value in [base.replace('01:00:00','02:00:00'),base.replace(',20,',',,'),base.replace(',20,',',-1,'),base.replace(',20,',',NaN,'),base.replace('load,','load_mw,'),base.replace('time,','time,timestamp,')]:
   with self.subTest(value=value),self.assertRaises(ValueError):normalize(value)
 def test_leap_year_not_silently_truncated(self):
  import pandas as pd
  text='time,load,wind_power,solar_power\n'+'\n'.join(str(t)+',1,2,3' for t in pd.date_range('2024-01-01',periods=8784,freq='h'))
  with self.assertRaisesRegex(ValueError,'8784'):normalize(text)

if __name__=='__main__':unittest.main()
