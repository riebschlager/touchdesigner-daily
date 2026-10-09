"""Run in TD Textport. Verify same-frame GPU history before using it in V2."""
import json
from pathlib import Path
import numpy as np
ROOT = Path(PHASE2_ROOT)
host = op('/project1').create(baseCOMP, 'phase2_prototype')
constant = host.create(constantTOP, 'zero')
constant.par.outputresolution = 'custom'
constant.par.resolutionw = constant.par.resolutionh = 8
constant.par.format = 'rgba32float'
buffers = [host.create(cacheTOP, 'buffer' + str(i)) for i in range(2)]
select = host.create(selectTOP, 'read')
shader = host.create(glslTOP, 'increment')
shader.par.format = 'rgba32float'
shader.par.glslversion = 'glsl460'
dat = host.create(textDAT, 'pixel')
dat.text = 'out vec4 fragColor; void main() { fragColor = TDOutputSwizzle(texelFetch(sTD2DInputs[0], ivec2(gl_FragCoord.xy), 0) + vec4(1, 2, -3, -4)); }'
shader.par.pixeldat = dat.name
shader.inputConnectors[0].connect(select)
for b in buffers:
    b.par.cachesize = 1
    b.par.cacheonce = False
    b.par.alwayscook = False
    b.par.format = 'rgba32float'
    b.inputConnectors[0].connect(constant)
    b.par.active = True
    b.cook(force=True)
    b.par.active = False
select.par.top = buffers[0].name
initial = buffers[0].numpyArray(delayed=False).copy()
values = []
for i in range(12):
    select.par.top = buffers[i % 2].name
    select.cook(force=True)
    shader.cook(force=True)
    dest = buffers[(i + 1) % 2]
    dest.inputConnectors[0].connect(shader)
    dest.par.replace = True
    dest.cook(force=True)
    dest.par.replace = False
    values.append(dest.numpyArray(delayed=False)[0, 0].tolist())
expected = [initial[0, 0] + (i + 1) * np.array([1, 2, -3, -4]) for i in range(12)]
execute = host.create(executeDAT, 'parameter_probe')
execute.par.active = False
report = {'build': str(app.version) + '.' + str(app.build), 'values': values,
          'twelve_same_frame_ticks_correct': bool(np.array_equal(values, expected)),
          'parameters': {n.name: [p.name for p in n.pars()] for n in (buffers[0], shader, execute)},
          'errors': host.errors(recurse=True)}
(ROOT / 'validation/phase2/prototype.json').write_text(json.dumps(report, indent=2))
print('PHASE2_PROTOTYPE', report['twelve_same_frame_ticks_correct'], values, report['errors'])
