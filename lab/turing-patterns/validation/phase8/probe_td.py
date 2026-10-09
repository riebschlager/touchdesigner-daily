"""Inventory actual build parameters before using diagnostics operators."""
from pathlib import Path
import json
ROOT = Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
host = op('/project1').create(baseCOMP, 'phase8_probe')
result = {'build': str(app.version) + '.' + str(app.build),
          'tdapi': getattr(op, 'TDAPI', None) is not None}
for kind in (textCOMP, tableDAT, executeDAT, cacheTOP, infoDAT, glslTOP):
    if result['tdapi']:
        result[kind.__name__ + '_tdapi'] = str(op.TDAPI.GetParameterList(kind.__name__))
    n = host.create(kind, 'probe_' + kind.__name__)
    result[kind.__name__] = {p.name: {'value': str(p.eval()), 'menus': list(p.menuNames or [])}
                             for p in n.pars()}
(ROOT / 'validation/phase8/parameters.json').write_text(json.dumps(result, indent=2))
print('PHASE8_PROBE', result['build'], 'TDAPI', result['tdapi'])
