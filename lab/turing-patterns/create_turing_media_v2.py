"""Build the V2 fixed-clock media-driven reaction-diffusion network in TouchDesigner.

USE
  1. Paste this entire file into a Text DAT in your project.
  2. Right-click the DAT and choose Run Script.
  3. Play the timeline: ambient seed patterns grow immediately (no media).
  4. Select turing_media_v2. On Media, choose Movie File to load your own clip,
     or drag any TOP into Source TOP to drive it live (camera, generator, etc.).
  5. Explore Media > Mask Mode, Injection Rate, and Appearance > Source Overlay.
  6. On Appearance, switch Color Mode to tint, extract or carry the clip's colors.
     Assign Appearance > Ramp TOP to replace the built-in teal/gold ramp with your own.
  7. On Presets, pick a preset and Apply (keeps the evolving state) or Apply + Reset.
     Save Current Preset stores your settings in the component; Export/Import share them.
  8. On Presets, press Generate Thumbnails, then view fk_explorer as a panel and
     click the Feed/Kill map or a reference thumbnail.

Phase 8 adds a compact status panel, shader diagnostics and consolidated validation.
Phase 7 adds measured GPU optimizations and configurable color/palette histories.
Phase 6 unifies boundaries and adds bounded, optional Velocity TOP transport.
Phase 5 adds raw state snapshots, independent resets and safe state resampling.
Phase 4 adds a versioned preset table, preset import/export and the Feed/Kill explorer.
Phase 3 adds independent media modes, domain confinement and carried-color sourcing.
Phase 2 provides the fixed simulation clock and explicit GPU state storage. No external Python packages or shader files.
Re-running creates turing_media_v2, turing_media_v2_2, and so on; existing operators are retained.
Outputs: out1 = final image, patterns = colored simulation, mask_preview =
influence mask, source_preview = fitted RGBA source, palette = clip color
ramp, state = raw A/B concentrations plus carried color.
Clear Source TOP and Movie File to remove the media influence. No external dependencies.

Default: 512 square, RGBA32F state, 60 ticks/second, 16 solver updates/tick.
Turn on Simulation > Rectangular Canvas for an independent Width and Height.
Simulation > Cell Size runs the simulation on a coarser grid (canvas / Cell Size)
and upscales it for display: larger cells give thicker lines at any canvas size.
Simulation > Speed controls elapsed simulation time; Solver Quality controls accuracy.
Save the .toe or save this component as a .tox to keep the generated network.

References:
  https://www.karlsims.com/rd.html
  https://derivative.ca/UserGuide/GLSL_TOP
  https://derivative.ca/UserGuide/Feedback_TOP

Phase 1 baseline results are in validation/phase1. Phase 2 clock validation and
reproduction instructions are in validation/phase2. The builder is standalone;
validation files and TDAPI are not required. Phase 3 validation is in
validation/phase3; Phase 4 preset/explorer validation is in validation/phase4.
Phase 5 validation is in validation/phase5; Phase 6 boundary/flow validation is in
validation/phase6; Phase 7 profiling/quality checks are in validation/phase7.
Phase 8 diagnostics and consolidated live validation are in validation/phase8.
"""


# =============================================================================
# 1. Configuration
# =============================================================================

import math

COMPONENT_BASENAME = 'turing_media_v2'
TICK_SECONDS = 1.0 / 60.0

def _rate(blend, frequency=60.0):
    return -math.log1p(-blend) * frequency


# The clip palette is built from a square grid of averaged cells, sorted into a ramp.
PALETTE_CELLS = 8
PALETTE_WIDTH = 64

# Canvas size in cells: square Resolution, or independent Width/Height when Rectangle is on.
CANVAS_WIDTH = 'parent().fetch("Appliedsize", (512, 512, 512, 512))[0]'
CANVAS_HEIGHT = 'parent().fetch("Appliedsize", (512, 512, 512, 512))[1]'
CANVAS_ASPECT = '({}) / max(1, ({}))'.format(CANVAS_WIDTH, CANVAS_HEIGHT)

HAS_SOURCE_TOP = 'parent().par.Sourcetop.eval() is not None'
HAS_MOVIE = 'parent().par.Moviefile.eval().strip()'
HAS_MEDIA = '({} or {})'.format(HAS_SOURCE_TOP, HAS_MOVIE)
HAS_DOMAIN = 'parent().par.Domaintop.eval() is not None'
HAS_VELOCITY = 'parent().par.Velocitytop.eval() is not None'
SIM_WIDTH = 'parent().fetch("Appliedsize", (512, 512, 512, 512))[2]'
SIM_HEIGHT = 'parent().fetch("Appliedsize", (512, 512, 512, 512))[3]'


# =============================================================================
# 2. Shared GLSL
# =============================================================================

# Shared GLSL: Oklab keeps averaged colours perceptually even; grey is a = b = 0.
OKLAB_GLSL = r"""
vec3 toLinear(vec3 c) { return pow(max(c, 0.0), vec3(2.2)); }
vec3 toDisplay(vec3 c) { return pow(max(c, 0.0), vec3(1.0 / 2.2)); }

vec3 linearToOklab(vec3 c) {
    float l = 0.4122214708 * c.r + 0.5363325363 * c.g + 0.0514459929 * c.b;
    float m = 0.2119034982 * c.r + 0.6806995451 * c.g + 0.1073969566 * c.b;
    float s = 0.0883024619 * c.r + 0.2817188376 * c.g + 0.6299787005 * c.b;
    vec3 lms = pow(max(vec3(l, m, s), 0.0), vec3(1.0 / 3.0));
    return vec3(0.2104542553 * lms.x + 0.7936177850 * lms.y - 0.0040720468 * lms.z,
                1.9779984951 * lms.x - 2.4285922050 * lms.y + 0.4505937099 * lms.z,
                0.0259040371 * lms.x + 0.7827717662 * lms.y - 0.8086757660 * lms.z);
}

vec3 oklabToLinear(vec3 lab) {
    vec3 lms = vec3(lab.x + 0.3963377774 * lab.y + 0.2158037573 * lab.z,
                    lab.x - 0.1055613458 * lab.y - 0.0638541728 * lab.z,
                    lab.x - 0.0894841775 * lab.y - 1.2914855480 * lab.z);
    lms = lms * lms * lms;
    return vec3( 4.0767416621 * lms.x - 3.3077115913 * lms.y + 0.2309699292 * lms.z,
                -1.2684380046 * lms.x + 2.6097574011 * lms.y - 0.3413193965 * lms.z,
                -0.0041960863 * lms.x - 0.7034186147 * lms.y + 1.7076147010 * lms.z);
}
"""


# Shared GLSL: the original teal/gold palette, also the fallback for other modes.
FIXED_PALETTE_GLSL = r"""
const vec3 PALETTE_DARK = vec3(0.012, 0.020, 0.040);
const vec3 PALETTE_MIDDLE = vec3(0.05, 0.65, 0.75);
const vec3 PALETTE_LIGHT = vec3(1.0, 0.80, 0.35);

vec3 fixedPalette(float t) {
    vec3 palette = mix(PALETTE_DARK, PALETTE_MIDDLE, smoothstep(0.0, 0.55, t));
    return mix(palette, PALETTE_LIGHT, smoothstep(0.45, 1.0, t));
}
"""


# Canvas addressing is shared by diffusion, transport and display. Display uses
# boundaryCoord only: both closed modes reconstruct with held edge values.
BOUNDARY_GLSL = r"""
uniform vec4 uBoundary; // canvas mode: wrap=0, no flux=1, empty exterior=2
const vec4 EMPTY_CELL = vec4(1.0, 0.0, 0.0, 0.0);
bool cellOutside(ivec2 p, ivec2 size) {
    return any(lessThan(p, ivec2(0))) || any(greaterThanEqual(p, size));
}
ivec2 boundaryCoord(ivec2 p, ivec2 size) {
    return uBoundary.x < 0.5 ? (p % size + size) % size : clamp(p, ivec2(0), size - 1);
}
vec4 boundaryState(ivec2 p, ivec2 size) {
    if (uBoundary.x > 1.5 && cellOutside(p, size)) return EMPTY_CELL;
    return texelFetch(sTD2DInputs[0], boundaryCoord(p, size), 0);
}
"""


# Domain walls are independent of the canvas exterior. Wrap repeats their mask;
# closed canvas modes extend edge mask values and never join opposite sides.
def _domain_glsl(input_index, channel="r"):
    return BOUNDARY_GLSL + r"""
uniform vec4 uDomain; // enabled, wall boundary (no flux / empty exterior), unused, unused
bool domainOpen(ivec2 p, ivec2 size) {
    if (uDomain.x < 0.5) return true;
    return texelFetch(sTD2DInputs[DOMAIN_INPUT], boundaryCoord(p, size), 0).DOMAIN_CHANNEL > 0.5;
}
vec4 domainBoundary(vec4 center) {
    return uDomain.y < 0.5 ? center : EMPTY_CELL;
}
""".replace('DOMAIN_INPUT', str(input_index)).replace('DOMAIN_CHANNEL', channel)


def _base_palette_glsl(ramp_v):
    """Shared GLSL: the optional Color > Ramp TOP, read from input 2 at row ramp_v, else the fixed ramp."""
    return FIXED_PALETTE_GLSL + r"""
uniform vec4 uRamp; // ramp TOP assigned, unused, unused, unused

// A horizontal ramp read left (t = 0) to right (t = 1) at texel centres.
vec3 basePalette(float t) {
    if (uRamp.x < 0.5) return fixedPalette(t);
    float width = float(textureSize(sTD2DInputs[2], 0).x);
    float x = (t * (width - 1.0) + 0.5) / width;
    return texture(sTD2DInputs[2], vec2(x, RAMP_V)).rgb;
}
""".replace('RAMP_V', repr(float(ramp_v)))


# =============================================================================
# 3. Simulation shaders
# =============================================================================

SEED_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uSeed; // random seed, radius in cells, unused, ambient seeds
uniform vec4 uSeedSize; // canvas width, height in cells, unused, unused
""" + _domain_glsl(0) + r"""

float hash(float n) {
    return fract(sin(n * 127.1 + uSeed.x * 31.7) * 43758.5453);
}

void main() {
    if (!domainOpen(ivec2(gl_FragCoord.xy), ivec2(uSeedSize.xy))) {
        fragColor = TDOutputSwizzle(EMPTY_CELL);
        return;
    }
    vec2 uv = vUV.st;
    float patchMask = 0.0;
    // Ten separated patches of chemical B, including one at the center.
    for (int i = 0; i < 10; ++i) {
        float n = float(i);
        vec2 center = (i == 0) ? vec2(0.5) :
            vec2(0.1 + 0.8 * hash(n * 3.0 + 1.0),
                 0.1 + 0.8 * hash(n * 3.0 + 2.0));
        // Measured in cells so patches stay round on a rectangular canvas.
        float seedMask = 1.0 - step(uSeed.y, length((uv - center) * uSeedSize.xy));
        patchMask = max(patchMask, seedMask);
    }
    // A gentler perturbation supports both the coral and dividing-spot presets.
    patchMask *= uSeed.w; // optional ambient seeds
    float A = mix(1.0, 0.5, patchMask);
    float B = 0.25 * patchMask;
    // Blue/alpha hold carried colour (Oklab a/b); every reset starts colourless.
    fragColor = TDOutputSwizzle(vec4(A, B, 0.0, 0.0));
}
"""


SIMULATION_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uRates; // feed, kill, diffusion A, diffusion B
uniform vec4 uStep;  // chemistry dt, substep seconds, maintain carried color, tick seconds
uniform vec4 uInfluence; // injection and recovery rates / simulation second
uniform vec4 uDye; // spread, injection, decay rates / simulation second, source (alpha/mask)
uniform vec4 uInfluenceMode; // continuous/stamp/chemistry, chemistry blend, unused, unused
uniform vec4 uChemistry; // feed min/max, kill min/max
""" + _domain_glsl(1, "g") + OKLAB_GLSL + r"""
const ivec2 OFFSETS[8] = ivec2[8](ivec2(-1, 0), ivec2(1, 0), ivec2(0, -1), ivec2(0, 1),
                                  ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1));
const float WEIGHTS[8] = float[8](0.2, 0.2, 0.2, 0.2, 0.05, 0.05, 0.05, 0.05);

// R/G = A/B, blue/alpha = signed Oklab a/b. The shared canvas helper
// wraps, holds an edge value (No Flux), or supplies empty exterior state.
vec4 readCell(ivec2 p) {
    return boundaryState(p, textureSize(sTD2DInputs[0], 0));
}

// Colour is weighted by chemical B, so it flows outward with growing pattern.
vec3 dyeSample(vec4 cell, float weight) {
    float w = weight * (cell.g + 0.001);
    return vec3(cell.ba * w, w);
}

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    if (!domainOpen(p, size)) {
        fragColor = TDOutputSwizzle(EMPTY_CELL);
        return;
    }
    vec4 cell = readCell(p);
    vec2 ab = cell.rg;

    // Neighbor differences preserve a uniform field exactly (no weight-sum drift).
    vec2 lap = vec2(0.0);
    bool carry = uStep.z > 0.5;
    vec3 dye = carry ? dyeSample(cell, 1.0) : vec3(0.0);
    for (int i = 0; i < 8; ++i) {
        ivec2 offset = OFFSETS[i];
        bool exterior = uBoundary.x > 1.5 && cellOutside(p + offset, size);
        bool open = domainOpen(p + offset, size);
        // Diagonal taps cannot cut across blocked orthogonal cells at corners.
        if (offset.x != 0 && offset.y != 0) {
            open = open && domainOpen(p + ivec2(offset.x, 0), size)
                        && domainOpen(p + ivec2(0, offset.y), size);
        }
        vec4 neighbor = exterior ? EMPTY_CELL : (open ? readCell(p + offset) : domainBoundary(cell));
        lap += WEIGHTS[i] * (neighbor.rg - ab);
        if (carry) dye += dyeSample(neighbor, WEIGHTS[i]);
    }
    vec2 chroma = carry ? mix(cell.ba, dye.xy / dye.z, 1.0 - exp(-uDye.x * uStep.y)) : cell.ba;

    float maskValue = clamp(texture(sTD2DInputs[1], vUV.st).r, 0.0, 1.0);
    vec4 source = texture(sTD2DInputs[2], vUV.st); // prepared straight RGBA
    vec2 rates = uRates.xy;
    if (uInfluenceMode.x > 1.5) {
        vec2 mapped = vec2(mix(uChemistry.x, uChemistry.y, maskValue),
                           mix(uChemistry.z, uChemistry.w, maskValue));
        // Transparent media and missing sources retain uniform chemistry.
        rates = mix(rates, mapped, uInfluenceMode.y * clamp(source.a, 0.0, 1.0));
    }
    float reaction = ab.x * ab.y * ab.y;
    vec2 change;
    change.x = uRates.z * lap.x - reaction + rates.x * (1.0 - ab.x);
    change.y = uRates.w * lap.y + reaction - (rates.x + rates.y) * ab.y;
    vec2 nextState = clamp(ab + uStep.x * change, 0.0, 1.0);
    if (uTDPass == 0) {
        // Recovery/fade is explicit, rather than multiplying the state by black.
        nextState = mix(nextState, vec2(1.0, 0.0), 1.0 - exp(-uInfluence.y * uStep.w));
        if (uInfluenceMode.x < 0.5) {
            nextState = mix(nextState, vec2(0.5, 0.25), 1.0 - exp(-uInfluence.x * maskValue * uStep.w));
        }
        // Color injection stays independent of chemical influence mode.
        if (carry) {
        float colorMask = uDye.w < 0.5 ? clamp(source.a, 0.0, 1.0) : maskValue;
        vec2 sourceChroma = linearToOklab(toLinear(source.rgb)).yz;
        chroma = mix(chroma, sourceChroma, 1.0 - exp(-uDye.y * colorMask * uStep.w));
        chroma *= exp(-uDye.z * uStep.w);
        }
    }
    fragColor = TDOutputSwizzle(vec4(nextState, chroma));
}
"""


STAMP_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uStamp; // stamp amount, unused, unused, unused
""" + _domain_glsl(2) + r"""
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    vec4 cell = texelFetch(sTD2DInputs[0], p, 0);
    if (!domainOpen(p, size)) cell = EMPTY_CELL;
    else {
        float mask = clamp(texture(sTD2DInputs[1], vUV.st).r, 0.0, 1.0);
        cell.rg = mix(cell.rg, vec2(0.5, 0.25), uStamp.x * mask);
    }
    fragColor = TDOutputSwizzle(cell);
}
"""


TRANSFORM_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uWarp; // grow, scale X/Y (% / second), rotation radians / second
uniform vec4 uDrift; // translate X/Y in cells / second, pivot X/Y in UV
uniform vec4 uWarpMode; // global transform enabled, unused, tick seconds, unused
uniform vec4 uFlow; // velocity enabled, strength, max displacement cells/tick, unused

""" + _domain_glsl(1) + r"""
// Explicit bilinear sampling preserves signed float state and canvas semantics.
vec4 readCell(ivec2 p, ivec2 size, vec4 center) {
    if (uBoundary.x > 1.5 && cellOutside(p, size)) return EMPTY_CELL;
    if (!domainOpen(p, size)) return domainBoundary(center);
    return boundaryState(p, size);
}

bool domainPath(ivec2 from, ivec2 to, ivec2 size) {
    ivec2 delta = to - from;
    ivec2 count = abs(delta), direction = ivec2(sign(vec2(delta)));
    if (count.x + count.y > 1024) return false;
    ivec2 at = from, moved = ivec2(0);
    for (int i = 0; i < 1024; ++i) {
        if (uBoundary.x > 0.5 && cellOutside(at, size)) return true;
        if (!domainOpen(at, size)) return false;
        if (at == to) return true;
        float tx = count.x == 0 ? 1e20 : (float(moved.x) + 0.5) / float(count.x);
        float ty = count.y == 0 ? 1e20 : (float(moved.y) + 0.5) / float(count.y);
        if (abs(tx - ty) < 1e-7) {
            if (!domainOpen(at + ivec2(direction.x, 0), size)
             || !domainOpen(at + ivec2(0, direction.y), size)) return false;
            at += direction;
            moved += ivec2(1);
        } else if (tx < ty) { at.x += direction.x; moved.x += 1; }
        else { at.y += direction.y; moved.y += 1; }
    }
    return domainOpen(at, size) && at == to;
}

void main() {
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 center = texelFetch(sTD2DInputs[0], p, 0);
    if (!domainOpen(p, size)) {
        fragColor = TDOutputSwizzle(EMPTY_CELL);
        return;
    }
    vec2 displacement = vec2(0.0);
    if (uFlow.x > 0.5) {
        // Prepared RG contains signed cells/second; B/A are ignored.
        vec2 velocity = texelFetch(sTD2DInputs[2], p, 0).rg;
        displacement = velocity * uFlow.y * uWarpMode.z;
        float distance = length(displacement);
        if (distance > uFlow.z) displacement *= uFlow.z / distance;
    }
    bool globalMove = uWarpMode.x > 0.5 &&
                      (any(notEqual(uWarp, vec4(0.0))) || any(notEqual(uDrift.xy, vec2(0.0))));
    // A zero field takes precisely the ordinary path; avoid identity resampling.
    if (!globalMove && all(equal(displacement, vec2(0.0)))) {
        fragColor = TDOutputSwizzle(center);
        return;
    }
    // Forward order: global scale/rotate/translate, then local flow. Evaluate
    // velocity at destination centers and backtrace once at the fixed tick boundary.
    vec2 source = gl_FragCoord.xy - displacement;
    if (globalMove) {
        vec2 pivot = uDrift.zw * vec2(size);
        vec2 q = source - pivot - uDrift.xy * uWarpMode.z;
        float c = cos(uWarp.w * uWarpMode.z), s = sin(uWarp.w * uWarpMode.z);
        q = vec2(c * q.x + s * q.y, -s * q.x + c * q.y);
        vec2 scale = exp((uWarp.x + uWarp.yz) * 0.01 * uWarpMode.z);
        source = pivot + q / max(scale, vec2(0.01));
    }
    source -= 0.5;
    ivec2 base = ivec2(floor(source));
    vec2 f = source - vec2(base);
    if (uDomain.x > 0.5) {
        // Conservative supercover traversal for EACH bilinear tap: a long
        // backtrace cannot jump across a wall or cut a blocked diagonal corner.
        // More than 1024 cell crossings rejects transport rather than skipping barriers.
        bool open = ((1.0-f.x)*(1.0-f.y) <= 0.0 || domainPath(p, base, size))
                 && (f.x*(1.0-f.y) <= 0.0 || domainPath(p, base + ivec2(1, 0), size))
                 && ((1.0-f.x)*f.y <= 0.0 || domainPath(p, base + ivec2(0, 1), size))
                 && (f.x*f.y <= 0.0 || domainPath(p, base + ivec2(1, 1), size));
        if (!open) {
            fragColor = TDOutputSwizzle(domainBoundary(center));
            return;
        }
    }
    vec4 bottom = mix(readCell(base, size, center), readCell(base + ivec2(1, 0), size, center), f.x);
    vec4 top = mix(readCell(base + ivec2(0, 1), size, center), readCell(base + ivec2(1, 1), size, center), f.x);
    fragColor = TDOutputSwizzle(mix(bottom, top, f.y));
}
"""


VELOCITY_SHADER = r"""
layout(location = 0) out vec4 fragColor;
""" + BOUNDARY_GLSL + r"""
vec2 velocityCell(ivec2 p, ivec2 size) {
    vec2 v = texelFetch(sTD2DInputs[0], boundaryCoord(p, size), 0).rg;
    // Invalid channels become zero. Finite extremes are bounded before strength
    // and length calculations so no finite input can overflow the backtrace.
    if (isnan(v.x) || isinf(v.x)) v.x = 0.0;
    if (isnan(v.y) || isinf(v.y)) v.y = 0.0;
    return clamp(v, vec2(-1e6), vec2(1e6));
}
void main() {
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    vec2 q = vUV.st * vec2(size) - 0.5;
    ivec2 p = ivec2(floor(q));
    vec2 f = fract(q);
    vec2 a = mix(velocityCell(p, size), velocityCell(p+ivec2(1,0), size), f.x);
    vec2 b = mix(velocityCell(p+ivec2(0,1), size), velocityCell(p+ivec2(1,1), size), f.x);
    fragColor = TDOutputSwizzle(vec4(mix(a,b,f.y), 0.0, 0.0));
}
"""


STATE_RESET_SHADER = r"""
layout(location = 0) out vec4 fragColor;
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 old = texelFetch(sTD2DInputs[0], p, 0);
    vec4 seed = texelFetch(sTD2DInputs[1], p, 0);
    fragColor = TDOutputSwizzle(vec4(seed.rg, old.ba));
}
"""

CLEAR_COLOR_SHADER = r"""
layout(location = 0) out vec4 fragColor;
void main() {
    vec4 state = texelFetch(sTD2DInputs[0], ivec2(gl_FragCoord.xy), 0);
    fragColor = TDOutputSwizzle(vec4(state.rg, 0.0, 0.0));
}
"""

RESIZE_STATE_SHADER = r"""
layout(location = 0) out vec4 fragColor;
""" + _domain_glsl(1) + r"""
void main() {
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    ivec2 dest = textureSize(sTD2DInputs[1], 0);
    if (!domainOpen(ivec2(gl_FragCoord.xy), dest)) {
        fragColor = TDOutputSwizzle(EMPTY_CELL);
        return;
    }
    vec2 q = vUV.st * vec2(size) - 0.5;
    ivec2 p = ivec2(floor(q));
    vec2 f = fract(q);
    vec4 a = texelFetch(sTD2DInputs[0], clamp(p, ivec2(0), size-1), 0);
    vec4 b = texelFetch(sTD2DInputs[0], clamp(p+ivec2(1,0), ivec2(0), size-1), 0);
    vec4 c = texelFetch(sTD2DInputs[0], clamp(p+ivec2(0,1), ivec2(0), size-1), 0);
    vec4 d = texelFetch(sTD2DInputs[0], clamp(p+ivec2(1,1), ivec2(0), size-1), 0);
    fragColor = TDOutputSwizzle(mix(mix(a,b,f.x), mix(c,d,f.x), f.y));
}
"""

UPLOAD_CALLBACKS = r'''
def onCook(scriptOp):
    import numpy as np
    array = scriptOp.parent().fetch('Uploadarray', None)
    if array is None:
        array = np.zeros((8, 8, 4), dtype=np.float32)
    scriptOp.copyNumpyArray(array.copy())
'''


# =============================================================================
# 4. Media processing
# =============================================================================

INFLUENCE_FIELD_SHADER = r"""
layout(location = 0) out vec4 fragColor;
void main() {
    float mask = texture(sTD2DInputs[0], vUV.st).r;
    float domain = texture(sTD2DInputs[1], vUV.st).r;
    fragColor = TDOutputSwizzle(vec4(mask, domain, 0.0, 1.0));
}
"""


DOMAIN_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uDomainMask; // enabled, threshold, invert, unused
void main() {
    float value = texture(sTD2DInputs[0], vUV.st).r;
    value = mix(value, 1.0 - value, uDomainMask.z);
    float open = uDomainMask.x < 0.5 ? 1.0 : step(uDomainMask.y, value);
    fragColor = TDOutputSwizzle(vec4(vec3(open), 1.0));
}
"""


PREPARE_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uTransform; // scale, offset X, offset Y, rotation in radians
uniform vec4 uAlpha; // unpremultiply source, ignore alpha, original aspect ratio, canvas aspect
void main() {
    vec2 sourceSize = vec2(textureSize(sTD2DInputs[0], 0));
    float aspect = (uAlpha.z > 0.0) ? uAlpha.z : sourceSize.x / max(sourceSize.y, 1.0);
    float canvas = max(uAlpha.w, 0.0001);
    // Work in height-normalized units (canvas spans canvas x 1) so fitting and
    // rotation keep the source undistorted on a rectangular canvas.
    vec2 fitSize = (aspect >= canvas) ? vec2(canvas, canvas / aspect) : vec2(aspect, 1.0);
    vec2 q = (vUV.st - vec2(0.5) - uTransform.yz) * vec2(canvas, 1.0);
    float c = cos(uTransform.w), s = sin(uTransform.w);
    // Inverse transform the output coordinate into the source texture.
    q = vec2(c * q.x + s * q.y, -s * q.x + c * q.y);
    vec2 uv = q / (fitSize * max(uTransform.x, 0.01)) + vec2(0.5);
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) {
        fragColor = TDOutputSwizzle(vec4(0.0));
        return;
    }
    vec4 rgba = texture(sTD2DInputs[0], uv);
    float originalAlpha = clamp(rgba.a, 0.0, 1.0);
    if (uAlpha.x > 0.5) {
        rgba.rgb = (originalAlpha > 0.0001) ? rgba.rgb / originalAlpha : vec3(0.0);
    }
    rgba.a = (uAlpha.y > 0.5) ? 1.0 : originalAlpha;
    if (rgba.a < 0.0001) rgba.rgb = vec3(0.0);
    fragColor = TDOutputSwizzle(vec4(clamp(rgba.rgb, 0.0, 1.0), rgba.a));
}
"""


# Alpha-weighted box quadrature before simulation-resolution masks/color injection.
# Full-grid path is exact. Coarse grids use 4x4 stratified bilinear taps over each
# destination footprint (bounded cost); this is a low-pass approximation, not a
# promise to preserve sub-cell detail. Transparent RGB never bleeds into color.
SIM_SOURCE_SHADER = r"""
layout(location = 0) out vec4 fragColor;
vec4 premultCell(ivec2 p, ivec2 size) {
    vec4 s = texelFetch(sTD2DInputs[0], clamp(p, ivec2(0), size-1), 0);
    return vec4(s.rgb*s.a, s.a);
}
vec4 premultSample(vec2 uv, ivec2 size) {
    vec2 pos = uv*vec2(size)-0.5;
    ivec2 p = ivec2(floor(pos));
    vec2 f = fract(pos);
    return mix(mix(premultCell(p,size), premultCell(p+ivec2(1,0),size),f.x),
               mix(premultCell(p+ivec2(0,1),size), premultCell(p+ivec2(1,1),size),f.x),f.y);
}
void main() {
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    if (all(equal(size, ivec2(uTDOutputInfo.res.zw)))) {
        fragColor = TDOutputSwizzle(texelFetch(sTD2DInputs[0], ivec2(gl_FragCoord.xy), 0));
        return;
    }
    vec2 ratio = vec2(size) * uTDOutputInfo.res.xy;
    ivec2 cells = ivec2(round(ratio));
    if (all(lessThan(abs(ratio-vec2(cells)), vec2(0.00001)))
            && all(greaterThanEqual(cells, ivec2(1))) && all(lessThanEqual(cells, ivec2(4)))) {
        // Exact small integer box: each source cell contributes once. Avoids
        // redundant bilinear taps at positions already centered on source texels.
        ivec2 origin = ivec2(gl_FragCoord.xy) * cells;
        vec4 total = vec4(0.0);
        for (int y=0; y<cells.y; ++y) for (int x=0; x<cells.x; ++x)
            total += premultCell(origin+ivec2(x,y), size);
        total /= float(cells.x*cells.y);
        fragColor = TDOutputSwizzle(vec4(total.a > 0.000001 ? total.rgb/total.a : vec3(0.0), total.a));
        return;
    }
    vec2 footprint = uTDOutputInfo.res.xy;
    vec4 total = vec4(0.0);
    for (int y = 0; y < 4; ++y) for (int x = 0; x < 4; ++x) {
        vec2 uv = vUV.st + ((vec2(x,y)+0.5)/4.0-0.5)*footprint;
        total += premultSample(uv, size);
    }
    total /= 16.0;
    fragColor = TDOutputSwizzle(vec4(total.a > 0.000001 ? total.rgb/total.a : vec3(0.0), total.a));
}
"""


MASK_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uMask; // mode index, gain, edge width in pixels, smoothing radius
uniform vec4 uMotion; // motion gain, history warmed up, unused, unused

vec4 sampleCurrent(vec2 uv) {
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) return vec4(0.0);
    return texture(sTD2DInputs[0], uv);
}
float luminance(vec3 rgb) {
    return clamp(dot(rgb, vec3(0.2126, 0.7152, 0.0722)), 0.0, 1.0);
}
float signalAt(vec2 uv, bool useTexture) {
    vec4 rgba = sampleCurrent(uv);
    return useTexture ? rgba.a * luminance(rgba.rgb) : rgba.a;
}
float rawMask(vec2 uv) {
    int mode = int(uMask.x + 0.5);
    // Motion smoothing samples outside the canvas too. Both histories are
    // transparent there; clamping only the previous sample creates false motion
    // along the edge of a completely stationary opaque/fractional-alpha source.
    if (mode == 5 && (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0))))) return 0.0;
    vec4 rgba = sampleCurrent(uv);
    float bright = rgba.a * luminance(rgba.rgb);
    if (mode == 0) return rgba.a;
    if (mode == 1) return bright;
    if (mode == 2) return rgba.a * (1.0 - luminance(rgba.rgb));
    if (mode == 3 || mode == 4) {
        bool useTexture = (mode == 4);
        vec2 d = vec2(uMask.z) / vec2(textureSize(sTD2DInputs[0], 0));
        float dx = signalAt(uv + vec2(d.x, 0.0), useTexture)
                 - signalAt(uv - vec2(d.x, 0.0), useTexture);
        float dy = signalAt(uv + vec2(0.0, d.y), useTexture)
                 - signalAt(uv - vec2(0.0, d.y), useTexture);
        float edge = clamp(length(vec2(dx, dy)), 0.0, 1.0);
        return useTexture ? edge * rgba.a : edge;
    }
    // Frame difference, not optical flow. Changes to alpha and texture both count.
    if (uMotion.y < 0.5) return 0.0;
    vec4 previous = texture(sTD2DInputs[1], clamp(uv, vec2(0.0), vec2(1.0)));
    float change = max(abs(rgba.a - previous.a),
                       abs(bright - previous.a * luminance(previous.rgb)));
    // Identical float textures can differ by a few ULPs after luminance math.
    return change <= 1e-6 ? 0.0 : clamp(change * uMotion.x, 0.0, 1.0);
}
void main() {
    vec2 uv = vUV.st;
    float value = rawMask(uv);
    if (uMask.w > 0.0) {
        vec2 d = vec2(uMask.w) / vec2(textureSize(sTD2DInputs[0], 0));
        value *= 0.25;
        value += 0.125 * (rawMask(uv + vec2(d.x, 0.0)) + rawMask(uv - vec2(d.x, 0.0))
                         + rawMask(uv + vec2(0.0, d.y)) + rawMask(uv - vec2(0.0, d.y)));
        value += 0.0625 * (rawMask(uv + d) + rawMask(uv - d)
                          + rawMask(uv + vec2(d.x, -d.y)) + rawMask(uv + vec2(-d.x, d.y)));
    }
    value = clamp(value * uMask.y, 0.0, 1.0);
    // Masks use RGB for their numeric value; alpha stays opaque.
    fragColor = TDOutputSwizzle(vec4(vec3(value), 1.0));
}
"""


# =============================================================================
# 5. Display and palette shaders
# =============================================================================

DISPLAY_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uDisplay; // color amount, contrast, invert, color mode index
uniform vec4 uColor; // tint spread in pixels, palette anchoring, carried saturation, ramp width
uniform vec4 uUpscale; // filter index (smooth, linear, nearest), unused, unused, unused
""" + BOUNDARY_GLSL + OKLAB_GLSL + _base_palette_glsl(0.75) + r"""
// Display reconstruction holds edge texels for BOTH closed boundary modes.
// It never adds empty padding or interpolates across opposite closed edges.
vec4 stateCell(ivec2 p, ivec2 size) {
    return texelFetch(sTD2DInputs[0], boundaryCoord(p, size), 0);
}

vec4 catmullRomWeights(float t) {
    float t2 = t * t, t3 = t2 * t;
    return vec4(-0.5 * t3 + t2 - 0.5 * t,
                 1.5 * t3 - 2.5 * t2 + 1.0,
                -1.5 * t3 + 2.0 * t2 + 0.5 * t,
                 0.5 * t3 - 0.5 * t2);
}

vec4 catmullRomRow(ivec2 p, ivec2 size, vec4 w) {
    return stateCell(p + ivec2(-1, 0), size) * w.x + stateCell(p, size) * w.y
         + stateCell(p + ivec2(1, 0), size) * w.z + stateCell(p + ivec2(2, 0), size) * w.w;
}

// Catmull-Rom passes through every cell value, so at Cell Size 1 it matches the state exactly.
vec4 sampleState(vec2 uv) {
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    if (all(equal(size, ivec2(uTDOutputInfo.res.zw))))
        return texelFetch(sTD2DInputs[0], ivec2(gl_FragCoord.xy), 0);
    int upscaleMode = int(uUpscale.x + 0.5);
    if (upscaleMode == 2) return stateCell(ivec2(floor(uv * vec2(size))), size);
    vec2 pos = uv * vec2(size) - 0.5;
    ivec2 base = ivec2(floor(pos));
    vec2 f = pos - vec2(base);
    if (upscaleMode == 1) {
        vec4 bottom = mix(stateCell(base, size), stateCell(base + ivec2(1, 0), size), f.x);
        vec4 top = mix(stateCell(base + ivec2(0, 1), size), stateCell(base + ivec2(1, 1), size), f.x);
        return mix(bottom, top, f.y);
    }
    vec4 wx = catmullRomWeights(f.x), wy = catmullRomWeights(f.y);
    return catmullRomRow(base + ivec2(0, -1), size, wx) * wy.x
         + catmullRomRow(base, size, wx) * wy.y
         + catmullRomRow(base + ivec2(0, 1), size, wx) * wy.z
         + catmullRomRow(base + ivec2(0, 2), size, wx) * wy.w;
}

// Disk-averaged source, premultiplied so transparent pixels contribute no colour.
vec4 tintSource(vec2 uv) {
    vec4 s = texture(sTD2DInputs[1], uv);
    vec4 total = vec4(s.rgb * s.a, s.a);
    if (uColor.x <= 0.0) return total;
    vec2 texel = 1.0 / vec2(textureSize(sTD2DInputs[1], 0));
    // Golden-angle spiral: sixteen evenly spread taps over the disk.
    for (int i = 0; i < 16; ++i) {
        float radius = uColor.x * sqrt((float(i) + 0.5) / 16.0);
        float angle = float(i) * 2.39996323;
        s = texture(sTD2DInputs[1], uv + radius * texel * vec2(cos(angle), sin(angle)));
        total += vec4(s.rgb * s.a, s.a);
    }
    return total / 17.0;
}

void main() {
    vec2 uv = vUV.st;
    vec4 state = sampleState(uv);
    float t = clamp(state.g * uDisplay.y, 0.0, 1.0);
    t = mix(t, 1.0 - t, uDisplay.z);
    vec3 palette = basePalette(t);
    int mode = int(uDisplay.w + 0.5);
    if (mode == 1) {
        // Source Tint: the clip's local colour becomes the middle of the ramp.
        vec4 source = tintSource(uv);
        vec3 ink = (source.a > 0.0001) ? source.rgb / source.a : vec3(0.0);
        vec3 tinted = mix(basePalette(0.0), ink, smoothstep(0.0, 0.55, t));
        tinted = mix(tinted, mix(ink, vec3(1.0), 0.6), smoothstep(0.45, 1.0, t));
        palette = mix(palette, tinted, clamp(source.a, 0.0, 1.0));
    } else if (mode == 2) {
        // Clip Palette: look up the luminance-sorted ramp (palette row 0) at texel centres.
        float x = (t * (uColor.w - 1.0) + 0.5) / uColor.w;
        vec3 lab = linearToOklab(toLinear(texture(sTD2DInputs[2], vec2(x, 0.25)).rgb));
        // Anchoring borrows the base ramp's lightness for contrast; hue stays.
        // Darkening scales chroma too, as a shade of the same colour would.
        float lightness = mix(lab.x, linearToOklab(toLinear(palette)).x, uColor.y);
        lab.yz *= min(lightness / max(lab.x, 0.0001), 1.0);
        lab.x = lightness;
        palette = clamp(toDisplay(oklabToLinear(lab)), 0.0, 1.0);
    } else if (mode == 3) {
        // Carried Color: lightness from the base ramp, hue/chroma from the state.
        vec3 lab = linearToOklab(toLinear(palette));
        lab.yz = state.ba * uColor.z;
        palette = clamp(toDisplay(oklabToLinear(lab)), 0.0, 1.0);
    }
    vec3 color = mix(vec3(t), palette, uDisplay.x);
    fragColor = TDOutputSwizzle(vec4(color, 1.0));
}
"""


PALETTE_CELLS_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uPalette; // cells per side, smoothing, history ready, ramp width

// Each output pixel averages an 8x8 grid of samples across its cell of the source.
void main() {
    float side = uPalette.x;
    vec2 origin = floor(vUV.st * side) / side;
    vec4 total = vec4(0.0);
    for (int y = 0; y < 8; ++y) {
        for (int x = 0; x < 8; ++x) {
            vec4 s = texture(sTD2DInputs[0], origin + (vec2(x, y) + 0.5) / (8.0 * side));
            total += vec4(s.rgb * s.a, s.a);
        }
    }
    total /= 64.0;
    vec3 rgb = (total.a > 0.0001) ? total.rgb / total.a : vec3(0.0);
    fragColor = TDOutputSwizzle(vec4(rgb, total.a)); // straight RGB, coverage
}
"""


PALETTE_SORT_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uPalette; // cells per side, smoothing, history ready, ramp width
""" + _base_palette_glsl(0.5) + r"""
const float MIN_COVERAGE = 0.25;

float luminance(vec3 rgb) {
    return dot(rgb, vec3(0.2126, 0.7152, 0.0722));
}

vec4 cellAt(int i, int side) {
    return texelFetch(sTD2DInputs[0], ivec2(i % side, i / side), 0);
}

// Row 0, pixel x holds the colour ranked x/(width-1) of the way from dark to
// light among the visible cells; ties break by index for a stable order.
// Row 1 carries the base ramp (Ramp TOP or fixed) so colorize needs no extra input.
void main() {
    float t = (gl_FragCoord.x - 0.5) / max(uPalette.w - 1.0, 1.0);
    if (gl_FragCoord.y > 1.0) {
        fragColor = TDOutputSwizzle(vec4(basePalette(t), 1.0));
        return;
    }
    if (uRamp.y < 0.5) {
        fragColor = TDOutputSwizzle(texelFetch(sTD2DInputs[1], ivec2(gl_FragCoord.xy), 0));
        return;
    }
    int side = int(uPalette.x + 0.5);
    int count = side * side;
    int visible = 0;
    for (int i = 0; i < count; ++i) {
        if (cellAt(i, side).a >= MIN_COVERAGE) ++visible;
    }
    vec3 color = basePalette(t); // fallback while nothing is visible
    if (visible > 0) {
        float position = t * float(visible - 1);
        int lowRank = int(floor(position));
        int highRank = min(lowRank + 1, visible - 1);
        vec3 low = vec3(0.0), high = vec3(0.0);
        for (int i = 0; i < count; ++i) {
            vec4 cell = cellAt(i, side);
            if (cell.a < MIN_COVERAGE) continue;
            float lum = luminance(cell.rgb);
            int rank = 0;
            for (int j = 0; j < count; ++j) {
                vec4 other = cellAt(j, side);
                float otherLum = luminance(other.rgb);
                if (other.a >= MIN_COVERAGE && (otherLum < lum || (otherLum == lum && j < i))) ++rank;
            }
            if (rank == lowRank) low = cell.rgb;
            if (rank == highRank) high = cell.rgb;
        }
        color = mix(low, high, position - float(lowRank));
    }
    if (uPalette.z > 0.5) {
        // Ease toward the new ramp so cuts and flicker do not strobe the colours.
        vec3 previous = texelFetch(sTD2DInputs[1], ivec2(gl_FragCoord.xy), 0).rgb;
        color = mix(color, previous, uPalette.y);
    }
    fragColor = TDOutputSwizzle(vec4(color, 1.0));
}
"""


COMPOSITE_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uComposite; // source overlay, pattern clipping to alpha, view index, unused
void main() {
    vec2 uv = vUV.st;
    vec4 pattern = texture(sTD2DInputs[0], uv);
    vec4 source = texture(sTD2DInputs[1], uv); // prepared straight RGBA
    float influenceMask = texture(sTD2DInputs[2], uv).r;
    int viewMode = int(uComposite.z + 0.5);
    if (viewMode == 1) {
        fragColor = TDOutputSwizzle(pattern);
        return;
    }
    if (viewMode == 2) {
        fragColor = TDOutputSwizzle(vec4(vec3(influenceMask), 1.0));
        return;
    }
    if (viewMode == 3) {
        // Checkerboard for alpha inspection, baked into this diagnostic view only.
        ivec2 cell = ivec2(gl_FragCoord.xy / 16.0);
        float shade = ((cell.x + cell.y) % 2 == 0) ? 0.12 : 0.24;
        vec3 preview = mix(vec3(shade), source.rgb, source.a);
        fragColor = TDOutputSwizzle(vec4(preview, 1.0));
        return;
    }
    float patternAlpha = mix(1.0, source.a, uComposite.y);
    vec3 background = pattern.rgb * patternAlpha;
    float overlayAlpha = source.a * uComposite.x;
    vec3 color = source.rgb * overlayAlpha + background * (1.0 - overlayAlpha);
    float alpha = overlayAlpha + patternAlpha * (1.0 - overlayAlpha);
    fragColor = TDOutputSwizzle(vec4(color, alpha)); // premultiplied composite
}
"""


# -----------------------------------------------------------------------------
# Feed/Kill explorer
# -----------------------------------------------------------------------------

# Curated reference points (name, feed, kill). Thumbnails are simulated from one
# fixed seed to a fixed age; initialization and media can change the outcome.
FK_EXAMPLES = (
    ('Coral', 0.0545, 0.062),
    ('Dividing Spots', 0.0367, 0.0649),
    ('Worms', 0.029, 0.057),
    ('Holes', 0.039, 0.058),
    ('Chaos', 0.026, 0.051),
    ('Moving Spots', 0.014, 0.054),
    ('Waves', 0.014, 0.045),
    ('U-Skate', 0.062, 0.0609),
)
# Panel = square map + thumbnail atlas (FK_COLUMNS x FK_ROWS tiles, first at top-left).
# Must match the constants in EXPLORER_CALLBACKS.
FK_MAP_SIZE = 512
FK_TILE = 128
FK_COLUMNS = 2
FK_ROWS = 4


def _fk_glsl():
    examples = ', '.join('vec2({!r}, {!r})'.format(feed, kill) for _, feed, kill in FK_EXAMPLES)
    return r"""
const int FK_COUNT = {count};
const int FK_COLUMNS = {columns};
const int FK_ROWS = {rows};
const int FK_TILE = {tile};
const float FK_MAP = {map_size}.0;
const vec2 FK_EXAMPLES[{count}] = vec2[{count}]({examples}); // feed, kill
const vec4 EMPTY_CELL = vec4(1.0, 0.0, 0.0, 0.0);

// Tile (0, 0) is bottom-left in texture space; example 0 sits top-left.
int fkIndex(ivec2 tile) {{ return (FK_ROWS - 1 - tile.y) * FK_COLUMNS + tile.x; }}

vec3 fkHue(int i) {{
    float h = float(i) / float(FK_COUNT);
    vec3 rgb = clamp(abs(mod(h * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);
    return mix(vec3(0.35), rgb, 0.8);
}}
""".format(count=len(FK_EXAMPLES), columns=FK_COLUMNS, rows=FK_ROWS, tile=FK_TILE,
           map_size=FK_MAP_SIZE, examples=examples)


# Every tile uses the same seed layout, so tiles differ only by feed/kill.
FK_SEED_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uFkSeed; // random seed, radius in cells, unused, unused

float hash(float n) {
    return fract(sin(n * 127.1 + uFkSeed.x * 31.7) * 43758.5453);
}

void main() {
    ivec2 local = ivec2(gl_FragCoord.xy) % FK_TILE;
    vec2 uv = (vec2(local) + 0.5) / float(FK_TILE);
    float patchMask = 0.0;
    for (int i = 0; i < 10; ++i) {
        float n = float(i);
        vec2 center = (i == 0) ? vec2(0.5) :
            vec2(0.1 + 0.8 * hash(n * 3.0 + 1.0), 0.1 + 0.8 * hash(n * 3.0 + 2.0));
        patchMask = max(patchMask, 1.0 - step(uFkSeed.y, length(uv - center) * float(FK_TILE)));
    }
    fragColor = TDOutputSwizzle(vec4(mix(1.0, 0.5, patchMask), 0.25 * patchMask, 0.0, 0.0));
}
"""


# Reference solver: dt=1, diffusion 1/.5, sixteen passes per tick; tiles wrap independently.
FK_SIM_SHADER = r"""
layout(location = 0) out vec4 fragColor;
const ivec2 OFFSETS[8] = ivec2[8](ivec2(-1, 0), ivec2(1, 0), ivec2(0, -1), ivec2(0, 1),
                                  ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1));
const float WEIGHTS[8] = float[8](0.2, 0.2, 0.2, 0.2, 0.05, 0.05, 0.05, 0.05);

vec4 readCell(ivec2 origin, ivec2 local) {
    local = (local % FK_TILE + FK_TILE) % FK_TILE;
    return texelFetch(sTD2DInputs[0], origin + local, 0);
}

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    ivec2 tile = p / FK_TILE;
    int index = fkIndex(tile);
    if (index < 0 || index >= FK_COUNT) {
        fragColor = TDOutputSwizzle(EMPTY_CELL);
        return;
    }
    ivec2 origin = tile * FK_TILE;
    vec2 ab = texelFetch(sTD2DInputs[0], p, 0).rg;
    vec2 lap = vec2(0.0);
    for (int i = 0; i < 8; ++i) {
        lap += WEIGHTS[i] * (readCell(origin, p - origin + OFFSETS[i]).rg - ab);
    }
    vec2 rates = FK_EXAMPLES[index];
    float reaction = ab.x * ab.y * ab.y;
    vec2 change = vec2(1.0 * lap.x - reaction + rates.x * (1.0 - ab.x),
                       0.5 * lap.y + reaction - (rates.x + rates.y) * ab.y);
    fragColor = TDOutputSwizzle(vec4(clamp(ab + change, 0.0, 1.0), 0.0, 0.0));
}
"""


FK_PANEL_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uFkMap; // feed min, feed max, kill min, kill max
uniform vec4 uFkCurrent; // feed, kill, thumbnails ready, contrast
""" + FIXED_PALETTE_GLSL + r"""
vec2 mapPixel(vec2 feedKill) {
    return vec2((feedKill.y - uFkMap.z) / (uFkMap.w - uFkMap.z),
                (feedKill.x - uFkMap.x) / (uFkMap.y - uFkMap.x)) * FK_MAP;
}

int selectedExample() {
    for (int i = 0; i < FK_COUNT; ++i) {
        if (all(lessThan(abs(FK_EXAMPLES[i] - uFkCurrent.xy), vec2(1e-6)))) return i;
    }
    return -1;
}

void main() {
    vec2 px = gl_FragCoord.xy;
    int selected = selectedExample();
    vec3 color;
    if (px.x < FK_MAP) {
        // Feed/Kill plane: kill along X, feed along Y, grid every 0.01.
        vec2 t = px / FK_MAP;
        float kill = mix(uFkMap.z, uFkMap.w, t.x);
        float feed = mix(uFkMap.x, uFkMap.y, t.y);
        vec2 perPixel = vec2(uFkMap.w - uFkMap.z, uFkMap.y - uFkMap.x) / FK_MAP;
        vec2 grid = abs(fract(vec2(kill, feed) / 0.01 + 0.5) - 0.5) * 0.01 / perPixel;
        color = vec3(0.035, 0.04, 0.06) + 0.06 * (1.0 - smoothstep(0.0, 1.0, min(grid.x, grid.y)));
        // Saddle-node line k = sqrt(F)/2 - F: uniform red states exist to its left.
        float curve = abs(kill - (0.5 * sqrt(max(feed, 0.0)) - feed)) / perPixel.x;
        color = mix(color, vec3(0.5, 0.4, 0.7), 0.8 * (1.0 - smoothstep(0.5, 1.5, curve)));
        for (int i = 0; i < FK_COUNT; ++i) {
            float r = length(px - mapPixel(FK_EXAMPLES[i]));
            float ring = 1.0 - smoothstep(1.0, 2.0, abs(r - 6.0));
            float fill = (i == selected) ? 1.0 - smoothstep(3.0, 4.0, r) : 0.0;
            color = mix(color, fkHue(i), max(ring, fill));
        }
        vec2 d = abs(px - mapPixel(uFkCurrent.xy));
        bool crosshair = min(d.x, d.y) < 0.75 && max(d.x, d.y) > 4.0 && max(d.x, d.y) < 14.0;
        if (crosshair) color = vec3(1.0);
    } else {
        ivec2 q = ivec2(px) - ivec2(int(FK_MAP), 0);
        ivec2 tile = q / FK_TILE;
        ivec2 local = q - tile * FK_TILE;
        int index = fkIndex(tile);
        if (uFkCurrent.z > 0.5) {
            float t = clamp(texelFetch(sTD2DInputs[0], q, 0).g * uFkCurrent.w, 0.0, 1.0);
            color = fixedPalette(t);
        } else {
            ivec2 checker = local / 16;
            color = vec3(((checker.x + checker.y) % 2 == 0) ? 0.07 : 0.1); // not generated yet
        }
        int edge = min(min(local.x, local.y), min(FK_TILE - 1 - local.x, FK_TILE - 1 - local.y));
        if (edge < 2) color = fkHue(index);
        else if (index == selected && edge < 5) color = vec3(1.0);
    }
    fragColor = TDOutputSwizzle(vec4(color, 1.0));
}
"""


# =============================================================================
# 6. Presets
# =============================================================================

# Built-in presets are complete: build-time parameter defaults plus these
# overrides. Media paths and TOP references are never part of a built-in.
BUILTIN_PRESETS = (
    ('Coral', 'Branching coral growth from ambient seeds. The default chemistry.', {}),
    ('Dividing Spots', 'Self-replicating spots from small ambient seeds.',
     {'Feed': 0.0367, 'Kill': 0.0649, 'Seedradius': 5.0}),
    ('Worms', 'Labyrinthine worms and mazes.', {'Feed': 0.029, 'Kill': 0.057, 'Seedradius': 6.0}),
    ('Holes', 'A filled field punctured by stable holes.', {'Feed': 0.039, 'Kill': 0.058}),
    ('Clip Seed', 'Media silhouette continuously seeds coral; no ambient seeds.',
     {'Ambient': False, 'Influencemode': 'continuous', 'Maskmode': 'alpha',
      'Strength': 600.0, 'Fade': 0.0}),
    ('Stamp and Evolve', 'Stamp Current Mask once, then let spots evolve with carried color.',
     {'Feed': 0.0367, 'Kill': 0.0649, 'Ambient': False, 'Influencemode': 'stamp',
      'Maskmode': 'alpha', 'Colormode': 'dye', 'Dyesource': 'mask'}),
    ('Chemistry Map', 'Media brightness maps local feed/kill; tinted by the source.',
     {'Influencemode': 'chemistry', 'Maskmode': 'bright', 'Colormode': 'tint'}),
    ('Color Swirl', 'Carried media color with slow growth and rotation.',
     {'Colormode': 'dye', 'Transform': True, 'Rotate': 30.0}),
    ('Wide Coarse', 'A 768x432 canvas on a 3-pixel grid with thick lines; uses Resize Behavior Reset.',
     {'Rectangle': True, 'Canvaswidth': 768, 'Canvasheight': 432, 'Cellsize': 3.0}),
)

# Custom parameters that are deliberately not preset data: runtime state,
# diagnostics, and the preset/explorer controls themselves. The builder fails
# if any other custom parameter is left out of the preset groups.
PRESET_EXCLUDED = ('Pause', 'Simtime', 'Simlag', 'Tickcount', 'Substeps',
                   'Preset', 'Presetname', 'Presetbindings', 'Presetfile', 'Importmode',
                   'Presetstatus', 'Explorerclick', 'Explorerreset', 'Fkfeedmin', 'Fkfeedmax',
                   'Fkkillmin', 'Fkkillmax', 'Thumbseed', 'Thumbage', 'Explorerstatus', 'Statefile', 'Statestatus')


PRESETS_MODULE = r'''
"""Versioned preset table for turing_media_v2.

Pure document helpers (no TouchDesigner access) come first, so they can be
tested outside TouchDesigner. Adapters that read or write the component follow.
"""
import copy
import json
import math
import re
from pathlib import Path

SCHEMA = 'turing_media_v2.presets'
VERSION = 1

GROUPS = (
    ('chemistry', ('Feed', 'Kill', 'Diffusiona', 'Diffusionb', 'Transformedge')),
    ('seed', ('Seed', 'Seedradius', 'Ambient')),
    ('dimensions', ('Resolution', 'Rectangle', 'Canvaswidth', 'Canvasheight', 'Cellsize', 'Resizebehavior')),
    ('timing', ('Clockmode', 'Speed', 'Solverquality', 'Renderfps', 'Maxcatchup')),
    ('media', ('Resetonsource', 'Mediaplay', 'Mediaspeed', 'Overridefps', 'Sequencefps', 'Mediascale',
               'Offsetx', 'Offsety', 'Rotation', 'Sourcepremult', 'Ignorealpha')),
    ('influence', ('Influencemode', 'Stampamount', 'Feedmin', 'Feedmax', 'Killmin', 'Killmax',
                   'Chemistryblend', 'Maskmode', 'Strength', 'Maskgain', 'Edgewidth',
                   'Smoothing', 'Motiongain', 'Fade')),
    ('domain', ('Domainthreshold', 'Domaininvert', 'Domainboundary')),
    ('transform', ('Transform', 'Grow', 'Scalex', 'Scaley', 'Translatex', 'Translatey',
                   'Rotate', 'Pivotx', 'Pivoty')),
    ('flow', ('Flow', 'Flowstrength', 'Flowmax')),
    ('display', ('Coloramount', 'Contrast', 'Invert', 'Overlay', 'Clipalpha', 'Viewmode',
                 'Upscale')),
    ('performance', ('Carryhistory', 'Palettehistory', 'Paletteinterval')),
    ('color', ('Colormode', 'Tintspread', 'Palettesmooth', 'Paletteanchor', 'Dyespread',
               'Dyesource', 'Dyeinject', 'Dyedecay', 'Dyesaturation')),
)
# Optional bindings: project-specific paths, stored separately so presets stay portable.
BINDINGS = ('Moviefile', 'Sourcetop', 'Domaintop', 'Ramptop', 'Velocitytop')
# Requested dimensions commit atomically through clock.ensure_size().
DIMENSIONS = ('Resolution', 'Rectangle', 'Canvaswidth', 'Canvasheight', 'Cellsize')


class PresetError(ValueError):
    pass


def parameter_names():
    return [name for _, names in GROUPS for name in names]


def slug(name, taken=()):
    base = re.sub(r'[^a-z0-9]+', '_', name.strip().lower()).strip('_') or 'preset'
    key, suffix = base, 2
    while key in taken:
        key = '{}_{}'.format(base, suffix)
        suffix += 1
    return key


def group_settings(flat):
    """Flat {parameter: value} -> settings grouped in schema order."""
    settings, known = {}, set()
    for group, names in GROUPS:
        known.update(names)
        values = {name: flat[name] for name in names if name in flat}
        if values:
            settings[group] = values
    extra = {name: value for name, value in flat.items() if name not in known}
    if extra:
        settings['other'] = extra
    return settings


def flatten(settings):
    flat = {}
    for group, values in settings.items():
        if not isinstance(values, dict):
            raise PresetError('settings group {!r} must be an object'.format(group))
        for name, value in values.items():
            if name in flat:
                raise PresetError('setting {!r} appears twice'.format(name))
            flat[name] = value
    return flat


def make_preset(name, flat, bindings=None, description='', builtin=False):
    preset = {'name': name, 'description': description, 'settings': group_settings(flat)}
    if bindings:
        preset['bindings'] = dict(bindings)
    if builtin:
        preset['builtin'] = True
    return preset


def empty_document():
    return {'schema': SCHEMA, 'version': VERSION, 'presets': []}


def _scalar(value):
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, (bool, int, str))


def validate_preset(preset, where='preset'):
    if not isinstance(preset, dict):
        raise PresetError('{} must be an object'.format(where))
    name = preset.get('name')
    if not isinstance(name, str) or not name.strip():
        raise PresetError('{} needs a non-empty name'.format(where))
    where = 'preset {!r}'.format(name)
    if not isinstance(preset.get('description', ''), str):
        raise PresetError('{} description must be text'.format(where))
    if not isinstance(preset.get('settings'), dict):
        raise PresetError('{} needs a settings object'.format(where))
    for key, value in flatten(preset['settings']).items():
        if not _scalar(value):
            raise PresetError('{} setting {!r} must be a finite number, toggle or text'.format(where, key))
    bindings = preset.get('bindings', {})
    if not isinstance(bindings, dict) or not all(isinstance(v, str) for v in bindings.values()):
        raise PresetError('{} bindings must map names to text'.format(where))
    if not isinstance(preset.get('builtin', False), bool):
        raise PresetError('{} builtin flag must be true or false'.format(where))
    return preset


def migrate(document):
    """Upgrade older schema versions in place. Version 1 is the first."""
    return document


def validate_document(document):
    if not isinstance(document, dict) or document.get('schema') != SCHEMA:
        raise PresetError('not a {} document'.format(SCHEMA))
    version = document.get('version')
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise PresetError('invalid preset schema version {!r}'.format(version))
    if version > VERSION:
        raise PresetError('preset schema version {} is newer than supported version {}'
                          .format(version, VERSION))
    document = migrate(document)
    presets = document.get('presets')
    if not isinstance(presets, list):
        raise PresetError('presets must be a list')
    names = set()
    for index, preset in enumerate(presets):
        validate_preset(preset, 'preset #{}'.format(index + 1))
        key = preset['name'].strip().casefold()
        if key in names:
            raise PresetError('duplicate preset name {!r}'.format(preset['name']))
        names.add(key)
    return document


def loads(text):
    try:
        document = json.loads(text)
    except ValueError as error:
        raise PresetError('invalid JSON: {}'.format(error))
    return validate_document(document)


def dumps(document):
    return json.dumps(validate_document(document), indent=2, allow_nan=False) + '\n'


def find(document, name):
    key = name.strip().casefold()
    for preset in document['presets']:
        if preset['name'].strip().casefold() == key:
            return preset
    return None


def menu_keys(document):
    keys = []
    for preset in document['presets']:
        keys.append(slug(preset['name'], keys))
    return keys


def upsert(document, preset):
    """Add or replace a user preset; returns True when it replaced one."""
    validate_preset(preset)
    existing = find(document, preset['name'])
    if existing is not None and existing.get('builtin'):
        raise PresetError('{!r} is a built-in preset; save under another name'.format(preset['name']))
    if existing is None:
        document['presets'].append(preset)
        return False
    document['presets'][document['presets'].index(existing)] = preset
    return True


def remove(document, name):
    preset = find(document, name)
    if preset is None:
        raise PresetError('no preset named {!r}'.format(name))
    if preset.get('builtin'):
        raise PresetError('{!r} is a built-in preset and cannot be deleted'.format(name))
    document['presets'].remove(preset)
    return preset


def merge(document, incoming, replace=False):
    """Import user presets. Embedded built-ins always win over imported copies."""
    result = copy.deepcopy(document)
    report = dict(added=[], replaced=[], renamed=[], skipped=[])
    if replace:
        result['presets'] = [p for p in result['presets'] if p.get('builtin')]
    builtins = {p['name'].strip().casefold() for p in result['presets'] if p.get('builtin')}
    for preset in copy.deepcopy(incoming['presets']):
        key = preset['name'].strip().casefold()
        if preset.pop('builtin', False) and key in builtins:
            report['skipped'].append(preset['name'])
            continue
        if key in builtins:
            original, suffix = preset['name'], 1
            while find(result, preset['name']) is not None:
                preset['name'] = '{} (imported{})'.format(
                    original, '' if suffix == 1 else ' {}'.format(suffix))
                suffix += 1
            report['renamed'].append([original, preset['name']])
        (report['replaced'] if upsert(result, preset) else report['added']).append(preset['name'])
    return result, report


def coerce(kind, value):
    """Return value converted to a parameter kind, or raise PresetError."""
    if kind == 'float':
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return float(value)
    elif kind == 'int':
        if isinstance(value, bool):
            pass
        elif isinstance(value, int):
            return value
        elif isinstance(value, float) and value.is_integer():
            return int(value)
    elif kind == 'bool':
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
    elif kind == 'str':
        if isinstance(value, str):
            return value
    elif isinstance(kind, tuple) and kind[0] == 'menu':
        if isinstance(value, str) and value in kind[1]:
            return value
    raise PresetError('{!r} is not a valid {} value'.format(value, kind if isinstance(kind, str) else 'menu'))


def effective_size(values):
    """(canvas w, canvas h, sim w, sim h), matching the network expressions."""
    rectangle = values['Rectangle']
    width = values['Canvaswidth'] if rectangle else values['Resolution']
    height = values['Canvasheight'] if rectangle else values['Resolution']
    cell = values['Cellsize']
    return (width, height, max(8, int(round(width / cell))), max(8, int(round(height / cell))))


def plan_apply(current, preset, spec, include_bindings=False):
    """Changes needed to apply preset over current values, without touching anything."""
    validate_preset(preset)
    report = dict(unknown=[], invalid=[], missing=[], changed=[], blocked=[], reset='')
    flat = flatten(preset['settings'])
    changes = {}
    for name, value in flat.items():
        if name not in spec or name in BINDINGS:
            report['unknown'].append(name)
            continue
        try:
            value = coerce(spec[name], value)
        except PresetError:
            report['invalid'].append(name)
            continue
        if value != current.get(name) or type(value) is not type(current.get(name)):
            changes[name] = value
    report['missing'] = [name for name in parameter_names() if name in spec and name not in flat]
    if include_bindings:
        for name, value in preset.get('bindings', {}).items():
            if name not in BINDINGS or name not in spec:
                report['unknown'].append(name)
            elif value != current.get(name):
                changes[name] = value
    after = dict(current)
    after.update(changes)
    report['resized'] = effective_size(current) != effective_size(after)
    return changes, report


def summary(name, report):
    parts = ['Applied {!r}: {} changed'.format(name, len(report['changed']))]
    parts.append('reset ({})'.format(report['reset']) if report['reset'] else 'state kept')
    for key in ('unknown', 'invalid', 'blocked', 'missing'):
        names = report[key]
        if names:
            more = '' if len(names) <= 4 else ' +{}'.format(len(names) - 4)
            parts.append('{} {}: {}{}'.format(len(names), key, ', '.join(names[:4]), more))
    return '; '.join(parts)


# -----------------------------------------------------------------------------
# TouchDesigner adapters
# -----------------------------------------------------------------------------

STYLES = {'Float': 'float', 'Int': 'int', 'Toggle': 'bool', 'File': 'str',
          'TOP': 'str', 'Str': 'str'}


def spec(c):
    kinds = {}
    for name in parameter_names() + list(BINDINGS):
        par = getattr(c.par, name, None)
        if par is None:
            continue
        if par.style in ('Menu', 'StrMenu'):
            kinds[name] = ('menu', tuple(par.menuNames))
        elif par.style in STYLES:
            kinds[name] = STYLES[par.style]
    return kinds


def current_values(c, kinds):
    values = {}
    for name, kind in kinds.items():
        par = c.par[name]
        if kind == 'str':
            # Keep a typed (possibly relative) path; evaluate driven bindings.
            if par.mode == ParMode.CONSTANT:
                value = par.val
            else:
                value = par.eval()
                value = getattr(value, 'path', value)
            values[name] = '' if value is None else str(value)
        else:
            values[name] = coerce(kind, par.eval())
    return values


def capture(c, include_bindings=False):
    """Current settings as flat preset values plus optional bindings."""
    values = current_values(c, spec(c))
    flat = {name: values[name] for name in parameter_names() if name in values}
    bindings = {name: values[name] for name in BINDINGS if name in values} if include_bindings else {}
    return flat, bindings


def mark_pending(c, values):
    # TD may skip absolute frames while GPU work blocks the UI. Keep expected
    # values until their callbacks arrive, and merge overlapping preset batches.
    pending = dict(c.fetch('Presetpending', {}))
    pending.update(values)
    c.store('Presetpending', pending)


def consume_pending(c, par):
    """True when a value-change callback belongs to a preset batch."""
    pending = dict(c.fetch('Presetpending', {}))
    if par.name not in pending:
        return False
    expected = pending.pop(par.name)
    c.store('Presetpending', pending)
    # A subsequent hand edit must retain the ordinary reset behavior. Typed
    # TOP bindings use their path text, not the OP returned by eval().
    actual = par.val if par.style in ('TOP', 'File', 'Str') else par.eval()
    return actual == expected


def set_quietly(c, values):
    """Set parameters without triggering their reset callbacks; returns blocked names."""
    blocked = []
    mark_pending(c, values)
    for name, value in values.items():
        par = c.par[name]
        if par.mode == ParMode.EXPORT:
            blocked.append(name)
            continue
        if par.mode != ParMode.CONSTANT:
            par.mode = ParMode.CONSTANT
        par.val = value
    return blocked


def apply(c, preset, reset=False, include_bindings=False):
    """Apply one preset as a batch with at most one reset; returns a report."""
    kinds = spec(c)
    current = current_values(c, kinds)
    changes, report = plan_apply(current, preset, kinds, include_bindings)
    report['blocked'] = set_quietly(c, changes)
    report['changed'] = sorted(name for name in changes if name not in report['blocked'])
    clock = c.op('clock').module
    if 'Clockmode' in changes or 'Speed' in changes:
        clock.rebase(c, clear_debt='Clockmode' in changes)
    if reset:
        report['reset'] = 'requested'
        clock.reset(c)
    else:
        if clock.ensure_size(c):
            report['reset'] = 'dimensions changed'
        source_reset = clock.ensure_source(c)
        if source_reset and not report['reset']:
            report['reset'] = 'source changed'
    return report


def document(c):
    return loads(c.op('presets').text)


def store_document(c, document, select=None):
    c.op('presets').text = dumps(document)
    refresh_menu(c, select)


def refresh_menu(c, select=None):
    doc = document(c)
    keys = menu_keys(doc)
    par = c.par.Preset
    current = par.eval()
    par.menuNames = keys
    par.menuLabels = [p['name'] if p.get('builtin') else p['name'] + '  (user)' for p in doc['presets']]
    if select is not None and find(doc, select) is not None:
        current = keys[doc['presets'].index(find(doc, select))]
    if keys:
        par.val = current if current in keys else keys[0]


def selected(c, doc):
    keys = menu_keys(doc)
    key = c.par.Preset.eval()
    if key not in keys:
        raise PresetError('no preset selected')
    return doc['presets'][keys.index(key)]


def status(c, text):
    c.par.Presetstatus.val = text
    print('{} presets: {}'.format(c.path, text))


def _path(c):
    path = c.par.Presetfile.eval().strip()
    if not path:
        raise PresetError('set Preset File first')
    path = Path(path)
    return path if path.is_absolute() else Path(project.folder) / path


def on_apply(c, reset=False):
    try:
        preset = selected(c, document(c))
        report = apply(c, preset, reset, bool(c.par.Presetbindings))
    except PresetError as error:
        status(c, 'Error: {}'.format(error))
        return None
    status(c, summary(preset['name'], report))
    return report


def on_save(c):
    try:
        doc = document(c)
        name = c.par.Presetname.eval().strip()
        if not name:
            number = 1
            while find(doc, 'User Preset {}'.format(number)) is not None:
                number += 1
            name = 'User Preset {}'.format(number)
        flat, bindings = capture(c, bool(c.par.Presetbindings))
        preset = make_preset(name, flat, bindings, 'Saved from {}'.format(c.path))
        replaced = upsert(doc, preset)
        store_document(c, doc, select=name)
    except PresetError as error:
        status(c, 'Error: {}'.format(error))
        return None
    status(c, '{} {!r}: {} settings{}'.format('Replaced' if replaced else 'Saved', name, len(flat),
                                             ', {} bindings'.format(len(bindings)) if bindings else ''))
    return preset


def on_delete(c):
    try:
        doc = document(c)
        preset = remove(doc, selected(c, doc)['name'])
        store_document(c, doc)
    except PresetError as error:
        status(c, 'Error: {}'.format(error))
        return None
    status(c, 'Deleted {!r}'.format(preset['name']))
    return preset


def on_export(c):
    try:
        path = _path(c)
        text = dumps(document(c))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    except (PresetError, OSError) as error:
        status(c, 'Error: {}'.format(error))
        return None
    status(c, 'Exported {} presets to {}'.format(len(document(c)['presets']), path))
    return path


def on_import(c):
    try:
        incoming = loads(_path(c).read_text())
        merged, report = merge(document(c), incoming, c.par.Importmode.eval() == 'replace')
        store_document(c, merged)
    except (PresetError, OSError) as error:
        status(c, 'Error: {}'.format(error))
        return None
    parts = ['Imported: {} added, {} replaced'.format(len(report['added']), len(report['replaced']))]
    if report['renamed']:
        parts.append('renamed ' + ', '.join('{} -> {}'.format(*pair) for pair in report['renamed']))
    if report['skipped']:
        parts.append('{} built-in copies skipped'.format(len(report['skipped'])))
    status(c, '; '.join(parts))
    return report


def clip_seed(c):
    """Seed From Clip Only: a partial preset over current settings, then one reset."""
    report = apply(c, {'name': 'Seed From Clip Only', 'settings': {
        'seed': {'Ambient': False},
        'influence': {'Influencemode': 'continuous', 'Maskmode': 'alpha',
                      'Strength': 600.0, 'Fade': 0.0}}}, reset=True)
    status(c, 'Seed From Clip Only: {} changed; reset'.format(len(report['changed'])))
    return report
'''


SNAPSHOT_MODULE = r'''
"""Raw float32 snapshots. ZIP/JSON/raw bytes: no image codecs or pickle."""
import copy
import hashlib
import json
import math
import os
import struct
import tempfile
import zipfile
from pathlib import Path

SCHEMA = 'turing_media_v2.state'
VERSION = 1
TEXTURES = ('state_a', 'state_b', 'media_a', 'media_b', 'palette_a', 'palette_b')
MAX_BYTES = 1024 * 1024 * 1024


class SnapshotError(ValueError):
    pass


def validate(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('metadata'), dict):
        raise SnapshotError('missing snapshot metadata')
    m = snapshot['metadata']
    if m.get('schema') != SCHEMA or type(m.get('version')) is not int or m['version'] != VERSION:
        raise SnapshotError('unsupported state schema/version')
    if m.get('encoding') != 'float32-le-rgba-bottom-up':
        raise SnapshotError('unsupported texture encoding')
    size = m.get('dimensions')
    if (not isinstance(size, list) or len(size) != 4 or
            any(type(n) is not int or n < 8 or n > 4096 for n in size)):
        raise SnapshotError('invalid dimensions')
    clock = m.get('clock', {})
    if (not isinstance(clock, dict) or type(clock.get('ticks')) is not int or clock['ticks'] < 0 or
            type(clock.get('debt')) not in (int, float) or
            not math.isfinite(clock['debt']) or clock['debt'] < 0 or
            type(clock.get('buffer')) is not int or clock['buffer'] not in (0, 1) or
            type(clock.get('media')) is not int or clock['media'] not in (0, 1)):
        raise SnapshotError('invalid simulation clock')
    if (m.get('simulation_seconds') != clock['ticks'] / 60.0 or
            not isinstance(m.get('settings'), dict) or not isinstance(m.get('bindings'), dict) or
            type(m.get('pause')) is not bool or type(m.get('palette_ready')) is not bool or
            type(m.get('motion_ready')) is not bool or type(m.get('motion_tick_ready')) is not bool or m.get('palette_reader') not in ('palette_a', 'palette_b')):
        raise SnapshotError('invalid settings/history metadata')
    last_tick = m.get('palette_last_tick', clock['ticks'])
    if type(last_tick) is not int or not 0 <= last_tick <= clock['ticks']:
        raise SnapshotError('invalid palette schedule')
    movie = m.get('movie')
    if (not isinstance(movie, dict) or movie.get('playmode') not in
            ('locked', 'specify', 'sequential', 'timecodeop') or
            movie.get('indexunit') not in ('indices', 'frames', 'seconds', 'fraction') or
            movie.get('cuepointunit') not in ('indices', 'frames', 'seconds', 'fraction') or
            any(type(movie.get(k)) not in (int, float) or not math.isfinite(movie[k])
                for k in ('position', 'index', 'cuepoint'))):
        raise SnapshotError('invalid movie position')
    textures = snapshot.get('textures', {})
    records = m.get('textures', {})
    if (not isinstance(textures, dict) or not isinstance(records, dict) or
            set(textures) != set(TEXTURES) or set(records) != set(TEXTURES)):
        raise SnapshotError('missing or unexpected texture')
    total = 0
    for name in TEXTURES:
        rec = records[name]
        if not isinstance(rec, dict):
            raise SnapshotError('invalid texture record ' + name)
        expected = ([size[3], size[2], 4] if name.startswith('state') else
                    [size[1], size[0], 4] if name.startswith('media') else [2, 64, 4])
        raw = textures[name]
        length = math.prod(expected) * 4
        if (rec.get('shape') != expected or not isinstance(raw, bytes) or len(raw) != length or
                rec.get('sha256') != hashlib.sha256(raw).hexdigest()):
            raise SnapshotError('invalid/corrupt texture {}'.format(name))
        if any(not math.isfinite(v[0]) for v in struct.iter_unpack('<f', raw)):
            raise SnapshotError('non-finite texture {}'.format(name))
        total += length
    if total > MAX_BYTES:
        raise SnapshotError('snapshot exceeds supported size')
    # JSON also rejects non-finite settings; no executable objects are persisted.
    try:
        json.dumps(m, allow_nan=False)
    except (ValueError, TypeError) as error:
        raise SnapshotError('invalid metadata: {}'.format(error))
    return snapshot


def write_file(path, snapshot):
    validate(snapshot)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.',
                                         suffix='.tmp', delete=False) as file:
            temporary = file.name
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('metadata.json', json.dumps(snapshot['metadata'], allow_nan=False))
            for name in TEXTURES:
                archive.writestr(name + '.f32', snapshot['textures'][name])
        # Verify the bytes from disk before atomically replacing the destination.
        verified = read_file(temporary)
        if verified != snapshot:
            raise SnapshotError('disk verification failed')
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)
    return path


def read_file(path):
    try:
        with zipfile.ZipFile(path, 'r') as archive:
            expected = {'metadata.json'} | {name + '.f32' for name in TEXTURES}
            entries = archive.infolist()
            if (len(entries) != len(expected) or {e.filename for e in entries} != expected or
                    sum(e.file_size for e in entries) > MAX_BYTES + 1024 * 1024 or
                    archive.getinfo('metadata.json').file_size > 1024 * 1024):
                raise SnapshotError('invalid archive contents/size')
            metadata = json.loads(archive.read('metadata.json'))
            textures = {name: archive.read(name + '.f32') for name in TEXTURES}
        return validate(dict(metadata=metadata, textures=textures))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
        raise SnapshotError('cannot read state: {}'.format(error))


def upload(c, raw, shape):
    # NumPy ships with TD; imported only for manual upload/snapshot operations.
    import numpy as np
    array = np.frombuffer(raw, dtype='<f4').reshape(shape).astype(np.float32, copy=True)
    c.store('Uploadarray', array)
    node = c.op('state_upload')
    node.cook(force=True)
    return node


def download(node):
    node.cook(force=True)
    array = node.numpyArray(delayed=False)
    if array is None:
        raise SnapshotError('texture download failed: ' + node.path)
    raw = array.astype('<f4', copy=True).tobytes(order='C')
    return raw, list(array.shape)


def _movie(c):
    movie = c.op('movie')
    if c.par.Moviefile.eval().strip():
        movie.cook(force=True)
    return dict(position=float(movie.index), playmode=movie.par.playmode.eval(),
                index=float(movie.par.index.eval()), indexunit=movie.par.indexunit.eval(),
                cuepoint=float(movie.par.cuepoint.eval()), cuepointunit=movie.par.cuepointunit.eval())


def capture(c):
    clock = c.op('clock').module
    clock.ensure_size(c)
    clock.ensure_source(c)
    if not clock._clock(c)['ready']:
        clock.reset(c)
    lib = c.op('preset_lib').module
    settings, bindings = lib.capture(c, include_bindings=True)
    state = clock._clock(c)
    m = dict(schema=SCHEMA, version=VERSION, encoding='float32-le-rgba-bottom-up',
             dimensions=list(c.fetch('Appliedsize')), simulation_seconds=state['ticks'] / 60.0,
             settings=settings, bindings=bindings, pause=bool(c.par.Pause),
             clock={k: state[k] for k in ('ticks', 'debt', 'buffer', 'media')},
             palette_ready=bool(c.fetch('Paletteready', False)),
             motion_ready=bool(c.fetch('Motionready', False)),
             motion_tick_ready=bool(c.fetch('Motiontickready', False)), movie=_movie(c), textures={},
             palette_reader=c.op('palette_read').par.top.eval().name,
             palette_last_tick=int(c.fetch('Palettelasttick', 0)),
             build=str(app.version) + '.' + str(app.build),
             replay='Equal settings, ticks and source samples reproduce state. External live '
                    'sources cannot rewind; sequential movie scheduling depends on output timing.')
    textures = {}
    for name in TEXTURES:
        raw, shape = download(c.op(name))
        textures[name] = raw
        m['textures'][name] = dict(shape=shape, sha256=hashlib.sha256(raw).hexdigest())
    return validate(dict(metadata=m, textures=textures))


def _seek_movie(c, data):
    movie = c.op('movie')
    movie.par.playmode = data['playmode']
    movie.par.indexunit = data['indexunit']
    movie.par.index = data['index']
    if c.par.Moviefile.eval().strip() and data['playmode'] == 'sequential':
        movie.par.cuepointunit = 'indices'
        movie.par.cuepoint = data['position']
        movie.par.cue = True
        movie.cook(force=True)
        movie.par.cue = False
    movie.par.cuepointunit = data['cuepointunit']
    movie.par.cuepoint = data['cuepoint']


def restore(c, snapshot):
    validate(snapshot)
    m = snapshot['metadata']
    lib = c.op('preset_lib').module
    kinds = lib.spec(c)
    saved_settings, saved_bindings = dict(m['settings']), dict(m['bindings'])
    # Schema-v1 Phase 5 snapshots predate flow. Only that complete legacy shape
    # receives safe defaults; partially missing new snapshots remain errors.
    flow_defaults = {'Flow': False, 'Flowstrength': 1.0, 'Flowmax': 8.0}
    legacy = not (set(flow_defaults) & set(saved_settings)) and 'Velocitytop' not in saved_bindings
    if legacy:
        saved_settings.update(flow_defaults)
        saved_bindings['Velocitytop'] = ''
    performance_defaults = {'Carryhistory': True, 'Palettehistory': True, 'Paletteinterval': 1}
    if not (set(performance_defaults) & set(saved_settings)):
        saved_settings.update(performance_defaults)
    values = dict(saved_settings, **saved_bindings, Pause=m['pause'])
    # Validate everything before touching parameters, buffers or media position.
    for name, value in values.items():
        if name != 'Pause':
            if name not in kinds:
                raise SnapshotError('unsupported snapshot setting ' + name)
            try:
                lib.coerce(kinds[name], value)
            except ValueError as error:
                raise SnapshotError('invalid setting {}: {}'.format(name, error))
        par = c.par[name]
        if type(value) in (int, float) and (
                (par.clampMin and value < par.min) or (par.clampMax and value > par.max)):
            raise SnapshotError('out-of-range snapshot setting ' + name)
        if par.mode == ParMode.EXPORT:
            raise SnapshotError('cannot restore exported parameter ' + name)
    if list(lib.effective_size(values)) != m['dimensions']:
        raise SnapshotError('settings do not match snapshot dimensions')
    if set(lib.parameter_names()) - set(saved_settings) or set(lib.BINDINGS) != set(saved_bindings):
        raise SnapshotError('incomplete snapshot settings/bindings')
    controls, clock_op = c.op('controls'), c.op('clock')
    controls_active, clock_active = bool(controls.par.active), bool(clock_op.par.active)
    controls.par.active = False
    clock_op.par.active = False
    controls.cook(force=True)
    try:
        # Detach old simulation dependencies before any dimension/settings change.
        # Cache buffers are held; this avoids cooking a resized solver on old state.
        initial = upload(c, snapshot['textures']['state_a'], m['textures']['state_a']['shape'])
        for name in TEXTURES:
            c.op(name).inputConnectors[0].connect(initial)
        lib.set_quietly(c, values)
        c.store('Appliedsize', tuple(m['dimensions']))
        _seek_movie(c, m['movie'])
        clock = clock_op.module
        # Each buffer gets an independent copy; all six histories/parities survive.
        for name in TEXTURES:
            source = upload(c, snapshot['textures'][name], m['textures'][name]['shape'])
            clock.capture(c.op(name), source)
        state = clock._clock(c)
        state.update(m['clock'], ready=True, frame=None)
        c.op('state_read').par.top = ('state_a', 'state_b')[state['buffer']]
        c.op('palette_read').par.top = ('palette_a', 'palette_b')[state['buffer']]
        # Stamp/clear can move the state buffer without moving palette history.
        c.op('palette_read').par.top = m['palette_reader']
        c.op('media_cache').par.top = ('media_a', 'media_b')[state['media']]
        c.op('media_previous').par.top = ('media_a', 'media_b')[1 - state['media']]
        c.store('Paletteready', m['palette_ready'])
        c.store('Palettelasttick', m.get('palette_last_tick', m['clock']['ticks']))
        c.store('Paletteelapsed', 1.0/60.0)
        c.store('Motionready', m['motion_ready'])
        c.store('Motiontickready', m['motion_tick_ready'])
        c.store('Sourcesignature', clock.source_signature(c))
        clock.rebase(c)
        for name in ('state', 'palette', 'media_mask', 'mask_preview'):
            c.op(name).cook(force=True)
    finally:
        controls.par.active = controls_active
        controls.cook(force=True)
        clock_op.par.active = clock_active
    return True


def status(c, text):
    c.par.Statestatus.val = text
    print('{} state: {}'.format(c.path, text))


def _path(c):
    value = c.par.Statefile.eval().strip()
    if not value:
        raise SnapshotError('set State File first')
    path = Path(value)
    return path if path.is_absolute() else Path(project.folder) / path


def action(c, name):
    try:
        if name == 'Savestate':
            snapshot = capture(c)
            c.store('Snapshot', snapshot)
            status(c, 'Saved in memory at {:.6f} s'.format(snapshot['metadata']['simulation_seconds']))
        elif name == 'Restorestate':
            snapshot = c.fetch('Snapshot', None)
            if snapshot is None:
                raise SnapshotError('save an in-memory state first')
            restore(c, snapshot)
            status(c, 'Restored in-memory state')
        elif name == 'Exportstate':
            path = write_file(_path(c), capture(c))
            status(c, 'Saved verified float32 state to {}'.format(path))
        elif name == 'Importstate':
            snapshot = read_file(_path(c))
            restore(c, snapshot)
            c.store('Snapshot', snapshot)
            status(c, 'Restored disk state')
    except (SnapshotError, OSError, RuntimeError) as error:
        status(c, 'Error: {}'.format(error))
        return False
    return True
'''


# =============================================================================
# 7. Callbacks
# =============================================================================

CONTROL_CALLBACKS = r'''
SIZE_PARAMETERS = ('Resolution', 'Rectangle', 'Canvaswidth', 'Canvasheight', 'Cellsize')


def resetSimulation(component):
    component.op('clock').module.reset(component)
    return


def onPulse(par):
    c = par.owner
    clock = c.op('clock').module
    presets = c.op('preset_lib').module
    name = par.name
    if name == 'Refreshdiagnostics':
        c.op('diagnostics').module.refresh(c, compile_shaders=True)
    elif name == 'Stamp':
        clock.stamp(c)
    elif name == 'Step':
        clock.step(c)
    elif name in ('Reset', 'Resetall'):
        clock.reset_all(c)
    elif name == 'Resetchemistry':
        clock.reset_chemistry(c)
    elif name == 'Clearcolor':
        clock.clear_color(c)
    elif name in ('Savestate', 'Restorestate', 'Exportstate', 'Importstate'):
        c.op('snapshot_lib').module.action(c, name)
    elif name == 'Reseed':
        # One reset: the Seed change itself is batched, not a second trigger.
        presets.set_quietly(c, {'Seed': c.par.Seed.eval() + 1})
        clock.reset_chemistry(c)
    elif name == 'Restartclip':
        clock.restart_media(c)
    elif name == 'Transformzero':
        for key in ('Grow', 'Scalex', 'Scaley', 'Translatex', 'Translatey', 'Rotate'):
            c.par[key].val = 0.0
    elif name == 'Clipseed':
        presets.clip_seed(c)
    elif name == 'Applypreset':
        presets.on_apply(c, reset=False)
    elif name == 'Applyreset':
        presets.on_apply(c, reset=True)
    elif name == 'Savepreset':
        presets.on_save(c)
    elif name == 'Deletepreset':
        presets.on_delete(c)
    elif name == 'Exportpresets':
        presets.on_export(c)
    elif name == 'Importpresets':
        presets.on_import(c)
    elif name == 'Generatethumbs':
        c.op('explorer').module.generate(c)
    return


def onValueChange(par, prev):
    c = par.owner
    # Preset batches apply their own single (or no) reset.
    if c.op('preset_lib').module.consume_pending(c, par):
        return
    if par.name in ('Pause', 'Clockmode', 'Speed'):
        c.op('clock').module.rebase(c, clear_debt=par.name == 'Clockmode')
        return
    if par.name in SIZE_PARAMETERS:
        c.op('clock').module.ensure_size(c)
    elif par.name in ('Moviefile', 'Sourcetop'):
        c.op('clock').module.ensure_source(c)
    return
'''


DIAGNOSTICS_CALLBACKS = r'''
"""Lightweight wall-clock status; explicit checks can demand every shader."""
import time
from pathlib import Path


def shader_result(log, errors=''):
    if errors:
        return 'error', str(errors)
    text = str(log).strip()
    if any(word in text.lower() for word in ('error:', 'failed to compile', 'compile failed', 'link failed')):
        return 'error', text
    if 'Compiled Successfully' in text:
        return 'ok', text
    return 'unchecked', text or 'Not cooked yet; use Check Shaders / Refresh.'


def source_status(c):
    par = c.par.Sourcetop
    source = par.eval()
    assigned = str(par.val or '').strip()
    expression = str(par.expr or '').strip()
    if source is not None:
        if source.family != 'TOP':
            return 'Invalid Source TOP: ' + source.path
        errors = source.errors()
        if errors:
            return 'Source TOP error: ' + str(errors).strip()
        return 'Valid TOP: {} ({} x {})'.format(source.path, source.width, source.height)
    if assigned or expression:
        return 'Invalid Source TOP: unresolved reference ' + (assigned or expression)
    if c.par.Moviefile.eval().strip():
        movie = c.op('movie')
        path = c.par.Moviefile.eval().strip()
        # Decoder errors arrive asynchronously. Catch missing literal local files
        # immediately; sequences, variable paths and URLs use decoder diagnostics.
        if not any(token in path for token in ('*', '?', '[', '%', '$', '://')):
            local = Path(path).expanduser()
            if not local.is_absolute():
                local = Path(project.folder) / local
            if not local.is_file():
                return 'Movie error: file not found ' + path
        errors = movie.errors()
        return ('Movie error: ' + str(errors).strip()) if errors else 'Movie assigned: ' + c.par.Moviefile.eval()
    return 'No media (ambient simulation)'


def refresh(c, compile_shaders=False):
    shaders, logs = [], []
    for name, info_name in c.fetch('Diagnosticshaders', []):
        node, info = c.op(name), c.op(info_name)
        if node is None or info is None:
            result, log = 'error', 'Missing shader operator or compiler Info DAT'
        else:
            try:
                if compile_shaders:
                    node.cook(force=True)
                    info.cook(force=True)
                result, log = shader_result(info.text, node.errors())
            except Exception as error:
                result, log = 'error', str(error)
        shaders.append((name, result))
        logs.append('{} [{}]\n{}'.format(name, result, log))
    c.op('shader_diagnostics').text = '\n\n'.join(logs)
    c.store('Shaderhealth', shaders)
    c.store('Diagnosticslastscan', time.perf_counter())
    update(c)
    return shaders


def status_rows(c):
    size = c.fetch('Appliedsize', (0, 0, 0, 0))
    state = c.fetch('Clockstate', {})
    health = c.fetch('Shaderhealth', [])
    failed = [name for name, result in health if result == 'error']
    unchecked = sum(result == 'unchecked' for _, result in health)
    issues = c.fetch('Buildissues', [])
    runtime = c.fetch('Runtimeerror', '')
    shader = '{} errors / {} unchecked / {} shaders'.format(len(failed), unchecked, len(health))
    if failed:
        shader += ': ' + ', '.join(failed)
    return [
        ('Build', c.fetch('Diagnosticbuild', 'unknown') + ' (validated: 2025.33230 macOS)'),
        ('Canvas / grid', '{} x {} / {} x {}'.format(*size)),
        ('Clock', '{} / {}'.format(c.par.Clockmode.eval(), 'paused' if c.par.Pause else 'running')),
        ('Ticks', '{} total / {} last frame'.format(state.get('ticks', 0), int(c.par.Tickcount))),
        ('Substeps', '{} per tick / {} last frame'.format(int(c.par.Substeps), int(c.par.Substeps) * int(c.par.Tickcount))),
        ('Time / lag', '{:.4f} s / {:.4f} s'.format(state.get('ticks', 0) / 60.0, state.get('debt', 0.0))),
        ('Source', source_status(c)),
        ('Shaders', shader),
        ('Build issues', '; '.join(issues) or 'None'),
        ('Runtime', runtime or 'OK'),
    ]


def update(c):
    rows = status_rows(c)
    table = c.op('status')
    # Only rewrite when changed; no texture download, solver or palette cook.
    if rows != c.fetch('Diagnosticsrows', None):
        table.clear()
        for row in rows:
            table.appendRow(row)
        c.store('Diagnosticsrows', rows)
        c.store('Diagnosticstext', 'TURING MEDIA V2\n' + '\n'.join(
            '{}: {}'.format(key, value if len(value) <= 100 else value[:97] + '...') for key, value in rows))


def onFrameStart(frame):
    c = me.parent()
    try:
        # Inspect existing compiler/error data twice a second, independent of Pause.
        if time.perf_counter() - c.fetch('Diagnosticslastscan', 0.0) >= 0.5:
            refresh(c)
        else:
            update(c)
    except Exception as error:
        c.store('Runtimeerror', 'Diagnostics: ' + str(error))
        c.store('Diagnosticstext', 'TURING MEDIA V2\nDiagnostics error: ' + str(error))
    return
'''


EXPLORER_CALLBACKS = r'''
"""Feed/Kill explorer: reference thumbnails and XY panel input.

Layout constants must match FK_* in the builder (checked by validation).
"""
MAP_SIZE = 512
TILE = 128
COLUMNS = 2
ROWS = 4
PANEL_WIDTH = MAP_SIZE + COLUMNS * TILE
PANEL_HEIGHT = ROWS * TILE
TICKS_PER_FRAME = 40


def examples(c):
    table = c.op('fk_examples')
    return [dict(name=table[row, 'name'].val, feed=float(table[row, 'feed'].val),
                 kill=float(table[row, 'kill'].val)) for row in range(1, table.numRows)]


def example_at(u, v):
    """Example index under normalized panel coordinates; None on the map."""
    x, y = u * PANEL_WIDTH, v * PANEL_HEIGHT
    if x < MAP_SIZE or x >= PANEL_WIDTH or y < 0 or y >= PANEL_HEIGHT:
        return None
    column, row = int((x - MAP_SIZE) // TILE), int(y // TILE)
    return (ROWS - 1 - row) * COLUMNS + column


def map_point(c, u, v):
    """(feed, kill) at normalized panel coordinates on the map; kill runs along X."""
    x = min(max(u * PANEL_WIDTH / MAP_SIZE, 0.0), 1.0)
    y = min(max(v, 0.0), 1.0)
    low, high = float(c.par.Fkfeedmin.eval()), float(c.par.Fkfeedmax.eval())
    feed = low + (high - low) * y
    low, high = float(c.par.Fkkillmin.eval()), float(c.par.Fkkillmax.eval())
    kill = low + (high - low) * x
    return round(feed, 5), round(kill, 5)


def pick(c, u, v, pressed=True):
    """One panel sample: map drags set Feed/Kill; a tile press selects its example."""
    index = example_at(u, v)
    if index is None:
        if u * PANEL_WIDTH >= MAP_SIZE:
            return None
        c.par.Feed, c.par.Kill = map_point(c, u, v)
        return 'map'
    rows = examples(c)
    if not pressed or index >= len(rows):
        return None
    c.par.Feed, c.par.Kill = rows[index]['feed'], rows[index]['kill']
    if c.par.Explorerreset:
        c.op('clock').module.reset(c)
    return rows[index]['name']


def _value(value):
    return float(getattr(value, 'val', value))


def poll(c):
    panel = c.op('fk_explorer')
    if panel is None:
        return
    try:
        down = _value(panel.panel.lselect) > 0.5
        u, v = _value(panel.panel.u), _value(panel.panel.v)
    except Exception:
        return
    was = c.fetch('Fkdown', False)
    if down != was:  # avoid touching storage every frame
        c.store('Fkdown', down)
    if down and c.par.Explorerclick:
        pick(c, u, v, pressed=not was)


def _status(c, text):
    c.par.Explorerstatus.val = text


def generate(c, synchronous=False):
    """Simulate every curated example from one fixed seed to a fixed age."""
    clock = c.op('clock').module
    token = c.fetch('Fkjob', 0) + 1
    c.store('Fkjob', token)
    c.store('Fkready', 0)
    for name in ('fk_a', 'fk_b'):
        c.op(name).inputConnectors[0].connect(c.op('fk_seed'))
        c.op(name).par.resetpulse.pulse()
        clock.capture(c.op(name), c.op('fk_seed'))
    c.op('fk_read').par.top = 'fk_a'
    total = max(1, int(round(float(c.par.Thumbage) * 60.0)))
    c.store('Fkprogress', dict(token=token, done=0, total=total, buffer=0,
                               seed=int(c.par.Thumbseed), synchronous=synchronous))
    return advance(c, token)


def advance(c, token):
    job = c.fetch('Fkprogress', None)
    if job is None or job['token'] != token or c.fetch('Fkjob', 0) != token:
        return False  # superseded by a newer Generate
    clock = c.op('clock').module
    count = job['total'] - job['done']
    if not job['synchronous']:
        count = min(count, TICKS_PER_FRAME)
    for _ in range(count):
        c.op('fk_read').cook(force=True)
        dest = 1 - job['buffer']
        clock.capture(c.op(('fk_a', 'fk_b')[dest]), c.op('fk_sim'))
        c.op('fk_read').par.top = ('fk_a', 'fk_b')[dest]
        job['buffer'] = dest
        job['done'] += 1
    c.store('Fkprogress', job)
    if job['done'] < job['total']:
        _status(c, 'Generating thumbnails: {}/{} ticks'.format(job['done'], job['total']))
        run('args[0].module.advance(args[1], args[2])', me, c, token, delayFrames=1)
        return False
    c.op('fk_read').cook(force=True)
    c.store('Fkready', 1)
    c.store('Fkreference', dict(seed=job['seed'], ticks=job['total'],
                                seconds=job['total'] / 60.0))
    c.op('fk_panel').cook(force=True)
    _status(c, 'Reference outcomes: seed {}, age {:.2f} s ({} ticks), {}-cell tiles, '
               'no media. Initialization and media change results.'
            .format(job['seed'], job['total'] / 60.0, job['total'], TILE))
    return True


def onFrameStart(frame):
    poll(me.parent())
    return
'''


CLOCK_CALLBACKS = r'''
import math
import time

TICK_SECONDS = 1.0 / 60.0
UPDATES_PER_TICK = 16


def plan_ticks(remainder, elapsed, speed, realtime, limit):
    """Keep fractional ticks and real-time debt; deterministic work is never dropped."""
    debt = max(0.0, remainder) + max(0.0, elapsed) * max(0.0, speed)
    ticks = int(math.floor(debt / TICK_SECONDS + 1e-9))
    if realtime:
        ticks = min(ticks, max(1, int(limit)))
    return ticks, max(0.0, debt - ticks * TICK_SECONDS)


def capture(target, source):
    """Explicit GPU copy, verified to replace repeatedly within one TD frame."""
    source.cook(force=True)
    resized = (target.width, target.height) != (source.width, source.height)
    target.inputConnectors[0].connect(source)
    if resized:
        # Cache TOP otherwise resamples its old texture during a size transition,
        # even when Replace is enabled. Clear first to make this a raw new copy.
        target.par.resetpulse.pulse()
    target.par.replace = True
    try:
        target.cook(force=True)
    finally:
        target.par.replace = False


def _clock(c):
    state = c.fetch('Clockstate', None)
    if state is None:
        state = dict(ticks=0, debt=0.0, buffer=0, media=0, ready=False,
                     last=time.perf_counter(), mode=c.par.Clockmode.eval(), frame=None)
        c.store('Clockstate', state)
    return state


def rebase(c, clear_debt=False):
    state = _clock(c)
    state['last'] = time.perf_counter()
    if clear_debt:
        state['debt'] = 0.0
    state['mode'] = c.par.Clockmode.eval()
    _status(c, 0)


def _status(c, count):
    state = _clock(c)
    c.par.Simtime = state['ticks'] * TICK_SECONDS
    c.par.Simlag = state['debt']
    c.par.Tickcount = count
    c.par.Substeps = UPDATES_PER_TICK * int(c.par.Solverquality)


def desired_size(c):
    return c.op('preset_lib').module.effective_size({
        key: c.par[key].eval() for key in ('Resolution', 'Rectangle', 'Canvaswidth',
                                         'Canvasheight', 'Cellsize')})


def source_signature(c):
    source = c.par.Sourcetop.eval()
    return (c.par.Moviefile.eval(), getattr(source, 'id', None), getattr(source, 'path', None),
            getattr(source, 'width', None), getattr(source, 'height', None))


def invalidate_motion(c):
    # New source / canvas starts from two identical samples, including during pause.
    for name in ('media_a', 'media_b'):
        capture(c.op(name), c.op('media_prepared'))
    state = _clock(c)
    state['media'] = 0
    c.op('media_cache').par.top = 'media_a'
    c.op('media_previous').par.top = 'media_b'
    c.store('Motionready', False)
    c.store('Motiontickready', False)
    for name in ('media_cache', 'media_previous', 'media_mask', 'mask_preview'):
        c.op(name).cook(force=True)
    c.store('Sourcesignature', source_signature(c))


def ensure_source(c):
    signature = source_signature(c)
    if signature != c.fetch('Sourcesignature', None):
        if _clock(c)['ready'] and c.par.Resetonsource:
            reset(c)
            return True
        invalidate_motion(c)
    return False


def ensure_size(c):
    size = desired_size(c)
    old = c.fetch('Appliedsize', None)
    if old is None or not _clock(c)['ready']:
        c.store('Appliedsize', size)
        return False
    if tuple(old) == tuple(size):
        return False
    if c.par.Resizebehavior.eval() == 'reset':
        reset(c)
        return True
    # Download before committing new dimensions. The stored dimensions gate all
    # geometry-dependent operators, so no solver cook can see mismatched buffers.
    snapshots = c.op('snapshot_lib').module
    raw, shape = snapshots.download(c.op('state_read'))
    upload = snapshots.upload(c, raw, shape)
    for name in ('state_a', 'state_b'):
        c.op(name).inputConnectors[0].connect(upload)
    c.store('Appliedsize', size)
    for name in ('state_a', 'state_b'):
        capture(c.op(name), c.op('state_resize'))
    _clock(c)['buffer'] = 0
    c.op('state_read').par.top = 'state_a'
    invalidate_motion(c)
    rebase(c)
    c.op('state').cook(force=True)
    c.par.Statestatus.val = 'Resampled state; age retained. New grid changes future evolution.'
    return False


def _seed_buffers(c, clear_color):
    if clear_color or not _clock(c)['ready']:
        source = c.op('seed')
    else:
        c.op('state_reset').cook(force=True)
        # Freeze result before either ping-pong buffer is replaced.
        capture(c.op('state_work'), c.op('state_reset'))
        source = c.op('state_work')
    for name in ('state_a', 'state_b'):
        capture(c.op(name), source)
    c.op('state_read').par.top = 'state_a'
    _clock(c)['buffer'] = 0


def reset_chemistry(c):
    # A pending resize is handled before resetting; seed controls are read here.
    if not _clock(c)['ready']:
        reset(c)
        return
    if ensure_size(c) or ensure_source(c):
        return
    _seed_buffers(c, clear_color=False)
    _clock(c).update(ticks=0, debt=0.0, frame=None)
    c.store('Palettelasttick', 0)
    c.store('Resetcount', c.fetch('Resetcount', 0) + 1)
    rebase(c)
    c.op('state').cook(force=True)


def clear_color(c):
    ensure_size(c)
    ensure_source(c)
    state = _clock(c)
    if not state['ready']:
        reset(c)
    dest = 1 - state['buffer']
    capture(c.op(('state_a', 'state_b')[dest]), c.op('state_clear_color'))
    c.op('state_read').par.top = ('state_a', 'state_b')[dest]
    state['buffer'] = dest
    c.op('state').cook(force=True)
    rebase(c)


def restart_media(c):
    c.op('movie').par.cuepulse.pulse()
    invalidate_motion(c)
    rebase(c)


def reset_all(c):
    c.op('movie').par.cuepulse.pulse()
    reset(c)

def reset(c):
    state = _clock(c)
    c.store('Appliedsize', desired_size(c))
    # Break old capture inputs before resizing/reinitializing the buffers.
    for name in ('state_a', 'state_b'):
        c.op(name).inputConnectors[0].connect(c.op('seed'))
        c.op(name).par.resetpulse.pulse()
        capture(c.op(name), c.op('seed'))
    c.op('state_read').par.top = 'state_a'
    for name in ('media_a', 'media_b'):
        c.op(name).par.resetpulse.pulse()
        capture(c.op(name), c.op('media_prepared'))
    c.op('media_cache').par.top = 'media_a'
    c.op('media_previous').par.top = 'media_b'
    c.store('Motionready', False)
    c.store('Motiontickready', False)
    c.store('Sourcesignature', source_signature(c))
    c.store('Paletteready', False)
    for name in ('palette_a', 'palette_b'):
        c.op(name).inputConnectors[0].connect(c.op('palette_init'))
        c.op(name).par.resetpulse.pulse()
        capture(c.op(name), c.op('palette_init'))
    c.op('palette_read').par.top = 'palette_a'
    c.store('Palettelasttick', 0)
    c.store('Paletteelapsed', TICK_SECONDS)
    # Custom ramp row and clip history initialize only when consumed.
    update_palette(c, reset=True)
    state.update(ticks=0, debt=0.0, buffer=0, media=0, ready=True,
                 last=time.perf_counter(), mode=c.par.Clockmode.eval(), frame=None)
    # Diagnostic: presets and pulses promise at most one reset per action.
    c.store('Resetcount', c.fetch('Resetcount', 0) + 1)
    for name in ('state_read', 'palette_read', 'media_cache', 'media_previous',
                 'media_mask', 'mask_preview', 'state', 'palette'):
        c.op(name).cook(force=True)
    _status(c, 0)
    c.store('Runtimeerror', '')


def palette_extract_required(c):
    return bool(c.par.Palettehistory or c.par.Colormode.eval() == 'ramp')


def palette_required(c):
    return bool(c.par.Palettehistory or c.par.Colormode.eval() == 'ramp'
                or c.par.Ramptop.eval() is not None)


def update_palette(c, reset=False):
    tick_index = 0 if reset else _clock(c)['ticks'] + 1
    last = int(c.fetch('Palettelasttick', 0))
    ready = bool(c.fetch('Paletteready', False))
    if not palette_required(c):
        return False
    if not reset and ready and tick_index - last < int(c.par.Paletteinterval):
        return False
    c.store('Paletteelapsed', max(1, tick_index - last) * TICK_SECONDS)
    reader = c.op('palette_read')
    dest = 'palette_b' if reader.par.top.eval().name == 'palette_a' else 'palette_a'
    reader.cook(force=True)
    if palette_extract_required(c):
        c.op('palette_cells').cook(force=True)
    capture(c.op(dest), c.op('palette_sort'))
    reader.par.top = dest
    c.store('Paletteready', True)
    c.store('Palettelasttick', tick_index)
    return True


def tick(c, sample=None):
    ensure_size(c)
    ensure_source(c)
    state = _clock(c)
    if not state['ready']:
        reset(c)
    # A controlled source can provide one sample per tick for offline replay.
    if sample is not None:
        sample(c, state['ticks'], state['ticks'] * TICK_SECONDS)
    c.store('Motiontickready', bool(c.fetch('Motionready', False)))
    media = 1 - state['media']
    capture(c.op(('media_a', 'media_b')[media]), c.op('media_prepared'))
    c.op('media_cache').par.top = ('media_a', 'media_b')[media]
    c.op('media_previous').par.top = ('media_a', 'media_b')[state['media']]
    c.op('media_cache').cook(force=True)
    c.op('media_previous').cook(force=True)
    c.op('media_mask').cook(force=True)
    c.op('mask_preview').cook(force=True)
    state['media'] = media
    c.store('Motionready', True)

    c.op('domain_mask').cook(force=True)
    if c.par.Flow and c.par.Velocitytop.eval() is not None:
        c.op('velocity_field').cook(force=True)
    c.op('influence_field').cook(force=True)
    c.op('state_read').cook(force=True)
    c.op('reaction_diffusion').cook(force=True)
    dest = 1 - state['buffer']
    capture(c.op(('state_a', 'state_b')[dest]), c.op('state_transform'))

    update_palette(c)
    c.op('state_read').par.top = ('state_a', 'state_b')[dest]
    state['buffer'] = dest
    state['ticks'] += 1


def stamp(c):
    """Apply the live mask once without advancing time, palette or motion history."""
    if c.par.Influencemode.eval() != 'stamp':
        return False
    ensure_size(c)
    ensure_source(c)
    state = _clock(c)
    if not state['ready']:
        reset(c)
    c.op('media_prepared').cook(force=True)
    c.op('stamp_mask').cook(force=True)
    c.op('domain_mask').cook(force=True)
    c.op('state_read').cook(force=True)
    dest = 1 - state['buffer']
    capture(c.op(('state_a', 'state_b')[dest]), c.op('state_stamp'))
    c.op('state_read').par.top = ('state_a', 'state_b')[dest]
    state['buffer'] = dest
    c.op('state').cook(force=True)
    rebase(c)
    return True


def advance(c, elapsed=None, sample=None):
    """One output frame; explicit elapsed seconds supports reproducible validation."""
    ensure_size(c)
    ensure_source(c)
    state = _clock(c)
    if not state['ready']:
        reset(c)
    now = time.perf_counter()
    measured = max(0.0, now - state['last'])
    state['last'] = now
    if state['mode'] != c.par.Clockmode.eval():
        rebase(c, clear_debt=True)
        measured = 0.0
    if c.par.Pause or float(c.par.Speed) <= 0.0:
        _status(c, 0)
        return 0
    realtime = c.par.Clockmode.eval() == 'realtime'
    if elapsed is None:
        elapsed = measured if realtime else 1.0 / float(c.par.Renderfps)
    count, debt = plan_ticks(state['debt'], elapsed, float(c.par.Speed),
                             realtime, int(c.par.Maxcatchup))
    # Commit debt per completed tick so a failed GPU cook does not lose time.
    state['debt'] = debt + count * TICK_SECONDS
    for _ in range(count):
        tick(c, sample)
        state['debt'] = max(0.0, state['debt'] - TICK_SECONDS)
    _status(c, count)
    return count


def step(c):
    if c.par.Pause:
        tick(c)
        rebase(c)
        _status(c, 1)


def onFrameStart(frame):
    c = me.parent()
    state = _clock(c)
    # An output frame may be demanded by several viewers/consumers.
    if state['frame'] != absTime.frame:
        try:
            advance(c)
        except Exception as error:
            c.store('Runtimeerror', 'Clock stopped: ' + str(error))
            me.par.active = False
            print('ERROR: {} clock stopped: {}'.format(c.path, error))
        state['frame'] = absTime.frame
    return


def onPlayStateChange(state):
    rebase(me.parent())
    return


def onStart():
    reset(me.parent())
    return


def onCreate():
    # Loading a TOX does not restore GPU cache textures. Reset on its first frame.
    c = me.parent()
    c.unstore('Clockstate')
    return
'''


# =============================================================================
# 8. Network construction
# =============================================================================

PARAMETER_PAGES = (
    ('Simulation', ('Turing', 'Clock')),
    ('Media', ('Media', 'Influence')),
    ('Motion', ('Transform', 'Flow', 'Domain')),
    ('Appearance', ('Display', 'Color')),
    ('Presets', ('Presets', 'Explorer')),
    ('State', ('State',)),
    ('Advanced', ('Performance', 'Diagnostics')),
)


def consolidate_parameter_pages(component):
    """Move existing controls without recreating parameters or changing values."""
    pages = {page.name: page for page in component.customPages}
    page_names = tuple(name for name, _ in PARAMETER_PAGES)
    if tuple(pages) == page_names:
        return
    # Capture every source before moving controls into an existing target page.
    sections = {name: [p for p in component.customPars if p.page.name == name]
                for _, names in PARAMETER_PAGES for name in names}
    missing = [name for name in sections if name not in pages]
    if missing:
        raise RuntimeError('Missing parameter pages: ' + ', '.join(missing))
    for target_name, source_names in PARAMETER_PAGES:
        target = component.appendCustomPage(target_name)
        order = 0
        for section_index, source_name in enumerate(source_names):
            for index, parameter in enumerate(sections[source_name]):
                parameter.page = target
                parameter.order = order
                if section_index and index == 0:
                    parameter.startSection = True
                order += 1
    for name, page in pages.items():
        if name not in page_names:
            # Page.destroy also destroys its parameters: only remove empty pages.
            if any(p.page.name == name for p in component.customPars):
                raise RuntimeError('Cannot remove nonempty parameter page: ' + name)
            page.destroy()
    component.sortCustomPages(*page_names)
    for name in ('Feed', 'Seed', 'Simtime', 'Mediascale', 'Sourcepremult',
                 'Maskmode', 'Savestate', 'Statefile', 'Presetfile', 'Fkfeedmin',
                 'Thumbseed', 'Dyespread'):
        getattr(component.par, name).startSection = True
    component.par.Presetstatus.label = 'Preset Status'
    component.par.Explorerstatus.label = 'Explorer Status'


def _unsupported(node, message):
    component = node if getattr(node.par, 'Clockmode', None) is not None else node.parent()
    issues = list(component.fetch('Buildissues', []))
    if message not in issues:
        issues.append(message)
    component.store('Buildissues', issues)
    print('ERROR: ' + message)
    raise RuntimeError(message)


def _set(node, name, value):
    """Fail clearly if a required parameter is unavailable in this TD build."""
    parameter = getattr(node.par, name, None)
    if parameter is None:
        _unsupported(node, 'Missing parameter {}.{} in this TouchDesigner build'.format(node.path, name))
    if isinstance(value, str) and parameter.menuNames and value not in parameter.menuNames:
        _unsupported(node, 'Unsupported value {!r} for {}.{}; supported: {}'.format(
            value, node.path, name, ', '.join(parameter.menuNames)))
    parameter.val = value
    return parameter


def _expression(node, name, expression):
    parameter = getattr(node.par, name, None)
    if parameter is None:
        _unsupported(node, 'Missing parameter {}.{}'.format(node.path, name))
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
    shaders = list(component.fetch('Diagnosticshaders', []))
    shaders.append((node.name, info.name))
    component.store('Diagnosticshaders', shaders)
    return node


def _buffer(component, name, initial, position):
    node = component.create(cacheTOP, name)
    node.nodeX, node.nodeY = position
    node.inputConnectors[0].connect(initial)
    for key, value in (('cachesize', 1), ('active', False), ('cacheonce', False),
                       ('alwayscook', False), ('replace', False), ('replaceindex', 0),
                       ('outputindex', 0), ('format', 'rgba32float'), ('resmult', False),
                       ('inputfiltertype', 'nearest')):
        _set(node, key, value)
    return node


def _build_diagnostics(component):
    # Standalone native creation is intentional; no TDAPI TOX dependency.
    page = component.appendCustomPage('Diagnostics')
    page.appendPulse('Refreshdiagnostics', label='Check Shaders / Refresh')
    component.store('Diagnosticbuild', '{}.{}'.format(app.version, app.build))
    status = component.create(tableDAT, 'status')
    status.nodeX, status.nodeY = -600, -700
    log = component.create(textDAT, 'shader_diagnostics')
    log.nodeX, log.nodeY = -600, -1030
    diagnostics = component.create(executeDAT, 'diagnostics')
    diagnostics.nodeX, diagnostics.nodeY = -100, -700
    diagnostics.text = DIAGNOSTICS_CALLBACKS.strip() + '\n'
    _set(diagnostics, 'active', False)
    _set(diagnostics, 'frameend', False)
    _set(diagnostics, 'framestart', True)
    panel = component.create(textCOMP, 'status_panel')
    panel.nodeX, panel.nodeY = -100, -1030
    for name, value in (('w', 640), ('h', 280), ('type', 'multiline'), ('fontsize', 14), ('alignx', 'left'),
                        ('aligny', 'top'), ('wordwrap', True), ('bgcolorr', 0.025),
                        ('bgcolorg', 0.035), ('bgcolorb', 0.045), ('bgalpha', 1.0),
                        ('textpaddingl', 10), ('textpaddingr', 10),
                        ('textpaddingt', 10), ('textpaddingb', 10)):
        _set(panel, name, value)
    _expression(panel, 'text', 'parent().fetch("Diagnosticstext", "Building...")')
    _set(diagnostics, 'active', True)
    return diagnostics


def _reader(component, name, source, position):
    node = component.create(selectTOP, name)
    node.nodeX, node.nodeY = position
    _set(node, 'top', source)
    _set(node, 'inputfiltertype', 'nearest')
    _set(node, 'format', 'rgba32float')
    return node


def _toggle(page, name, label, default):
    parameter = page.appendToggle(name, label=label)[0]
    parameter.default = default
    parameter.val = default
    return parameter


def _menu(page, name, label, items, default):
    parameter = page.appendMenu(name, label=label)[0]
    parameter.menuNames = [item[0] for item in items]
    parameter.menuLabels = [item[1] for item in items]
    parameter.default = default
    parameter.val = default
    return parameter


def _menu_index(name):
    return 'parent().par.{0}.menuNames.index(parent().par.{0}.eval())'.format(name)


def _build_presets(component):
    """Embedded preset library and versioned table, with a coverage check."""
    library = component.create(textDAT, 'preset_lib')
    library.text = PRESETS_MODULE.strip() + '\n'
    library.nodeX, library.nodeY = -850, -380
    table = component.create(textDAT, 'presets')
    table.nodeX, table.nodeY = -1100, -380
    lib = library.module

    # Every non-pulse custom parameter is preset data, a binding, or deliberately excluded.
    classified = set(lib.parameter_names()) | set(lib.BINDINGS) | set(PRESET_EXCLUDED)
    for name in classified:
        if getattr(component.par, name, None) is None:
            raise RuntimeError('Preset table names missing parameter {}'.format(name))
    unclassified = [par.name for par in component.customPars
                    if par.style != 'Pulse' and par.name not in classified]
    if unclassified:
        raise RuntimeError('Preset coverage: unclassified parameters {}'.format(unclassified))

    # Built-ins are complete: current (default) values plus overrides, no bindings.
    defaults, _ = lib.capture(component)
    document = lib.empty_document()
    for name, description, overrides in BUILTIN_PRESETS:
        unknown = sorted(set(overrides) - set(defaults))
        if unknown:
            raise RuntimeError('Built-in preset {} sets unknown parameters {}'.format(name, unknown))
        values = dict(defaults)
        values.update(overrides)
        document['presets'].append(lib.make_preset(name, values, None, description, builtin=True))
    lib.store_document(component, document, select=BUILTIN_PRESETS[0][0])
    component.par.Presetstatus.val = '{} built-in presets, schema version {}'.format(
        len(BUILTIN_PRESETS), lib.VERSION)


def _build_explorer(component):
    """Feed/Kill reference thumbnails, map panel, and the optional XY panel COMP."""
    atlas_width, atlas_height = FK_COLUMNS * FK_TILE, FK_ROWS * FK_TILE
    if len(FK_EXAMPLES) != FK_COLUMNS * FK_ROWS:
        raise RuntimeError('FK_EXAMPLES must fill the thumbnail atlas')
    fk_glsl = _fk_glsl()

    examples = component.create(tableDAT, 'fk_examples')
    examples.nodeX, examples.nodeY = 1400, -900
    examples.clear()
    examples.appendRow(['index', 'name', 'feed', 'kill', 'preset', 'note'])
    builtin_names = {name for name, _, _ in BUILTIN_PRESETS}
    for index, (name, feed, kill) in enumerate(FK_EXAMPLES):
        examples.appendRow([index, name, repr(feed), repr(kill),
                            name if name in builtin_names else '',
                            'reference outcome: fixed seed and age, no media'])

    seed = _shader(component, 'fk_seed', 'fk_seed_pixel', fk_glsl + FK_SEED_SHADER, (1400, -300))
    _set(seed, 'outputresolution', 'custom')
    _set(seed, 'resolutionw', atlas_width)
    _set(seed, 'resolutionh', atlas_height)
    _uniforms(seed, [('uFkSeed', ('parent().par.Thumbseed', '5', '0', '0'))])
    for index, name in enumerate(('fk_a', 'fk_b')):
        _buffer(component, name, seed, (1400 + index * 220, -600))
    reader = _reader(component, 'fk_read', 'fk_a', (1650, -300))
    simulation = _shader(component, 'fk_sim', 'fk_sim_pixel', fk_glsl + FK_SIM_SHADER, (1900, -300))
    simulation.inputConnectors[0].connect(reader)
    _set(simulation, 'npasses', 16)

    panel_top = _shader(component, 'fk_panel', 'fk_panel_pixel', fk_glsl + FK_PANEL_SHADER, (2150, -300))
    panel_top.inputConnectors[0].connect(reader)
    _set(panel_top, 'outputresolution', 'custom')
    _set(panel_top, 'resolutionw', FK_MAP_SIZE + atlas_width)
    _set(panel_top, 'resolutionh', atlas_height)
    _uniforms(panel_top, [
        ('uFkMap', ('parent().par.Fkfeedmin', 'parent().par.Fkfeedmax',
                    'parent().par.Fkkillmin', 'parent().par.Fkkillmax')),
        ('uFkCurrent', ('parent().par.Feed', 'parent().par.Kill',
                        'parent().fetch("Fkready", 0)', 'parent().par.Contrast')),
    ])

    explorer = component.create(executeDAT, 'explorer')
    explorer.nodeX, explorer.nodeY = 1650, -900
    _set(explorer, 'active', False)
    explorer.text = EXPLORER_CALLBACKS.strip() + '\n'
    for name in ('framestart', 'playstatechange', 'start', 'create', 'frameend'):
        _set(explorer, name, name == 'framestart')

    # The XY panel is optional: report unsupported parameters instead of failing the build.
    try:
        panel = component.create(containerCOMP, 'fk_explorer')
        panel.nodeX, panel.nodeY = 2400, -300
        _set(panel, 'w', FK_MAP_SIZE + atlas_width)
        _set(panel, 'h', atlas_height)
        _set(panel, 'top', 'fk_panel')
        _set(explorer, 'active', True)
    except RuntimeError as error:
        if component.op('fk_explorer') is not None:
            component.op('fk_explorer').destroy()
        component.par.Explorerstatus.val = 'XY panel unavailable: {}'.format(error)
        print('WARNING: Feed/Kill XY panel not built: {}'.format(error))


def build_turing_media_v2(container=None):
    if container is None:
        container = me.parent()

    # Never overwrite a pre-existing component, even if the script is rerun.
    name, suffix = COMPONENT_BASENAME, 2
    while container.op(name) is not None:
        name = '{}_{}'.format(COMPONENT_BASENAME, suffix)
        suffix += 1
    component = container.create(baseCOMP, name)
    component.nodeX, component.nodeY = me.nodeX + 220, me.nodeY

    page = component.appendCustomPage('Turing')
    resolution = _number(page, 'Resolution', 'Resolution (square)', 512, 64, 2048, True)
    _toggle(page, 'Rectangle', 'Rectangular Canvas', False)
    canvas_width = _number(page, 'Canvaswidth', 'Width', 768, 64, 4096, True)
    canvas_height = _number(page, 'Canvasheight', 'Height', 432, 64, 4096, True)
    resolution.enableExpr = 'not me.par.Rectangle'
    canvas_width.enableExpr = 'me.par.Rectangle'
    canvas_height.enableExpr = 'me.par.Rectangle'
    _number(page, 'Cellsize', 'Cell Size (pixels)', 1.0, 1.0, 8.0)
    _number(page, 'Feed', 'Feed', 0.0545, 0.0, 0.1)
    _number(page, 'Kill', 'Kill', 0.062, 0.0, 0.1)
    _number(page, 'Diffusiona', 'Diffusion A', 1.0, 0.0, 1.0)
    _number(page, 'Diffusionb', 'Diffusion B', 0.5, 0.0, 1.0)
    # Retain the parameter name and 'clear' token for existing presets/snapshots.
    _menu(page, 'Transformedge', 'Boundary', [
        ('wrap', 'Wrap'), ('noflux', 'No Flux'), ('clear', 'Empty Exterior'),
    ], 'wrap')
    _number(page, 'Seed', 'Seed', 1, 0, 1000000, True)
    _number(page, 'Seedradius', 'Seed Radius (cells)', 9.0, 3.0, 32.0)
    _toggle(page, 'Ambient', 'Ambient Seeds', True)
    for name, label in (('Reset', 'Reset All'), ('Reseed', 'Reseed + Reset Chemistry')):
        page.appendPulse(name, label=label)

    state_page = component.appendCustomPage('State')
    state_page.appendPulse('Resetchemistry', label='Reset Chemistry')
    state_page.appendPulse('Clearcolor', label='Clear Carried Color')
    state_page.appendPulse('Resetall', label='Reset All')
    _menu(state_page, 'Resizebehavior', 'Resize Behavior', [
        ('reset', 'Reset'), ('resample', 'Resample State')], 'reset')
    state_page.appendPulse('Savestate', label='Save State (memory)')
    state_page.appendPulse('Restorestate', label='Restore State (memory)')
    state_file = state_page.appendFile('Statefile', label='State File (.tstate)')[0]
    state_file.default = 'turing_media_v2.tstate'
    state_file.val = 'turing_media_v2.tstate'
    state_page.appendPulse('Exportstate', label='Save State to Disk')
    state_page.appendPulse('Importstate', label='Restore State from Disk')
    state_status = state_page.appendStr('Statestatus', label='Status')[0]
    state_status.val = 'No state saved'
    state_status.readOnly = True

    preset_page = component.appendCustomPage('Presets')
    _menu(preset_page, 'Preset', 'Preset', [('coral', 'Coral')], 'coral')
    preset_page.appendPulse('Applypreset', label='Apply Preset (keep state)')
    preset_page.appendPulse('Applyreset', label='Apply Preset + Reset')
    preset_name = preset_page.appendStr('Presetname', label='Save As Name')[0]
    preset_name.default = ''
    preset_name.val = ''
    preset_page.appendPulse('Savepreset', label='Save Current Preset')
    preset_page.appendPulse('Deletepreset', label='Delete User Preset')
    _toggle(preset_page, 'Presetbindings', 'Include Media/TOP Bindings', False)
    preset_file = preset_page.appendFile('Presetfile', label='Preset File (.json)')[0]
    preset_file.default = 'turing_media_v2_presets.json'
    preset_file.val = 'turing_media_v2_presets.json'
    _menu(preset_page, 'Importmode', 'Import Mode', [
        ('merge', 'Merge (replace same names)'), ('replace', 'Replace User Presets')], 'merge')
    preset_page.appendPulse('Importpresets', label='Import Presets')
    preset_page.appendPulse('Exportpresets', label='Export Presets')
    preset_status = preset_page.appendStr('Presetstatus', label='Status')[0]
    preset_status.readOnly = True
    clock_page = component.appendCustomPage('Clock')
    _menu(clock_page, 'Clockmode', 'Clock Mode', [
        ('realtime', 'Real Time'), ('framestepped', 'Frame Stepped')], 'realtime')
    _number(clock_page, 'Speed', 'Speed', 1.0, 0.0, 8.0)
    _number(clock_page, 'Solverquality', 'Solver Quality', 1, 1, 4, True)
    fps = _number(clock_page, 'Renderfps', 'Render FPS', 60.0, 1.0, 240.0)
    fps.enableExpr = "me.par.Clockmode == 'framestepped'"
    _toggle(clock_page, 'Pause', 'Pause', False)
    clock_page.appendPulse('Step', label='Step (one tick)')
    limit = _number(clock_page, 'Maxcatchup', 'Max Catch-up Ticks / Frame', 4, 1, 32, True)
    limit.enableExpr = "me.par.Clockmode == 'realtime'"
    for name, label, integer in (('Simtime', 'Simulation Time (seconds)', False),
                                  ('Simlag', 'Simulation Lag (seconds)', False),
                                  ('Tickcount', 'Ticks Last Frame', True),
                                  ('Substeps', 'Substeps / Tick', True)):
        parameter = _number(clock_page, name, label, 0, 0, 1000000000, integer)
        parameter.readOnly = True

    media_page = component.appendCustomPage('Media')
    movie_file = media_page.appendFile('Moviefile', label='Movie File (blank = none)')[0]
    movie_file.default = ''
    movie_file.val = ''
    source_top = media_page.appendTOP('Sourcetop', label='Source TOP (overrides Movie File)')[0]
    source_top.default = ''
    source_top.val = ''
    _toggle(media_page, 'Mediaplay', 'Play Media', True)
    _number(media_page, 'Mediaspeed', 'Media Speed', 0.5, -2.0, 2.0)
    media_page.appendPulse('Restartclip', label='Restart Media')
    _toggle(media_page, 'Resetonsource', 'Reset on Source Change', False)
    _toggle(media_page, 'Overridefps', 'Override FPS (image sequences)', False)
    _number(media_page, 'Sequencefps', 'Sequence FPS', 30.0, 1.0, 120.0)
    _number(media_page, 'Mediascale', 'Scale', 0.9, 0.05, 3.0)
    _number(media_page, 'Offsetx', 'Offset X', 0.0, -1.0, 1.0)
    _number(media_page, 'Offsety', 'Offset Y', 0.0, -1.0, 1.0)
    _number(media_page, 'Rotation', 'Rotation (degrees)', 0.0, -180.0, 180.0)
    _toggle(media_page, 'Sourcepremult', 'Source Premultiplied', False)
    _toggle(media_page, 'Ignorealpha', 'Ignore Source Alpha', False)

    influence_page = component.appendCustomPage('Influence')
    _menu(influence_page, 'Influencemode', 'Influence Mode', [
        ('continuous', 'Continuous Seed'), ('stamp', 'Stamp Once'),
        ('chemistry', 'Chemistry Map')], 'continuous')
    stamp = influence_page.appendPulse('Stamp', label='Stamp Current Mask')[0]
    stamp.enableExpr = "me.par.Influencemode == 'stamp'"
    amount = _number(influence_page, 'Stampamount', 'Stamp Amount', 1.0, 0.0, 1.0)
    amount.enableExpr = "me.par.Influencemode == 'stamp'"
    for name, label, default in (('Feedmin', 'Map Feed Minimum', .025),
                                  ('Feedmax', 'Map Feed Maximum', .065),
                                  ('Killmin', 'Map Kill Minimum', .045),
                                  ('Killmax', 'Map Kill Maximum', .070),
                                  ('Chemistryblend', 'Chemistry Map Blend', 1.0)):
        parameter = _number(influence_page, name, label, default, 0.0,
                            1.0 if name == 'Chemistryblend' else .1)
        parameter.enableExpr = "me.par.Influencemode == 'chemistry'"
    _menu(influence_page, 'Maskmode', 'Mask Mode', [
        ('alpha', 'Silhouette'), ('bright', 'Bright Texture'), ('dark', 'Dark Texture'),
        ('edgealpha', 'Silhouette Edges'), ('edgetexture', 'Texture Edges'), ('motion', 'Motion'),
    ], 'edgealpha')
    strength = _number(influence_page, 'Strength', 'Injection Rate (1 / second)', _rate(0.08), 0.0, 600.0)
    strength.enableExpr = "me.par.Influencemode == 'continuous'"
    _number(influence_page, 'Maskgain', 'Mask Gain', 1.0, 0.0, 8.0)
    _number(influence_page, 'Edgewidth', 'Edge Width (cells)', 3.0, 1.0, 12.0)
    _number(influence_page, 'Smoothing', 'Mask Smoothing (cells)', 1.0, 0.0, 8.0)
    _number(influence_page, 'Motiongain', 'Motion Gain', 4.0, 0.1, 20.0)
    _number(influence_page, 'Fade', 'Recovery Rate (1 / second)', 0.0, 0.0, 60.0)
    influence_page.appendPulse('Clipseed', label='Seed From Clip Only')

    domain_page = component.appendCustomPage('Domain')
    domain_top = domain_page.appendTOP('Domaintop', label='Domain Mask TOP (red; blank = all)')[0]
    domain_top.default = ''
    domain_top.val = ''
    _number(domain_page, 'Domainthreshold', 'Domain Threshold', .5, 0.0, 1.0)
    _toggle(domain_page, 'Domaininvert', 'Invert Domain', False)
    _menu(domain_page, 'Domainboundary', 'Domain Boundary', [
        ('noflux', 'No Flux'), ('empty', 'Empty Exterior')], 'noflux')

    page = component.appendCustomPage('Display')
    _number(page, 'Coloramount', 'Color Amount', 1.0, 0.0, 1.0)
    _number(page, 'Contrast', 'Contrast', 2.5, 0.1, 6.0)
    invert = page.appendToggle('Invert', label='Invert')[0]
    invert.default = False
    invert.val = False

    _number(page, 'Overlay', 'Source Overlay', 0.2, 0.0, 1.0)
    _number(page, 'Clipalpha', 'Clip Patterns to Alpha', 0.0, 0.0, 1.0)
    _menu(page, 'Viewmode', 'Output View', [
        ('final', 'Final'), ('patterns', 'Patterns'), ('mask', 'Influence Mask'),
        ('source', 'Source on Checkerboard'),
    ], 'final')
    _menu(page, 'Upscale', 'Upscale Filter', [
        ('smooth', 'Smooth (Cubic)'), ('linear', 'Linear'), ('nearest', 'Nearest (Pixels)'),
    ], 'smooth')

    transform_page = component.appendCustomPage('Transform')
    _toggle(transform_page, 'Transform', 'Enable Transform', False)
    _number(transform_page, 'Grow', 'Grow / Shrink (% / second)', 6000.0 * math.log1p(0.001), -300.0, 300.0)
    _number(transform_page, 'Scalex', 'Scale X (% / second)', 0.0, -300.0, 300.0)
    _number(transform_page, 'Scaley', 'Scale Y (% / second)', 0.0, -300.0, 300.0)
    _number(transform_page, 'Translatex', 'Translate X (cells / second)', 0.0, -480.0, 480.0)
    _number(transform_page, 'Translatey', 'Translate Y (cells / second)', 0.0, -480.0, 480.0)
    _number(transform_page, 'Rotate', 'Rotate (degrees / second)', 6.0, -600.0, 600.0)
    _number(transform_page, 'Pivotx', 'Pivot X', 0.5, 0.0, 1.0)
    _number(transform_page, 'Pivoty', 'Pivot Y', 0.5, 0.0, 1.0)
    transform_page.appendPulse('Transformzero', label='Zero Motion')

    flow_page = component.appendCustomPage('Flow')
    _toggle(flow_page, 'Flow', 'Enable Velocity', False)
    velocity_top = flow_page.appendTOP('Velocitytop', label='Velocity TOP (RG cells / second)')[0]
    velocity_top.default = ''
    velocity_top.val = ''
    _number(flow_page, 'Flowstrength', 'Velocity Strength', 1.0, 0.0, 100.0)
    _number(flow_page, 'Flowmax', 'Max Displacement (cells / tick)', 8.0, 0.0, 64.0)

    color_page = component.appendCustomPage('Color')
    _menu(color_page, 'Colormode', 'Color Mode', [
        ('fixed', 'Fixed Palette'), ('tint', 'Source Tint'), ('ramp', 'Clip Palette'),
        ('dye', 'Carried Color'),
    ], 'fixed')
    ramp_top = color_page.appendTOP('Ramptop', label='Ramp TOP (blank = teal/gold)')[0]
    ramp_top.default = ''
    ramp_top.val = ''
    _number(color_page, 'Tintspread', 'Tint Spread (cells)', 6.0, 0.0, 24.0)
    _number(color_page, 'Palettesmooth', 'Palette Smoothing (seconds)', -1.0 / (60.0 * math.log(0.9)), 0.0, 10.0)
    _number(color_page, 'Paletteanchor', 'Palette Anchoring', 0.5, 0.0, 1.0)
    _number(color_page, 'Dyespread', 'Color Spread Rate (1 / second)', _rate(0.5, 960.0), 0.0, 4000.0)
    _menu(color_page, 'Dyesource', 'Carried Color Source', [
        ('alpha', 'Source Alpha'), ('mask', 'Influence Mask')], 'alpha')
    _number(color_page, 'Dyeinject', 'Color Injection Rate (1 / second)', _rate(0.05), 0.0, 600.0)
    _number(color_page, 'Dyedecay', 'Color Decay Rate (1 / second)', 0.0, 0.0, 60.0)
    _number(color_page, 'Dyesaturation', 'Color Saturation', 1.5, 0.0, 4.0)

    performance_page = component.appendCustomPage('Performance')
    _toggle(performance_page, 'Carryhistory', 'Maintain Carried Color', True)
    _toggle(performance_page, 'Palettehistory', 'Continuous Palette History', False)
    _number(performance_page, 'Paletteinterval', 'Palette Update Interval (ticks)', 1, 1, 600, True)

    explorer_page = component.appendCustomPage('Explorer')
    _toggle(explorer_page, 'Explorerclick', 'Panel Click Sets Feed/Kill', True)
    _toggle(explorer_page, 'Explorerreset', 'Reset When Choosing Example', False)
    _number(explorer_page, 'Fkfeedmin', 'Map Feed Minimum', 0.0, 0.0, 0.1)
    _number(explorer_page, 'Fkfeedmax', 'Map Feed Maximum', 0.08, 0.0, 0.1)
    _number(explorer_page, 'Fkkillmin', 'Map Kill Minimum', 0.04, 0.0, 0.1)
    _number(explorer_page, 'Fkkillmax', 'Map Kill Maximum', 0.07, 0.0, 0.1)
    _number(explorer_page, 'Thumbseed', 'Thumbnail Seed', 1, 0, 1000000, True)
    _number(explorer_page, 'Thumbage', 'Thumbnail Age (seconds)', 10.0, 0.5, 60.0)
    explorer_page.appendPulse('Generatethumbs', label='Generate Thumbnails')
    explorer_status = explorer_page.appendStr('Explorerstatus', label='Status')[0]
    explorer_status.default = 'Thumbnails not generated'
    explorer_status.val = 'Thumbnails not generated'
    explorer_status.readOnly = True

    diagnostics = _build_diagnostics(component)
    consolidate_parameter_pages(component)

    # A transparent canvas-sized source: no media means no influence at all.
    blank = component.create(constantTOP, 'blank')
    blank.nodeX, blank.nodeY = -1250, 400
    _set(blank, 'outputresolution', 'custom')
    _expression(blank, 'resolutionw', CANVAS_WIDTH)
    _expression(blank, 'resolutionh', CANVAS_HEIGHT)
    _set(blank, 'format', 'rgba32float')
    _set(blank, 'alpha', 0.0)

    movie = component.create(moviefileinTOP, 'movie')
    movie.nodeX, movie.nodeY = -1250, 850
    _expression(movie, 'file', 'parent().par.Moviefile')
    _set(movie, 'playmode', 'sequential')
    _expression(movie, 'play', 'parent().par.Mediaplay')
    _expression(movie, 'speed', 'parent().par.Mediaspeed')
    _set(movie, 'textendleft', 'cycle')
    _set(movie, 'textendright', 'cycle')
    _set(movie, 'premultrgbbyalpha', 'off')
    _expression(movie, 'overridesample', 'parent().par.Overridefps')
    _expression(movie, 'samplerate', 'parent().par.Sequencefps')
    movie_info = component.create(infoCHOP, 'movie_info')
    movie_info.nodeX, movie_info.nodeY = -1050, 850
    _set(movie_info, 'op', movie.name)

    # Optional Source TOP; falls back to blank so the select never errors when unassigned.
    source_top = component.create(selectTOP, 'media_top')
    source_top.nodeX, source_top.nodeY = -1250, 625
    _expression(source_top, 'top', 'parent().par.Sourcetop.eval() if {} else op("blank")'
                                   .format(HAS_SOURCE_TOP))

    source = component.create(switchTOP, 'media_source')
    source.nodeX, source.nodeY = -950, 400
    source.inputConnectors[0].connect(blank)
    source.inputConnectors[1].connect(movie)
    source.inputConnectors[2].connect(source_top)
    _set(source, 'blend', False)
    _expression(source, 'index', '2 if {} else 1 if {} else 0'.format(HAS_SOURCE_TOP, HAS_MOVIE))

    prepared = _shader(component, 'media_prepared', 'prepare_pixel', PREPARE_SHADER, (-700, 650))
    prepared.inputConnectors[0].connect(source)
    _set(prepared, 'outputresolution', 'custom')
    _expression(prepared, 'resolutionw', CANVAS_WIDTH)
    _expression(prepared, 'resolutionh', CANVAS_HEIGHT)
    _set(prepared, 'inputfiltertype', 'linear')
    _set(prepared, 'inputextenduv', 'zero')
    _uniforms(prepared, [
        ('uTransform', ('parent().par.Mediascale', 'parent().par.Offsetx',
                        'parent().par.Offsety', 'parent().par.Rotation * 0.0174532925199433')),
        ('uAlpha', ('parent().par.Sourcepremult if {} else 0'.format(HAS_MEDIA),
                    # Ignore Alpha would make the blank source an opaque mask.
                    'parent().par.Ignorealpha if {} else 0'.format(HAS_MEDIA),
                    # The blank is rendered at the canvas size, so it fills the canvas.
                    'op("media_top").width / max(1, op("media_top").height) if {} '
                    'else op("movie").width / max(1, op("movie").height) if {} '
                    'else ({})'.format(HAS_SOURCE_TOP, HAS_MOVIE, CANVAS_ASPECT),
                    CANVAS_ASPECT)),
    ])

    # Motion Cache TOPs explicitly disable Active, Cache Once and Always Cook.
    # Readers may recook for any viewer, but history is replaced ONLY by tick,
    # invalidation or restore. A stopped source therefore compares two identical
    # samples on the next tick instead of retaining an old moving frame.
    for index, name in enumerate(('media_a', 'media_b')):
        _buffer(component, name, prepared, (-650, 1150 + index * 150))
    cache = _reader(component, 'media_cache', 'media_a', (-400, 650))
    previous = _reader(component, 'media_previous', 'media_b', (-150, 900))

    # Separate normalized simulation samples from full-resolution display/media history.
    sim_samples = {}
    for name, source_node in (('sim_source', cache), ('sim_previous', previous), ('sim_live', prepared)):
        node = _shader(component, name + '_prepare', name + '_pixel', SIM_SOURCE_SHADER, (-400, -2100 - len(sim_samples)*350))
        node.inputConnectors[0].connect(source_node)
        _set(node, 'outputresolution', 'custom')
        _expression(node, 'resolutionw', SIM_WIDTH)
        _expression(node, 'resolutionh', SIM_HEIGHT)
        _set(node, 'inputfiltertype', 'linear')
        _set(node, 'inputextenduv', 'hold')
        reader = _reader(component, name, source_node.name, (0, -2100 - len(sim_samples)*350))
        _expression(reader, 'top', 'op("{}") if parent().fetch("Appliedsize")[0:2] == parent().fetch("Appliedsize")[2:4] else op("{}")'.format(source_node.name, node.name))
        if name == 'sim_previous':
            _expression(reader, 'top', 'op("sim_source") if parent().par.Maskmode.eval() != "motion" else ('
                        'op("media_previous") if parent().fetch("Appliedsize")[0:2] == parent().fetch("Appliedsize")[2:4] '
                        'else op("sim_previous_prepare"))')
        sim_samples[name] = reader

    mask = _shader(component, 'media_mask', 'mask_pixel', MASK_SHADER, (100, 650))
    mask.inputConnectors[0].connect(sim_samples['sim_source'])
    mask.inputConnectors[1].connect(sim_samples['sim_previous'])
    _set(mask, 'inputfiltertype', 'linear')
    _set(mask, 'inputextenduv', 'zero')
    _uniforms(mask, [
        # Mask input/output are at simulation size; widths stay in simulation cells.
        ('uMask', (_menu_index('Maskmode'), 'parent().par.Maskgain',
                   'parent().par.Edgewidth',
                   'parent().par.Smoothing')),
        ('uMotion', ('parent().par.Motiongain',
                     'parent().fetch("Motiontickready", False)', '0', '0')),
    ])
    mask_preview = component.create(resolutionTOP, 'mask_preview')
    mask_preview.nodeX, mask_preview.nodeY = 350, 650
    mask_preview.inputConnectors[0].connect(mask)
    _set(mask_preview, 'outputresolution', 'custom')
    _expression(mask_preview, 'resolutionw', CANVAS_WIDTH)
    _expression(mask_preview, 'resolutionh', CANVAS_HEIGHT)
    _set(mask_preview, 'inputfiltertype', 'linear')
    source_preview = component.create(nullTOP, 'source_preview')
    source_preview.nodeX, source_preview.nodeY = -400, 1050
    source_preview.inputConnectors[0].connect(prepared)

    # Domain input uses normalized canvas UV, nearest red-channel sampling and
    # a hard threshold. No media fitting or alpha interpretation is applied.
    domain_top = _reader(component, 'domain_top', 'blank', (-1250, -750))
    _expression(domain_top, 'top', 'parent().par.Domaintop.eval() if {} else op("blank")'.format(HAS_DOMAIN))
    domain_mask = _shader(component, 'domain_prepare', 'domain_pixel', DOMAIN_SHADER, (-950, -750))
    domain_mask.inputConnectors[0].connect(domain_top)
    _set(domain_mask, 'outputresolution', 'custom')
    _expression(domain_mask, 'resolutionw', SIM_WIDTH)
    _expression(domain_mask, 'resolutionh', SIM_HEIGHT)
    _uniforms(domain_mask, [('uDomainMask', (HAS_DOMAIN, 'parent().par.Domainthreshold',
                                             'parent().par.Domaininvert', '0'))])
    domain = component.create(nullTOP, 'domain_mask')
    domain.nodeX, domain.nodeY = -700, -750
    domain.inputConnectors[0].connect(domain_mask)
    domain_uniform = ('uDomain', (HAS_DOMAIN, _menu_index('Domainboundary'), '0', '0'))
    boundary_uniform = ('uBoundary', (_menu_index('Transformedge'), '0', '0', '0'))

    velocity_top = _reader(component, 'velocity_top', 'blank', (-1250, -1750))
    _expression(velocity_top, 'top', 'parent().par.Velocitytop.eval() if parent().par.Flow and {} else op("blank")'.format(HAS_VELOCITY))
    velocity = _shader(component, 'velocity_prepare', 'velocity_pixel', VELOCITY_SHADER, (-950, -1750))
    velocity.inputConnectors[0].connect(velocity_top)
    _set(velocity, 'outputresolution', 'custom')
    _expression(velocity, 'resolutionw', SIM_WIDTH)
    _expression(velocity, 'resolutionh', SIM_HEIGHT)
    _uniforms(velocity, [boundary_uniform])
    velocity_field = component.create(nullTOP, 'velocity_field')
    velocity_field.nodeX, velocity_field.nodeY = -700, -1750
    velocity_field.inputConnectors[0].connect(velocity)

    # GLSL TOP has three inputs: pack influence R and domain G into one field.
    field = _shader(component, 'influence_prepare', 'influence_pixel', INFLUENCE_FIELD_SHADER, (-450, -750))
    field.inputConnectors[0].connect(mask)
    field.inputConnectors[1].connect(domain)
    _set(field, 'outputresolution', 'custom')
    _expression(field, 'resolutionw', SIM_WIDTH)
    _expression(field, 'resolutionh', SIM_HEIGHT)
    influence_field = component.create(nullTOP, 'influence_field')
    influence_field.nodeX, influence_field.nodeY = -200, -750
    influence_field.inputConnectors[0].connect(field)

    stamp_mask = _shader(component, 'stamp_mask', 'stamp_mask_pixel', MASK_SHADER, (600, 650))
    stamp_mask.inputConnectors[0].connect(sim_samples['sim_live'])
    stamp_mask.inputConnectors[1].connect(sim_samples['sim_source'])
    _set(stamp_mask, 'inputfiltertype', 'linear')
    _set(stamp_mask, 'inputextenduv', 'zero')
    _uniforms(stamp_mask, [
        ('uMask', (_menu_index('Maskmode'), 'parent().par.Maskgain',
                   'parent().par.Edgewidth',
                   'parent().par.Smoothing')),
        ('uMotion', ('parent().par.Motiongain', 'parent().fetch("Motiontickready", False)', '0', '0')),
    ])

    seed = _shader(component, 'seed', 'seed_pixel', SEED_SHADER, (-600, 200))
    seed.inputConnectors[0].connect(domain)
    _set(seed, 'outputresolution', 'custom')
    # The seed sets the simulation grid; every state operator downstream follows it.
    _expression(seed, 'resolutionw', SIM_WIDTH)
    _expression(seed, 'resolutionh', SIM_HEIGHT)
    _uniforms(seed, [('uSeed', ('parent().par.Seed', 'parent().par.Seedradius',
                                '0', 'parent().par.Ambient')),
                     ('uSeedSize', (SIM_WIDTH, SIM_HEIGHT, '0', '0')), domain_uniform, boundary_uniform])

    # Explicit texture ping-pong; frame-based Feedback TOPs cannot advance here.
    for index, name in enumerate(('state_a', 'state_b')):
        _buffer(component, name, seed, (-850, -250 - index * 150))
    state_read = _reader(component, 'state_read', 'state_a', (-350, 200))

    upload_callbacks = component.create(textDAT, 'state_upload_callbacks')
    upload_callbacks.text = UPLOAD_CALLBACKS.strip() + '\n'
    upload_callbacks.nodeX, upload_callbacks.nodeY = -1400, -1400
    upload_node = component.create(scriptTOP, 'state_upload')
    upload_node.nodeX, upload_node.nodeY = -1400, -1100
    _set(upload_node, 'callbacks', upload_callbacks.name)
    _set(upload_node, 'format', 'rgba32float')
    _set(upload_node, 'inputfiltertype', 'nearest')
    resize = _shader(component, 'state_resize', 'resize_pixel', RESIZE_STATE_SHADER, (-1100, -1100))
    resize.inputConnectors[0].connect(upload_node)
    resize.inputConnectors[1].connect(domain)
    _set(resize, 'outputresolution', 'custom')
    _expression(resize, 'resolutionw', SIM_WIDTH)
    _expression(resize, 'resolutionh', SIM_HEIGHT)
    _uniforms(resize, [domain_uniform, boundary_uniform])
    reset_node = _shader(component, 'state_reset', 'reset_pixel', STATE_RESET_SHADER, (-800, -1100))
    reset_node.inputConnectors[0].connect(state_read)
    reset_node.inputConnectors[1].connect(seed)
    _buffer(component, 'state_work', seed, (-800, -1450))
    clear_node = _shader(component, 'state_clear_color', 'clear_color_pixel', CLEAR_COLOR_SHADER, (-500, -1100))
    clear_node.inputConnectors[0].connect(state_read)

    simulation = _shader(component, 'reaction_diffusion', 'simulation_pixel',
                         SIMULATION_SHADER, (-100, 200))
    simulation.inputConnectors[0].connect(state_read)
    simulation.inputConnectors[1].connect(influence_field)
    simulation.inputConnectors[2].connect(sim_samples['sim_source'])
    _expression(simulation, 'npasses', '16 * parent().par.Solverquality')
    _uniforms(simulation, [
        ('uRates', ('parent().par.Feed', 'parent().par.Kill',
                    'parent().par.Diffusiona', 'parent().par.Diffusionb')),
        ('uStep', ('1.0 / parent().par.Solverquality', '1.0 / (960.0 * parent().par.Solverquality)',
                   'parent().par.Carryhistory', repr(TICK_SECONDS))),
        ('uInfluence', ('parent().par.Strength', 'parent().par.Fade', '0', '0')),
        ('uDye', ('parent().par.Dyespread', 'parent().par.Dyeinject',
                  'parent().par.Dyedecay', _menu_index('Dyesource'))),
        ('uInfluenceMode', (_menu_index('Influencemode'), 'parent().par.Chemistryblend', '0', '0')),
        ('uChemistry', ('parent().par.Feedmin', 'parent().par.Feedmax',
                        'parent().par.Killmin', 'parent().par.Killmax')),
        domain_uniform, boundary_uniform,
    ])

    # Applied once at the tick boundary, after every numerical substep.
    transform = _shader(component, 'state_transform', 'transform_pixel',
                        TRANSFORM_SHADER, (150, 200))
    transform.inputConnectors[0].connect(simulation)
    transform.inputConnectors[1].connect(domain)
    transform.inputConnectors[2].connect(velocity_field)
    _uniforms(transform, [
        ('uWarp', ('parent().par.Grow', 'parent().par.Scalex', 'parent().par.Scaley',
                   'parent().par.Rotate * 0.0174532925199433')),
        ('uDrift', ('parent().par.Translatex', 'parent().par.Translatey',
                    'parent().par.Pivotx', 'parent().par.Pivoty')),
        ('uFlow', ('parent().par.Flow and {}'.format(HAS_VELOCITY),
                   'parent().par.Flowstrength', 'parent().par.Flowmax', '0')),
        ('uWarpMode', ('parent().par.Transform',
                       '0', repr(TICK_SECONDS), '0')),
        domain_uniform, boundary_uniform,
    ])

    stamp_node = _shader(component, 'state_stamp', 'stamp_pixel', STAMP_SHADER, (150, -550))
    stamp_node.inputConnectors[0].connect(state_read)
    stamp_node.inputConnectors[1].connect(stamp_mask)
    stamp_node.inputConnectors[2].connect(domain)
    _uniforms(stamp_node, [
        ('uStamp', ('parent().par.Stampamount', '0', '0', '0')),
        domain_uniform, boundary_uniform,
    ])

    state = component.create(nullTOP, 'state')
    state.nodeX, state.nodeY = 150, 420
    state.inputConnectors[0].connect(state_read)
    _set(state, 'format', 'rgba32float')

    # Clip palette history uses the same explicit tick commits as chemical state.
    palette_uniforms = [('uPalette', (str(PALETTE_CELLS),
                                      'math.exp(-parent().fetch("Paletteelapsed", 1.0/60.0) / parent().par.Palettesmooth) if parent().par.Palettesmooth > 0 else 0',
                                      'parent().fetch("Paletteready", False)',
                                      str(PALETTE_WIDTH)))]
    palette_cells = _shader(component, 'palette_cells', 'palette_cells_pixel',
                            PALETTE_CELLS_SHADER, (-150, 1350))
    palette_cells.inputConnectors[0].connect(cache)
    _set(palette_cells, 'outputresolution', 'custom')
    _set(palette_cells, 'resolutionw', PALETTE_CELLS)
    _set(palette_cells, 'resolutionh', PALETTE_CELLS)
    _set(palette_cells, 'inputfiltertype', 'linear')
    _set(palette_cells, 'inputextenduv', 'zero')
    _uniforms(palette_cells, palette_uniforms)

    palette_init = _shader(component, 'palette_init', 'palette_init_pixel',
                           'layout(location=0) out vec4 fragColor;\n' + FIXED_PALETTE_GLSL +
                           '\nvoid main(){ float t=(gl_FragCoord.x-0.5)/63.0; fragColor=TDOutputSwizzle(vec4(fixedPalette(t),1.0)); }',
                           (100, 1550))
    palette_init.nodeX, palette_init.nodeY = 100, 1550
    _set(palette_init, 'outputresolution', 'custom')
    _set(palette_init, 'resolutionw', PALETTE_WIDTH)
    _set(palette_init, 'resolutionh', 2)
    _set(palette_init, 'format', 'rgba32float')
    for index, name in enumerate(('palette_a', 'palette_b')):
        _buffer(component, name, palette_init, (350 + index * 220, 1750))
    palette_read = _reader(component, 'palette_read', 'palette_a', (350, 1550))

    # Optional Ramp TOP; falls back to palette_init so the select never errors when blank.
    ramp = component.create(selectTOP, 'ramp')
    ramp.nodeX, ramp.nodeY = 100, 1750
    _expression(ramp, 'top', 'parent().par.Ramptop.eval() if parent().par.Ramptop.eval() is not None '
                             'else op("palette_init")')
    ramp_uniform = ('uRamp', ('1 if parent().par.Ramptop.eval() is not None else 0',
                                'parent().par.Palettehistory or parent().par.Colormode.eval() == "ramp"', '0', '0'))

    palette_samples = _reader(component, 'palette_samples', 'palette_init', (-150, 1750))
    _expression(palette_samples, 'top', 'op("palette_cells") if parent().par.Palettehistory or parent().par.Colormode.eval() == "ramp" else op("palette_init")')

    palette_sort = _shader(component, 'palette_sort', 'palette_sort_pixel',
                           PALETTE_SORT_SHADER, (350, 1350))
    palette_sort.inputConnectors[0].connect(palette_samples)
    palette_sort.inputConnectors[1].connect(palette_read)
    palette_sort.inputConnectors[2].connect(ramp)
    _set(palette_sort, 'outputresolution', 'custom')
    _set(palette_sort, 'resolutionw', PALETTE_WIDTH)
    _set(palette_sort, 'resolutionh', 2)
    _set(palette_sort, 'inputfiltertype', 'linear')
    _uniforms(palette_sort, palette_uniforms + [ramp_uniform])
    palette = component.create(nullTOP, 'palette')
    palette.nodeX, palette.nodeY = 600, 1350
    palette.inputConnectors[0].connect(palette_read)

    display = _shader(component, 'colorize', 'display_pixel', DISPLAY_SHADER, (400, 200))
    display.inputConnectors[0].connect(state)
    display.inputConnectors[1].connect(prepared)
    display.inputConnectors[2].connect(palette)
    # Upscales the (possibly coarser) state back to the canvas size.
    _set(display, 'outputresolution', 'custom')
    _expression(display, 'resolutionw', CANVAS_WIDTH)
    _expression(display, 'resolutionh', CANVAS_HEIGHT)
    _uniforms(display, [
        ('uDisplay', ('parent().par.Coloramount', 'parent().par.Contrast',
                      'parent().par.Invert', _menu_index('Colormode'))),
        ('uColor', ('parent().par.Tintspread * parent().par.Cellsize', 'parent().par.Paletteanchor',
                    'parent().par.Dyesaturation', str(PALETTE_WIDTH))),
        ('uUpscale', (_menu_index('Upscale'), '0', '0', '0')),
        boundary_uniform,
        ramp_uniform,
    ])
    _set(display, 'inputfiltertype', 'linear')

    patterns = component.create(nullTOP, 'patterns')
    patterns.nodeX, patterns.nodeY = 650, 200
    patterns.inputConnectors[0].connect(display)
    composite = _shader(component, 'composite', 'composite_pixel', COMPOSITE_SHADER, (900, 200))
    composite.inputConnectors[0].connect(patterns)
    composite.inputConnectors[1].connect(prepared)
    composite.inputConnectors[2].connect(mask_preview)
    _set(composite, 'inputfiltertype', 'linear')
    _uniforms(composite, [('uComposite', ('parent().par.Overlay', 'parent().par.Clipalpha',
                                        _menu_index('Viewmode'), '0'))])

    # Channel-only formats preserve float32 mask values and exact binary walls.
    for node, format_name in ((mask, 'mono32float'), (stamp_mask, 'mono32float'),
                              (domain_mask, 'mono8fixed'), (field, 'rg32float'),
                              (display, 'rgba16float')):
        _set(node, 'format', format_name)

    out = component.create(outTOP, 'out1')
    out.nodeX, out.nodeY = 1150, 200
    out.inputConnectors[0].connect(composite)
    out.viewer = True

    clock = component.create(executeDAT, 'clock')
    clock.nodeX, clock.nodeY = -100, -160
    _set(clock, 'active', False)
    clock.text = CLOCK_CALLBACKS.strip() + '\n'
    for name in ('framestart', 'playstatechange', 'start', 'create'):
        _set(clock, name, True)
    _set(clock, 'frameend', False)

    _build_presets(component)
    snapshot_lib = component.create(textDAT, 'snapshot_lib')
    snapshot_lib.text = SNAPSHOT_MODULE.strip() + '\n'
    snapshot_lib.nodeX, snapshot_lib.nodeY = -1100, -1450
    _build_explorer(component)

    callbacks = component.create(parameterexecuteDAT, 'controls')
    callbacks.nodeX, callbacks.nodeY = -350, -160
    _set(callbacks, 'active', False)
    callbacks.text = CONTROL_CALLBACKS.strip() + '\n'
    _set(callbacks, 'op', '..')
    _set(callbacks, 'pars', 'Stamp Step Pause Clockmode Speed Reset Reseed Resolution Rectangle '
                            'Canvaswidth Canvasheight Cellsize Seed Seedradius Ambient Moviefile '
                            'Sourcetop Clipseed Restartclip Transformzero Applypreset Applyreset '
                            'Savepreset Deletepreset Importpresets Exportpresets Generatethumbs '
                            'Resetchemistry Clearcolor Resetall Savestate Restorestate Exportstate Importstate '
                            'Refreshdiagnostics')
    _set(callbacks, 'custom', True)
    _set(callbacks, 'builtin', False)
    _set(callbacks, 'onpulse', True)
    _set(callbacks, 'valuechange', True)
    for name in ('expressionchange', 'exportchange', 'enablechange', 'modechange', 'valueschanged'):
        parameter = getattr(callbacks.par, name, None)
        if parameter is not None:
            parameter.val = False
    _set(callbacks, 'active', True)
    callbacks.cook(force=True)  # Register custom parameter monitoring immediately.

    help_dat = component.create(textDAT, 'README')
    help_dat.text = NETWORK_HELP
    help_dat.nodeX, help_dat.nodeY = -600, -380

    # Match UI-created operators; keep all generated viewers available.
    for node in component.children:
        node.viewer = True

    # The COMP viewer gives the simulation a visible consumer while playback runs.
    _expression(component, 'opviewer', 'me.op("out1")')
    nodeview = getattr(component.par, 'nodeview', None)
    if nodeview is not None:
        nodeview.val = 'opviewer'
    component.viewer = True
    clock.module.reset(component)
    diagnostics.module.refresh(component, compile_shaders=True)
    diagnostics.cook(force=True)  # Register automatic diagnostic updates.
    _set(clock, 'active', True)
    print('Created {}. Play the timeline; view {}/out1.'.format(component.path, component.path))
    print('Choose Media > Movie File or Source TOP, or leave both blank for no media input.')
    print('Explore Media > Mask Mode and Injection Rate, then Appearance > Source Overlay.')
    return component


# =============================================================================
# 9. Embedded help
# =============================================================================

NETWORK_HELP = '''TURING MEDIA V2 / PHASE 8 — DIAGNOSTICS AND VALIDATION

QUICK START
Paste the entire builder into a Text DAT and Run Script. Play the timeline.
Each run creates a uniquely named turing_media_v2 component. No external
packages, shader files, or TDAPI component are required. Save as a TOX to reuse.
Leave Media > Movie File and Source TOP blank for ambient patterns, or assign
media. Source TOP overrides Movie File. Use Simulation > Pause and Step to inspect.

PARAMETER PAGES
Simulation: canvas, chemistry, seeds and clock controls.
Media: source, playback, fitting, influence and masks.
Motion: global transform, velocity flow and domain confinement.
Appearance: display, output view, palettes and carried color.
Presets: preset management and Feed/Kill explorer settings.
State: resets, resize behavior, memory snapshots and disk persistence.
Advanced: history/performance controls and shader diagnostics.
Separators divide the original sections. Parameter names, values, bindings,
preset data and snapshot formats are unchanged by this layout.

DIAGNOSTICS / SUPPORTED BUILD
View status_panel as a panel for canvas/grid dimensions, Clock Mode and Pause,
total/last-frame ticks, numerical substeps, simulation age/lag, source validity,
shader health, unsupported build settings and runtime failures. The status DAT
contains the same fields without truncation. shader_diagnostics contains full
compiler logs with operator names. Diagnostic observations never advance state.
Existing compiler/error data refresh twice a wall-clock second, even when paused;
status rows update each frame. With the timeline stopped, use Advanced >
Check Shaders / Refresh. This pulse demands all shaders (including the optional
explorer) but does not commit a tick or history sample. Initial construction also
checks all shaders. An unchecked shader is reported separately from success.
Missing required parameters and unsupported menu values raise a named error in
Textport and remain in Build issues; the partially built component is retained.
A clock exception disables its Execute DAT and records Runtime: Clock stopped.
Fix the reported operator/settings, Reset All, then enable clock > Active.
Known live-supported build: TouchDesigner 2025.33230 on macOS. The panel reports
the actual build; other builds remain unvalidated. Source validity reports the
active TOP or movie; an unassigned source is valid ambient operation. An unresolved
TOP reference is reported even when the rendering fallback is transparent.

SIMULATION / CLOCK UNITS
One tick is 1/60 simulation second. Speed 1 advances one simulation second per
elapsed second. The reference is V1 at 60 FPS: 16 chemistry updates with dt=1
per tick (960 chemistry time units per simulation second).
Real Time uses monotonic wall time. Max Catch-up Ticks / Frame bounds the work
per output frame. Unprocessed time is retained as Simulation Lag, not dropped.
A sustained overload increases lag: lower resolution/Speed or increase Cell Size.
Frame Stepped advances Speed / Render FPS simulation seconds per output frame.
It executes ALL required ticks, regardless of the catch-up limit or wall time.
Fractional ticks accumulate; 120 FPS at Speed 1 alternates zero and one tick.
Solver Quality 1..4 uses 16*quality substeps per tick, with chemistry dt=1/quality
(always <=1). Quality changes numerical accuracy and cost, not elapsed time.
Nonlinear patterns can differ with numerical accuracy, especially at long ages.
Pause freezes chemistry, carried color, palette history, and sampled motion
history. Live source previews/overlay can still change; media playback has its
own controls. Speed zero also freezes state and holds existing time debt.
Step advances exactly one 1/60-second tick while paused, even at Speed zero.
Step does nothing while running. It leaves Pause on and preserves time debt.
Pause/resume rebases wall time, so paused time is never caught up. Changing
Clock Mode clears fractional time and catch-up debt, preserving state/age.
Reset All restores seed, colorless state and initial palette/media samples, resets
age/debt, restarts the movie and preserves Pause. Reset Chemistry keeps color
and palette/media history. Startup/load reinitializes GPU history; a saved
in-memory or disk snapshot can then restore it.
Simulation Time, Simulation Lag, Ticks Last Frame, and Substeps / Tick are
read-only diagnostics. Viewer recooks do not advance the clock.

SOURCE SAMPLING / DETERMINISM
Each tick samples the available prepared source, then computes the influence
mask against the previous tick sample. It runs solver substeps, transforms
state once at the end of the tick, and commits state and palette history.
Several ticks in one output frame reuse the available live/movie source unless
an offline caller supplies per-tick samples. Equal ticks/settings/source samples
produce the same results at 30 and 60 output FPS (tolerance 1e-6 in validation).
A live camera or ordinarily playing movie sampled at different output FPS can
supply DIFFERENT samples. Frame Stepped does not resample or seek movies. State
snapshots restore movie position and both sampled media/palette histories; equal
subsequent movie frames/tick samples reproduce evolution. Sequential playback
still depends on output timing and decoder scheduling. For controlled offline input, the
clock DAT exposes advance(component, sample=callback); callback receives
(component, tick_index, simulation_seconds) before each tick's source capture.
Motion measures alpha and alpha-weighted luminance changes per tick, not optical
flow. Changes <=1e-6 are treated as floating-point noise. It settles to zero on
the next unchanged tick; while paused history holds. Source changes invalidate
both samples immediately and suppress the first new tick difference.
Changing source TOP dimensions also invalidates the history. Both media_a/b
Cache TOPs have Active, Cache Once and Always Cook disabled, cache size one,
and RGBA32F format. Only explicit replacement advances them. Ordinary recooks
and diagnostic refreshes retain both samples; Reset All, Restart Media, source
changes and canvas resizing invalidate them. Snapshot restore reinstates both
samples/readiness instead. A stopped source settles on the next sampled tick;
Pause holds the last tick mask until Step/resume or explicit invalidation.

SIMULATION / CANVAS AND CHEMISTRY
Feed/Kill and Diffusion A/B control chemistry. Ambient Seeds adds ten initial
patches. Editing Seed, Seed Radius or Ambient Seeds takes effect on the next
explicit reset. Source changes keep chemistry by default and invalidate motion
history. Dimension edits follow State > Resize Behavior. Simulation > Reset is a
Reset All alias. Reseed increments the seed and resets chemistry once, keeping
carried color. Restart Media cues the movie and retains chemistry/age/color. The former Coral/Dividing Spots pulses are now presets (Presets page).
Resolution controls a square canvas; Rectangular Canvas enables Width/Height.
Cell Size divides the canvas dimensions for a coarser simulation, upscaled by
Appearance > Upscale Filter. Larger cells make thicker lines and lower GPU cost.
Seed Radius, Edge Width, Mask Smoothing, Tint Spread and Translate use cells.

MEDIA PAGE
Movie File supports clips and image sequences; Source TOP supports generators,
cameras, renders, etc. Do not reference this component's own output (cook loop).
Play Media/Media Speed/Restart Media affect only the movie. Reset on Source
Change is off by default. Turn it on to reset chemistry/color/age and sampled
histories when Movie File or Source TOP changes (without rewinding the movie). Override FPS and
Sequence FPS are for image sequences. Scale, Offset X/Y and Rotation position
the media while preserving its aspect. Offsets are fractions of canvas size.
Prepared media is straight RGBA. Source Premultiplied unpremultiplies incoming
RGB when required; movie input premultiplication is off. Ignore Source Alpha
makes the fitted media rectangle opaque; transparent padding stays transparent.

MEDIA / INFLUENCE
Mask Mode: Silhouette=alpha, Bright/Dark Texture=alpha*brightness/darkness,
Silhouette Edges=outline, Texture Edges=internal detail, Motion=tick difference.
Mask Gain, Edge Width, Mask Smoothing and Motion Gain shape the mask.
Continuous Seed: Injection Rate blends toward A=.5/B=.25 once per tick; Recovery Rate blends
toward A=1/B=0. Rates are inverse simulation seconds, with exponential blending:
amount = 1-exp(-rate*mask*elapsed_seconds); recovery uses mask=1.
Zero disables a rate. Default injection is about 5/second; try 2..10.
Recovery is zero by default; try .06..3. Weak influence may not ignite patterns.
Seed From Clip Only disables ambient seeds, selects Silhouette, sets injection
to 600/second and recovery to zero, then resets. Reduce injection afterward for
weaker continuous influence. It selects Continuous Seed explicitly.
Stamp Once disables automatic concentration injection. Press Stamp Current Mask
for one exact blend toward A=.5/B=.25, using Stamp Amount * current live mask.
It works paused, does not advance simulation time or sampled media/palette history,
and leaves signed carried color unchanged. Repeated presses deliberately re-stamp.
Reset does not stamp; selecting Stamp Once does not stamp. Resume or Step to let
chemistry evolve independently. Injection Rate is unused in this mode.
Chemistry Map disables concentration injection. The selected mask value m maps
feed=lerp(Feed Minimum, Feed Maximum, m) and kill likewise. Local rates blend
from uniform Turing Feed/Kill by Chemistry Map Blend * prepared source alpha.
Transparent regions/no media retain uniform rates. Blend=0 restores the baseline.
Ranges may descend for reversed maps. Recovery and color injection remain
independent in ALL three modes. Mode/range/domain changes preserve age and state;
new settings apply on the next tick (or explicit stamp).

MOTION / DOMAIN
Domain Mask TOP is independent of Source TOP and works with every influence mode.
Blank means the whole canvas. Red is sampled nearest in normalized canvas UV
at simulation-cell centers, optionally inverted, then thresholded: value >=
Domain Threshold is open. Alpha is ignored; use RGB for an opaque grayscale mask.
The TOP fills the canvas without media fitting/transforms. A coarse grid can
miss sub-cell features: make walls at least one simulation cell thick.
Blocked cells always hold A=1/B=0/colorless. No Flux substitutes the center cell
for blocked stencil neighbors, blocking chemical/color diffusion. Empty Exterior
substitutes A=1/B=0/colorless and acts as a chemical sink at the interface.
Diagonal taps also require both orthogonal cells open to prevent corner leakage.
Ambient seeds/reset, injection, stamps and transforms all respect the domain.
Transforms trace each bilinear tap through crossed cells, including wrap seams,
and reject paths through blocked cells. No Flux retains the destination state;
Empty Exterior restores it empty. Paths longer than 1024 cell crossings per
one tick are conservatively rejected. Transport near walls can retain/erase
cells instead of smoothly sliding along the wall. Domain changes during Pause
are pending until Step/resume/Stamp/Reset; they never silently evolve state.
Domain confinement controls raw state, not output opacity. Display reconstruction
can soften a boundary on coarse grids; Clip Patterns to Alpha remains display-only.
Canvas Boundary is on the Simulation page and applies independently of Domain Boundary.
Wrap repeats the domain mask across seams; both closed modes hold its edge values.
Canvas Empty Exterior always supplies empty state outside the canvas, even when
Domain Boundary is No Flux. Walls inside the canvas retain their own policy.

PRESETS PAGE
Presets live in the 'presets' Text DAT as a versioned JSON table (schema
turing_media_v2.presets, version 1), saved with the TOE/TOX. Each preset holds
a name, description and COMPLETE settings grouped as chemistry, seed,
dimensions, timing, media fitting, influence, domain, transform, flow, display and
color (including Resize Behavior and Reset on Source Change). Pause, diagnostics,
snapshot file/status and the Presets/Explorer controls are not preset data.
Built-in presets (read-only) are rebuilt from defaults on every build:
Coral, Dividing Spots, Worms, Holes, Clip Seed, Stamp and Evolve, Chemistry Map,
Color Swirl, Wide Coarse. User presets are marked (user) in the menu.
Apply Preset (keep state) sets every parameter in ONE batch and does not reset:
chemical state, carried color, age and palette/media history continue. Seed
settings are stored but take effect at the next reset. If effective canvas or
simulation dimensions change, Resize Behavior selects one reset or resampling
with age/color preserved. The policy IN THE PRESET applies; built-ins use Reset.
Apply Preset + Reset sets everything, then resets exactly once.
Source bindings invalidate motion history and follow Reset on Source Change.
Multiple size/source changes in one preset batch trigger at most one reset.
Save Current Preset stores all current values under Save As Name (blank picks
'User Preset N'); the same name replaces that user preset. Built-in names are
refused. Delete User Preset removes the selected user preset.
Include Media/TOP Bindings: when on, Save stores Movie File, Source TOP, Domain
Mask TOP and Ramp TOP paths (typed relative paths are kept) and Apply restores
them. When off (default), bindings are neither saved nor applied, so presets
stay portable between projects.
Export Presets writes the whole table to Preset File (relative paths resolve
from the project folder). Import Presets reads a file: Merge adds and replaces
same-named user presets; Replace User Presets first removes all user presets.
Imported copies of built-ins are skipped; a user preset named like a built-in
is renamed '<name> (imported)'. Files with a newer schema version, invalid JSON,
duplicate names or non-finite values are refused without changing anything.
Unknown settings (e.g. from a newer build) are kept in the table and reported
as unknown when applied; missing settings keep their current values and are
reported. Menu values not offered by this build are reported as invalid.
Parameters driven by an expression are set to constant; exported parameters
are left alone and reported as blocked. Status shows the last result.
Seed From Clip Only (Media page) is a partial preset with one reset.

STATE PAGE / RESETS AND SNAPSHOTS
Reset Chemistry applies the current seed to A/B and resets simulation age/debt;
keeps signed carried color, palette history, motion samples and movie position.
Clear Carried Color zeros blue/alpha (signed Oklab a/b); chemical
A/B (red/green), simulation age, palette and media position remain unchanged.
Restart Media (Media page) cues the movie, invalidates motion history and retains
chemistry, carried color, palette and age. Reset All combines seed, color clear,
movie restart and initial palette/media histories, resetting age/debt once.
Every operation retains Pause. Simulation > Reset is the Reset All alias; Reseed
increments Seed and invokes Reset Chemistry once. Apply Preset + Reset retains
movie position while clearing chemistry/color/age/histories, as in Phase 4.

Save State (memory) saves one snapshot in component storage; Restore State reuses
it without consuming it. Saves are independent of Pause. Snapshots include all
six float32 ping-pong textures, active readers, dimensions, tick count and clock
debt, all 78 preset settings, five media/TOP bindings, Pause, motion readiness,
palette readiness, movie position/mode/index and schema version. Settings restore
as constants; exported settings are refused before anything changes. Presets and
explorer thumbnails are not part of the evolving simulation snapshot.

State File (.tstate) uses ZIP with versioned JSON metadata and six little-endian
raw float32 RGBA payloads, rows bottom to top. No image/color conversion, alpha
premultiplication, quantization, image codec or pickle is used. State alpha is
signed chroma DATA, not opacity. Each payload includes dimensions and SHA-256.
Save State to Disk captures the CURRENT state, checks the disk round trip and
atomically replaces the destination. Restore State from Disk validates schema,
settings, dimensions, sizes, hashes and finite values before applying, then also
keeps that snapshot in memory. Relative paths resolve from the project folder.
Save/restore may block while downloading/uploading GPU textures. Saving memory
also requires CPU memory for all six arrays. Snapshots survive subsequent ticks,
pauses, resets and resizes; a restored snapshot uses its original dimensions.

Movie sources restore their position and sampled histories. For exact future
playback, provide the same subsequent movie frames/source samples per tick:
Specify Index movie playback can be driven by an offline sample callback.
Sequential movies still depend on output timing/decoder scheduling. External
live TOPs/cameras cannot rewind; their chemistry restores exactly, while live
preview/overlay and subsequent source samples can differ. Bindings reference
external media files/operators: snapshots do not embed their assets. Rebuilding
or changing external shader/texture processing also changes future playback.
After TOE/TOX load GPU buffers initialize afresh; Restore State recovers a saved
memory snapshot, or Restore State from Disk recovers a .tstate snapshot.

Resize Behavior: Reset (default) initializes chemistry/color/histories and age
once when effective canvas or grid dimensions change. Resample State retains
age/debt, color and palette, explicitly interpolates all raw state channels at
normalized pixel centers with clamped edges, and respects the new domain mask.
Motion samples invalidate when dimensions change. Every requested dimension
change commits through the clock; both state buffers have the new grid before
the next solver tick. Hidden Width/Height edits in square mode have no effect.
Resampling preserves continuity but changes the discrete simulation and may
alter future behavior. Large cell/canvas changes can smooth away small features.
No resampling is needed when dimensions are unchanged.

EXPLORER PAGE / FEED-KILL PANEL
fk_explorer is a Container COMP panel (768x512). Open it as a viewer or panel.
Left: the Feed/Kill plane (kill along X, feed along Y, faint grid every 0.01)
with colored rings at curated examples, a crosshair at the current Feed/Kill,
and the saddle-node line k = sqrt(F)/2 - F (uniform reacted states exist left
of it). Right: eight reference thumbnails, first at top-left, borders matching
the ring colors; the selected example gets a white border.
Click or drag on the map to set Feed/Kill (rounded to 5 decimals); click a
thumbnail to choose that example exactly. This never resets, unless Reset
When Choosing Example is on. Panel Click Sets Feed/Kill disables input.
Map Feed/Kill Minimum/Maximum set the plotted range.
Generate Thumbnails simulates all examples together in a 256x512 atlas of
independently wrapping 128-cell tiles: one fixed seed layout (Thumbnail Seed),
radius 5 cells, the reference solver (dt=1, diffusion 1/.5, 16 updates/tick),
for Thumbnail Age seconds (default 10 = 600 ticks), spread across frames.
They are REFERENCE OUTCOMES only: other seeds, ages, sizes, diffusion, media
and domains can produce different patterns. fk_examples lists their names
and values; Status records seed and age. Thumbnails do not touch the main state.
Network: fk_seed -> fk_a/fk_b (explicit ping-pong) -> fk_read -> fk_sim;
fk_read -> fk_panel -> fk_explorer background. explorer: Execute DAT that polls
panel input each frame and generates thumbnails.

APPEARANCE / COLOR AND DISPLAY
All four color modes remain: Fixed Palette, Source Tint, Clip Palette, Carried
Color. Ramp TOP optionally replaces the teal/gold ramp (horizontal middle row).
Tint Spread blurs source color. Clip Palette sorts averaged 8x8 cells into a
64-step ramp; cells below 25% alpha coverage are ignored. Palette Smoothing is
a time constant in simulation seconds: 0=instant, default ~.158 seconds.
History retention per update is exp(-elapsed_ticks/60 / smoothing_seconds).
Palette Anchoring borrows base-ramp lightness. Color Amount, Contrast and
Invert affect display; changing color mode never resets simulation.
Carried Color stores signed Oklab a/b in state blue/alpha. Color Spread Rate
mixes toward B-weighted neighbors each substep by 1-exp(-rate*substep_seconds).
Carried Color Source selects Source Alpha (default) or the Influence Mask.
Color Injection Rate independently blends toward source chroma using that value
in the exponent, in every influence mode; Color Decay Rate fades toward gray by exp(-rate*tick_seconds).
Default spread ~665.42/second, injection ~3.08/second, decay 0. Saturation only
affects display. Maintain Carried Color defaults on in every color mode.
Source Overlay adds live media over patterns. Clip Patterns to Alpha clips
display only; it does not confine simulation. Output is premultiplied RGBA.
Output View selects final/patterns/mask/source-on-checkerboard. Upscale Filter
selects cubic, linear or nearest reconstruction for coarse simulations.

ADVANCED / PERFORMANCE
Maintain Carried Color (default on) enables injection, neighbor spreading and
color decay. Turn off when carried color is unnecessary: A/B evolution is
unchanged, and existing signed chroma is retained. Global/velocity transport
still moves all state channels. Clear Carried Color is the explicit erase action.
Re-enabling resumes from retained chroma; there is no retroactive media history.
Continuous Palette History defaults off. Clip Palette requests extraction;
other modes hold the last clip ramp. A custom Ramp TOP refreshes the base row
without sampling/sorting media unless clip extraction is also required.
Enable continuous history to keep a warmed clip ramp across color-mode changes.
Palette Update Interval is an integer number of simulation ticks (1..600, default
1); it is independent of output FPS and Solver Quality. The first needed update
initializes immediately. Smoothing uses elapsed simulation time since the last
update. Larger intervals intentionally sample fewer media frames and hold colors
between updates; switching modes takes effect on the next tick. Pause freezes
palette updates. Reset initializes the fixed fallback ramp and any required
clip/base ramp; Reset Chemistry rebases cadence while keeping palette values.
Snapshots save the cadence offset and all three performance settings. Complete
older snapshots restore carried and continuous palette history on, interval 1.
Partially missing new performance settings are refused. Older presets leave
missing performance controls at their current values, following the preset contract.

When grid and canvas match, display and simulation source reads bypass resampling.
Coarse masks/injection use simulation-size alpha-weighted box filtering from
full-resolution prepared media: exact integer boxes up to 4 cells per axis,
otherwise bounded 4x4 quadrature with premultiplication BEFORE bilinear filtering.
Edge Width and Smoothing remain simulation-cell units. This bounded low-pass
filter can change coarse media influence and removes sub-cell detail; increase
grid resolution for fine silhouettes. Domain walls retain nearest hard-threshold
sampling independently. Motion history and Source Preview stay full-resolution.
Mask Preview reconstructs the simulation mask to canvas size with linear filtering.
Single-channel masks and two-channel influence retain float32; binary domains
use mono8; the colorized visual intermediate uses RGBA16F. Final compositing,
sources, palette histories and all signed chemical state remain RGBA32F.
Half-float chemical simulation was tested separately for 3600 ticks in coral and
spots and failed pointwise fidelity; it is not a supported simulation mode.
Profiling results, methods and limits: validation/phase7/README.md.

MOTION / TRANSFORM
Enable Transform to move chemical and color state after every tick's solver.
Grow and Scale X/Y are continuous percent rates per simulation second:
scale = exp((grow + axis_scale)*.01*tick_seconds). Positive values expand.
Translate X/Y uses cells/second; Rotate uses degrees/second. Pivot X/Y is UV.
Motion stays undistorted on rectangular grids. Default Grow ~6 and Rotate 6
reproduce the old .1% and .1 degree/frame at 60 FPS. Try Grow 6..30, Rotate 6..60.
Zero Motion clears global rates without resetting. Bilinear transport smooths
sub-cell features; exact zero motion bypasses resampling.

TURING > BOUNDARY
Wrap connects opposite edges for diffusion and state transport.
No Flux holds the nearest edge cell for exterior samples: no chemical/color
diffusion across the canvas boundary, and backtraces hold edge values.
Empty Exterior supplies A=1/B=0/colorless for exterior stencil and transport taps.
This acts as a sink; shrink/translation can refill the exposed area with empty state.
All modes use explicit integer addressing and transport interpolates all raw channels.
Display cubic/linear reconstruction wraps only in Wrap; BOTH closed modes hold
edge values so coarse reconstruction cannot connect opposite edges or add a visual
empty border. Resizing remains normalized bilinear with held edges, independently.
The legacy parameter name Transformedge and token 'clear' remain portable. Old
Clear presets now mean consistent Empty Exterior, including diffusion; choose
No Flux to retain the old clamped diffusion behavior. Wrap is unchanged.

MOTION / VELOCITY FLOW
Enable Velocity and assign Velocity TOP. Blank/disabled/Strength=0 means no flow.
Red = signed X velocity, green = signed Y velocity in simulation cells/second;
positive X goes right, positive Y goes up (bottom-left UV origin). Zero RG is still.
Blue/alpha are ignored; use a floating-point TOP for negative values. No 0.5 bias,
color conversion, premultiplication or media fitting is applied. Different TOP sizes
fill normalized canvas UV, with explicit bilinear interpolation at cell centers.
Wrap repeats the velocity input; closed modes hold its edges. Nonfinite channels
become zero; finite channels clamp to +/-1,000,000 cells/second before interpolation.
Strength multiplies velocity. Each fixed tick backtraces destination velocity *
Strength * tick_seconds, clamping vector length to Max Displacement (default 8
cells/tick, maximum 64; zero disables displacement). This limit slows oversized
inputs instead of dropping ticks or skipping barriers. At Cell Size > 1 units
still mean simulation cells, not output pixels. Solver Quality does not change flow.
Forward order is global scale/rotate/translate, then flow. Velocity is sampled
once per tick at destination centers; the inverse global transform follows local
backtracing. This is first-order semi-Lagrangian transport, not a fluid solver.
Bilinear transport smooths small features and is not mass conserving; repeated
fractional motion can blur patterns. Domain supercover traversal tests every
nonzero tap and rejects wall crossings, including wrap seams and diagonal corners.
Pause freezes flow; Step moves one tick. Zero velocity reproduces the ordinary
path exactly. Presets capture flow settings; Velocity TOP is an optional binding.
Snapshots save settings/binding, not external field contents or its producer history.
Replay requires the same velocity samples at each tick, as with live media. Phase 5
snapshots restore with flow disabled; partially missing new flow metadata is refused.

MIGRATION FROM V1 / PHASE 1
Passes, Timestep and Running are replaced by Clock controls. At 60 FPS, old
speed passes*timestep/16 corresponds to Speed; Solver Quality is independent.
Convert an old per-frame blend p to rate=-60*ln(1-p). Color Spread used per-pass
p: rate=-960*ln(1-p). A rate of 600 approximates old full injection; finite rates
approach the target exponentially. Partial alpha/mask now scales rate inside
the exponent, so intermediate masks may differ from V1 at the reference FPS.
Convert old palette retention s to smoothing_seconds=-1/(60*ln(s)); s=0 is instant.
Translation/rotation: multiply old per-frame rates by 60. Grow/scale percentage
p: continuous_percent_per_second=6000*ln(1+p/100).
Default no-media chemistry remains the 16-update dt=1 reference. Phase 1 reports
are historical baseline evidence; Phase 2 intentionally changes controls/network.
Phase 4: Turing > Coral / Dividing Spots pulses became the Coral and Dividing
Spots presets; select them on Presets and use Apply Preset + Reset for the old
behavior (they now also restore every other setting to its default).

NETWORK / OUTPUTS
state_a/b, palette_a/b, media_a/b are RGBA32F GPU Cache TOPs. Automatic capture
is disabled. The clock explicitly replaces the inactive buffer and switches
the reader only after completing the tick. Repeated Feedback TOP cooks are not
used. Ordinary ticks stay on the GPU. Manual snapshots and resampling download/
upload raw arrays through NumPy bundled with TouchDesigner; no pip install or
external package/shader file is required. These operations can stall the GPU.
snapshot_lib: raw snapshot/restore and verified disk persistence; state_upload:
Script TOP staging texture; state_resize: explicit raw bilinear resampler.
clock: Execute DAT scheduler and callable reset/step/advance API. Each reset
increments the stored diagnostic counter Resetcount (component.fetch).
preset_lib: preset module (apply/capture/import/export); presets: JSON table.
state_read -> reaction_diffusion -> state_transform -> inactive state buffer.
media_prepared -> inactive full-size media buffer -> simulation source/previous -> mask.
media_cache -> optional palette_cells -> palette_sort -> inactive palette buffer.
Palette reader parity is independent of the state reader and updates on cadence.
out1=final display; patterns=colored simulation before overlay/clipping;
mask_preview=last tick mask; source_preview=live fitted straight RGBA;
palette=64x2 (clip ramp row 0, base ramp row 1); state=raw A/B + signed Oklab a/b.
State alpha is DATA, not opacity. Do not premultiply or color-convert it.
Each shader has a compiler Info DAT. The unselected blank movie may report an
empty-file diagnostic; the transparent fallback is used until media is assigned.
VALIDATED WORKFLOWS
validation/phase8 documents the reproducible offline and live runners. The suite
checks empty-field stability, finite bounded A/B, Pause/Step, stamp/continuous
influence, canvas/domain boundaries, signed snapshot restoration, resize safety,
fractional-alpha and premultiplied output, preset serialization and controlled
30/60-FPS replay. It also injects and repairs a shader error to verify diagnostics,
checks unsupported parameter reporting and tests motion stop/invalidation over
real timeline frames. Each report includes the final builder SHA-256 and build.
Earlier phases retain historical evidence and detailed contracts in phase2..7.
Live-supported build: TouchDesigner 2025.33230 on macOS.
'''


# =============================================================================
# Text DAT entry point
# =============================================================================

# A Text DAT's Run Script action executes this top-level call.
try:
    _script_dat = me
except NameError:
    print('Paste this file into a TouchDesigner Text DAT and choose Run Script.')
else:
    turing_component = build_turing_media_v2()
