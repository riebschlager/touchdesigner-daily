"""Run historical clock/influence/preset/snapshot suites against fresh Phase 8 builds."""
from pathlib import Path
import hashlib
import json
import shutil
ROOT=Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
OUT=ROOT/'validation/phase8'
SUITES=[('clock_regression','phase2'),('phase3_regression','phase3'),
        ('presets_regression','phase4'),('snapshots_regression','phase5'), ('boundaries_regression','phase6'), ('performance_regression','phase7')]


def next_suite():
    if not SUITES:
        summary={}
        for name in ('clock_regression/report.json','phase3_regression/report.json',
                     'presets_regression/report.json','snapshots_regression/report.json','boundaries_regression/report.json','performance_regression/report.json'):
            r=json.loads((OUT/name).read_text());checks=r['checks']
            failed=[k for k,v in checks.items() if not(v.get('passed',False) if isinstance(v,dict) else v)]
            summary[name]=dict(passed=not failed,checks=len(checks),failed=failed)
        if (OUT/'frame_report.json').exists():
            r=json.loads((OUT/'frame_report.json').read_text());checks=r['checks']
            failed=[k for k,v in checks.items() if not v.get('passed',False)]
            summary['frame_report.json']=dict(passed=not failed,checks=len(checks),failed=failed)
        (OUT/'summary.json').write_text(json.dumps(summary,indent=2))
        print('PHASE8_ALL_COMPLETE',all(v['passed'] for v in summary.values()))
        return
    label,phase=SUITES.pop(0);folder=OUT/label;folder.mkdir(parents=True,exist_ok=True)
    host=op('/project1').create(baseCOMP,'phase8_'+label)
    builder=host.create(textDAT,'builder');builder.text=(ROOT/'create_turing_media_v2.py').read_text()
    ns=dict(globals(),me=builder);exec(compile(builder.text,'create_turing_media_v2.py','exec'),ns)
    c=ns['turing_component'];c.op('clock').par.active=False
    if phase!='phase2':c.par.Pause=True
    if phase=='phase4':host.create(constantTOP,'fixture_source')
    if phase=='phase5':shutil.copyfile(ROOT/'validation/phase5/fixture.mp4',folder/'fixture.mp4')
    test=host.create(textDAT,'validate')
    code=(ROOT/'validation'/phase/'validate_td.py').read_text()
    if phase=='phase4':
        code=code.replace("check('manual_seed_edit_resets_once', resets() == C.fetch('Phase4before')['resets'] + 1)",
                          "check('manual_seed_edit_deferred_phase5', resets() == C.fetch('Phase4before')['resets'])")
    if phase=='phase7':
        code=code.replace('ROOT=OUT.parents[1]', 'ROOT=Path({!r})'.format(str(ROOT)))
        code=code.replace("OUT/'reference_v6.py'", "ROOT/'validation/phase7/reference_v6.py'")
        code=code.replace('histories,precision_start]', 'histories,finish]')
    if phase in ('phase5','phase6'):
        code=code.replace("(OUT.parents[1]/'create_turing_media_v2.py').read_bytes()", "C.parent().op('builder').text.encode()")
    test.text=code
    path=folder/'report.json';path.unlink(missing_ok=True)
    test.module.start(c,str(folder))
    def poll():
        if path.exists():
            r=json.loads(path.read_text());r['source_sha256']=hashlib.sha256(builder.text.encode()).hexdigest()
            r['build']=str(app.version)+'.'+str(app.build)
            path.write_text(json.dumps(r,indent=2))
            next_suite()
        else:run('args[0]()',poll,delayFrames=30)
    poll()


next_suite()
