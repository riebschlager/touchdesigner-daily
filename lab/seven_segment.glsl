// Seven-segment display filter — TouchDesigner GLSL TOP
// Input 0: video (pre-blur or downsample it first — point sampling shimmers)
// Set uniforms on the GLSL TOP's Vectors page. Suggested defaults in brackets.

uniform float uCellW;        // cell width in px; height = 2x            [16]
uniform float uGap;          // spacing between cells, fraction of cell  [0.1]
uniform float uThick;        // segment half-thickness (digit units)     [0.1]
uniform float uSegGap;       // gap between segments                     [0.04]
uniform float uSlant;        // italic shear                             [0.12]
uniform float uMode;         // 0 = per-segment sampling, 1 = digit ramp [0]
uniform float uThresh;       // on threshold (mode 0)                    [0.45]
uniform float uSoft;         // threshold softness, 0 = hard binary      [0.05]
uniform float uGhost;        // brightness of unlit segments             [0.07]
uniform float uDiag;         // 1 = add diagonals + center verticals     [0]
uniform float uGlow;         // in-cell halo (real bloom goes after)     [0.3]
uniform vec3  uLedColor;     // fixed LED color                          [1, 0.15, 0.05]
uniform float uUseSrcColor;  // 0 = LED color, 1 = source color          [0]

out vec4 fragColor;

// bit0 = a ... bit6 = g, ordered by lit-segment count: blank,1,7,4,3,5,0,9,8
const int DIGIT_RAMP[9] = int[9](0x00, 0x06, 0x07, 0x66, 0x4F, 0x6D, 0x3F, 0x6F, 0x7F);

float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

// Segment from a to b with pointed (hexagonal) ends, half-thickness t
float sdSeg(vec2 p, vec2 a, vec2 b, float t) {
    vec2 ba  = b - a;
    float hl = length(ba) * 0.5;
    vec2 dir = ba / (2.0 * hl);
    vec2 q   = p - (a + b) * 0.5;
    q = abs(vec2(dot(q, dir), dot(q, vec2(-dir.y, dir.x))));
    return max(q.y - t, q.x + q.y - hl);
}

// Digit-space point -> input UV (inverse of the local transform in main)
vec2 digitToUV(vec2 q, vec2 id, vec2 cell, vec2 res, float s) {
    q.x += q.y * uSlant;
    vec2 f = q * s / vec2(1.0, 2.0) + 0.5;
    return (id + f) * cell / res;
}

void main() {
    vec2 res  = uTDOutputInfo.res.zw;
    vec2 cell = vec2(uCellW, uCellW * 2.0);
    vec2 g    = vUV.st * res / cell;
    vec2 id   = floor(g);
    vec2 f    = fract(g);

    // Local digit coords: x in [-0.5, 0.5], y in [-1, 1], inset by cell gap
    float s = max(1.0 - 2.0 * uGap, 0.05);
    vec2 p  = (f - 0.5) * vec2(1.0, 2.0) / s;
    p.x -= p.y * uSlant;

    float W  = 0.5 - uThick;
    float H  = 1.0 - uThick;
    float sg = uSegGap;
    float px = 2.0 / (cell.y * s);          // one pixel in digit units (AA width)

    vec2 A[13];
    vec2 B[13];
    // Standard 7: a b c d e f g
    A[0] = vec2(-W + sg,  H);     B[0] = vec2( W - sg,  H);
    A[1] = vec2( W,  H - sg);     B[1] = vec2( W,  sg);
    A[2] = vec2( W, -sg);         B[2] = vec2( W, -H + sg);
    A[3] = vec2(-W + sg, -H);     B[3] = vec2( W - sg, -H);
    A[4] = vec2(-W, -sg);         B[4] = vec2(-W, -H + sg);
    A[5] = vec2(-W,  H - sg);     B[5] = vec2(-W,  sg);
    A[6] = vec2(-W + sg, 0.0);    B[6] = vec2( W - sg, 0.0);
    // Extras: four diagonals + two center verticals (14-seg style, g unsplit)
    float dg = uThick + sg;
    A[7]  = vec2(-dg,  dg);       B[7]  = vec2(-W + dg,  H - dg);
    A[8]  = vec2( dg,  dg);       B[8]  = vec2( W - dg,  H - dg);
    A[9]  = vec2(-dg, -dg);       B[9]  = vec2(-W + dg, -H + dg);
    A[10] = vec2( dg, -dg);       B[10] = vec2( W - dg, -H + dg);
    A[11] = vec2(0.0,  dg);       B[11] = vec2(0.0,  H - dg);
    A[12] = vec2(0.0, -dg);       B[12] = vec2(0.0, -H + dg);

    vec3 cellC = texture(sTD2DInputs[0], (id + 0.5) * cell / res).rgb;
    int  mask  = DIGIT_RAMP[int(clamp(luma(cellC), 0.0, 0.999) * 9.0)];
    int  n     = uDiag > 0.5 ? 13 : 7;

    vec3 col = vec3(0.0);
    for (int i = 0; i < n; i++) {
        float t    = i < 7 ? uThick : uThick * 0.8;
        float d    = sdSeg(p, A[i], B[i], t);
        float fill = 1.0 - smoothstep(-px, px, d);

        vec3 src;
        float on;
        if (uMode < 0.5) {
            src = texture(sTD2DInputs[0],
                          digitToUV((A[i] + B[i]) * 0.5, id, cell, res, s)).rgb;
            on  = smoothstep(uThresh - uSoft - 1e-4, uThresh + uSoft + 1e-4, luma(src));
        } else {
            src = cellC;
            on  = (i < 7 && ((mask >> i) & 1) == 1) ? 1.0 : 0.0;
        }

        vec3  c    = mix(uLedColor, src, uUseSrcColor);
        float glow = uGlow * on * exp(-max(d, 0.0) * 12.0);
        col += c * (fill * mix(uGhost, 1.0, on) + glow);
    }

    fragColor = TDOutputSwizzle(vec4(col, 1.0));
}
