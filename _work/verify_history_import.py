"""Read actual input files, verify no physical changes, and write optional ready copies."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import io,json
import pandas as pd
from fastapi.testclient import TestClient
from backend.app import app
from backend.input_datasets import entries

target=Path('data/import-ready');target.mkdir(exist_ok=True,parents=True)
report=[]
client=TestClient(app,raise_server_exceptions=True)
if True:  # Do not run production scheduler lifespan during read-only import verification.
 for key in ('alashankou-2023','alashankou-2025','extreme-muswellbrook-2019'):
  path,_,_=entries()[key];text=path.read_text(encoding='utf-8-sig')
  response=client.post('/api/source-import/preview',json={'text':text,'filename':path.name})
  assert response.status_code==200,response.text
  result=response.json();original=pd.read_csv(io.StringIO(text));converted=pd.read_csv(io.StringIO(result['csv']))
  assert len(converted)==8760
  for raw,column in [('load','load_kw'),('wind_power','wind_kw'),('solar_power','pv_kw')]:
   assert (original[raw].to_numpy()==converted[column].to_numpy()).all(),column
  assert (pd.to_datetime(original.time).to_numpy()==pd.to_datetime(converted.timestamp).to_numpy()).all()
  output=target/f'{key}_standard_kw.csv';output.write_text(result['csv'],encoding='utf-8-sig')
  output.with_suffix('.source.json').write_text(json.dumps(result['source_import'],ensure_ascii=False,indent=2),encoding='utf-8')
  report.append({'dataset':key,'rows':len(converted),'timestamps_identical':True,'power_values_identical':True,'output':str(output)})
Path('docs/history-import-verification-20261122.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))
