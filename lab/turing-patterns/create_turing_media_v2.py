"""Build the V2 fixed-clock media-driven reaction-diffusion network in TouchDesigner.

USE
  1. Paste this entire file into a Text DAT in your project.
  2. Right-click the DAT and choose Run Script.
  3. Play the timeline: ambient seed patterns grow immediately (no media).
  4. Select turing_media_v2. On Media, choose Movie File to load your own clip,
     or drag any TOP into Source TOP to drive it live (camera, generator, etc.).
  5. Explore Influence > Mask Mode, Strength, and Display > Source Overlay.
  6. On Color, switch Color Mode to tint, extract or carry the clip's colors.
     Assign Color > Ramp TOP to replace the built-in teal/gold ramp with your own.

Phase 3 adds independent media modes, domain confinement and carried-color sourcing.
Phase 2 provides the fixed simulation clock and explicit GPU state storage. No external Python packages or shader files.
Re-running creates turing_media_v2, turing_media_v2_2, and so on; existing operators are retained.
Outputs: out1 = final image, patterns = colored simulation, mask_preview =
influence mask, source_preview = fitted RGBA source, palette = clip color
ramp, state = raw A/B concentrations plus carried color.
Clear Source TOP and Movie File to remove the media influence. No external dependencies.

Default: 512 square, RGBA32F state, 60 ticks/second, 16 solver updates/tick.
Turn on Turing > Rectangular Canvas for an independent Width and Height.
Turing > Cell Size runs the simulation on a coarser grid (canvas / Cell Size)
and upscales it for display: larger cells give thicker lines at any canvas size.
Clock > Speed controls elapsed simulation time; Solver Quality controls accuracy.
Save the .toe or save this component as a .tox to keep the generated network.

References:
  https://www.karlsims.com/rd.html
  https://derivative.ca/UserGuide/GLSL_TOP
  https://derivative.ca/UserGuide/Feedback_TOP

Phase 1 baseline results are in validation/phase1. Phase 2 clock validation and
reproduction instructions are in validation/phase2. The builder is standalone;
validation files and TDAPI are not required. Phase 3 validation is in
validation/phase3. Phases 4–8 are not implemented.
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
CANVAS_WIDTH = 'parent().par.Canvaswidth if parent().par.Rectangle else parent().par.Resolution'
CANVAS_HEIGHT = 'parent().par.Canvasheight if parent().par.Rectangle else parent().par.Resolution'
CANVAS_ASPECT = ('parent().par.Canvaswidth / max(1, parent().par.Canvasheight) '
                 'if parent().par.Rectangle else 1')

# Media input: an assigned Source TOP wins over Movie File; neither means no media.
HAS_SOURCE_TOP = 'parent().par.Sourcetop.eval() is not None'
HAS_MOVIE = 'parent().par.Moviefile.eval().strip()'
HAS_MEDIA = '({} or {})'.format(HAS_SOURCE_TOP, HAS_MOVIE)
HAS_DOMAIN = 'parent().par.Domaintop.eval() is not None'

# The simulation grid: the canvas divided by Cell Size, so each cell spans several pixels.
SIM_WIDTH = 'max(8, int(round(({}) / parent().par.Cellsize)))'.format(CANVAS_WIDTH)
SIM_HEIGHT = 'max(8, int(round(({}) / parent().par.Cellsize)))'.format(CANVAS_HEIGHT)


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


# Shared by solver, stamp, seed and transport. Domain textures are binary and
# match the simulation grid; Wrap repeats the mask, Clear blocks exterior cells.
def _domain_glsl(input_index, channel="r"):
    return r"""
uniform vec4 uDomain; // enabled, boundary (no flux / empty exterior), unused, unused
const vec4 EMPTY_CELL = vec4(1.0, 0.0, 0.0, 0.0);
bool domainOpen(ivec2 p, ivec2 size, bool clearEdges) {
    if (uDomain.x < 0.5) return true;
    bool outside = any(lessThan(p, ivec2(0))) || any(greaterThanEqual(p, size));
    if (clearEdges && outside) return false;
    p = (p % size + size) % size;
    return texelFetch(sTD2DInputs[DOMAIN_INPUT], p, 0).DOMAIN_CHANNEL > 0.5;
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
    if (!domainOpen(ivec2(gl_FragCoord.xy), ivec2(uSeedSize.xy), true)) {
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
uniform vec4 uStep;  // chemistry dt, substep seconds, edge mode (wrap, clear), tick seconds
uniform vec4 uInfluence; // injection and recovery rates / simulation second
uniform vec4 uDye; // spread, injection, decay rates / simulation second, source (alpha/mask)
uniform vec4 uInfluenceMode; // continuous/stamp/chemistry, chemistry blend, unused, unused
uniform vec4 uChemistry; // feed min/max, kill min/max
""" + _domain_glsl(1, "g") + OKLAB_GLSL + r"""
const ivec2 OFFSETS[8] = ivec2[8](ivec2(-1, 0), ivec2(1, 0), ivec2(0, -1), ivec2(0, 1),
                                  ivec2(-1, -1), ivec2(1, -1), ivec2(-1, 1), ivec2(1, 1));
const float WEIGHTS[8] = float[8](0.2, 0.2, 0.2, 0.2, 0.05, 0.05, 0.05, 0.05);

// Integer addressing makes the nine-cell stencil exact. Wrap both axes, or in
// Clear mode clamp to the edge (zero flux) so opposite edges never interact.
// R = A, G = B, B/A = carried colour as Oklab a/b.
vec4 readCell(ivec2 p) {
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    p = (uStep.z > 0.5) ? clamp(p, ivec2(0), size - 1) : (p % size + size) % size;
    return texelFetch(sTD2DInputs[0], p, 0);
}

// Colour is weighted by chemical B, so it flows outward with growing pattern.
vec3 dyeSample(vec4 cell, float weight) {
    float w = weight * (cell.g + 0.001);
    return vec3(cell.ba * w, w);
}

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    if (!domainOpen(p, size, uStep.z > 0.5)) {
        fragColor = TDOutputSwizzle(EMPTY_CELL);
        return;
    }
    vec4 cell = readCell(p);
    vec2 ab = cell.rg;

    // Neighbor differences preserve a uniform field exactly (no weight-sum drift).
    vec2 lap = vec2(0.0);
    vec3 dye = dyeSample(cell, 1.0);
    for (int i = 0; i < 8; ++i) {
        ivec2 offset = OFFSETS[i];
        bool open = domainOpen(p + offset, size, uStep.z > 0.5);
        // Diagonal taps cannot cut across blocked orthogonal cells at corners.
        if (offset.x != 0 && offset.y != 0) {
            open = open && domainOpen(p + ivec2(offset.x, 0), size, uStep.z > 0.5)
                        && domainOpen(p + ivec2(0, offset.y), size, uStep.z > 0.5);
        }
        vec4 neighbor = open ? readCell(p + offset) : domainBoundary(cell);
        lap += WEIGHTS[i] * (neighbor.rg - ab);
        dye += dyeSample(neighbor, WEIGHTS[i]);
    }
    vec2 chroma = mix(cell.ba, dye.xy / dye.z, 1.0 - exp(-uDye.x * uStep.y));

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
        float colorMask = uDye.w < 0.5 ? clamp(source.a, 0.0, 1.0) : maskValue;
        vec2 sourceChroma = linearToOklab(toLinear(source.rgb)).yz;
        chroma = mix(chroma, sourceChroma, 1.0 - exp(-uDye.y * colorMask * uStep.w));
        chroma *= exp(-uDye.z * uStep.w);
    }
    fragColor = TDOutputSwizzle(vec4(nextState, chroma));
}
"""


STAMP_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uStamp; // stamp amount, canvas edge mode, unused, unused
""" + _domain_glsl(2) + r"""
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    vec4 cell = texelFetch(sTD2DInputs[0], p, 0);
    if (!domainOpen(p, size, uStamp.y > 0.5)) cell = EMPTY_CELL;
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
uniform vec4 uWarpMode; // active, edge mode index, tick seconds, unused

""" + _domain_glsl(1) + r"""
// Manual bilinear over integer texels keeps torus edges exact and avoids
// relying on 32-bit float texture filtering. Clear mode refills from outside.
vec4 readCell(ivec2 p, ivec2 size, vec4 center) {
    if (!domainOpen(p, size, uWarpMode.y > 0.5)) return domainBoundary(center);
    bool outside = any(lessThan(p, ivec2(0))) || any(greaterThanEqual(p, size));
    if (uWarpMode.y > 0.5 && outside) return EMPTY_CELL;
    p = (p % size + size) % size;
    return texelFetch(sTD2DInputs[0], p, 0);
}

bool domainPath(ivec2 from, ivec2 to, ivec2 size) {
    ivec2 delta = to - from;
    ivec2 count = abs(delta), direction = ivec2(sign(vec2(delta)));
    if (count.x + count.y > 1024) return false;
    ivec2 at = from, moved = ivec2(0);
    for (int i = 0; i < 1024; ++i) {
        if (!domainOpen(at, size, uWarpMode.y > 0.5)) return false;
        if (at == to) return true;
        float tx = count.x == 0 ? 1e20 : (float(moved.x) + 0.5) / float(count.x);
        float ty = count.y == 0 ? 1e20 : (float(moved.y) + 0.5) / float(count.y);
        if (abs(tx - ty) < 1e-7) {
            if (!domainOpen(at + ivec2(direction.x, 0), size, uWarpMode.y > 0.5)
             || !domainOpen(at + ivec2(0, direction.y), size, uWarpMode.y > 0.5)) return false;
            at += direction;
            moved += ivec2(1);
        } else if (tx < ty) { at.x += direction.x; moved.x += 1; }
        else { at.y += direction.y; moved.y += 1; }
    }
    return domainOpen(at, size, uWarpMode.y > 0.5) && at == to;
}

void main() {
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    ivec2 p = ivec2(gl_FragCoord.xy);
    vec4 center = texelFetch(sTD2DInputs[0], p, 0);
    if (!domainOpen(p, size, uWarpMode.y > 0.5)) {
        fragColor = TDOutputSwizzle(EMPTY_CELL);
        return;
    }
    if (uWarpMode.x < 0.5) {
        fragColor = TDOutputSwizzle(center);
        return;
    }
    // Forward move at the end of each fixed tick: scale, rotate about the pivot, then translate.
    // Each output cell samples the inverse of that move from the previous state.
    vec2 pivot = uDrift.zw * vec2(size);
    vec2 q = gl_FragCoord.xy - pivot - uDrift.xy * uWarpMode.z;
    float c = cos(uWarp.w * uWarpMode.z), s = sin(uWarp.w * uWarpMode.z);
    q = vec2(c * q.x + s * q.y, -s * q.x + c * q.y);
    vec2 scale = exp((uWarp.x + uWarp.yz) * 0.01 * uWarpMode.z);
    vec2 source = pivot + q / max(scale, vec2(0.01)) - 0.5;
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
    return clamp(change * uMotion.x, 0.0, 1.0);
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
uniform vec4 uUpscale; // filter index (smooth, linear, nearest), edge mode index (wrap, clear), unused, unused
""" + OKLAB_GLSL + _base_palette_glsl(0.75) + r"""
// The state can be coarser than the output. Integer fetches with wrapping keep
// the torus seamless and avoid relying on 32-bit float texture filtering.
// Clear mode clamps instead, so edge pixels never blend in the opposite edge.
vec4 stateCell(ivec2 p, ivec2 size) {
    p = (uUpscale.y > 0.5) ? clamp(p, ivec2(0), size - 1) : (p % size + size) % size;
    return texelFetch(sTD2DInputs[0], p, 0);
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


# =============================================================================
# 6. Presets
# =============================================================================

# Legacy preset pulses adapted to the new timing units.
# A versioned preset table is deferred to phase 4.
PRESET_PULSE_HANDLERS = '''    elif par.name == 'Coral':
        component.par.Feed = 0.0545
        component.par.Kill = 0.062
        component.par.Diffusiona = 1.0
        component.par.Diffusionb = 0.5
        component.par.Speed = 1.0
        component.par.Solverquality = 1
        component.par.Seedradius = 9.0
    elif par.name == 'Spots':
        component.par.Feed = 0.0367
        component.par.Kill = 0.0649
        component.par.Diffusiona = 1.0
        component.par.Diffusionb = 0.5
        component.par.Speed = 1.0
        component.par.Solverquality = 1
        component.par.Seedradius = 5.0
    elif par.name == 'Clipseed':
        component.par.Ambient = False
        component.par.Influencemode = 'continuous'
        component.par.Maskmode = 'alpha'
        component.par.Strength = 600.0
        component.par.Fade = 0.0
'''


# =============================================================================
# 7. Callbacks
# =============================================================================

CONTROL_CALLBACKS = '''
def resetSimulation(component):
    component.op('clock').module.reset(component)
    return

def onPulse(par):
    component = par.owner
    if par.name == 'Stamp':
        component.op('clock').module.stamp(component)
        return
    if par.name == 'Step':
        component.op('clock').module.step(component)
        return
    if par.name == 'Reseed':
        component.par.Seed = component.par.Seed.eval() + 1
''' + PRESET_PULSE_HANDLERS + '''    elif par.name == 'Restartclip':
        component.op('movie').par.cuepulse.pulse()
    elif par.name == 'Transformzero':
        for name in ('Grow', 'Scalex', 'Scaley', 'Translatex', 'Translatey', 'Rotate'):
            component.par[name].val = 0.0
        return
    resetSimulation(component)
    return

def onValueChange(par, prev):
    if par.name in ('Pause', 'Clockmode', 'Speed'):
        par.owner.op('clock').module.rebase(par.owner, clear_debt=par.name == 'Clockmode')
        return
    if par.name in ('Resolution', 'Rectangle', 'Canvaswidth', 'Canvasheight', 'Cellsize',
                    'Seed', 'Seedradius', 'Ambient', 'Moviefile', 'Sourcetop'):
        resetSimulation(par.owner)
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
    target.inputConnectors[0].connect(source)
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


def reset(c):
    state = _clock(c)
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
    c.store('Paletteready', False)
    for name in ('palette_a', 'palette_b'):
        c.op(name).inputConnectors[0].connect(c.op('palette_init'))
        c.op(name).par.resetpulse.pulse()
        capture(c.op(name), c.op('palette_init'))
    c.op('palette_read').par.top = 'palette_a'
    c.op('palette_sort').cook(force=True)
    for name in ('palette_a', 'palette_b'):
        capture(c.op(name), c.op('palette_sort'))
    c.op('palette_read').par.top = 'palette_a'
    c.store('Paletteready', True)
    state.update(ticks=0, debt=0.0, buffer=0, media=0, ready=True,
                 last=time.perf_counter(), mode=c.par.Clockmode.eval(), frame=None)
    for name in ('state_read', 'palette_read', 'media_cache', 'media_previous',
                 'media_mask', 'mask_preview', 'state', 'palette'):
        c.op(name).cook(force=True)
    _status(c, 0)


def tick(c, sample=None):
    state = _clock(c)
    if not state['ready']:
        reset(c)
    # A controlled source can provide one sample per tick for offline replay.
    if sample is not None:
        sample(c, state['ticks'], state['ticks'] * TICK_SECONDS)
    media = 1 - state['media']
    capture(c.op(('media_a', 'media_b')[media]), c.op('media_prepared'))
    c.op('media_cache').par.top = ('media_a', 'media_b')[media]
    c.op('media_previous').par.top = ('media_a', 'media_b')[state['media']]
    c.op('media_cache').cook(force=True)
    c.op('media_previous').cook(force=True)
    c.op('media_mask').cook(force=True)
    c.op('mask_preview').cook(force=True)
    state['media'] = media

    c.op('domain_mask').cook(force=True)
    c.op('influence_field').cook(force=True)
    c.op('state_read').cook(force=True)
    c.op('reaction_diffusion').cook(force=True)
    dest = 1 - state['buffer']
    capture(c.op(('state_a', 'state_b')[dest]), c.op('state_transform'))

    c.op('palette_read').cook(force=True)
    c.op('palette_cells').cook(force=True)
    capture(c.op(('palette_a', 'palette_b')[dest]), c.op('palette_sort'))
    c.op('state_read').par.top = ('state_a', 'state_b')[dest]
    c.op('palette_read').par.top = ('palette_a', 'palette_b')[dest]
    state['buffer'] = dest
    state['ticks'] += 1


def stamp(c):
    """Apply the live mask once without advancing time, palette or motion history."""
    if c.par.Influencemode.eval() != 'stamp':
        return False
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
        advance(c)
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
    _number(page, 'Seed', 'Seed', 1, 0, 1000000, True)
    _number(page, 'Seedradius', 'Seed Radius (cells)', 9.0, 3.0, 32.0)
    _toggle(page, 'Ambient', 'Ambient Seeds', True)
    for name, label in (('Reset', 'Reset'), ('Reseed', 'Reseed'),
                        ('Coral', 'Coral Preset'), ('Spots', 'Dividing Spots Preset')):
        page.appendPulse(name, label=label)
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
    media_page.appendPulse('Restartclip', label='Restart Clip + Reset')
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
    _menu(transform_page, 'Transformedge', 'Edges', [
        ('wrap', 'Wrap'), ('clear', 'Clear'),
    ], 'wrap')
    transform_page.appendPulse('Transformzero', label='Zero Motion')

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

    # Manual sample history advances with ticks, including while single-stepping.
    for index, name in enumerate(('media_a', 'media_b')):
        _buffer(component, name, prepared, (-650, 1150 + index * 150))
    cache = _reader(component, 'media_cache', 'media_a', (-400, 650))
    previous = _reader(component, 'media_previous', 'media_b', (-150, 900))

    mask = _shader(component, 'media_mask', 'mask_pixel', MASK_SHADER, (100, 650))
    mask.inputConnectors[0].connect(cache)
    mask.inputConnectors[1].connect(previous)
    _set(mask, 'inputfiltertype', 'linear')
    _set(mask, 'inputextenduv', 'zero')
    _uniforms(mask, [
        # The mask is built at canvas size; widths are in cells, so convert to pixels.
        ('uMask', (_menu_index('Maskmode'), 'parent().par.Maskgain',
                   'parent().par.Edgewidth * parent().par.Cellsize',
                   'parent().par.Smoothing * parent().par.Cellsize')),
        ('uMotion', ('parent().par.Motiongain',
                     '1', '0', '0')),
    ])
    mask_preview = component.create(nullTOP, 'mask_preview')
    mask_preview.nodeX, mask_preview.nodeY = 350, 650
    mask_preview.inputConnectors[0].connect(mask)
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

    # GLSL TOP has three inputs: pack influence R and domain G into one field.
    field = _shader(component, 'influence_prepare', 'influence_pixel', INFLUENCE_FIELD_SHADER, (-450, -750))
    field.inputConnectors[0].connect(mask_preview)
    field.inputConnectors[1].connect(domain)
    _set(field, 'outputresolution', 'custom')
    _expression(field, 'resolutionw', SIM_WIDTH)
    _expression(field, 'resolutionh', SIM_HEIGHT)
    influence_field = component.create(nullTOP, 'influence_field')
    influence_field.nodeX, influence_field.nodeY = -200, -750
    influence_field.inputConnectors[0].connect(field)

    stamp_mask = _shader(component, 'stamp_mask', 'stamp_mask_pixel', MASK_SHADER, (600, 650))
    stamp_mask.inputConnectors[0].connect(prepared)
    stamp_mask.inputConnectors[1].connect(cache)
    _set(stamp_mask, 'inputfiltertype', 'linear')
    _set(stamp_mask, 'inputextenduv', 'zero')
    _uniforms(stamp_mask, [
        ('uMask', (_menu_index('Maskmode'), 'parent().par.Maskgain',
                   'parent().par.Edgewidth * parent().par.Cellsize',
                   'parent().par.Smoothing * parent().par.Cellsize')),
        ('uMotion', ('parent().par.Motiongain', '1', '0', '0')),
    ])

    seed = _shader(component, 'seed', 'seed_pixel', SEED_SHADER, (-600, 200))
    seed.inputConnectors[0].connect(domain)
    _set(seed, 'outputresolution', 'custom')
    # The seed sets the simulation grid; every state operator downstream follows it.
    _expression(seed, 'resolutionw', SIM_WIDTH)
    _expression(seed, 'resolutionh', SIM_HEIGHT)
    _uniforms(seed, [('uSeed', ('parent().par.Seed', 'parent().par.Seedradius',
                                '0', 'parent().par.Ambient')),
                     ('uSeedSize', (SIM_WIDTH, SIM_HEIGHT, '0', '0')), domain_uniform])

    # Explicit texture ping-pong; frame-based Feedback TOPs cannot advance here.
    for index, name in enumerate(('state_a', 'state_b')):
        _buffer(component, name, seed, (-850, -250 - index * 150))
    state_read = _reader(component, 'state_read', 'state_a', (-350, 200))

    simulation = _shader(component, 'reaction_diffusion', 'simulation_pixel',
                         SIMULATION_SHADER, (-100, 200))
    simulation.inputConnectors[0].connect(state_read)
    simulation.inputConnectors[1].connect(influence_field)
    simulation.inputConnectors[2].connect(cache)
    _expression(simulation, 'npasses', '16 * parent().par.Solverquality')
    _uniforms(simulation, [
        ('uRates', ('parent().par.Feed', 'parent().par.Kill',
                    'parent().par.Diffusiona', 'parent().par.Diffusionb')),
        ('uStep', ('1.0 / parent().par.Solverquality', '1.0 / (960.0 * parent().par.Solverquality)',
                   _menu_index('Transformedge'), repr(TICK_SECONDS))),
        ('uInfluence', ('parent().par.Strength', 'parent().par.Fade', '0', '0')),
        ('uDye', ('parent().par.Dyespread', 'parent().par.Dyeinject',
                  'parent().par.Dyedecay', _menu_index('Dyesource'))),
        ('uInfluenceMode', (_menu_index('Influencemode'), 'parent().par.Chemistryblend', '0', '0')),
        ('uChemistry', ('parent().par.Feedmin', 'parent().par.Feedmax',
                        'parent().par.Killmin', 'parent().par.Killmax')),
        domain_uniform,
    ])

    # Applied once at the tick boundary, after every numerical substep.
    transform = _shader(component, 'state_transform', 'transform_pixel',
                        TRANSFORM_SHADER, (150, 200))
    transform.inputConnectors[0].connect(simulation)
    transform.inputConnectors[1].connect(domain)
    _uniforms(transform, [
        ('uWarp', ('parent().par.Grow', 'parent().par.Scalex', 'parent().par.Scaley',
                   'parent().par.Rotate * 0.0174532925199433')),
        ('uDrift', ('parent().par.Translatex', 'parent().par.Translatey',
                    'parent().par.Pivotx', 'parent().par.Pivoty')),
        ('uWarpMode', ('parent().par.Transform',
                       _menu_index('Transformedge'), repr(TICK_SECONDS), '0')),
        domain_uniform,
    ])

    stamp_node = _shader(component, 'state_stamp', 'stamp_pixel', STAMP_SHADER, (150, -550))
    stamp_node.inputConnectors[0].connect(state_read)
    stamp_node.inputConnectors[1].connect(stamp_mask)
    stamp_node.inputConnectors[2].connect(domain)
    _uniforms(stamp_node, [
        ('uStamp', ('parent().par.Stampamount', _menu_index('Transformedge'), '0', '0')),
        domain_uniform,
    ])

    state = component.create(nullTOP, 'state')
    state.nodeX, state.nodeY = 150, 420
    state.inputConnectors[0].connect(state_read)
    _set(state, 'format', 'rgba32float')

    # Clip palette history uses the same explicit tick commits as chemical state.
    palette_uniforms = [('uPalette', (str(PALETTE_CELLS),
                                      'math.exp(-1.0 / (60.0 * parent().par.Palettesmooth)) if parent().par.Palettesmooth > 0 else 0',
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

    palette_init = component.create(constantTOP, 'palette_init')
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
    ramp_uniform = ('uRamp', ('1 if parent().par.Ramptop.eval() is not None else 0', '0', '0', '0'))

    palette_sort = _shader(component, 'palette_sort', 'palette_sort_pixel',
                           PALETTE_SORT_SHADER, (350, 1350))
    palette_sort.inputConnectors[0].connect(palette_cells)
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
        ('uUpscale', (_menu_index('Upscale'), _menu_index('Transformedge'), '0', '0')),
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

    callbacks = component.create(parameterexecuteDAT, 'controls')
    callbacks.nodeX, callbacks.nodeY = -350, -160
    _set(callbacks, 'active', False)
    callbacks.text = CONTROL_CALLBACKS.strip() + '\n'
    _set(callbacks, 'op', '..')
    _set(callbacks, 'pars', 'Stamp Step Pause Clockmode Speed Reset Reseed Coral Spots Resolution Rectangle Canvaswidth Canvasheight Cellsize Seed Seedradius Ambient Moviefile Sourcetop Clipseed Restartclip Transformzero')
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
    _set(clock, 'active', True)
    print('Created {}. Play the timeline; view {}/out1.'.format(component.path, component.path))
    print('Choose Media > Movie File or Source TOP, or leave both blank for no media input.')
    print('Explore Influence > Mask Mode and Strength, then Display > Source Overlay.')
    return component


# =============================================================================
# 9. Embedded help
# =============================================================================

NETWORK_HELP = '''TURING MEDIA V2 / PHASE 3 — INDEPENDENT MEDIA INFLUENCE

QUICK START
Paste the entire builder into a Text DAT and Run Script. Play the timeline.
Each run creates a uniquely named turing_media_v2 component. No external
packages, shader files, or TDAPI component are required. Save as a TOX to reuse.
Leave Media > Movie File and Source TOP blank for ambient patterns, or assign
media. Source TOP overrides Movie File. Use Clock > Pause and Step to inspect.

CLOCK PAGE / UNITS
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
Reset restores seed, colorless state and initial palette/media samples, resets
age/debt, and preserves Pause. Startup/load reinitializes GPU history.
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
supply DIFFERENT samples. Frame Stepped does not resample or seek movies; movie
position/snapshot controls are later work. For controlled offline input, the
clock DAT exposes advance(component, sample=callback); callback receives
(component, tick_index, simulation_seconds) before each tick's source capture.
Motion measures alpha and alpha-weighted luminance changes per tick, not optical
flow. It settles to zero on the next unchanged tick; while paused history holds.

TURING PAGE
Feed/Kill and Diffusion A/B control chemistry. Coral and Dividing Spots set
chemistry, Speed=1, Quality=1 and seed radius, then reset. Ambient Seeds adds
ten initial patches. Seed, Seed Radius, Ambient Seeds, dimensions, and source
binding changes still reset in Phase 3 (deliberate reset controls are Phase 5). Reset keeps the current media position;
Restart Clip cues the movie and resets. Reseed increments the random seed.
Resolution controls a square canvas; Rectangular Canvas enables Width/Height.
Cell Size divides the canvas dimensions for a coarser simulation, upscaled by
Display > Upscale Filter. Larger cells make thicker lines and lower GPU cost.
Seed Radius, Edge Width, Mask Smoothing, Tint Spread and Translate use cells.

MEDIA PAGE
Movie File supports clips and image sequences; Source TOP supports generators,
cameras, renders, etc. Do not reference this component's own output (cook loop).
Play Media/Media Speed/Restart Clip affect only the movie. Override FPS and
Sequence FPS are for image sequences. Scale, Offset X/Y and Rotation position
the media while preserving its aspect. Offsets are fractions of canvas size.
Prepared media is straight RGBA. Source Premultiplied unpremultiplies incoming
RGB when required; movie input premultiplication is off. Ignore Source Alpha
makes the fitted media rectangle opaque; transparent padding stays transparent.

INFLUENCE PAGE
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

DOMAIN PAGE
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
Without a domain, canvas edges retain the Phase 2 contract. With a domain, Wrap
repeats its mask across seams; Clear treats out-of-canvas cells as blocked, so
Domain Boundary also governs that interface. Full boundary unification is Phase 6.

COLOR / DISPLAY
All four color modes remain: Fixed Palette, Source Tint, Clip Palette, Carried
Color. Ramp TOP optionally replaces the teal/gold ramp (horizontal middle row).
Tint Spread blurs source color. Clip Palette sorts averaged 8x8 cells into a
64-step ramp; cells below 25% alpha coverage are ignored. Palette Smoothing is
a time constant in simulation seconds: 0=instant, default ~.158 seconds.
History retention per tick is exp(-tick_seconds / smoothing_seconds).
Palette Anchoring borrows base-ramp lightness. Color Amount, Contrast and
Invert affect display; changing color mode never resets simulation.
Carried Color stores signed Oklab a/b in state blue/alpha. Color Spread Rate
mixes toward B-weighted neighbors each substep by 1-exp(-rate*substep_seconds).
Carried Color Source selects Source Alpha (default) or the Influence Mask.
Color Injection Rate independently blends toward source chroma using that value
in the exponent, in every influence mode; Color Decay Rate fades toward gray by exp(-rate*tick_seconds).
Default spread ~665.42/second, injection ~3.08/second, decay 0. Saturation only
affects display. Color history is maintained in every color mode.
Source Overlay adds live media over patterns. Clip Patterns to Alpha clips
display only; it does not confine simulation. Output is premultiplied RGBA.
Output View selects final/patterns/mask/source-on-checkerboard. Upscale Filter
selects cubic, linear or nearest reconstruction for coarse simulations.

TRANSFORM PAGE
Enable Transform to move chemical and color state after every tick's solver.
Grow and Scale X/Y are continuous percent rates per simulation second:
scale = exp((grow + axis_scale)*.01*tick_seconds). Positive values expand.
Translate X/Y uses cells/second; Rotate uses degrees/second. Pivot X/Y is UV.
Motion stays undistorted on rectangular grids. Default Grow ~6 and Rotate 6
reproduce the old .1% and .1 degree/frame at 60 FPS. Try Grow 6..30, Rotate 6..60.
Zero Motion clears rates without resetting. Bilinear transport slightly softens
state each tick. Wrap connects opposite edges; inherited Clear transport fills
exterior with A=1/B=0/colorless, while the diffusion stencil clamps edges.
Full boundary unification belongs to Phase 6. Shrink+Clear needs seeds/influence.

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

NETWORK / OUTPUTS
state_a/b, palette_a/b, media_a/b are RGBA32F GPU Cache TOPs. Automatic capture
is disabled. The clock explicitly replaces the inactive buffer and switches
the reader only after completing the tick. Repeated Feedback TOP cooks are not
used. No CPU texture download/upload or external packages run in the product.
clock: Execute DAT scheduler and callable reset/step/advance API.
state_read -> reaction_diffusion -> state_transform -> inactive state buffer.
media_prepared -> inactive media buffer -> media_cache/media_previous -> mask.
media_cache -> palette_cells -> palette_sort -> inactive palette buffer.
out1=final display; patterns=colored simulation before overlay/clipping;
mask_preview=last tick mask; source_preview=live fitted straight RGBA;
palette=64x2 (clip ramp row 0, base ramp row 1); state=raw A/B + signed Oklab a/b.
State alpha is DATA, not opacity. Do not premultiply or color-convert it.
Each shader has a compiler Info DAT. The unselected blank movie may report an
empty-file diagnostic; the transparent fallback is used until media is assigned.
Validation scripts/results: validation/phase2 and validation/phase3.
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

