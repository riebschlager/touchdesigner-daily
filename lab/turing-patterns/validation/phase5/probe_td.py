from pathlib import Path
import json
root = Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
host = op('/project1').create(baseCOMP, 'phase5_probe')
result = {'build': str(app.version) + '.' + str(app.build), 'tdapi': getattr(op, 'TDAPI', None) is not None}
for kind in (scriptTOP, cacheTOP, moviefileinTOP, glslTOP):
    n = host.create(kind, 'probe_' + kind.__name__)
    result[kind.__name__] = {p.name: {'value': str(p.eval()), 'menus': list(p.menuNames or [])} for p in n.pars()}
    if kind == moviefileinTOP:
        result['movie_members'] = [k for k in dir(n) if 'index' in k.lower() or 'frame' in k.lower()]
    n.destroy()
(root / 'validation/phase5/parameters.json').write_text(json.dumps(result, indent=2))
print('PHASE5_PROBE', result['build'], 'TDAPI', result['tdapi'])
