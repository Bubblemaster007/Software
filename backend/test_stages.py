import unittest
from fastapi.testclient import TestClient
from backend.app import app
class StageTests(unittest.TestCase):
 def test_fault_repair_and_stage_totals(self):
  c=TestClient(app);csv=c.get('/api/demo').json()['csv'];payload={'csv':csv,'parameters':{'grid_channel_kw':4000},'model':'case33','stages':[{'name':'故障','end_hour':12,'failed_lines':[1]},{'name':'恢复','end_hour':48}]}
  r=c.post('/api/balance',json=payload);self.assertEqual(r.status_code,200,r.text);d=r.json()
  self.assertTrue(all(abs(x['power_deficit_kw']-x['load_kw'])<1e-6 for x in d['rows'][:12]))
  self.assertTrue(all(x['power_deficit_kw']<1e-6 for x in d['rows'][12:]))
  self.assertAlmostEqual(sum(x['expected_energy_not_served_mwh'] for x in d['phase_metrics'])*1000,d['metrics']['expected_energy_deficit_kwh'],places=4)
  self.assertEqual(d['rows'][11]['stage'],'故障');self.assertEqual(d['rows'][12]['stage'],'恢复')
  self.assertEqual(len(d['network_details']),48)
  for row,snapshot in zip(d['rows'],d['network_details']):
   self.assertEqual(len(snapshot['nodes']),33);self.assertEqual(len(snapshot['lines']),32)
   self.assertAlmostEqual(sum(n['load_kw'] for n in snapshot['nodes']),row['load_kw'],places=5)
   self.assertAlmostEqual(sum(n['served_kw'] for n in snapshot['nodes']),row['load_served_kw'],places=5)
   self.assertTrue(all(n['linear_voltage_pu'] is None for n in snapshot['nodes'] if not n['connected']))
  broken=d['network_details'][11];restored=d['network_details'][12]
  self.assertTrue(broken['lines'][0]['failed']);self.assertAlmostEqual(broken['lines'][0]['flow_kw'],0)
  self.assertFalse(restored['lines'][0]['failed']);self.assertTrue(all(n['connected'] for n in restored['nodes']))
 def test_gaps_and_reverse_end_rejected(self):
  c=TestClient(app);csv=c.get('/api/demo').json()['csv']
  for ends in ([12,47],[20,12,48],[12,12,48]):
   r=c.post('/api/balance',json={'csv':csv,'parameters':{},'stages':[{'name':str(i),'end_hour':e} for i,e in enumerate(ends)]})
   self.assertEqual(r.status_code,422)
 def test_soc_continues_between_stages(self):
  c=TestClient(app);csv='timestamp,load_kw,wind_kw,pv_kw\n2026-01-01 00:00,100,0,0\n2026-01-01 01:00,100,0,0'
  p={'csv':csv,'parameters':{'emergency_gen_kw':0,'storage_energy_kwh':1000}}
  a=c.post('/api/balance',json=p).json();p['stages']=[{'name':'一','end_hour':1},{'name':'二','end_hour':2}];b=c.post('/api/balance',json=p).json()
  self.assertEqual([x['soc'] for x in a['rows']],[x['soc'] for x in b['rows']]);self.assertLess(b['rows'][1]['soc'],b['rows'][0]['soc'])
 def test_stage_names_are_distinct_after_trimming(self):
  c=TestClient(app);csv=c.get('/api/demo').json()['csv']
  for names in (['故障','故障'],['故障',' 故障 '],[' ','恢复']):
   r=c.post('/api/balance',json={'csv':csv,'parameters':{},'stages':[{'name':names[0],'end_hour':12},{'name':names[1],'end_hour':48}]})
   self.assertEqual(r.status_code,422,r.text)
  r=c.post('/api/balance',json={'csv':csv,'parameters':{},'stages':[{'name':' 故障 ','end_hour':12},{'name':' 恢复 ','end_hour':48}]})
  self.assertEqual(r.status_code,200,r.text)
  d=r.json();self.assertEqual([x['name'] for x in d['stages']],['故障','恢复'])
  self.assertEqual(len(d['phase_metrics']),2)
if __name__=='__main__':unittest.main()
