from pathlib import Path
import json
ROOT=Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
host=op('/project1').create(baseCOMP,'phase7_probe')
result={'build':str(app.version)+'.'+str(app.build),'tdapi':getattr(op,'TDAPI',None) is not None}
for kind in (glslTOP,cacheTOP,nullTOP,resolutionTOP):
    n=host.create(kind,'probe_'+kind.__name__)
    result[kind.__name__]={p.name:{'value':str(p.eval()),'menus':list(p.menuNames or [])} for p in n.pars()}
    result[kind.__name__+'_metrics']={key:str(getattr(n,key,'unavailable')) for key in ('gpuCookTime','gpuMemory','cookTime','totalCooks')}
(ROOT/'validation/phase7/parameters.json').write_text(json.dumps(result,indent=2))
print('PHASE7_PROBE',result['build'])
