"""Build the V2 baseline media-driven reaction-diffusion network in TouchDesigner.

USE
  1. Paste this entire file into a Text DAT in your project.
  2. Right-click the DAT and choose Run Script.
  3. Play the timeline: ambient seed patterns grow immediately (no media).
  4. Select turing_media_v2. On Media, choose Movie File to load your own clip,
     or drag any TOP into Source TOP to drive it live (camera, generator, etc.).
  5. Explore Influence > Mask Mode, Strength, and Display > Source Overlay.
  6. On Color, switch Color Mode to tint, extract or carry the clip's colors.
     Assign Color > Ramp TOP to replace the built-in teal/gold ramp with your own.

Phase 1 preserves V1 simulation and display behavior. No external Python packages or shader files.
Re-running creates turing_media_v2, turing_media_v2_2, and so on; existing operators are retained.
Outputs: out1 = final image, patterns = colored simulation, mask_preview =
influence mask, source_preview = fitted RGBA source, palette = clip color
ramp, state = raw A/B concentrations plus carried color.
Clear Source TOP and Movie File to remove the media influence. No external dependencies.

Default: 512 square, 32-bit float state, 16 simulation steps per frame.
Turn on Turing > Rectangular Canvas for an independent Width and Height.
Turing > Cell Size runs the simulation on a coarser grid (canvas / Cell Size)
and upscales it for display: larger cells give thicker lines at any canvas size.
Simulation speed therefore depends on frame rate. Passes costs GPU time.
Save the .toe or save this component as a .tox to keep the generated network.

References:
  https://www.karlsims.com/rd.html
  https://derivative.ca/UserGuide/GLSL_TOP
  https://derivative.ca/UserGuide/Feedback_TOP

Validation: TouchDesigner 2025.33230 on macOS; 12 live baseline cases,
288 pixel-exact output comparisons against V1, matching network/parameters,
and passing shader, pause, reset, and finite-concentration checks. Other builds
have not been live-validated. See validation/phase1 for the harness and results.
This builder remains standalone; validation files are not required to run it.
Later V2 phases are not implemented.
"""


# =============================================================================
# 1. Configuration
# =============================================================================

COMPONENT_BASENAME = 'turing_media_v2'

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
uniform vec4 uStep;  // timestep, running, edge mode index (wrap, clear), unused
uniform vec4 uInfluence; // strength per frame, fade per frame, unused, unused
uniform vec4 uDye; // colour spread per pass, injection per frame, decay per frame, unused
""" + OKLAB_GLSL + r"""
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
    vec4 cell = readCell(p);
    vec2 ab = cell.rg;
    if (uStep.y < 0.5) {
        fragColor = TDOutputSwizzle(cell);
        return;
    }

    vec2 lap = -ab;
    vec3 dye = dyeSample(cell, 1.0);
    for (int i = 0; i < 8; ++i) {
        vec4 neighbor = readCell(p + OFFSETS[i]);
        lap += WEIGHTS[i] * neighbor.rg;
        dye += dyeSample(neighbor, WEIGHTS[i]);
    }
    vec2 chroma = mix(cell.ba, dye.xy / dye.z, uDye.x);

    float reaction = ab.x * ab.y * ab.y;
    vec2 change;
    change.x = uRates.z * lap.x - reaction + uRates.x * (1.0 - ab.x);
    change.y = uRates.w * lap.y + reaction - (uRates.x + uRates.y) * ab.y;
    vec2 nextState = clamp(ab + uStep.x * change, 0.0, 1.0);
    if (uTDPass == 0) {
        // Recovery/fade is explicit, rather than multiplying the state by black.
        nextState = mix(nextState, vec2(1.0, 0.0), uInfluence.y);
        float maskValue = clamp(texture(sTD2DInputs[1], vUV.st).r, 0.0, 1.0);
        nextState = mix(nextState, vec2(0.5, 0.25), uInfluence.x * maskValue);
        // Visible source pixels stain the carried colour toward their own chroma.
        vec4 source = texture(sTD2DInputs[2], vUV.st); // prepared straight RGBA
        vec2 sourceChroma = linearToOklab(toLinear(source.rgb)).yz;
        chroma = mix(chroma, sourceChroma, uDye.y * clamp(source.a, 0.0, 1.0));
        chroma *= 1.0 - uDye.z;
    }
    fragColor = TDOutputSwizzle(vec4(nextState, chroma));
}
"""


TRANSFORM_SHADER = r"""
layout(location = 0) out vec4 fragColor;
uniform vec4 uWarp; // grow %, scale X %, scale Y %, rotation radians (all per frame)
uniform vec4 uDrift; // translate X/Y in cells per frame, pivot X/Y in UV
uniform vec4 uWarpMode; // active, edge mode index, unused, unused

const vec4 EMPTY_CELL = vec4(1.0, 0.0, 0.0, 0.0); // A=1, B=0, colourless

// Manual bilinear over integer texels keeps torus edges exact and avoids
// relying on 32-bit float texture filtering. Clear mode refills from outside.
vec4 readCell(ivec2 p, ivec2 size) {
    bool outside = any(lessThan(p, ivec2(0))) || any(greaterThanEqual(p, size));
    if (uWarpMode.y > 0.5 && outside) return EMPTY_CELL;
    p = (p % size + size) % size;
    return texelFetch(sTD2DInputs[0], p, 0);
}

void main() {
    ivec2 size = textureSize(sTD2DInputs[0], 0);
    if (uWarpMode.x < 0.5) {
        fragColor = TDOutputSwizzle(texelFetch(sTD2DInputs[0], ivec2(gl_FragCoord.xy), 0));
        return;
    }
    // Forward move per frame: scale, rotate about the pivot, then translate.
    // Each output cell samples the inverse of that move from the previous state.
    vec2 pivot = uDrift.zw * vec2(size);
    vec2 q = gl_FragCoord.xy - pivot - uDrift.xy;
    float c = cos(uWarp.w), s = sin(uWarp.w);
    q = vec2(c * q.x + s * q.y, -s * q.x + c * q.y);
    vec2 scale = (1.0 + uWarp.x * 0.01) * (1.0 + uWarp.yz * 0.01);
    vec2 source = pivot + q / max(scale, vec2(0.01)) - 0.5;
    ivec2 base = ivec2(floor(source));
    vec2 f = source - vec2(base);
    vec4 bottom = mix(readCell(base, size), readCell(base + ivec2(1, 0), size), f.x);
    vec4 top = mix(readCell(base + ivec2(0, 1), size), readCell(base + ivec2(1, 1), size), f.x);
    fragColor = TDOutputSwizzle(mix(bottom, top, f.y));
}
"""


# =============================================================================
# 4. Media processing
# =============================================================================

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

# Legacy pulse clauses, embedded unchanged in CONTROL_CALLBACKS below.
# A versioned preset table is deferred to phase 4.
PRESET_PULSE_HANDLERS = '''    elif par.name == 'Coral':
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
    elif par.name == 'Clipseed':
        component.par.Ambient = False
        component.par.Maskmode = 'alpha'
        component.par.Strength = 1.0
        component.par.Fade = 0.0
'''


# =============================================================================
# 7. Callbacks
# =============================================================================

CONTROL_CALLBACKS = '''
def resetSimulation(component):
    component.store('Resetframe', absTime.frame)
    component.op('feedback').par.resetpulse.pulse()
    return

def onPulse(par):
    component = par.owner
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
    if par.name in ('Resolution', 'Rectangle', 'Canvaswidth', 'Canvasheight', 'Cellsize',
                    'Seed', 'Seedradius', 'Ambient', 'Moviefile', 'Sourcetop'):
        resetSimulation(par.owner)
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
    _number(page, 'Timestep', 'Timestep', 1.0, 0.0, 1.0)
    _number(page, 'Passes', 'Passes / frame', 16, 1, 128, True)
    running = page.appendToggle('Running', label='Running')[0]
    running.default = True
    running.val = True
    _number(page, 'Seed', 'Seed', 1, 0, 1000000, True)
    _number(page, 'Seedradius', 'Seed Radius (cells)', 9.0, 3.0, 32.0)
    _toggle(page, 'Ambient', 'Ambient Seeds', True)
    for name, label in (('Reset', 'Reset'), ('Reseed', 'Reseed'),
                        ('Coral', 'Coral Preset'), ('Spots', 'Dividing Spots Preset')):
        page.appendPulse(name, label=label)
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
    _menu(influence_page, 'Maskmode', 'Mask Mode', [
        ('alpha', 'Silhouette'), ('bright', 'Bright Texture'), ('dark', 'Dark Texture'),
        ('edgealpha', 'Silhouette Edges'), ('edgetexture', 'Texture Edges'), ('motion', 'Motion'),
    ], 'edgealpha')
    _number(influence_page, 'Strength', 'Strength', 0.08, 0.0, 1.0)
    _number(influence_page, 'Maskgain', 'Mask Gain', 1.0, 0.0, 8.0)
    _number(influence_page, 'Edgewidth', 'Edge Width (cells)', 3.0, 1.0, 12.0)
    _number(influence_page, 'Smoothing', 'Mask Smoothing (cells)', 1.0, 0.0, 8.0)
    _number(influence_page, 'Motiongain', 'Motion Gain', 4.0, 0.1, 20.0)
    _number(influence_page, 'Fade', 'Fade / frame', 0.0, 0.0, 0.1)
    influence_page.appendPulse('Clipseed', label='Seed From Clip Only')

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
    _number(transform_page, 'Grow', 'Grow / Shrink (% / frame)', 0.1, -5.0, 5.0)
    _number(transform_page, 'Scalex', 'Scale X (% / frame)', 0.0, -5.0, 5.0)
    _number(transform_page, 'Scaley', 'Scale Y (% / frame)', 0.0, -5.0, 5.0)
    _number(transform_page, 'Translatex', 'Translate X (cells / frame)', 0.0, -8.0, 8.0)
    _number(transform_page, 'Translatey', 'Translate Y (cells / frame)', 0.0, -8.0, 8.0)
    _number(transform_page, 'Rotate', 'Rotate (degrees / frame)', 0.1, -10.0, 10.0)
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
    _number(color_page, 'Palettesmooth', 'Palette Smoothing', 0.9, 0.0, 0.99)
    _number(color_page, 'Paletteanchor', 'Palette Anchoring', 0.5, 0.0, 1.0)
    _number(color_page, 'Dyespread', 'Color Spread / pass', 0.5, 0.0, 1.0)
    _number(color_page, 'Dyeinject', 'Color Injection / frame', 0.05, 0.0, 1.0)
    _number(color_page, 'Dyedecay', 'Color Decay / frame', 0.0, 0.0, 0.05)
    _number(color_page, 'Dyesaturation', 'Color Saturation', 1.5, 0.0, 4.0)

    component.store('Resetframe', absTime.frame)
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

    cache = component.create(cacheTOP, 'media_cache')
    cache.nodeX, cache.nodeY = -400, 650
    cache.inputConnectors[0].connect(prepared)
    _set(cache, 'cachesize', 2)
    _set(cache, 'active', True)
    _set(cache, 'step', 1)
    _set(cache, 'format', 'rgba32float')
    previous = component.create(cacheselectTOP, 'media_previous')
    previous.nodeX, previous.nodeY = -150, 900
    _set(previous, 'cachetop', cache.name)
    _set(previous, 'index', -1)

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
                     '1 if absTime.frame - parent().fetch("Resetframe", -9999) > 2 else 0', '0', '0')),
    ])
    mask_preview = component.create(nullTOP, 'mask_preview')
    mask_preview.nodeX, mask_preview.nodeY = 350, 650
    mask_preview.inputConnectors[0].connect(mask)
    source_preview = component.create(nullTOP, 'source_preview')
    source_preview.nodeX, source_preview.nodeY = -400, 1050
    source_preview.inputConnectors[0].connect(prepared)

    seed = _shader(component, 'seed', 'seed_pixel', SEED_SHADER, (-600, 200))
    _set(seed, 'outputresolution', 'custom')
    # The seed sets the simulation grid; every state operator downstream follows it.
    _expression(seed, 'resolutionw', SIM_WIDTH)
    _expression(seed, 'resolutionh', SIM_HEIGHT)
    _uniforms(seed, [('uSeed', ('parent().par.Seed', 'parent().par.Seedradius',
                                '0', 'parent().par.Ambient')),
                     ('uSeedSize', (SIM_WIDTH, SIM_HEIGHT, '0', '0'))])

    feedback = component.create(feedbackTOP, 'feedback')
    feedback.nodeX, feedback.nodeY = -350, 200
    feedback.inputConnectors[0].connect(seed)
    _set(feedback, 'format', 'rgba32float')
    _set(feedback, 'reset', False)

    simulation = _shader(component, 'reaction_diffusion', 'simulation_pixel',
                         SIMULATION_SHADER, (-100, 200))
    simulation.inputConnectors[0].connect(feedback)
    simulation.inputConnectors[1].connect(mask_preview)
    simulation.inputConnectors[2].connect(prepared)
    _expression(simulation, 'npasses', 'parent().par.Passes')
    _uniforms(simulation, [
        ('uRates', ('parent().par.Feed', 'parent().par.Kill',
                    'parent().par.Diffusiona', 'parent().par.Diffusionb')),
        ('uStep', ('parent().par.Timestep', 'parent().par.Running', _menu_index('Transformedge'), '0')),
        ('uInfluence', ('parent().par.Strength', 'parent().par.Fade', '0', '0')),
        ('uDye', ('parent().par.Dyespread', 'parent().par.Dyeinject',
                  'parent().par.Dyedecay', '0')),
    ])

    # Applied once per frame after all passes, so the move compounds through feedback.
    transform = _shader(component, 'state_transform', 'transform_pixel',
                        TRANSFORM_SHADER, (150, 200))
    transform.inputConnectors[0].connect(simulation)
    _uniforms(transform, [
        ('uWarp', ('parent().par.Grow', 'parent().par.Scalex', 'parent().par.Scaley',
                   'parent().par.Rotate * 0.0174532925199433')),
        ('uDrift', ('parent().par.Translatex', 'parent().par.Translatey',
                    'parent().par.Pivotx', 'parent().par.Pivoty')),
        ('uWarpMode', ('1 if parent().par.Transform and parent().par.Running else 0',
                       _menu_index('Transformedge'), '0', '0')),
    ])

    state = component.create(nullTOP, 'state')
    state.nodeX, state.nodeY = 150, 420
    state.inputConnectors[0].connect(transform)
    _set(state, 'format', 'rgba32float')
    _set(feedback, 'top', state.name)

    # Clip palette: averaged cells -> luminance-sorted ramp, eased through feedback.
    palette_uniforms = [('uPalette', (str(PALETTE_CELLS), 'parent().par.Palettesmooth',
                                      '1 if absTime.frame - parent().fetch("Resetframe", -9999) > 2 else 0',
                                      str(PALETTE_WIDTH)))]
    palette_cells = _shader(component, 'palette_cells', 'palette_cells_pixel',
                            PALETTE_CELLS_SHADER, (-150, 1350))
    palette_cells.inputConnectors[0].connect(prepared)
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
    palette_feedback = component.create(feedbackTOP, 'palette_feedback')
    palette_feedback.nodeX, palette_feedback.nodeY = 350, 1550
    palette_feedback.inputConnectors[0].connect(palette_init)
    _set(palette_feedback, 'format', 'rgba32float')
    _set(palette_feedback, 'reset', False)

    # Optional Ramp TOP; falls back to palette_init so the select never errors when blank.
    ramp = component.create(selectTOP, 'ramp')
    ramp.nodeX, ramp.nodeY = 100, 1750
    _expression(ramp, 'top', 'parent().par.Ramptop.eval() if parent().par.Ramptop.eval() is not None '
                             'else op("palette_init")')
    ramp_uniform = ('uRamp', ('1 if parent().par.Ramptop.eval() is not None else 0', '0', '0', '0'))

    palette_sort = _shader(component, 'palette_sort', 'palette_sort_pixel',
                           PALETTE_SORT_SHADER, (350, 1350))
    palette_sort.inputConnectors[0].connect(palette_cells)
    palette_sort.inputConnectors[1].connect(palette_feedback)
    palette_sort.inputConnectors[2].connect(ramp)
    _set(palette_sort, 'outputresolution', 'custom')
    _set(palette_sort, 'resolutionw', PALETTE_WIDTH)
    _set(palette_sort, 'resolutionh', 2)
    _set(palette_sort, 'inputfiltertype', 'linear')
    _uniforms(palette_sort, palette_uniforms + [ramp_uniform])
    palette = component.create(nullTOP, 'palette')
    palette.nodeX, palette.nodeY = 600, 1350
    palette.inputConnectors[0].connect(palette_sort)
    _set(palette_feedback, 'top', palette.name)

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

    callbacks = component.create(parameterexecuteDAT, 'controls')
    callbacks.nodeX, callbacks.nodeY = -350, -160
    _set(callbacks, 'active', False)
    callbacks.text = CONTROL_CALLBACKS.strip() + '\n'
    _set(callbacks, 'op', '..')
    _set(callbacks, 'pars', 'Reset Reseed Coral Spots Resolution Rectangle Canvaswidth Canvasheight Cellsize Seed Seedradius Ambient Moviefile Sourcetop Clipseed Restartclip Transformzero')
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
    print('Choose Media > Movie File or Source TOP, or leave both blank for no media input.')
    print('Explore Influence > Mask Mode and Strength, then Display > Source Overlay.')
    return component


# =============================================================================
# 9. Embedded help
# =============================================================================

NETWORK_HELP = '''TURING MEDIA V2 / PHASE 1 BASELINE

PHASE 1
This standalone V2 preserves the V1 controls, GLSL, defaults, and output names.
Timing is still frame-dependent. The new clock, influence modes, preset storage,
snapshots, and boundary changes belong to later phases.
Each run creates turing_media_v2 (or the next available numbered suffix).

QUICK START
Play the timeline: ambient seed patterns grow immediately.
Select the Base COMP > Media > Movie File to load your own clip, or drag any
TOP onto Media > Source TOP to drive it live. Source TOP wins when both are set.
Leave both blank for no media input. Check that a GIF actually animates in
Movie File In; if necessary use a PNG sequence or Hap Alpha movie.
For a PNG sequence, paste the folder path into Movie File. Turn on Override FPS
and set Sequence FPS to the intended rate. GIFs with unequal frame delays need
resampling when converted to a fixed-FPS sequence.

MEDIA PAGE
Source TOP: any TOP (camera, Noise, Text, a render, another network's output)
replaces Movie File as the source. It is read live through media_top (a Select
TOP), so playback is controlled wherever that TOP lives; Play Media / Media
Speed / Restart Clip only affect Movie File. Assigning, changing or clearing it
resets the simulation. Don't assign this component's own out1 (a cook loop).
Play Media / Media Speed / Restart Clip control playback. Scale / Offset X/Y /
Rotation fit and position the source in the simulation's canvas, keeping its
aspect ratio on square and rectangular canvases. Offsets are fractions of the
canvas width/height.
Ignore Source Alpha lets opaque video use its whole fitted rectangle.
Source Premultiplied: turn on only if the decoded RGB is already multiplied by
alpha. The Movie File In premultiply option is Off; this toggle unpremultiplies
existing source data.
Transparent padding stays transparent, even with Ignore Source Alpha on.
The fitting shader normalizes source RGB into straight RGBA for mask/composite.

INFLUENCE PAGE
Silhouette = alpha; Bright Texture = alpha times luminance;
Dark Texture = alpha times inverted luminance.
Silhouette Edges traces the outer contour. Texture Edges includes internal detail.
Motion uses differences in BOTH alpha and alpha-weighted luminance against the
previous cached project frame. This is frame difference, not optical flow.
The two-frame cache keeps capturing when playback is paused, so motion settles
back to zero. Source changes can produce a brief transient.
Mask Gain, Edge Width and Mask Smoothing shape the input. Preview it via Display
> Output View > Influence Mask, or view mask_preview directly.
Strength blends concentrations toward A=.5, B=.25 ONCE per project frame.
Start around .03-.15 with ambient patterns already present. Higher strengths
pin the source into the pattern. Weak sources may not ignite an empty field,
especially at high passes. Seed From Clip Only turns off Ambient Seeds, selects
Silhouette, sets Strength=1 and Fade=0, and resets for a clear comparison.
Reduce Strength afterward to let stamped shapes evolve more freely.
Fade gently recovers toward A=1, B=0 once per frame. Default zero. Try .001-.005;
even small values can suppress growth, especially with weak influence.

TURING PAGE
Feed, Kill, diffusion, timestep, passes, reset and presets match the original.
Ambient Seeds adds the original ten seed patches; enabled by default.
Running freezes the chemical state. Media playback is controlled separately.
Reset keeps media position. Restart Clip cues media and resets simulation.
Resolution sets a square canvas. Rectangular Canvas switches to independent
Width and Height (cells); seeds and source fit follow the new shape.
Cell Size (pixels) decouples the simulation grid from the canvas: the state is
canvas / Cell Size cells and is upscaled for display (Display > Upscale Filter).
Line width is fixed in cells, so Cell Size 4 makes lines four times thicker on
screen, and the simulation is ~16x cheaper, which leaves room for more Passes.
Seed Radius, Edge Width, Mask Smoothing, Tint Spread and Translate stay in cells.
Changing canvas size/shape, Cell Size, Seed, Seed Radius, Ambient Seeds or Movie
File resets state.
Speed, influence and fade depend on project FPS. Changing resolution changes
pattern scale. Parameters do not automatically keep the output in a loop:
a looping clip can keep developing a different chemical history on each loop.

DISPLAY PAGE
Source Overlay composites the original clip over the patterns.
Clip Patterns to Alpha confines DISPLAYED patterns to the current silhouette.
It does not restrict the simulation. At 1, out1 has alpha for downstream compositing.
Output View: Final / Patterns / Influence Mask / Source on Checkerboard.
Checkerboard is a diagnostic background only, never a simulation input.
The final composite uses premultiplied alpha; source_preview uses straight RGBA.
Color Amount: 0 = grayscale, 1 = the selected Color Mode. Contrast/Invert apply
to every mode.
Upscale Filter (only visible with Cell Size above 1): Smooth = Catmull-Rom cubic,
round contours; Linear = bilinear, slightly faceted; Nearest = visible square cells.

COLOR PAGE
Color Mode chooses where pattern colors come from. Switching never resets.
Ramp TOP (optional): drag a Ramp TOP (or any TOP) here to replace the built-in
  teal/gold ramp everywhere it is used: Fixed Palette, the Tint dark end and
  transparent fallback, Clip Palette anchoring/fallback, and Carried Color
  lightness. It is read horizontally along its middle row: left = background
  (low B), right = pattern peaks. Use a horizontal ramp; it is resampled to
  64 steps, so very hard color stops soften slightly.
  Contrast/Invert still choose where on the ramp each pixel lands. Clear it to
  return to teal/gold.
Fixed Palette: the base ramp (teal/gold, or the Ramp TOP when assigned).
Source Tint: the clip's local color becomes the middle of the ramp; dark stays
  dark, peaks lighten toward white. Tint Spread blurs the source (in cells) so
  color bleeds past the silhouette. Transparent areas fall back to Fixed Palette.
Clip Palette: the clip is averaged into an 8x8 grid, sorted dark->light into a
  64-pixel ramp (view palette), and used in place of the fixed ramp everywhere.
  Cells under 25% coverage are ignored; nothing visible = base ramp.
  Palette Smoothing eases the ramp per frame (0 = instant, .99 = very slow).
  Palette Anchoring borrows lightness from the base ramp (keeping the clip's
  hue/chroma) so backgrounds stay dark and peaks bright. 0 = pure clip ramp.
Carried Color: hue/chroma travel INSIDE the simulation (state blue/alpha, Oklab
  a/b). Visible source pixels stain it once per frame by Color Injection; each
  pass it spreads to neighbors weighted by chemical B, so color rides outward
  with growing pattern and stays after the clip moves. Lightness still comes
  from the base ramp. Color Spread: per-pass mixing (0 freezes). Color Decay:
  per-frame fade toward gray (0 = permanent). Color Saturation: display boost,
  since averaging desaturates. Uncolored areas read as gray. Reset clears color.
  The carried color always runs, so it has history when you switch to it.

TRANSFORM PAGE
Moves the chemical state (and carried color) a little every frame, inside the
feedback loop, so the move compounds: patterns spiral, zoom and drift forever
while the reaction keeps re-forming them. Applied once per frame after all
passes, so its speed depends on project FPS, not Passes. Off by default; also
frozen while Running is off.
Grow / Shrink: uniform zoom about the pivot (+ grows outward, - pulls inward).
Scale X / Y: extra per-axis stretch on top of Grow (+/- for shear-like flows).
Translate X / Y: drift in cells per frame. Rotate: degrees per frame.
Pivot X / Y: the center for scale and rotation (0-1 across the canvas).
Rotation works in cells, so it stays undistorted on a rectangular canvas.
Edges: Wrap keeps the torus (shrinking tiles the field); Clear refills the
border with empty field (A=1, B=0) so the influence or seeds must re-grow it.
Edges applies even with Transform off: Clear also stops the reaction and the
display upscale from wrapping, so opposite edges never bleed into each other.
Zero Motion clears every rate without resetting. Sampling is bilinear, which
slightly softens each frame; the reaction re-sharpens it. Small values go a long
way: try Grow .1-.5, Rotate .1-1. Pair with a nonzero Strength or Ambient Seeds
so Shrink + Clear never empties the field.

USEFUL OPERATORS
out1: final image (or the selected diagnostic view).
patterns: colored simulation before clipping/overlay.
mask_preview: grayscale influence; its alpha intentionally stays 1.
source_preview: fitted source with actual alpha, no baked checkerboard.
state: red=A, green=B, blue/alpha=carried color (Oklab a/b), 32-bit float, at
  the simulation grid size (canvas / Cell Size), not the canvas size.
  Its alpha is not opacity; the TD viewer may show it as transparent.
palette: 64x2; row 0 = clip color ramp, row 1 = base ramp (Ramp TOP or
  teal/gold, resampled to 64 steps). palette_cells: the 8x8 averaged colors/coverage.
ramp: Select TOP of Color > Ramp TOP (shows palette_init while it is blank).
movie_info: length, current index, sample rate and decode info.
Each GLSL TOP has an Info DAT for compiler messages. Its Pixel Shader parameter
points to the actual DAT; TD may add a suffix such as _pixel1 during creation.
movie may report a missing-file error while Movie File is blank; it is unselected
and the transparent blank branch is used. Selecting a valid file enables that branch.
media_top: Select TOP of Media > Source TOP (shows blank while it is unassigned).

NETWORK
movie + blank + media_top (Select TOP of Source TOP) -> media_source -> media_prepared -> media_cache (2 frames)
media_previous selects cache index -1. media_mask reads current and previous.
mask_preview -> reaction_diffusion input 1; feedback remains input 0.
seed -> feedback -> reaction_diffusion -> state_transform -> state;
Feedback Target TOP = state.
media_prepared -> reaction_diffusion input 2 (carried color injection).
media_prepared -> palette_cells -> palette_sort -> palette; palette_feedback
(Target TOP = palette, initialized by palette_init) feeds palette_sort input 1.
ramp (Select TOP of Color > Ramp TOP) -> palette_sort input 2 -> palette row 1.
state + media_prepared + palette -> colorize (upscales to canvas) -> patterns.
composite reads patterns, prepared source and mask.
Injection/fade/color stain use uTDPass==0, not every simulation pass.

EXPERIMENTS
Default: Silhouette Edges, Strength=.08, Source Overlay=.2, ambient seeds on.
Bright Texture: animate internal detail. Motion: try slower media and higher gain.
Clip Patterns to Alpha=1 + Source Overlay=0: a silhouette filled with live patterns.
Seed From Clip Only: stamp the clip into an initially empty field; lower Strength
or set it to zero afterward to watch the seeded pattern evolve independently.
Carried Color + Seed From Clip Only + Color Injection=.2: patterns grow out of the
clip wearing its colors; lower Strength to let them roam. Color Decay=.002 keeps
older trails fading. Clip Palette with a colorful video and Smoothing=.97 gives
a slowly drifting palette that follows the edit.
Save the Base COMP as .tox for reuse. This script always creates a new component.
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

