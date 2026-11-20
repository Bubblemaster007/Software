"""Owned native solver process. Numeric NPZ protocol, no pickle or user executables."""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import numpy as np
import scipy
from scipy.optimize import OptimizeResult
from backend.process_identity import process_identity
from backend.runtime_identity import build_identity
from backend.study_control import StudyCancelled

ROOT = Path(__file__).resolve().parents[1]


def stop_owned(child):
    """Popen retains the exact owned process handle; never enumerate/kill other PIDs."""
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def native_milp(model, terms, seconds, gap, cancelled=None, log_dir=None, expected_build_id=None):
    if cancelled and cancelled():
        raise StudyCancelled('原生求解启动前取消')
    started = time.monotonic()
    identity = process_identity(os.getpid())
    if identity is None:
        raise RuntimeError('无法确认父工作进程身份，未启动原生求解')
    expected = expected_build_id or build_identity()['build_id']
    with TemporaryDirectory(prefix='terminal-milp-') as directory:
        folder = Path(directory)
        objective = np.zeros(len(model.lower))
        for i, cost in terms.items():
            objective[i] += cost
        matrix = model.matrix()
        np.savez_compressed(folder/'input.npz', objective=objective, lower=model.lower, upper=model.upper,
                            integrality=model.integral, data=matrix.data, indices=matrix.indices, indptr=matrix.indptr,
                            rows=np.asarray(matrix.shape[0]), columns=np.asarray(matrix.shape[1]),
                            constraint_lower=model.cl, constraint_upper=model.cu)
        digest = hashlib.sha256((folder/'input.npz').read_bytes()).hexdigest()
        options = {'deadline': time.time()+max(.001, seconds-(time.monotonic()-started)), 'relative_gap': gap,
                   'parent_pid': os.getpid(), 'parent_identity': identity, 'build_id': expected}
        (folder/'options.json').write_text(json.dumps(options), encoding='utf-8')
        with (folder/'native.log').open('wb') as stream:
            # Windows venv python.exe can be a redirector with a second process.
            # Own the actual interpreter handle and reuse the exact NumPy/SciPy site.
            executable = getattr(sys, '_base_executable', sys.executable)
            python_path = os.pathsep.join(dict.fromkeys([str(ROOT), str(Path(np.__file__).resolve().parents[1]), str(Path(scipy.__file__).resolve().parents[1])]))
            child = subprocess.Popen([executable, '-m', 'backend.milp_worker', str(folder)], cwd=ROOT,
                                     stdout=stream, stderr=subprocess.STDOUT,
                                     env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONPATH': python_path},
                                     creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            print(f'Native MILP pid={child.pid}, numeric_input_sha256={digest}', flush=True)
            timed_out = False
            try:
                while child.poll() is None:
                    if cancelled and cancelled():
                        stop_owned(child)
                        raise StudyCancelled('已停止本任务拥有的原生求解进程')
                    if time.monotonic()-started > seconds+5:
                        stop_owned(child)
                        timed_out = True
                        break
                    time.sleep(.1)
            finally:
                stop_owned(child)
        log = (folder/'native.log').read_text(encoding='utf-8', errors='replace')
        if log_dir is not None:
            target = Path(log_dir)
            target.mkdir(parents=True, exist_ok=True)
            with (target/'solver.log').open('a', encoding='utf-8') as out:
                out.write(f'pid={child.pid} input_sha256={digest} exit={child.returncode}\n'+log[-200000:]+'\n')
        if timed_out:
            return OptimizeResult(status=1, message='原生进程超过墙钟预算，已停止；未提交未经保存的可行解', x=None, fun=None, mip_gap=None, mip_dual_bound=None)
        if child.returncode != 0 or not (folder/'result.json').exists() or not (folder/'result.npz').exists():
            if log_dir is not None:
                failure = Path(log_dir)/('solver-failure-'+uuid.uuid4().hex)
                failure.mkdir()
                for filename in ('input.npz', 'options.json', 'native.log'):
                    shutil.copyfile(folder/filename, failure/filename)
            print(log[-12000:], flush=True)
            raise RuntimeError(f'原生求解进程异常退出({child.returncode})，无成功结论；数值模型及诊断日志已保留')
        metadata = json.loads((folder/'result.json').read_text(encoding='utf-8'))
        with np.load(folder/'result.npz', allow_pickle=False) as data:
            solution = data['x'].copy() if metadata.pop('has_x') else None
        return OptimizeResult(**metadata, x=solution)
