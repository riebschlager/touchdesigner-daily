"""Reject missing, failing, wrong-build or stale live validation evidence."""
from pathlib import Path
import hashlib
import json

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
SHA=hashlib.sha256((ROOT/'create_turing_media_v2.py').read_bytes()).hexdigest()
FILES=('report.json','frame_report.json','clock_regression/report.json','phase3_regression/report.json',
       'presets_regression/report.json','snapshots_regression/report.json','boundaries_regression/report.json',
       'performance_regression/report.json')
summary={}
for name in FILES:
    r=json.loads((OUT/name).read_text())
    failed=[k for k,v in r['checks'].items() if not(v.get('passed',False) if isinstance(v,dict) else v)]
    cases=r.get('cases',[])
    failed_cases=[c['name'] for c in cases if not c.get('passed',False)]
    current=r.get('source_sha256',r.get('sha256'))==SHA
    build=r.get('build')=='099.2025.33230'
    summary[name]={'passed':not failed and not failed_cases and r.get('passed',True) and current and build,
                   'checks':len(r['checks']),'cases':len(cases),'failed':failed+failed_cases,
                   'current_source':current,'build':r.get('build')}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
assert all(v['passed'] for v in summary.values()),'Phase 8 evidence is incomplete, stale or failing'
