"""Call validate(component) from a Text DAT module after a successful API fetch."""
import hashlib
import json
from pathlib import Path


def validate(c, destination):
    import numpy as np
    checks = {}
    def check(name, condition):
        checks[name] = bool(condition)
        if not condition:
            raise AssertionError(name)

    check('live API success', c.par.Status.eval().startswith('Loaded '))
    n = c.op('colors').numRows - 1
    values = np.array([[float(c.op('colors')[i, j]) for j in range(2, 6)]
                       for i in range(1, n + 1)])
    for reverse in (False, True):
        c.par.Reverse = reverse
        # Explicit rebuild also makes the validator usable inside one Textport command.
        c.op('runtime').module.rebuild(c)
        expected = values[::-1] if reverse else values
        c.op('palette_chop').cook(force=True)
        chop = c.op('palette_chop').numpyArray().T
        check('CHOP order reverse=' + str(reverse), np.allclose(chop, expected, atol=1e-6))
        for name in ('ramp', 'palette_top'):
            c.op(name).cook(force=True)
        ramp = c.op('ramp').numpyArray(delayed=False)
        swatches = c.op('palette_top').numpyArray(delayed=False)
        check('ramp dimensions', ramp.shape == (1, 1024, 4))
        check('TOP dimensions', swatches.shape == (64, 1024, 4))
        for i, rgba in enumerate(expected):
            x = int((i + 0.5) * 1024 / n)
            check('swatch {} reverse={}'.format(i, reverse),
                  np.allclose(swatches[32, x], rgba, atol=1e-5))
        check('ramp endpoints reverse=' + str(reverse),
              np.allclose(ramp[0, 0], expected[0], atol=.005) and
              np.allclose(ramp[0, -1], expected[-1], atol=.005))
    c.par.Reverse = False
    c.op('runtime').module.rebuild(c)
    before = c.op('colors').text
    seed = c.par.Seedhex.eval()
    c.par.Seedhex = 'invalid'
    c.par.Generate.pulse()
    c.op('runtime').module.request(c)
    check('invalid seed preserves palette', c.op('colors').text == before)
    check('invalid seed status', 'hexadecimal' in c.par.Status.eval())
    c.par.Seedhex = seed
    c.par.Status = 'Validated palette; press New Random Palette'
    check('no operator errors', not c.errors(recurse=True))
    report = {'build': str(app.build), 'component': c.path, 'checks': checks,
              'builder_sha256': hashlib.sha256(Path(destination).parent.parent.parent.joinpath(
                  'create_color_palette.py').read_bytes()).hexdigest()}
    Path(destination).write_text(json.dumps(report, indent=2))
    print('PALETTE_VALIDATED', len(checks), 'checks')
    return report
