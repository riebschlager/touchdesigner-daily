"""Execute in TD Textport after setting PHASE4_ROOT. Runs the Phase 4 checks, then
fresh-build reruns of the Phase 3 suite and the Phase 2 clock suite.
Existing components are preserved and the TOE is not saved."""
from pathlib import Path
import json
ROOT = Path(PHASE4_ROOT)
PHASE4_OUT = ROOT / 'validation/phase4'
phase4_host = op('/project1').create(baseCOMP, 'phase4_validation')

# Record the live parameter inventories of operator types new in Phase 4.
phase4_inventory = {'build': str(app.version) + '.' + str(app.build)}
for phase4_type, phase4_name in ((containerCOMP, 'probe_container'), (executeDAT, 'probe_execute'),
                                 (tableDAT, 'probe_table')):
    phase4_probe = phase4_host.create(phase4_type, phase4_name)
    phase4_inventory[phase4_name] = [p.name for p in phase4_probe.pars()]
    phase4_probe.destroy()
(PHASE4_OUT / 'parameters.json').write_text(json.dumps(phase4_inventory, indent=2))

# A real TOP for the optional-binding check (custom TOP paths are relative to
# the component's parent network, so this is referenced as fixture_source).
phase4_host.create(constantTOP, 'fixture_source')


def phase4_build(host):
    builder = host.create(textDAT, 'builder')
    builder.text = (ROOT / 'create_turing_media_v2.py').read_text()
    namespace = dict(globals(), me=builder)
    exec(compile(builder.text, 'create_turing_media_v2.py', 'exec'), namespace)
    return namespace['turing_component']


def phase4_wait(path, then, label):
    """Poll for a suite's report.json, then continue."""
    def poll():
        if path.exists():
            print(label, 'report written:', path)
            then()
        else:
            run('args[0]()', poll, delayFrames=30)
    poll()


def phase4_clock_regression():
    host = op('/project1').create(baseCOMP, 'phase4_clock_regression')
    component = phase4_build(host)
    component.op('clock').par.active = False
    test = host.create(textDAT, 'validate')
    test.text = (ROOT / 'validation/phase2/validate_td.py').read_text()
    out = PHASE4_OUT / 'clock_regression'
    (out / 'report.json').unlink(missing_ok=True)
    test.module.start(component, str(out))
    phase4_wait(out / 'report.json', phase4_summary, 'PHASE2_REGRESSION')


def phase4_phase3_regression():
    host = op('/project1').create(baseCOMP, 'phase4_phase3_regression')
    component = phase4_build(host)
    component.par.Pause = True
    component.op('clock').par.active = False
    test = host.create(textDAT, 'validate')
    test.text = (ROOT / 'validation/phase3/validate_td.py').read_text()
    out = PHASE4_OUT / 'phase3_regression'
    (out / 'report.json').unlink(missing_ok=True)
    test.module.start(component, str(out))
    phase4_wait(out / 'report.json', phase4_clock_regression, 'PHASE3_REGRESSION')


def phase4_summary():
    summary = {}
    for name in ('report.json', 'phase3_regression/report.json', 'clock_regression/report.json'):
        report = json.loads((PHASE4_OUT / name).read_text())
        checks = report.get('checks', {})
        passed = [bool(v.get('passed', v)) if isinstance(v, dict) else bool(v) for v in checks.values()]
        summary[name] = {'passed': report.get('passed', all(passed)), 'checks': len(passed),
                         'failed': [k for k, ok in zip(checks, passed) if not ok]}
    (PHASE4_OUT / 'summary.json').write_text(json.dumps(summary, indent=2))
    print('PHASE4_ALL_COMPLETE', all(v['passed'] and not v['failed'] for v in summary.values()))


phase4 = phase4_build(phase4_host)
phase4.op('clock').par.active = False
print('PHASE4_BUILD', phase4.path, phase4.errors(recurse=True))
(PHASE4_OUT / 'report.json').unlink(missing_ok=True)
phase4_test = phase4_host.create(textDAT, 'validate')
phase4_test.text = (PHASE4_OUT / 'validate_td.py').read_text()
phase4_test.module.start(phase4, str(PHASE4_OUT), chain=phase4_phase3_regression)
