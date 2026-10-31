# Build a Tile Mosaic filter network in TouchDesigner.
# Paste into a Text DAT and run it (Ctrl+R).
# Creates, next to this DAT:
#   mosaic_src (video)   ─┐
#                          ├─> tile_mosaic (Base COMP) -> tile_mosaic_out
#   mosaic_atlas (texture)┘
# The atlas texture is cut into a grid of square tiles; each output cell
# picks a tile from the video's brightness (and optionally hue).
# In "Sorted" mapping the tiles are re-ranked by brightness every time the
# atlas cooks (every frame for a movie atlas), so dark cells get dark tiles.
# Re-running deletes and rebuilds the network.

# Pass 1: average luma of each atlas tile. Output is one pixel per tile.
LUMA_SHADER = r'''
out vec4 fragColor;

void main() {
    vec2 n    = uTDOutputInfo.res.zw;
    vec2 tile = floor(gl_FragCoord.xy);
    float sum = 0.0;
    for (int j = 0; j < 8; j++)
        for (int i = 0; i < 8; i++) {
            vec3 c = texture(sTD2DInputs[0], (tile + (vec2(i, j) + 0.5) / 8.0) / n).rgb;
            sum += dot(c, vec3(0.2126, 0.7152, 0.0722));
        }
    fragColor = TDOutputSwizzle(vec4(sum / 64.0, 0.0, 0.0, 1.0));
}
'''

# Pass 2: brightness rank of each tile (ties broken by index -> unique ranks).
RANK_SHADER = r'''
out vec4 fragColor;

void main() {
    ivec2 sz = textureSize(sTD2DInputs[0], 0);
    ivec2 p  = ivec2(gl_FragCoord.xy);
    int   me = p.y * sz.x + p.x;
    float l  = texelFetch(sTD2DInputs[0], p, 0).r;
    int rank = 0;
    for (int j = 0; j < sz.y; j++)
        for (int i = 0; i < sz.x; i++) {
            float o = texelFetch(sTD2DInputs[0], ivec2(i, j), 0).r;
            int   k = j * sz.x + i;
            if (o < l || (o == l && k < me)) rank++;
        }
    fragColor = TDOutputSwizzle(vec4(float(rank), 0.0, 0.0, 1.0));
}
'''

# Pass 3: invert the ranks. Pixel k holds the (x, y) of the k-th darkest tile.
SORT_SHADER = r'''
out vec4 fragColor;

void main() {
    ivec2 sz  = textureSize(sTD2DInputs[0], 0);
    ivec2 p   = ivec2(gl_FragCoord.xy);
    float k   = float(p.y * sz.x + p.x);
    vec2 tile = vec2(0.0);
    for (int j = 0; j < sz.y; j++)
        for (int i = 0; i < sz.x; i++)
            if (texelFetch(sTD2DInputs[0], ivec2(i, j), 0).r == k) tile = vec2(i, j);
    fragColor = TDOutputSwizzle(vec4(tile, 0.0, 1.0));
}
'''

SHADER = r'''
// Tile Mosaic — TouchDesigner GLSL TOP
// Input 0: video (pre-blurred)   Input 1: atlas texture (resized to ~tile res)
// Input 2: sorted tile lookup (one pixel per tile; its size defines the grid)

uniform float uCellW;       // output cell size in px
uniform float uMapping;     // 0 = scan, 1 = diagonal, 2 = luma x hue, 3 = sorted
uniform float uMatch;       // 0 = raw tile, 1 = rescale tile to cell brightness
uniform float uTint;        // 0 = tile color, 1 = recolor tile with source color
uniform float uGrout;       // grout width, fraction of cell
uniform vec3  uGroutColor;
uniform float uRotate;      // 1 = random 90° rotation per cell

out vec4 fragColor;

float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }

vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + 1e-10)), d / (q.x + 1e-10), q.x);
}

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

void main() {
    vec2 res  = uTDOutputInfo.res.zw;
    vec2 g    = vUV.st * res / uCellW;
    vec2 id   = floor(g);
    vec2 f    = fract(g);

    vec3  src = texture(sTD2DInputs[0], (id + 0.5) * uCellW / res).rgb;
    float L   = clamp(luma(src), 0.0, 0.9999);

    // Tile grid comes from the lookup texture (rows follow atlas aspect)
    vec2  n  = vec2(textureSize(sTD2DInputs[2], 0));
    float nx = n.x;
    float ny = n.y;

    vec2 tile;
    if (uMapping < 0.5) {                       // scan: every tile, reading order
        float idx = floor(L * nx * ny);
        tile = vec2(mod(idx, nx), floor(idx / nx));
    } else if (uMapping < 1.5) {                // diagonal: u = v = brightness
        tile = floor(vec2(L) * n);
    } else if (uMapping < 2.5) {                // 2D: u = brightness, v = hue
        float h = clamp(rgb2hsv(src).x, 0.0, 0.9999);
        tile = floor(vec2(L, h) * n);
    } else {                                    // sorted: k-th darkest tile
        float idx = floor(L * nx * ny);
        tile = texelFetch(sTD2DInputs[2], ivec2(int(mod(idx, nx)), int(idx / nx)), 0).rg;
    }

    // Grout inset + edge AA
    float inset = max(1.0 - 2.0 * uGrout, 0.01);
    vec2  q     = (f - 0.5) / inset + 0.5;
    float edge  = min(min(q.x, 1.0 - q.x), min(q.y, 1.0 - q.y)) * uCellW * inset;
    float mask  = clamp(edge + 0.5, 0.0, 1.0);

    if (uRotate > 0.5) {
        int r = int(hash(id) * 4.0);
        for (int i = 0; i < r; i++) q = vec2(1.0 - q.y, q.x);
    }
    q = clamp(q, 0.0, 1.0);

    vec3 col = texture(sTD2DInputs[1], (tile + q) / n).rgb;

    // Tile average (4x4 taps) for brightness matching
    vec3 avg = vec3(0.0);
    for (int j = 0; j < 4; j++)
        for (int i = 0; i < 4; i++)
            avg += texture(sTD2DInputs[1], (tile + (vec2(i, j) + 0.5) / 4.0) / n).rgb;
    avg /= 16.0;

    col = mix(col, col * (L / max(luma(avg), 0.02)), uMatch);
    col = mix(col, luma(col) * src / max(L, 0.02), uTint);

    fragColor = TDOutputSwizzle(vec4(mix(uGroutColor, col, mask), 1.0));
}
'''

COMP_NAME = 'tile_mosaic'
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


def make_pass(comp, name, shader, x, y):
    dat = comp.create(textDAT, name + '_pixel')
    dat.nodeX, dat.nodeY = x, y - 150
    dat.text = shader
    g = comp.create(glslTOP, name)
    g.nodeX, g.nodeY = x, y
    for d in list(g.docked):
        d.destroy()
    try_set(g, 'pixeldat', dat.name)
    try_set(g, 'format', 'rgba32float')   # exact integer ranks up to 2^24
    return g


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


def build():
    host = me.parent()
    for n in (COMP_NAME, 'mosaic_src', 'mosaic_atlas', COMP_NAME + '_out'):
        old = host.op(n)
        if old:
            old.destroy()

    x0, y0 = me.nodeX + 250, me.nodeY

    src = host.create(moviefileinTOP, 'mosaic_src')
    src.nodeX, src.nodeY = x0, y0
    atlas = host.create(moviefileinTOP, 'mosaic_atlas')
    atlas.nodeX, atlas.nodeY = x0, y0 - 150

    comp = host.create(baseCOMP, COMP_NAME)
    comp.nodeX, comp.nodeY = x0 + 200, y0 - 75

    out = host.create(nullTOP, COMP_NAME + '_out')
    out.nodeX, out.nodeY = x0 + 400, y0 - 75

    # ---- Custom parameters ----
    page = comp.appendCustomPage('Mosaic')
    add_float(page, 'Cellw', 'Cell Size (px)', 24, 4, 128)
    add_int(page, 'Tiles', 'Atlas Tiles Across', 16, 1, 64)
    m = page.appendMenu('Mapping', label='Mapping')[0]
    m.menuNames = ['scan', 'diagonal', 'lumahue', 'sorted']
    m.menuLabels = ['Scan (all tiles)', 'Diagonal (u = v)', 'Luma x Hue',
                    'Sorted by brightness']
    m.default = 'sorted'
    m.val = 'sorted'
    add_float(page, 'Match', 'Brightness Match', 1.0, 0, 1)
    add_float(page, 'Tint', 'Source Tint', 0.0, 0, 1)
    add_float(page, 'Grout', 'Grout Width', 0.05, 0, 0.3)
    gc = page.appendRGB('Groutcolor', label='Grout Color')
    for p in gc:
        p.default = 0.05
        p.val = 0.05
    add_toggle(page, 'Rotate', 'Random Rotation', False)
    add_float(page, 'Preblur', 'Input Pre-Blur', 2, 0, 32)

    # ---- Interior ----
    in1 = comp.create(inTOP, 'in1')       # video
    in1.nodeX, in1.nodeY = 0, 0
    in2 = comp.create(inTOP, 'in2')       # atlas
    in2.nodeX, in2.nodeY = 0, -200

    blur = comp.create(blurTOP, 'preblur')
    blur.nodeX, blur.nodeY = 200, 0
    in1.outputConnectors[0].connect(blur.inputConnectors[0])
    try_set(blur, 'size', expr='parent().par.Preblur')

    # Resize atlas so each tile is ~ one output cell (avoids minification shimmer)
    fit = comp.create(resolutionTOP, 'atlas_fit')
    fit.nodeX, fit.nodeY = 200, -200
    in2.outputConnectors[0].connect(fit.inputConnectors[0])
    try_set(fit, 'outputresolution', 'custom')
    try_set(fit, 'resolutionw',
            expr='max(1, int(parent().par.Tiles * parent().par.Cellw))')
    try_set(fit, 'resolutionh',
            expr="max(1, int(parent().par.Tiles * parent().par.Cellw * op('in2').height / max(op('in2').width, 1)))")
    try_set(fit, 'inputfiltertype', 'mipmap')

    # Brightness sort: tile luma -> rank -> sorted lookup (one pixel per tile)
    tluma = make_pass(comp, 'tile_luma', LUMA_SHADER, 200, -500)
    fit.outputConnectors[0].connect(tluma.inputConnectors[0])
    try_set(tluma, 'outputresolution', 'custom')
    try_set(tluma, 'resolutionw', expr='max(1, int(parent().par.Tiles))')
    try_set(tluma, 'resolutionh',
            expr="max(1, int(parent().par.Tiles * op('atlas_fit').height / max(op('atlas_fit').width, 1) + 0.5))")

    trank = make_pass(comp, 'tile_rank', RANK_SHADER, 400, -500)
    tluma.outputConnectors[0].connect(trank.inputConnectors[0])
    try_set(trank, 'outputresolution', 'useinput')

    tsort = make_pass(comp, 'tile_sort', SORT_SHADER, 600, -500)
    trank.outputConnectors[0].connect(tsort.inputConnectors[0])
    try_set(tsort, 'outputresolution', 'useinput')

    pixel = comp.create(textDAT, 'mosaic_pixel')
    pixel.nodeX, pixel.nodeY = 400, -250
    pixel.text = SHADER

    glsl = comp.create(glslTOP, 'mosaic_glsl')
    glsl.nodeX, glsl.nodeY = 400, 0
    for d in list(glsl.docked):
        d.destroy()
    blur.outputConnectors[0].connect(glsl.inputConnectors[0])   # input 0
    fit.outputConnectors[0].connect(glsl.inputConnectors[1])    # input 1
    tsort.outputConnectors[0].connect(glsl.inputConnectors[2])  # input 2
    try_set(glsl, 'pixeldat', pixel.name)
    try_set(glsl, 'format', 'rgba16float')
    try_set(glsl, 'outputresolution', 'useinput')

    P = 'parent().par.'
    uniforms = [
        ('uCellW',      [P + 'Cellw']),
        ('uMapping',    [P + 'Mapping.menuIndex']),
        ('uMatch',      [P + 'Match']),
        ('uTint',       [P + 'Tint']),
        ('uGrout',      [P + 'Grout']),
        ('uGroutColor', [P + 'Groutcolorr', P + 'Groutcolorg', P + 'Groutcolorb']),
        ('uRotate',     ['float(' + P + 'Rotate)']),
    ]
    for i, (name, exprs) in enumerate(uniforms):
        set_uniform(glsl, i, name, exprs)

    o = comp.create(outTOP, 'out1')
    o.nodeX, o.nodeY = 600, 0
    glsl.outputConnectors[0].connect(o.inputConnectors[0])

    # External wiring (after in1/in2/out1 exist)
    src.outputConnectors[0].connect(comp.inputConnectors[0])
    atlas.outputConnectors[0].connect(comp.inputConnectors[1])
    comp.outputConnectors[0].connect(out.inputConnectors[0])
    out.viewer = True

    print('[tile_mosaic] built at', comp.path,
          '- set mosaic_src to your video and mosaic_atlas to your texture')
    for g in (tluma, trank, tsort, glsl):
        if g.errors() or g.warnings():
            print('[tile_mosaic] {} messages:'.format(g.name), g.errors(), g.warnings())
    for w in warnings:
        print('[tile_mosaic] warning:', w)


build()
