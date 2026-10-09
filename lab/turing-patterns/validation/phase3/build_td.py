"""Execute in TD Textport; preserve existing components and do not save the TOE."""
from pathlib import Path
import json
ROOT = Path(PHASE3_ROOT)
phase3_host = op('/project1').create(baseCOMP, 'phase3_validation')
# TDAPI is absent in this project; standalone builder must not acquire a dependency.
# Validate against the target build's actual parameter inventories instead.
phase3_probe = phase3_host.create(glslTOP, 'parameter_probe')
phase3_parameters = [p.name for p in phase3_probe.pars()]
(ROOT / 'validation/phase3/parameters.json').write_text(json.dumps({
    'build': str(app.version) + '.' + str(app.build), 'glslTOP': phase3_parameters}, indent=2))
phase3_runner = phase3_host.create(textDAT, 'builder')
phase3_runner.text = (ROOT / 'create_turing_media_v2.py').read_text()
phase3_namespace = dict(globals(), me=phase3_runner)
exec(compile(phase3_runner.text, 'create_turing_media_v2.py', 'exec'), phase3_namespace)
phase3 = phase3_namespace['turing_component']
phase3.par.Pause = True
phase3.op('clock').par.active = False
print('PHASE3_BUILD', phase3.path, phase3.errors(recurse=True))
