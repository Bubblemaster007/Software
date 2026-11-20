from fastapi.testclient import TestClient
from backend.app import app
c=TestClient(app);csv=c.get('/api/demo').json()['csv']
r=c.post('/api/balance',json={'csv':csv,'parameters':{'grid_channel_kw':4000},'model':'case33'});assert r.status_code==200,r.text;d=r.json()
for row in d['rows']:
 assert abs(row['load_kw']-row['load_served_kw']-row['power_deficit_kw'])<1e-6
 supply=row['renewable_used_kw']+row['firm_grid_dispatch_kw']+row['emergency_gen_kw']+row['storage_discharge_kw']
 demand=row['load_served_kw']+row['storage_charge_kw']+row['estimated_line_loss_kw']
 assert abs(supply-demand)<1e-4,(supply,demand)
print('48h network balance and AC energy conservation passed',d['metrics'])
r=c.post('/api/balance',json={'csv':'\n'.join(csv.splitlines()[:3]),'parameters':{'grid_channel_kw':4000},'model':'case33','failed_lines':[1]});assert r.status_code==200,r.text
for row in r.json()['rows']:assert abs(row['power_deficit_kw']-row['load_kw'])<1e-5
print('Root outage verified')
