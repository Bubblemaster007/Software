from fastapi.testclient import TestClient
from backend.app import app
c=TestClient(app);csv=c.get('/api/demo').json()['csv'];p=c.post('/api/projects',json={'name':'场景集成验证','state':{'csv':csv}}).json()
hazard='timestamp,wind_speed\n'+'\n'.join(line.split(',')[0]+',100' for line in csv.strip().splitlines()[1:])
body={'project_id':p['id'],'name':'高风速验证','seed':42,'hazard_csv':hazard,'devices':[{'device_id':'grid','device_type':'grid_channel','rated_kw':4000}]}
r=c.post('/api/scenarios/faults',json=body);assert r.status_code==200,r.text;s=r.json();again=c.post('/api/scenarios/faults',json=body).json();assert s['states']==again['states']
r=c.post('/api/balance',json={'project_id':p['id'],'project_revision':1,'scenario_id':s['id'],'csv':csv,'parameters':{'grid_channel_kw':4000}});assert r.status_code==200,r.text
assert any(x['firm_grid_dispatch_kw']==0 for x in r.json()['rows']);assert len(c.get('/api/runs',params={'project_id':p['id']}).json())==1
assert c.put('/api/projects/'+p['id'],json={'name':p['name'],'expected_revision':0,'state':{}}).status_code==409
print('Project isolation, version conflict, deterministic faults and capacity coupling passed')
