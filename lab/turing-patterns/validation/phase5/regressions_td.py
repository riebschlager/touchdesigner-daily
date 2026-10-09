"""Fresh-build Phase 2/3/4 regression suites, with one intentional Phase 5 seed-contract adaptation."""
from pathlib import Path
import json
ROOT = Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
OUT = ROOT / 'validation/phase5'


def build(label):
    host=op('/project1').create(baseCOMP,'phase5_'+label)
    builder=host.create(textDAT,'builder')
    builder.text=(ROOT/'create_turing_media_v2.py').read_text()
    ns=dict(globals(),me=builder)
    exec(compile(builder.text,'create_turing_media_v2.py','exec'),ns)
    component=ns['turing_component'];component.op('clock').par.active=False
    return host,component


def wait(path,then):
    def poll():
        if path.exists():
            then()
        else:
            run('args[0]()',poll,delayFrames=30)
    poll()


def phase2():
    host,c=build('clock_regression')
    test=host.create(textDAT,'validate')
    test.text=(ROOT/'validation/phase2/validate_td.py').read_text()
    path=OUT/'clock_regression/report.json';path.unlink(missing_ok=True)
    test.module.start(c,str(path.parent))
    wait(path,phase3)


def phase3():
    host,c=build('phase3_regression')
    c.par.Pause=True
    test=host.create(textDAT,'validate')
    test.text=(ROOT/'validation/phase3/validate_td.py').read_text()
    path=OUT/'phase3_regression/report.json';path.unlink(missing_ok=True)
    test.module.start(c,str(path.parent))
    wait(path,phase4)


def phase4():
    host,c=build('presets_regression')
    host.create(constantTOP,'fixture_source')
    test=host.create(textDAT,'validate')
    text=(ROOT/'validation/phase4/validate_td.py').read_text()
    # Phase 5 deliberately defers hand-edited seed controls to explicit reset.
    text=text.replace("check('manual_seed_edit_resets_once', resets() == C.fetch('Phase4before')['resets'] + 1)",
                      "check('manual_seed_edit_waits_for_explicit_reset_phase5', resets() == C.fetch('Phase4before')['resets'])")
    test.text=text
    path=OUT/'presets_regression/report.json';path.unlink(missing_ok=True)
    test.module.start(c,str(path.parent),chain=finish)


def finish():
    summary={}
    for name in ('report.json','clock_regression/report.json','phase3_regression/report.json',
                 'presets_regression/report.json'):
        r=json.loads((OUT/name).read_text());checks=r.get('checks',{})
        failed=[k for k,v in checks.items() if not (v.get('passed',False) if isinstance(v,dict) else v)]
        summary[name]=dict(passed=not failed,checks=len(checks),failed=failed)
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2))
    print('PHASE5_ALL_COMPLETE',all(v['passed'] for v in summary.values()))


phase2()
