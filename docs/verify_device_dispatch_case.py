"""Reproducible artificial 24h grid separation/reconnection study; not acceptance data."""
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.resource_dispatch import DispatchInput, dispatch
from backend.engineering import Inventory
from backend.network_data import Network
from backend.runtime_identity import build_identity

network = Network(nodes=[{'node': 1, 'pd_kw': 0}, {'node': 2, 'pd_kw': 100}],
                  lines=[{'line': 7, 'from_node': 1, 'to_node': 2, 'r_ohm': .1, 'x_ohm': .05, 'capacity_kva': 100}])
inventory = Inventory(
    loads=[{'id': 'H', 'name': '基本保障', 'node': 2, 'load_class': '基本保障', 'peak_kw': 50, 'target_hours': 24},
           {'id': 'R', 'name': '居民', 'node': 2, 'load_class': '居民生活', 'peak_kw': 50, 'minimum_supply_ratio': .8, 'target_hours': 24}],
    sources=[{'id': 'PV', 'name': '光伏', 'node': 2, 'kind': '光伏', 'rated_kw': 70,
              'curve_kw': [max(0, 70 * math.sin((h - 6) / 12 * math.pi)) if 6 <= h <= 18 else 0 for h in range(24)]},
             {'id': 'D', 'name': '应急机组', 'node': 2, 'kind': '柴油机', 'rated_kw': 80, 'minimum_kw': 10,
              'fuel_kwh': 300, 'startup_minutes': 60, 'grid_forming': True, 'black_start': True}],
    storage=[{'id': 'B', 'name': '储能', 'node': 2, 'power_kw': 40, 'energy_kwh': 100, 'grid_forming': True, 'black_start': True}])
request = DispatchInput(project_id='synthetic', project_revision=1, engineering_revision=1, steps=24,
                        grid_available_kw=[100] * 6 + [0] * 12 + [100] * 6,
                        line_status={7: [1] * 6 + [0] * 12 + [1] * 6})
result = dispatch(request, inventory, network)
assert result['status'] == 'optimal', result['solver']
assert result['metrics']['maximum_balance_residual_kw'] < 1e-4
assert all(not row['lines'][0]['closed'] for row in result['rows'][6:18])
assert any(row['served_kw'] > 0 and row['grid_kw'] == 0 for row in result['rows'][6:18])
record = {'scope': '人工24小时线路断联/恢复、多源储研究算例；非实测与正式性能验收',
          'input': {'parameters': request.model_dump(mode='json'), 'network': network.model_dump(),
                    'inventory': inventory.model_dump(), 'runtime': build_identity()}, 'result': result}
path = Path(__file__).with_name('逐设备24小时断联恢复联调.json')
path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS: synthetic 24h separation/recovery; residual', result['metrics']['maximum_balance_residual_kw'],
      'runtime', result['runtime_seconds'], 'seconds')
