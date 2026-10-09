from pathlib import Path
import json
import traceback
ROOT = Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
OUT = ROOT / 'validation/phase5'
host = op('/project1').create(baseCOMP, 'phase5_validation')
builder = host.create(textDAT, 'builder')
builder.text = (ROOT / 'create_turing_media_v2.py').read_text()
try:
    namespace = dict(globals(), me=builder)
    exec(compile(builder.text, 'create_turing_media_v2.py', 'exec'), namespace)
    C = namespace['turing_component']
    C.op('clock').par.active = False
    C.par.Pause = True
    (OUT / 'build.json').write_text(json.dumps({'path': C.path, 'errors': C.errors(recurse=True)}, indent=2))
    print('PHASE5_BUILD', C.path, C.errors(recurse=True))
except Exception:
    (OUT / 'build.json').write_text(json.dumps({'exception': traceback.format_exc()}, indent=2))
    raise
