# Build a Seven/Fourteen-Segment display network in TouchDesigner.
# Paste into a Text DAT and run it (Ctrl+R).
# Creates, next to this DAT:
#   seg_src (video) -> seven_segment (Base COMP) -> seven_segment_out
# Source menu switches between video, text, and text revealed by video.
# Text comes from the Text parameter (use \n for line breaks) or a Text DAT,
# and is turned into a mask texture (one pixel per character) by a Script TOP.
# Re-running deletes and rebuilds the network.

# Script TOP callbacks: string -> 14-bit segment masks (red channel, 32-bit float).
TEXT_CALLBACKS = r'''
import numpy as np

#  ───a───
# │\  │  /│
# f h i j b
# │  \│/  │
#  ─g1─g2─
# │  /│\  │
# e k l m c
# │/  │  \│
#  ───d───
SEGS = ['a', 'b', 'c', 'd', 'e', 'f', 'g1', 'g2', 'h', 'i', 'j', 'k', 'l', 'm']
BIT  = {s: 1 << i for i, s in enumerate(SEGS)}

FONT = {
    'A': 'a b c e f g1 g2',   'B': 'a b c d g2 i l',    'C': 'a d e f',
    'D': 'a b c d i l',       'E': 'a d e f g1',        'F': 'a e f g1',
    'G': 'a c d e f g2',      'H': 'b c e f g1 g2',     'I': 'a d i l',
    'J': 'b c d e',           'K': 'e f g1 j m',        'L': 'd e f',
    'M': 'b c e f h j',       'N': 'b c e f h m',       'O': 'a b c d e f',
    'P': 'a b e f g1 g2',     'Q': 'a b c d e f m',     'R': 'a b e f g1 g2 m',
    'S': 'a c d f g1 g2',     'T': 'a i l',             'U': 'b c d e f',
    'V': 'e f j k',           'W': 'b c e f k m',       'X': 'h j k m',
    'Y': 'h j l',             'Z': 'a d j k',
    '0': 'a b c d e f j k',   '1': 'b c j',             '2': 'a b d e g1 g2',
    '3': 'a b c d g2',        '4': 'b c f g1 g2',       '5': 'a c d f g1 g2',
    '6': 'a c d e f g1 g2',   '7': 'a b c',             '8': 'a b c d e f g1 g2',
    '9': 'a b c d f g1 g2',
    ' ': '',                  '-': 'g1 g2',             '+': 'g1 g2 i l',
    '*': 'g1 g2 h i j k l m', '/': 'j k',               '\\': 'h m',
    '_': 'd',                 '=': 'd g1 g2',           '|': 'i l',
    '(': 'j m',               ')': 'h k',               '<': 'j m',
    '>': 'h k',               '[': 'a d e f',           ']': 'a b c d',
    '?': 'a b g2 l',          '$': 'a c d f g1 g2 i l', '%': 'c f g1 g2 j k',
    '^': 'k m',               ',': 'k',                 "'": 'i',
    '"': 'f i',               '!': 'b c',
}


def onSetupParameters(scriptOp):
    return


def onCook(scriptOp):
    comp = scriptOp.parent()
    dat  = comp.par.Textdat.eval()
    txt  = dat.text if dat else comp.par.Text.eval().replace('\\n', '\n')
    lines = txt.upper().split('\n')
    if comp.par.Layout.eval() == 'repeat':
        lines = [l + ' ' * int(comp.par.Spacing) for l in lines]
    w = max(1, max(len(l) for l in lines))
    arr = np.zeros((len(lines), w, 4), np.float32)
    arr[..., 3] = 1.0
    for r, line in enumerate(reversed(lines)):          # TD row 0 = bottom
        for c, ch in enumerate(line):
            arr[r, c, 0] = sum(BIT[s] for s in FONT.get(ch, '').split())
    scriptOp.copyNumpyArray(arr)
'''

SHADER = r'''
// Seven/fourteen-segment display — TouchDesigner GLSL TOP
// Input 0: video (pre-blurred)
// Input 1: text masks (one px per char, red = 14-bit segment mask, 32-bit float)

uniform float uCellW;        // cell width in px; height = 2x
uniform float uGap;          // spacing between cells, fraction of cell
uniform float uThick;        // segment half-thickness (digit units)
uniform float uSegGap;       // gap between segments
uniform float uSlant;        // italic shear
uniform float uSource;       // 0 = video, 1 = text, 2 = text revealed by video
uniform float uMode;         // video: 0 = per-segment sampling, 1 = digit ramp
uniform float uThresh;       // on threshold (video per-segment / reveal)
uniform float uSoft;         // threshold softness, 0 = hard binary
uniform float uGhost;        // brightness of unlit segments
uniform float uDiag;         // video: 1 = show the 14-segment extras
uniform float uGlow;         // in-cell halo (real bloom goes after)
uniform vec3  uLedColor;     // fixed LED color
uniform float uUseSrcColor;  // 0 = LED color, 1 = source color
uniform float uLayout;       // text: 0 = repeat, 1 = place
uniform vec2  uTextPos;      // text place: top-left cell (x right, y down)
uniform float uCenter;       // text place: 1 = center the block
uniform float uScroll;       // text: chars of horizontal offset
uniform float uStagger;      // text repeat: extra char offset per row

out vec4 fragColor;

// bit0 = a ... bit5 = f, bit6 = g1, bit7 = g2, bit8..13 = h i j k l m
// ordered by lit-segment count: blank,1,7,4,3,5,0,9,8
const int DIGIT_RAMP[9] = int[9](0x00, 0x06, 0x07, 0xE6, 0xCF, 0xED, 0x3F, 0xEF, 0xFF);

float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
float bitOn(int m, int i) { return float((m >> i) & 1); }

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

// Segment mask of the character shown in cell cid
int textMask(ivec2 cid, ivec2 grid) {
    ivec2 tsz    = textureSize(sTD2DInputs[1], 0);
    ivec2 cr     = ivec2(cid.x, grid.y - 1 - cid.y);   // top row = 0
    int   scroll = int(floor(uScroll));
    ivec2 t;
    if (uLayout < 0.5) {                               // repeat: read through the grid
        int len = tsz.x * tsz.y;
        int k   = cr.y * grid.x + cr.x + scroll + cr.y * int(uStagger);
        k = ((k % len) + len) % len;
        t = ivec2(k % tsz.x, k / tsz.x);
    } else {                                           // place: one block, wraps as a marquee
        ivec2 pos = uCenter > 0.5 ? (grid - tsz) / 2 : ivec2(uTextPos);
        int   per = max(grid.x, tsz.x + 1);
        t   = cr - pos;
        t.x = (((t.x + scroll) % per) + per) % per;
        if (t.y < 0 || t.y >= tsz.y || t.x >= tsz.x) return 0;
    }
    return int(texelFetch(sTD2DInputs[1], ivec2(t.x, tsz.y - 1 - t.y), 0).r + 0.5);
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

    vec2 A[14];
    vec2 B[14];
    // a b c d e f
    A[0] = vec2(-W + sg,  H);     B[0] = vec2( W - sg,  H);
    A[1] = vec2( W,  H - sg);     B[1] = vec2( W,  sg);
    A[2] = vec2( W, -sg);         B[2] = vec2( W, -H + sg);
    A[3] = vec2(-W + sg, -H);     B[3] = vec2( W - sg, -H);
    A[4] = vec2(-W, -sg);         B[4] = vec2(-W, -H + sg);
    A[5] = vec2(-W,  H - sg);     B[5] = vec2(-W,  sg);
    // g1 g2 (split middle bar)
    A[6] = vec2(-W + sg, 0.0);    B[6] = vec2(-sg, 0.0);
    A[7] = vec2( sg, 0.0);        B[7] = vec2( W - sg, 0.0);
    // h i j (top diag, vertical, diag)  k l m (bottom diag, vertical, diag)
    float dg = uThick + sg;
    A[8]  = vec2(-dg,  dg);       B[8]  = vec2(-W + dg,  H - dg);
    A[9]  = vec2(0.0,  dg);       B[9]  = vec2(0.0,  H - dg);
    A[10] = vec2( dg,  dg);       B[10] = vec2( W - dg,  H - dg);
    A[11] = vec2(-dg, -dg);       B[11] = vec2(-W + dg, -H + dg);
    A[12] = vec2(0.0, -dg);       B[12] = vec2(0.0, -H + dg);
    A[13] = vec2( dg, -dg);       B[13] = vec2( W - dg, -H + dg);

    vec3 cellC = texture(sTD2DInputs[0], (id + 0.5) * cell / res).rgb;
    int  ramp  = DIGIT_RAMP[int(clamp(luma(cellC), 0.0, 0.999) * 9.0)];
    int  tmask = uSource > 0.5 ? textMask(ivec2(id), ivec2(res / cell)) : 0;
    int  n     = (uSource > 0.5 || uDiag > 0.5) ? 14 : 8;

    vec3 col = vec3(0.0);
    for (int i = 0; i < n; i++) {
        float t    = i < 8 ? uThick : uThick * 0.8;
        float d    = sdSeg(p, A[i], B[i], t);
        float fill = 1.0 - smoothstep(-px, px, d);

        vec3 src;
        float on;
        if (uSource > 0.5 && uSource < 1.5) {           // text
            src = cellC;
            on  = bitOn(tmask, i);
        } else if (uMode < 0.5 || uSource > 1.5) {      // video per-segment / reveal
            src = texture(sTD2DInputs[0],
                          digitToUV((A[i] + B[i]) * 0.5, id, cell, res, s)).rgb;
            on  = smoothstep(uThresh - uSoft - 1e-4, uThresh + uSoft + 1e-4, luma(src));
            if (uSource > 1.5) on *= bitOn(tmask, i);
        } else {                                        // video digit ramp
            src = cellC;
            on  = bitOn(ramp, i);
        }

        vec3  c    = mix(uLedColor, src, uUseSrcColor);
        float glow = uGlow * on * exp(-max(d, 0.0) * 12.0);
        col += c * (fill * mix(uGhost, 1.0, on) + glow);
    }

    fragColor = TDOutputSwizzle(vec4(col, 1.0));
}
'''

COMP_NAME = 'seven_segment'
warnings = []


def try_set(o, parname, value=None, expr=None):
    p = getattr(o.par, parname, None)
    if p is None:
        warnings.append('{}: no parameter "{}"'.format(o.path, parname))
        return
    if expr is not None:
        p.expr = expr
        p.mode = ParMode.EXPRESSION
    else:
        p.val = value


def set_uniform(glsl, i, name, exprs):
    seq = getattr(glsl.seq, 'vec', None) if hasattr(glsl, 'seq') else None
    if seq is not None:
        if seq.numBlocks <= i:
            seq.numBlocks = i + 1
        try_set(glsl, 'vec{}name'.format(i), name)
        for c, e in zip('xyzw', exprs):
            try_set(glsl, 'vec{}value{}'.format(i, c), expr=e)
    else:
        try_set(glsl, 'uniname{}'.format(i), name)
        for c, e in zip('xyzw', exprs):
            try_set(glsl, 'value{}{}'.format(i, c), expr=e)


def add_float(page, name, label, default, lo, hi):
    p = page.appendFloat(name, label=label)[0]
    p.default = default
    p.val = default
    p.normMin, p.normMax = lo, hi
    p.min, p.clampMin = lo, True
    return p


def add_int(page, name, label, default, lo, hi):
    p = page.appendInt(name, label=label)[0]
    p.default = default
    p.val = default
    p.normMin, p.normMax = lo, hi
    p.min, p.clampMin = lo, True
    return p


def add_toggle(page, name, label, default):
    p = page.appendToggle(name, label=label)[0]
    p.default = default
    p.val = default
    return p


def add_menu(page, name, label, names, labels, default):
    m = page.appendMenu(name, label=label)[0]
    m.menuNames = names
    m.menuLabels = labels
    m.default = default
    m.val = default
    return m


def build():
    host = me.parent()
    for n in (COMP_NAME, 'seg_src', COMP_NAME + '_out'):
        old = host.op(n)
        if old:
            old.destroy()

    x0, y0 = me.nodeX + 250, me.nodeY

    src = host.create(moviefileinTOP, 'seg_src')
    src.nodeX, src.nodeY = x0, y0

    comp = host.create(baseCOMP, COMP_NAME)
    comp.nodeX, comp.nodeY = x0 + 200, y0

    out = host.create(nullTOP, COMP_NAME + '_out')
    out.nodeX, out.nodeY = x0 + 400, y0

    # ---- Custom parameters ----
    page = comp.appendCustomPage('Source')
    add_menu(page, 'Source', 'Source', ['video', 'text', 'textvideo'],
             ['Video', 'Text', 'Text x Video (reveal)'], 'video')
    add_menu(page, 'Videomode', 'Video Mode', ['segments', 'ramp'],
             ['Per-Segment Sampling', 'Digit Ramp'], 'segments')
    add_float(page, 'Thresh', 'Threshold', 0.45, 0, 1)
    add_float(page, 'Soft', 'Softness', 0.05, 0, 0.5)
    add_toggle(page, 'Diag', '14-Segment Extras (Video)', False)
    add_float(page, 'Preblur', 'Input Pre-Blur', 2, 0, 32)

    page = comp.appendCustomPage('Text')
    t = page.appendStr('Text', label='Text')[0]
    t.default = 'HELLO WORLD'
    t.val = 'HELLO WORLD'
    page.appendDAT('Textdat', label='Text DAT (overrides)')
    add_menu(page, 'Layout', 'Layout', ['repeat', 'place'],
             ['Repeat (fill grid)', 'Place'], 'repeat')
    add_int(page, 'Spacing', 'Repeat Spacing', 1, 0, 16)
    add_int(page, 'Stagger', 'Repeat Row Stagger', 0, -16, 16)
    add_toggle(page, 'Center', 'Center (Place)', True)
    add_int(page, 'Posx', 'Position X (cells)', 0, -64, 64)
    add_int(page, 'Posy', 'Position Y (cells, down)', 0, -64, 64)
    add_float(page, 'Scrollspeed', 'Scroll Speed (chars/s)', 0, -20, 20)
    add_float(page, 'Scrolloffset', 'Scroll Offset (chars)', 0, -100, 100)

    page = comp.appendCustomPage('Display')
    add_float(page, 'Cellw', 'Cell Width (px)', 16, 4, 128)
    add_float(page, 'Gap', 'Cell Gap', 0.1, 0, 0.4)
    add_float(page, 'Thick', 'Segment Thickness', 0.1, 0.02, 0.25)
    add_float(page, 'Seggap', 'Segment Gap', 0.04, 0, 0.15)
    add_float(page, 'Slant', 'Slant', 0.12, -0.5, 0.5)
    add_float(page, 'Ghost', 'Unlit Brightness', 0.07, 0, 1)
    add_float(page, 'Glow', 'Glow', 0.3, 0, 2)
    lc = page.appendRGB('Ledcolor', label='LED Color')
    for p, v in zip(lc, (1.0, 0.15, 0.05)):
        p.default = v
        p.val = v
    add_toggle(page, 'Usesrccolor', 'Use Source Color', False)

    # ---- Interior ----
    in1 = comp.create(inTOP, 'in1')
    in1.nodeX, in1.nodeY = 0, 0

    blur = comp.create(blurTOP, 'preblur')
    blur.nodeX, blur.nodeY = 200, 0
    in1.outputConnectors[0].connect(blur.inputConnectors[0])
    try_set(blur, 'size', expr='parent().par.Preblur')

    # Text -> mask texture (one pixel per character)
    cb = comp.create(textDAT, 'text_masks_callbacks')
    cb.nodeX, cb.nodeY = 200, -350
    cb.text = TEXT_CALLBACKS
    masks = comp.create(scriptTOP, 'text_masks')
    masks.nodeX, masks.nodeY = 200, -200
    for d in list(masks.docked):
        d.destroy()
    try_set(masks, 'callbacks', cb.name)
    try_set(masks, 'format', 'rgba32float')   # masks up to 16383 must stay exact

    pixel = comp.create(textDAT, 'segment_pixel')
    pixel.nodeX, pixel.nodeY = 400, -250
    pixel.text = SHADER

    glsl = comp.create(glslTOP, 'segment_glsl')
    glsl.nodeX, glsl.nodeY = 400, 0
    for d in list(glsl.docked):
        d.destroy()
    blur.outputConnectors[0].connect(glsl.inputConnectors[0])    # input 0
    masks.outputConnectors[0].connect(glsl.inputConnectors[1])   # input 1
    try_set(glsl, 'pixeldat', pixel.name)
    try_set(glsl, 'format', 'rgba16float')
    try_set(glsl, 'outputresolution', 'useinput')

    P = 'parent().par.'
    uniforms = [
        ('uCellW',       [P + 'Cellw']),
        ('uGap',         [P + 'Gap']),
        ('uThick',       [P + 'Thick']),
        ('uSegGap',      [P + 'Seggap']),
        ('uSlant',       [P + 'Slant']),
        ('uSource',      [P + 'Source.menuIndex']),
        ('uMode',        [P + 'Videomode.menuIndex']),
        ('uThresh',      [P + 'Thresh']),
        ('uSoft',        [P + 'Soft']),
        ('uGhost',       [P + 'Ghost']),
        ('uDiag',        ['float(' + P + 'Diag)']),
        ('uGlow',        [P + 'Glow']),
        ('uLedColor',    [P + 'Ledcolorr', P + 'Ledcolorg', P + 'Ledcolorb']),
        ('uUseSrcColor', ['float(' + P + 'Usesrccolor)']),
        ('uLayout',      [P + 'Layout.menuIndex']),
        ('uTextPos',     [P + 'Posx', P + 'Posy']),
        ('uCenter',      ['float(' + P + 'Center)']),
        ('uScroll',      [P + 'Scrolloffset + absTime.seconds * ' + P + 'Scrollspeed']),
        ('uStagger',     [P + 'Stagger']),
    ]
    for i, (name, exprs) in enumerate(uniforms):
        set_uniform(glsl, i, name, exprs)

    o = comp.create(outTOP, 'out1')
    o.nodeX, o.nodeY = 600, 0
    glsl.outputConnectors[0].connect(o.inputConnectors[0])

    # External wiring (after in1/out1 exist)
    src.outputConnectors[0].connect(comp.inputConnectors[0])
    comp.outputConnectors[0].connect(out.inputConnectors[0])
    out.viewer = True

    print('[seven_segment] built at', comp.path,
          '- set seg_src to your video, then pick Source on the Source page')
    for g in (masks, glsl):
        if g.errors() or g.warnings():
            print('[seven_segment] {} messages:'.format(g.name), g.errors(), g.warnings())
    for w in warnings:
        print('[seven_segment] warning:', w)


build()
