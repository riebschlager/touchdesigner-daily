"""Build a Gray-Scott reaction-diffusion network inside TouchDesigner.

USE
  1. Paste this entire file into a Text DAT in your project.
  2. Right-click the DAT and choose Run Script.
  3. Select the new turing_patterns Base COMP and open its Turing page.
  4. Start timeline playback and view its out1 TOP.

Written for TouchDesigner 2023/2025. No external Python packages or files.
Re-running creates a new numbered component; existing operators are retained.
Output: out1 = colored image; state = raw A/B concentrations in red/green.

Default: 512 square, 32-bit float state, 16 simulation steps per frame.
Simulation speed therefore depends on frame rate. Passes costs GPU time.
Save the .toe or save this component as a .tox to keep the generated network.

References:
  https://www.karlsims.com/rd.html
  https://derivative.ca/UserGuide/GLSL_TOP
  https://derivative.ca/UserGuide/Feedback_TOP

Validation: Python syntax, numerical smoke tests, and standalone GLSL 4.60
compilation of all three pixel shaders with stubs for TD-provided declarations.
This file has not been run in a live TouchDesigner session here.
"""


SEED_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uSeed; // random seed, radius in cells, resolution, unused

float hash(float n) {
    return fract(sin(n * 127.1 + uSeed.x * 31.7) * 43758.5453);
}

void main() {
    vec2 uv = vUV.st;
    float patchMask = 0.0;
    // Ten separated patches of chemical B, including one at the center.
    for (int i = 0; i < 10; ++i) {
        float n = float(i);
        vec2 center = (i == 0) ? vec2(0.5) :
            vec2(0.1 + 0.8 * hash(n * 3.0 + 1.0),
                 0.1 + 0.8 * hash(n * 3.0 + 2.0));
        float seedMask = 1.0 - step(uSeed.y / uSeed.z, distance(uv, center));
        patchMask = max(patchMask, seedMask);
    }
    // A gentler perturbation supports both the coral and dividing-spot presets.
    float A = mix(1.0, 0.5, patchMask);
    float B = 0.25 * patchMask;
    fragColor = TDOutputSwizzle(vec4(A, B, 0.0, 1.0));
}
"""


SIMULATION_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uRates; // feed, kill, diffusion A, diffusion B
uniform vec4 uStep;  // timestep, running, unused, unused

// Integer addressing makes the nine-cell stencil exact. Wrap both axes.
vec2 readCell(ivec2 p) {
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    p = (p % size + size) % size;
    return texelFetch(sTD2DInputs[0], p, 0).rg;
}

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec2 ab = readCell(p);
    if (uStep.y < 0.5) {
        fragColor = TDOutputSwizzle(vec4(ab, 0.0, 1.0));
        return;
    }

    vec2 lap = -ab;
    lap += 0.2 * (readCell(p + ivec2(-1, 0))
                + readCell(p + ivec2( 1, 0))
                + readCell(p + ivec2( 0,-1))
                + readCell(p + ivec2( 0, 1)));
    lap += 0.05 * (readCell(p + ivec2(-1,-1))
                 + readCell(p + ivec2( 1,-1))
                 + readCell(p + ivec2(-1, 1))
                 + readCell(p + ivec2( 1, 1)));

    float reaction = ab.x * ab.y * ab.y;
    vec2 change;
    change.x = uRates.z * lap.x - reaction + uRates.x * (1.0 - ab.x);
    change.y = uRates.w * lap.y + reaction - (uRates.x + uRates.y) * ab.y;
    vec2 nextState = clamp(ab + uStep.x * change, 0.0, 1.0);
    fragColor = TDOutputSwizzle(vec4(nextState, 0.0, 1.0));
}
"""


DISPLAY_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uDisplay; // color amount, contrast, invert, unused

void main() {
    float B = texture(sTD2DInputs[0], vUV.st).g;
    float t = clamp(B * uDisplay.y, 0.0, 1.0);
    t = mix(t, 1.0 - t, uDisplay.z);
    vec3 dark = vec3(0.012, 0.020, 0.040);
    vec3 middle = vec3(0.05, 0.65, 0.75);
    vec3 light = vec3(1.0, 0.80, 0.35);
    vec3 palette = mix(dark, middle, smoothstep(0.0, 0.55, t));
    palette = mix(palette, light, smoothstep(0.45, 1.0, t));
    vec3 color = mix(vec3(t), palette, uDisplay.x);
    fragColor = TDOutputSwizzle(vec4(color, 1.0));
}
"""


CONTROL_CALLBACKS = '''
def onPulse(par):
    component = par.owner
    if par.name == 'Reseed':
        component.par.Seed = component.par.Seed.eval() + 1
    elif par.name == 'Coral':
        component.par.Feed = 0.0545
        component.par.Kill = 0.062
        component.par.Diffusiona = 1.0
        component.par.Diffusionb = 0.5
        component.par.Timestep = 1.0
        component.par.Seedradius = 9.0
    elif par.name == 'Spots':
        component.par.Feed = 0.0367
        component.par.Kill = 0.0649
        component.par.Diffusiona = 1.0
        component.par.Diffusionb = 0.5
        component.par.Timestep = 1.0
        component.par.Seedradius = 5.0
    component.op('feedback').par.resetpulse.pulse()
    return

def onValueChange(par, prev):
    if par.name in ('Resolution', 'Seed', 'Seedradius'):
        par.owner.op('feedback').par.resetpulse.pulse()
    return
'''


NETWORK_HELP = '''TURING PATTERNS / GRAY-SCOTT REACTION-DIFFUSION

Select the containing Base COMP and open its Turing parameter page.
Play the timeline. Patterns need several seconds to grow; give them time.
The colored output is out1. The raw state is state (R=A, G=B).

CONTROLS
  Feed / Kill: small changes can produce very different results.
  Passes: simulation steps per frame, not total iterations.
  Timestep: numerical integration step; keep at 1 or below.
  Running: freezes the state while letting display controls remain usable.
  Reset: restarts from the current seed. Reseed: new seed and reset.
  Coral / Dividing Spots: parameter presets and reset.
  Resolution / Seed / Seed Radius: change automatically resets the state.
  Color Amount: 0 = grayscale, 1 = the teal/gold palette.
  Contrast / Invert: display only.

NETWORK
  seed -> feedback -> reaction_diffusion -> state
  feedback Target TOP = state (no physical cable back to feedback)
  state -> colorize -> out1
  seed_pixel, simulation_pixel, display_pixel contain editable GLSL.
  seed_info, simulation_info, display_info show shader compiler messages.

TIPS
  Start at 512 square and 16 passes. Lower passes/resolution if too slow.
  Changing resolution changes the apparent pattern scale.
  Color Amount = 0 is helpful for seeing concentration differences.
  A uniform empty field will stay empty; use Reset or Reseed to inject B.
  A frozen/black result may be a parameter choice: try Coral, then wait.
  If a TOP shows a checkerboard/red error, inspect its corresponding Info DAT.
  Add image effects downstream of out1, not inside the state feedback loop.
  For interaction, add another TOP input to reaction_diffusion and inject B
  from a mask. Its input 0 must remain the A/B state for multipass feedback.
  To inject once per frame rather than once per pass, use uTDPass == 0.

No external dependencies. Save this Base as a .tox for reuse.
'''


def _set(node, name, value):
    """Fail clearly if a required parameter is unavailable in this TD build."""
    parameter = getattr(node.par, name, None)
    if parameter is None:
        raise RuntimeError('Missing parameter {}.{} in this TouchDesigner build'
                           .format(node.path, name))
    parameter.val = value
    return parameter


def _expression(node, name, expression):
    parameter = getattr(node.par, name, None)
    if parameter is None:
        raise RuntimeError('Missing parameter {}.{}'.format(node.path, name))
    parameter.expr = expression


def _number(page, name, label, value, low, high, integer=False):
    group = (page.appendInt if integer else page.appendFloat)(name, label=label)
    parameter = group[0]
    parameter.default = value
    parameter.val = value
    parameter.min, parameter.max = low, high
    parameter.normMin, parameter.normMax = low, high
    parameter.clampMin = True
    parameter.clampMax = True
    return parameter


def _uniforms(node, uniforms):
    # 2023 builds have fixed rows; current builds may use dynamic sequences.
    sequence = getattr(getattr(node, 'seq', None), 'vec', None)
    if sequence is not None:
        sequence.numBlocks = len(uniforms)
    for index, (name, expressions) in enumerate(uniforms):
        _set(node, 'vec{}name'.format(index), name)
        for axis, expression in zip('xyzw', expressions):
            _expression(node, 'vec{}value{}'.format(index, axis), expression)


def _shader(component, name, dat_name, code, position):
    node = component.create(glslTOP, name)
    dat = component.create(textDAT, dat_name)
    dat.text = code.strip() + '\n'
    node.nodeX, node.nodeY = position
    dat.nodeX, dat.nodeY = position[0], position[1] - 170
    _set(node, 'mode', 'vertexpixel')
    # TD injects #version and its built-in declarations; don't put them in DATs.
    _set(node, 'glslversion', 'glsl460')
    _set(node, 'pixeldat', dat.name)
    _set(node, 'format', 'rgba32float')
    _set(node, 'inputfiltertype', 'nearest')
    _set(node, 'inputextenduv', 'repeat')
    _set(node, 'resmult', False)
    _set(node, 'outputresolution', 'useinput')
    _set(node, 'npasses', 1)
    info_name = {'reaction_diffusion': 'simulation', 'colorize': 'display'}.get(name, name)
    info = component.create(infoDAT, info_name + '_info')
    _set(info, 'op', node.name)
    info.nodeX, info.nodeY = position[0], position[1] - 300
    return node


def build_turing_patterns(container=None):
    if container is None:
        container = me.parent()

    # Never overwrite a pre-existing component, even if the script is rerun.
    name, suffix = 'turing_patterns', 2
    while container.op(name) is not None:
        name = 'turing_patterns_{}'.format(suffix)
        suffix += 1
    component = container.create(baseCOMP, name)
    component.nodeX, component.nodeY = me.nodeX + 220, me.nodeY

    page = component.appendCustomPage('Turing')
    _number(page, 'Resolution', 'Resolution (square)', 512, 64, 2048, True)
    _number(page, 'Feed', 'Feed', 0.0545, 0.0, 0.1)
    _number(page, 'Kill', 'Kill', 0.062, 0.0, 0.1)
    _number(page, 'Diffusiona', 'Diffusion A', 1.0, 0.0, 1.0)
    _number(page, 'Diffusionb', 'Diffusion B', 0.5, 0.0, 1.0)
    _number(page, 'Timestep', 'Timestep', 1.0, 0.0, 1.0)
    _number(page, 'Passes', 'Passes / frame', 16, 1, 128, True)
    running = page.appendToggle('Running', label='Running')[0]
    running.default = True
    running.val = True
    _number(page, 'Seed', 'Seed', 1, 0, 1000000, True)
    _number(page, 'Seedradius', 'Seed Radius (cells)', 9.0, 3.0, 32.0)
    for name, label in (('Reset', 'Reset'), ('Reseed', 'Reseed'),
                        ('Coral', 'Coral Preset'), ('Spots', 'Dividing Spots Preset')):
        page.appendPulse(name, label=label)
    _number(page, 'Coloramount', 'Color Amount', 1.0, 0.0, 1.0)
    _number(page, 'Contrast', 'Contrast', 2.5, 0.1, 6.0)
    invert = page.appendToggle('Invert', label='Invert')[0]
    invert.default = False
    invert.val = False

    seed = _shader(component, 'seed', 'seed_pixel', SEED_SHADER, (-600, 200))
    _set(seed, 'outputresolution', 'custom')
    _expression(seed, 'resolutionw', 'parent().par.Resolution')
    _expression(seed, 'resolutionh', 'parent().par.Resolution')
    _uniforms(seed, [('uSeed', ('parent().par.Seed', 'parent().par.Seedradius',
                              'parent().par.Resolution', '0'))])

    feedback = component.create(feedbackTOP, 'feedback')
    feedback.nodeX, feedback.nodeY = -350, 200
    feedback.inputConnectors[0].connect(seed)
    _set(feedback, 'format', 'rgba32float')
    _set(feedback, 'reset', False)

    simulation = _shader(component, 'reaction_diffusion', 'simulation_pixel',
                         SIMULATION_SHADER, (-100, 200))
    simulation.inputConnectors[0].connect(feedback)
    _expression(simulation, 'npasses', 'parent().par.Passes')
    _uniforms(simulation, [
        ('uRates', ('parent().par.Feed', 'parent().par.Kill',
                    'parent().par.Diffusiona', 'parent().par.Diffusionb')),
        ('uStep', ('parent().par.Timestep', 'parent().par.Running', '0', '0')),
    ])

    state = component.create(nullTOP, 'state')
    state.nodeX, state.nodeY = 150, 200
    state.inputConnectors[0].connect(simulation)
    _set(state, 'format', 'rgba32float')
    _set(feedback, 'top', state.name)

    display = _shader(component, 'colorize', 'display_pixel', DISPLAY_SHADER, (400, 200))
    display.inputConnectors[0].connect(state)
    _uniforms(display, [('uDisplay', ('parent().par.Coloramount',
                                     'parent().par.Contrast', 'parent().par.Invert', '0'))])
    _set(display, 'inputfiltertype', 'linear')

    out = component.create(outTOP, 'out1')
    out.nodeX, out.nodeY = 650, 200
    out.inputConnectors[0].connect(display)
    out.viewer = True

    callbacks = component.create(parameterexecuteDAT, 'controls')
    callbacks.nodeX, callbacks.nodeY = -350, -160
    _set(callbacks, 'active', False)
    callbacks.text = CONTROL_CALLBACKS.strip() + '\n'
    _set(callbacks, 'op', '..')
    _set(callbacks, 'pars', 'Reset Reseed Coral Spots Resolution Seed Seedradius')
    _set(callbacks, 'custom', True)
    _set(callbacks, 'builtin', False)
    _set(callbacks, 'onpulse', True)
    _set(callbacks, 'valuechange', True)
    for name in ('expressionchange', 'exportchange', 'enablechange', 'modechange', 'valueschanged'):
        parameter = getattr(callbacks.par, name, None)
        if parameter is not None:
            parameter.val = False
    _set(callbacks, 'active', True)

    help_dat = component.create(textDAT, 'README')
    help_dat.text = NETWORK_HELP
    help_dat.nodeX, help_dat.nodeY = -600, -380

    # The COMP viewer gives the simulation a visible consumer while playback runs.
    _expression(component, 'opviewer', 'me.op("out1")')
    nodeview = getattr(component.par, 'nodeview', None)
    if nodeview is not None:
        nodeview.val = 'opviewer'
    component.viewer = True
    feedback.par.resetpulse.pulse()
    print('Created {}. Play the timeline; view {}/out1.'.format(component.path, component.path))
    print('Controls: select the Base COMP and open its Turing page.')
    return component


# A Text DAT's Run Script action executes this top-level call.
try:
    _script_dat = me
except NameError:
    print('Paste this file into a TouchDesigner Text DAT and choose Run Script.')
else:
    turing_component = build_turing_patterns()
