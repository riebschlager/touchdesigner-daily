"""Run in Textport with PHASE1_ROOT set to the project source directory."""
import json
from pathlib import Path

ROOT = Path(PHASE1_ROOT)
host = op('/project1').create(baseCOMP, 'phase1_validation')
runner = host.create(textDAT, 'build_v1')
runner.text = (ROOT / 'create_turing_media.py').read_text()
namespace = dict(globals(), me=runner)
exec(compile(runner.text, 'create_turing_media.py', 'exec'), namespace)
baseline = namespace['turing_component']
report = {'build': str(app.version) + '.' + str(app.build), 'component': baseline.path,
          'operators': {n.name: {'type': n.OPType, 'parameters': [p.name for p in n.pars()]}
                        for n in baseline.children}}
(ROOT / 'validation/phase1/parameters.json').write_text(json.dumps(report, indent=2))
print('PHASE1_PROBE', baseline.path)
