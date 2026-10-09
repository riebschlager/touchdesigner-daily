"""Check final fingerprints and summarize stage timing estimates and resident memory."""
from pathlib import Path
import json, hashlib
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
GROUPS=('simulation','media','palette','display')
source_hash=hashlib.sha256((ROOT/'create_turing_media_v2.py').read_bytes()).hexdigest()
summary={}
for name in ('report.json','frame_report.json','clock_regression/report.json','phase3_regression/report.json',
             'presets_regression/report.json','snapshots_regression/report.json','boundaries_regression/report.json'):
 r=json.loads((OUT/name).read_text());fingerprint=r.get('sha256',r.get('source_sha256'))
 failed=[k for k,v in r['checks'].items() if not (v.get('passed',False) if isinstance(v,dict) else v)]
 summary[name]={'passed':not failed and r.get('passed',True) and fingerprint==source_hash,
                'checks':len(r['checks']),'failed':failed,'current_source':fingerprint==source_hash}
before=json.loads((OUT/'profile_before.json').read_text());after=json.loads((OUT/'profile_after.json').read_text())
assert after['sha256']==source_hash
assert before['sha256']==hashlib.sha256((OUT/'reference_v6.py').read_bytes()).hexdigest()
rows={}
for name in before['cases']:
 b,a=before['cases'][name]['mean'],after['cases'][name]['mean']
 bt=sum(b[g+'_gpu_ms_estimate'] for g in GROUPS);at=sum(a[g+'_gpu_ms_estimate'] for g in GROUPS)
 bm=sum(b[g+'_bytes'] for g in GROUPS);am=sum(a[g+'_bytes'] for g in GROUPS)
 rows[name]={'before_gpu_ms_estimate':bt,'after_gpu_ms_estimate':at,'gpu_reduction_percent':(1-at/bt)*100,
             'before_memory_mib':bm/2**20,'after_memory_mib':am/2**20,'memory_reduction_percent':(1-am/bm)*100,
             'stages':{g:{'before_gpu_ms_estimate':b[g+'_gpu_ms_estimate'],'after_gpu_ms_estimate':a[g+'_gpu_ms_estimate'],
                          'before_bytes':b[g+'_bytes'],'after_bytes':a[g+'_bytes']} for g in GROUPS}}
summary['profiles']={'passed':all(not v['errors'] for r in (before,after) for v in r['cases'].values()),'current_source':True}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2))
(OUT/'profile_comparison.json').write_text(json.dumps(rows,indent=2))
print(json.dumps(rows,indent=2))
assert all(v['passed'] for v in summary.values()),summary
