"""Create an API-powered palette component in TouchDesigner.

Paste this file into a Text DAT and Run Script. Or, from Textport:
    exec(compile(open('/absolute/path/create_color_palette.py').read(), 'palette', 'exec'))

Select the new color_palette COMP, then pulse New Random Palette.
Outputs: ramp (smooth TOP), palette_top (equal-width swatches TOP),
palette_chop (r/g/b/a, one sample per color). All references are relative.
No pip packages or API keys. Save the COMP as a TOX to keep it portable.
"""

MODES = ['monochrome', 'monochrome-dark', 'monochrome-light', 'analogic',
         'complement', 'analogic-complement', 'triad', 'quad']

RUNTIME = r'''
import json
import queue
import random
import re
import ssl
import os
import threading
import time
import urllib.parse
import urllib.request

# Only plain Python data crosses threads. All TD access stays on the main thread.
_results = queue.Queue()
_pending = None
_last_request = -100.0


def normalize_hex(value):
    value = str(value).strip().lstrip('#')
    if re.fullmatch(r'[0-9a-fA-F]{3}', value):
        value = ''.join(c * 2 for c in value)
    if not re.fullmatch(r'[0-9a-fA-F]{6}', value):
        raise ValueError('Seed Hex must contain 3 or 6 hexadecimal digits')
    return value.upper()


def parse_palette(payload, count):
    colors = payload.get('colors') if isinstance(payload, dict) else None
    if not isinstance(colors, list) or len(colors) != count:
        raise ValueError('API returned an unexpected number of colors')
    result = []
    for color in colors:
        h = normalize_hex(color['hex']['value'])
        result.append((h, str(color.get('name', {}).get('value', h))))
    return result


def status(c, message, url=None):
    c.par.Status = message
    if url is not None:
        c.par.Requesturl = url


def apply(c, colors):
    # Palette is the authoritative, serializable source for every output.
    table = c.op('colors')
    table.clear()
    table.appendRow(['hex', 'name', 'r', 'g', 'b', 'a'])
    for h, name in colors:
        table.appendRow(['#' + h, name] +
                        [int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4)] + [1])
    rebuild(c)


def rebuild(c):
    colors = c.op('colors')
    values = [[float(colors[i, j]) for j in range(2, 6)]
              for i in range(1, colors.numRows)]
    if c.par.Reverse.eval():
        values.reverse()
    n = len(values)
    for name, stepped in [('ramp_keys', False), ('swatch_keys', True)]:
        keys = c.op(name)
        keys.clear()
        keys.appendRow(['pos', 'r', 'g', 'b', 'a'])
        for i, rgba in enumerate(values):
            keys.appendRow([i / (n if stepped else max(1, n - 1))] + rgba)
        if stepped:
            keys.appendRow([1] + values[-1])
    c.op('rgba').cook(force=True)


def _worker(url, count, token, results):
    # No OPs, pars, storage, run(), or other TD APIs here.
    try:
        request = urllib.request.Request(url, headers={
            'User-Agent': 'TouchDesigner-Palette/1.0', 'Accept': 'application/json'})
        context = ssl.create_default_context()
        # Some macOS TD builds have a nonexistent build-machine OpenSSL CA path.
        # Add TD's bundled certificate roots without disabling HTTPS verification.
        try:
            import certifi
        except ImportError:
            if os.path.isfile('/etc/ssl/cert.pem'):
                context.load_verify_locations('/etc/ssl/cert.pem')
        else:
            context.load_verify_locations(certifi.where())
        with urllib.request.urlopen(request, timeout=12, context=context) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('API response was too large')
        colors = parse_palette(json.loads(raw), count)
        results.put((token, colors, None))
    except Exception as error:
        results.put((token, None, str(error)))


def request(c, randomize=False):
    global _pending, _last_request
    poll(c)
    if _pending is not None:
        return  # One bounded request at a time; rapid clicks cannot spawn more threads.
    if time.monotonic() - _last_request < 1:
        status(c, 'Please wait one second between requests')
        return
    try:
        seed = ('%06X' % random.randrange(0x1000000) if randomize
                else normalize_hex(c.par.Seedhex.eval()))
        count = int(c.par.Colorcount.eval())
        if not 2 <= count <= 16:
            raise ValueError('Color Count must be between 2 and 16')
        mode = c.par.Harmony.eval()
        if mode not in MODES:
            raise ValueError('Unknown harmony mode')
    except Exception as error:
        status(c, str(error))
        return
    c.par.Seedhex = seed
    url = 'https://www.thecolorapi.com/scheme?' + urllib.parse.urlencode(
        {'hex': seed, 'mode': mode, 'count': count, 'format': 'json'})
    token = time.monotonic_ns()
    _pending = (token, time.monotonic())
    _last_request = time.monotonic()
    status(c, 'Loading palette...', url)
    threading.Thread(target=_worker, args=(url, count, token, _results), daemon=True).start()


def poll(c):
    global _pending
    while True:
        try:
            token, colors, error = _results.get_nowait()
        except queue.Empty:
            break
        if _pending is None or token != _pending[0]:
            continue
        _pending = None
        if error:
            status(c, 'Request failed; keeping palette: ' + error)
        else:
            apply(c, colors)
            status(c, 'Loaded {} colors from The Color API'.format(len(colors)))
    if _pending and time.monotonic() - _pending[1] > 20:
        _pending = None
        status(c, 'Request timed out; keeping palette')


MODES = ['monochrome', 'monochrome-dark', 'monochrome-light', 'analogic',
         'complement', 'analogic-complement', 'triad', 'quad']
'''

CHOP_CALLBACKS = r'''
def onCook(scriptOp):
    table = scriptOp.parent().op('colors')
    indices = list(range(1, table.numRows))
    if scriptOp.parent().par.Reverse.eval():
        indices.reverse()
    scriptOp.clear()
    scriptOp.numSamples = len(indices)
    scriptOp.rate = 1
    for column, name in enumerate(('r', 'g', 'b', 'a'), 2):
        scriptOp.appendChan(name).vals = [float(table[i, column]) for i in indices]
'''

CONTROL_CALLBACKS = r'''
def onPulse(par):
    c = me.parent()
    runtime = c.op('runtime').module
    if par.name in ('Newpalette', 'Generate'):
        runtime.request(c, randomize=(par.name == 'Newpalette'))
    elif par.name == 'Check':
        runtime.poll(c)


def onValueChange(par, prev):
    if par.name == 'Reverse':
        me.parent().op('runtime').module.rebuild(me.parent())
'''

POLL_CALLBACKS = r'''
def onFrameStart(frame):
    me.parent().op('runtime').module.poll(me.parent())


def onStart():
    # The saved colors/keys survive reopening. Requests never run on project load.
    me.parent().par.Status = 'Saved palette ready; press New Random Palette'
'''

HELP = '''COLOR PALETTE - The Color API

New Random Palette: random seed + selected Harmony, fetched over HTTPS.
Generate From Seed: repeat a Seed Hex, Harmony and Color Count combination.
Seed Hex accepts #RRGGBB, RRGGBB or RGB. Count: 2-16 colors.
Settings apply on the next Generate/New Random Palette pulse.
Reverse changes every output immediately without fetching again.

Outputs (inside this COMP, with external TOP/CHOP connectors):
  ramp: smooth 1024 x 1 gradient; use as Lookup TOP input or Ramp TOP parameter.
  palette_top: 1024 x 64 equal-width color swatches.
  palette_chop: r/g/b/a channels, N samples, normalized sRGB 0-1.
    Example: op('color_palette/palette_chop')['r'][2] = third color's red.
  colors: source hex/name/RGBA table (API order; Reverse applies at outputs).
  ramp_keys: pos/r/g/b/a key table; reusable with another Ramp TOP.

Internet requests run off the UI thread; frame polling applies results on the main
thread. Keep realtime playback running, or press Check Request to apply a finished
response while paused. Nothing automatically requests palettes on frame changes,
parameter edits, project reopen, or output cooks. Requests are at least 1s apart.
A bundled starter palette is visible immediately; Status identifies it as offline.
Errors/timeouts leave the last palette intact. The source table is saved in the
TOE/TOX, so saved palettes work offline. Save this COMP as a TOX for reuse.

Palette generation uses color-wheel harmonies, not popularity rankings.
The Color API: https://www.thecolorapi.com/about
API documentation: https://www.thecolorapi.com/docs
No keys, third-party packages, or local supporting files required.
'''


def _create(parent_op, kind, name, x, y):
    api = getattr(op, 'TDAPI', None)
    if api is not None:
        api.GetParameterList(kind.__name__)
        result = api.CreateOp(parent_op, kind, name, x=x, y=y)
    else:
        # Standalone projects (including this repo's existing builders) have no TDAPI TOX.
        result = parent_op.create(kind, name)
        result.nodeX, result.nodeY = x, y
        for i, docked in enumerate(result.docked):
            docked.nodeX, docked.nodeY = x, y - 150 * (i + 1)
    result.viewer = True
    return result


def _set(node, name, value):
    parameter = getattr(node.par, name, None)
    if parameter is None:
        raise RuntimeError('{}: required parameter {} is unavailable'.format(node.path, name))
    if parameter.isMenu and parameter.menuNames and value not in parameter.menuNames:
        raise RuntimeError('{}: unsupported {} value {!r}'.format(node.path, name, value))
    parameter.val = value


def build_palette(parent_op):
    # Never replace existing operators. A second run receives a unique COMP name.
    api = getattr(op, 'TDAPI', None)
    x, y = (api.FindEmptyArea(parent_op, 180, 140) if api else
            (0, min([n.nodeY for n in parent_op.children] + [0]) - 220))
    c = _create(parent_op, baseCOMP, 'color_palette', x, y)
    page = c.appendCustomPage('Palette')
    page.appendPulse('Newpalette', label='New Random Palette')
    page.appendPulse('Generate', label='Generate From Seed')
    p = page.appendStr('Seedhex', label='Seed Hex')[0]
    p.default = '24B1E0'
    p.val = p.default
    p = page.appendMenu('Harmony', label='Harmony')[0]
    p.menuNames = MODES
    p.menuLabels = [m.replace('-', ' ').title() for m in MODES]
    p.default = 'analogic-complement'
    p.val = p.default
    p = page.appendInt('Colorcount', label='Color Count')[0]
    p.default, p.val = 5, 5
    p.min, p.max, p.clampMin, p.clampMax = 2, 16, True, True
    page.appendToggle('Reverse', label='Reverse Palette')
    page.appendPulse('Check', label='Check Request (While Paused)')
    page.appendStr('Status', label='Status')
    page.appendStr('Requesturl', label='Last Request URL')

    runtime = _create(c, textDAT, 'runtime', -650, 350)
    runtime.text = RUNTIME
    colors = _create(c, tableDAT, 'colors', -650, 100)
    for name, y in [('ramp_keys', -100), ('swatch_keys', -350)]:
        _create(c, tableDAT, name, -400, y)
        n = _create(c, nullDAT, name + '_ref', -200, y)
        n.inputConnectors[0].connect(c.op(name))

    rgba = _create(c, scriptCHOP, 'rgba', 0, 200)
    rgba.par.callbacks.eval().text = CHOP_CALLBACKS
    _set(rgba, 'timeslice', False)
    null = _create(c, nullCHOP, 'rgba_ref', 220, 200)
    null.inputConnectors[0].connect(rgba)
    out = _create(c, outCHOP, 'palette_chop', 440, 200)
    out.inputConnectors[0].connect(null)

    for name, keys, smooth, y in [('gradient', 'ramp_keys', True, -100),
                                   ('swatches', 'swatch_keys', False, -350)]:
        r = _create(c, rampTOP, name, 0, y)
        _set(r, 'dat', keys + '_ref')
        _set(r, 'type', 'horizontal')
        interp = 'interpnotches' if hasattr(r.par, 'interpnotches') else 'interp'
        _set(r, interp, 'linear' if smooth else 'step')
        _set(r, 'outputresolution', 'custom')
        _set(r, 'resolutionw', 1024)
        _set(r, 'resolutionh', 1 if smooth else 64)
        _set(r, 'format', 'rgba32float')
        # Keep TOP numbers equal to the API's normalized sRGB/CHOP numbers on TD 2025+.
        if hasattr(r.par, 'parmcolorspace'):
            _set(r, 'parmcolorspace', 'passthrough')
        n = _create(c, nullTOP, name + '_ref', 220, y)
        n.inputConnectors[0].connect(r)
        out = _create(c, outTOP, 'ramp' if smooth else 'palette_top', 440, y)
        out.inputConnectors[0].connect(n)
        _set(out, 'connectorder', 0 if smooth else 1)

    controls = _create(c, parameterexecuteDAT, 'controls', -650, -600)
    _set(controls, 'active', False)
    controls.text = CONTROL_CALLBACKS
    for name, value in [('op', '..'), ('pars', 'Newpalette Generate Check Reverse'),
                        ('custom', True), ('builtin', False), ('onpulse', True),
                        ('valuechange', True)]:
        _set(controls, name, value)
    poller = _create(c, executeDAT, 'poll', -400, -600)
    poller.text = POLL_CALLBACKS
    _set(poller, 'framestart', True)
    _set(poller, 'start', True)
    help_dat = _create(c, textDAT, 'README', -150, -600)
    help_dat.text = HELP
    runtime.module.apply(c, [(h, label) for h, label in [
        ('264653', 'Starter: deep teal'), ('2A9D8F', 'Starter: teal'),
        ('E9C46A', 'Starter: sand'), ('F4A261', 'Starter: orange'),
        ('E76F51', 'Starter: coral')]])
    c.par.Status = 'Offline starter palette; press New Random Palette'
    _set(controls, 'active', True)
    if hasattr(c.par, 'opviewer'):
        c.par.opviewer.expr = "me.op('palette_top')"
        if hasattr(c.par, 'nodeview'):
            _set(c, 'nodeview', 'opviewer')
    if api:
        api.CheckErrors(c, recurse=True)
    else:
        errors = c.errors(recurse=True)
        if errors:
            print('Palette build diagnostics:', errors)
    print('Created', c.path, '- select it and pulse New Random Palette')
    return c


try:
    op
except NameError:
    pass  # Allows offline import of the embedded Python for validation.
else:
    palette_component = build_palette(me.parent())
