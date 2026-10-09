from pathlib import Path
import json
ROOT = Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
host = op('/project1').create(baseCOMP, 'phase8_validation')
builder = host.create(textDAT, 'builder')
builder.text = (ROOT / 'create_turing_media_v2.py').read_text()
ns = dict(globals(), me=builder)
exec(compile(builder.text, 'create_turing_media_v2.py', 'exec'), ns)
C = ns['turing_component']
C.op('clock').par.active = False
C.par.Pause = True
(ROOT / 'validation/phase8/component.json').write_text(json.dumps({'path': C.path}))
print('PHASE8_BUILT', C.path, C.fetch('Shaderhealth'))
