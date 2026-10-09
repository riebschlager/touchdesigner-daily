from pathlib import Path
import json
ROOT = Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
host = op('/project1').create(baseCOMP, 'phase6_probe')
api = getattr(op, 'TDAPI', None)
result = {'build': str(app.version)+'.'+str(app.build), 'tdapi': api is not None}
for kind in (glslTOP, selectTOP, nullTOP, cacheTOP):
    if api is not None:
        result[kind.__name__+'_api'] = api.GetParameterList(kind.__name__)
        n = api.CreateOp(host, kind, 'probe_'+kind.__name__)
    else:
        n = host.create(kind, 'probe_'+kind.__name__)
    result[kind.__name__] = {p.name: {'value': str(p.eval()), 'menus': list(p.menuNames or [])} for p in n.pars()}
    n.destroy()
(ROOT/'validation/phase6/parameters.json').write_text(json.dumps(result, indent=2))
print('PHASE6_PROBE', result['build'], 'TDAPI', result['tdapi'])
