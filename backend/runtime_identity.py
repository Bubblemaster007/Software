"""A frozen identity lets the launcher reuse matching services without killing old ones."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_identity():
    files = [p for p in (ROOT / 'backend').glob('*.py') if not p.name.startswith(('test_', 'verify_'))]
    files += list((ROOT / 'vendor/topic2').rglob('*.py'))
    index = ROOT / 'frontend/dist/index.html'
    if index.exists():
        files.append(index)
    digest = hashlib.sha256()
    for p in sorted(files):
        digest.update(p.relative_to(ROOT).as_posix().encode())
        digest.update(b'\0')
        digest.update(p.read_bytes())
        digest.update(b'\0')
    return {'build_id': digest.hexdigest(), 'api_version': 'devices.1', 'service': 'terminal-power-platform'}


if __name__ == '__main__':
    print(json.dumps(build_identity()))
