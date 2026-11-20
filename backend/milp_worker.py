"""Fixed native MILP entry point. Exit if the originating worker is no longer valid."""
from pathlib import Path
import json
import math
import os
import sys
import threading
import time
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix
from backend.process_identity import process_identity
from backend.runtime_identity import build_identity


def main(folder):
    print(f'Native solver executing pid={os.getpid()} parent={os.getppid()}', flush=True)
    options = json.loads((folder/'options.json').read_text(encoding='utf-8'))
    if build_identity()['build_id'] != options['build_id']:
        raise RuntimeError('原生子进程与冻结的代码构建不一致，未运行混合版本')
    def parent_watchdog():
        missing = 0
        while True:
            if process_identity(options['parent_pid']) != options['parent_identity']:
                missing += 1
                if missing >= 2:
                    os._exit(89)  # Only this native child exits; no other PID is targeted.
            else:
                missing = 0
            time.sleep(.2)
    threading.Thread(target=parent_watchdog, daemon=True).start()
    with np.load(folder/'input.npz', allow_pickle=False) as arrays:
        matrix = csc_matrix((arrays['data'], arrays['indices'], arrays['indptr']), shape=(int(arrays['rows']), int(arrays['columns'])))
        remaining = options['deadline']-time.time()
        if remaining <= 0:
            metadata = {'status': 1, 'message': '原生进程准备期间达到墙钟时限', 'fun': None, 'mip_gap': None, 'mip_dual_bound': None, 'has_x': False}
            x = np.zeros(0)
        else:
            solved = milp(arrays['objective'], integrality=arrays['integrality'], bounds=Bounds(arrays['lower'], arrays['upper']),
                          constraints=LinearConstraint(matrix, arrays['constraint_lower'], arrays['constraint_upper']),
                          options={'time_limit': remaining, 'mip_rel_gap': options['relative_gap']})
            def finite(value):
                return float(value) if value is not None and math.isfinite(float(value)) else None
            metadata = {'status': int(solved.status), 'message': str(solved.message), 'fun': finite(solved.fun),
                        'mip_gap': finite(getattr(solved, 'mip_gap', None)), 'mip_dual_bound': finite(getattr(solved, 'mip_dual_bound', None)), 'has_x': solved.x is not None}
            x = solved.x if solved.x is not None else np.zeros(0)
    np.savez(folder/'result.npz', x=x)
    (folder/'result.json').write_text(json.dumps(metadata, ensure_ascii=False, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
