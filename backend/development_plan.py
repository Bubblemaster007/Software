"""Read-only, source-traceable target requirements. Statuses are reviewed, not inferred."""
from pathlib import Path
import json
from collections import Counter
from fastapi import APIRouter
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix='/api/development-plan', tags=['软件功能规划与验收'])


@router.get('')
def plan():
    data = json.loads((ROOT / 'docs/software_plan.json').read_text(encoding='utf-8'))
    return {**data, 'counts': dict(Counter(row['status'] for row in data['requirements'])),
            'note': '状态为开发证据台账，不代表任务书性能、科研精度或示范区验收已通过。'}


@router.get('/document')
def document():
    return FileResponse(ROOT / 'docs/软件开发规划.md', filename='软件开发规划.md', media_type='text/markdown; charset=utf-8')
