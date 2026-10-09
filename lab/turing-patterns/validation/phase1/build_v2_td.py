"""Run in Textport after probe_td.py and the V1 capture have completed."""
import json
from pathlib import Path

ROOT = Path(PHASE1_ROOT)
host = op('/project1/phase1_validation')
runner = host.create(textDAT, 'build_v2')
runner.text = (ROOT / 'create_turing_media_v2.py').read_text()
namespace = dict(globals(), me=runner)
exec(compile(runner.text, 'create_turing_media_v2.py', 'exec'), namespace)
candidate = namespace['turing_component']
second = namespace['build_turing_media_v2'](host)
assert candidate.name == 'turing_media_v2'
assert second.name == 'turing_media_v2_2'
assert candidate != second
second.par.Running = False
second.viewer = False
second.allowCooking = False


def topology(component):
    return {n.name: {'type': n.OPType, 'inputs': [i.name for i in n.inputs],
                     'parameters': {p.name: {'expression': p.expr, 'value': str(p.val)}
                                    for p in n.pars() if p.name != 'pageindex'}}
            for n in component.children}


def custom_parameters(component):
    return {p.name: {'default': str(p.default), 'label': p.label,
                     'min': p.min, 'max': p.max, 'menuNames': p.menuNames,
                     'menuLabels': p.menuLabels, 'enableExpr': p.enableExpr,
                     'page': p.page.name} for p in component.customPars}


baseline = host.op('turing_media')
structure = {'v1_topology': topology(baseline), 'v2_topology': topology(candidate),
             'v1_parameters': custom_parameters(baseline),
             'v2_parameters': custom_parameters(candidate),
             'unique_names': [candidate.name, second.name]}
(ROOT / 'validation/phase1/structure.json').write_text(json.dumps(structure, indent=2))
host.op('capture').module.start(candidate, str(ROOT / 'validation/phase1/v2'))
