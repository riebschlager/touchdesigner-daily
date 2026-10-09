"""Live baseline capture; run in TD, not system Python.

Load into a Text DAT and call its module.start(component, output_directory).
Uses TD's bundled NumPy only for lossless test captures. The product builder
does not depend on this harness. Each tick runs on a distinct project frame.
"""
import hashlib
import json
from pathlib import Path
import traceback

import numpy as np

OUTPUTS = ('out1', 'patterns', 'mask_preview', 'source_preview', 'palette', 'state')
CASES = [
    ('coral', {}, 'Coral'),
    ('spots', {}, 'Spots'),
    ('media_fixed', {'Sourcetop': '@fixture', 'Maskmode': 'alpha', 'Clipalpha': 1}, None),
    ('media_tint', {'Sourcetop': '@fixture', 'Maskmode': 'alpha', 'Clipalpha': 1, 'Colormode': 'tint'}, None),
    ('media_palette', {'Sourcetop': '@fixture', 'Maskmode': 'alpha', 'Clipalpha': 1, 'Colormode': 'ramp'}, None),
    ('media_carried', {'Sourcetop': '@fixture', 'Maskmode': 'alpha', 'Clipalpha': 1, 'Colormode': 'dye'}, None),
    ('rectangle', {'Rectangle': True, 'Canvaswidth': 384, 'Canvasheight': 216}, None),
    ('coarse_smooth', {'Rectangle': True, 'Canvaswidth': 384, 'Canvasheight': 216, 'Cellsize': 4}, None),
    ('coarse_linear', {'Rectangle': True, 'Canvaswidth': 384, 'Canvasheight': 216, 'Cellsize': 4, 'Upscale': 'linear'}, None),
    ('coarse_nearest', {'Rectangle': True, 'Canvaswidth': 384, 'Canvasheight': 216, 'Cellsize': 4, 'Upscale': 'nearest'}, None),
    ('transform_wrap', {'Transform': True, 'Grow': .2, 'Rotate': .4, 'Translatex': .3}, None),
    ('transform_clear', {'Transform': True, 'Grow': -.2, 'Rotate': .4, 'Translatex': .3, 'Transformedge': 'clear'}, None),
]

FIXTURE = '''
layout(location = 0) out vec4 fragColor;
void main() {
    vec2 uv = vUV.st;
    float a = (1.0 - smoothstep(0.20, 0.28, length(uv - 0.5))) * (0.35 + 0.65 * uv.x);
    fragColor = TDOutputSwizzle(vec4(uv.x, 1.0 - uv.y, 0.2 + 0.6 * uv.y, a));
}
'''


def start(component, output_directory):
    global comp, dest, report, case_index, frame, defaults, fixture, initial, frozen
    comp = component
    dest = Path(output_directory)
    dest.mkdir(parents=True, exist_ok=True)
    defaults = {p.name: p.default for p in comp.customPars if not p.isPulse}
    fixture = comp.parent().op('phase1_rgba')
    if fixture is None:
        fixture = comp.parent().create(glslTOP, 'phase1_rgba')
        shader = comp.parent().create(textDAT, 'phase1_rgba_pixel')
        shader.text = FIXTURE
        fixture.par.pixeldat = shader
        fixture.par.outputresolution = 'custom'
        fixture.par.resolutionw = 256
        fixture.par.resolutionh = 192
        fixture.par.format = 'rgba32float'
    report = {'build': str(app.build), 'component': comp.path, 'cases': [],
              'frames': 180, 'passes': 16, 'seed': 1, 'outputs': OUTPUTS,
              'fixture_sha256': hashlib.sha256(FIXTURE.encode()).hexdigest()}
    case_index = -1
    next_case()


def next_case():
    global case_index, frame, initial, frozen
    case_index += 1
    if case_index == len(CASES):
        report['complete'] = True
        (dest / 'report.json').write_text(json.dumps(report, indent=2))
        comp.par.Running = False
        print('PHASE1_CAPTURE_COMPLETE', str(dest))
        return
    name, settings, pulse = CASES[case_index]
    comp.op('controls').par.active = False
    for key, value in defaults.items():
        comp.par[key].val = value
    for key, value in settings.items():
        comp.par[key].val = fixture.path if value == '@fixture' else value
    comp.op('controls').par.active = True
    if pulse:
        comp.par[pulse].pulse()
    comp.op('feedback').par.reset = True
    comp.op('palette_feedback').par.reset = True
    frame = -2
    initial, frozen = None, None
    run(tick, delayFrames=1)


def arrays():
    return {name: comp.op(name).numpyArray(delayed=False).copy() for name in OUTPUTS}


def snapshot(label):
    data = arrays()
    case = CASES[case_index][0]
    np.savez_compressed(str(dest / (case + '_' + label + '.npz')), **data)
    if label == 'evolved':
        comp.op('out1').save(str(dest / (case + '.png')))
    return data


def tick():
    global frame, initial, frozen
    try:
        frame += 1
        if frame == 0:
            comp.op('feedback').par.reset = False
            comp.op('palette_feedback').par.reset = False
            comp.store('Resetframe', absTime.frame)
        comp.op('out1').cook(force=True)
        if frame == -1:
            initial = snapshot('initial')['state']
        elif frame == 180:
            data = snapshot('evolved')
            frozen = data['state']
            errors = {n.name: n.errors() for n in comp.children if n.errors()}
            # V1 documents the unselected, empty movie input as an expected diagnostic.
            expected = {k: v for k, v in errors.items() if k == 'movie' and not comp.par.Moviefile.eval()}
            errors = {k: v for k, v in errors.items() if k not in expected}
            report['cases'].append({
                'name': CASES[case_index][0], 'errors': errors, 'expected_inactive_errors': expected,
                'shapes': {k: list(v.shape) for k, v in data.items()},
                'finite': all(bool(np.isfinite(v).all()) for v in data.values()),
                'state_changed': bool(np.any(initial != frozen)),
                'chemical_range': [float(frozen[:, :, :2].min()), float(frozen[:, :, :2].max())],
                'parameters': {p.name: str(p.eval()) for p in comp.customPars if not p.isPulse},
                'shader_info': {n.name: n.text for n in comp.children if n.OPType == 'infoDAT'},
            })
            comp.par.Running = False
        elif frame == 190:
            paused = snapshot('paused')['state']
            report['cases'][-1]['pause_exact'] = bool(np.array_equal(paused, frozen))
            comp.par.Reset.pulse()
        elif frame == 192:
            reset = snapshot('reset')['state']
            seed = comp.op('seed').numpyArray(delayed=False)
            report['cases'][-1]['reset_matches_seed'] = bool(np.array_equal(reset, seed))
            (dest / 'report.json').write_text(json.dumps(report, indent=2))
            next_case()
            return
        run(tick, delayFrames=1)
    except Exception:
        report['exception'] = traceback.format_exc()
        (dest / 'report.json').write_text(json.dumps(report, indent=2))
        print(report['exception'])
