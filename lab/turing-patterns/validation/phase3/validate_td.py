"""Text DAT module: start(component, output_dir). Product needs no NumPy; tests do."""
import json
import math
from pathlib import Path
import numpy as np

TOL = 1e-6
OUTPUTS = ('state', 'palette', 'out1', 'patterns', 'mask_preview', 'source_preview')


def image(name):
    C.op(name).cook(force=True)
    return C.op(name).numpyArray(delayed=False).copy()


def configure(**settings):
    controls = C.op('controls')
    controls.par.active = False
    controls.cook(force=True)
    try:
        for name, value in settings.items():
            C.par[name].val = value
    finally:
        controls.par.active = True
        controls.cook(force=True)


def reset(**settings):
    configure(Clockmode='framestepped', Renderfps=60, Speed=1, Pause=False,
              Resolution=64, Rectangle=False, Cellsize=1, Solverquality=1,
              Ambient=False, Feed=.0545, Kill=.062, Diffusiona=1, Diffusionb=.5,
              Influencemode='stamp', Strength=5, Fade=0, Dyeinject=0, Dyedecay=0,
              Dyespread=0, Transform=False, Sourcetop=SOURCE.path,
              Domaintop='', Domainboundary='noflux', Domainthreshold=.5, Domaininvert=False,
              Maskmode='alpha', Maskgain=1, Smoothing=0, Mediascale=1,
              Sourcepremult=False, Ignorealpha=False, Colormode='dye',
              Feedmin=.025, Feedmax=.065, Killmin=.045, Killmax=.07, Chemistryblend=1,
              Dyesource='alpha', Stampamount=1, **settings)
    # Parameter callbacks are disabled during configure, so reset is intentional once.
    C.op('clock').module.reset(C)


def set_seed(code):
    C.op('seed').par.pixeldat.eval().text = code


def seed_uniform(a=1, b=0, ca=0, cb=0):
    set_seed('out vec4 fragColor; void main(){fragColor=TDOutputSwizzle(vec4(%s,%s,%s,%s));}'
             % tuple(float(v) for v in (a, b, ca, cb)))


def evolve(ticks):
    for _ in range(ticks):
        C.op('clock').module.advance(C)
    return image('state')


def check(name, passed, **metrics):
    REPORT['checks'][name] = dict(passed=bool(passed), **metrics)
    print('PHASE3_CHECK', name, bool(passed))


def fixture(name, code):
    shader = C.parent().create(glslTOP, name)
    dat = C.parent().create(textDAT, name + '_pixel')
    dat.text = code
    shader.par.pixeldat = dat.name
    shader.par.outputresolution = 'custom'
    shader.par.resolutionw = 64
    shader.par.resolutionh = 64
    shader.par.format = 'rgba32float'
    shader.viewer = True
    return shader


def start(c, output_dir):
    global C, ROOT, REPORT, SOURCE, DOMAIN, SEED, TASKS
    C, ROOT = c, Path(output_dir)
    ROOT.mkdir(parents=True, exist_ok=True)
    C.op('clock').par.active = False
    REPORT = {'build': str(app.version)+'.'+str(app.build), 'tolerance': TOL, 'checks': {}}
    SEED = C.op('seed').par.pixeldat.eval().text
    SOURCE = fixture('influence_source', '''out vec4 fragColor;
    uniform float uSample;
    void main(){
        vec2 p=vUV.st-vec2(.5+.12*sin(uSample*.07), .5);
        float alpha=(1.0-smoothstep(.18,.24,length(p)))*.65;
        fragColor=TDOutputSwizzle(vec4(.1+.8*vUV.s,.2+.6*vUV.t,.25,alpha));
    }''')
    SOURCE.seq.vec.numBlocks = 1
    SOURCE.par.vec0name = 'uSample'
    SOURCE.par.vec0valuex = 0
    DOMAIN = fixture('domain_fixture', '''out vec4 fragColor;
    void main(){ivec2 p=ivec2(gl_FragCoord.xy);
        float open=(p.x>1 && p.x<62 && p.y>1 && p.y<62 && p.x!=32)?1.0:0.0;
        fragColor=TDOutputSwizzle(vec4(vec3(open),1.0));}''')
    TASKS = [stamp_checks, chemistry_checks, domain_checks, color_checks, replay_checks, pulse_start]
    run('args[0].module.next_test()', me, delayFrames=2)


def next_test():
    if not TASKS:
        finish()
        return
    TASKS.pop(0)()
    (ROOT/'progress.json').write_text(json.dumps(REPORT, indent=2))
    if TASKS:
        run('args[0].module.next_test()', me, delayFrames=2)


def stamp_checks():
    reset()
    before=image('state')
    configure(Pause=True)
    history={n:image(n) for n in ('palette','media_cache','media_previous')}
    stamp=C.op('clock').module.stamp
    applied=stamp(C)
    after=image('state')
    m=image('stamp_mask')[:,:,0]
    expected=before.copy()
    expected[:,:,0] += (.5-before[:,:,0])*m
    expected[:,:,1] += (.25-before[:,:,1])*m
    diff=float(np.max(np.abs(after-expected)))
    check('stamp_exact_current_mask', applied and diff<TOL, max_abs=diff)
    check('stamp_no_time_or_history', C.fetch('Clockstate')['ticks']==0 and
          all(np.array_equal(a,image(n)) for n,a in history.items()))
    for _ in range(4): C.op('clock').module.advance(C, elapsed=10)
    check('paused_stamp_holds', np.array_equal(after,image('state')))
    configure(Pause=False)
    grown=evolve(30)
    check('stamp_evolves_without_reinjection', not np.array_equal(grown,after),
          max_abs=float(np.max(np.abs(grown-after))))
    # Zero chemistry isolates the absence of auto-injection in stamp mode.
    reset()
    configure(Feed=0,Kill=0,Diffusiona=0,Diffusionb=0)
    evolve(12)
    check('stamp_mode_never_auto_injects', np.array_equal(image('state'),before))
    configure(Influencemode='continuous')
    continuous=evolve(12)
    check('continuous_injects_every_tick', float(continuous[:,:,1].max())>0)
    frozen=image('state')
    check('stamp_noop_other_modes', not stamp(C) and np.array_equal(frozen,image('state')))
    # True live sample: alter alpha without advancing sampled history.
    configure(Influencemode='stamp',Pause=True,Stampamount=.4)
    SOURCE.par.vec0valuex=21
    prior=image('state')
    stamp(C)
    current=image('state')
    mask=image('stamp_mask')[:,:,0]*.4
    expected=prior.copy()
    expected[:,:,:2] += (np.array([.5,.25])-prior[:,:,:2])*mask[:,:,None]
    check('stamp_partial_amount_live_sample', np.max(np.abs(current-expected))<TOL)


def chemistry_checks():
    global SEED
    seed_uniform(.6,.2)
    old_source=SOURCE.par.pixeldat.eval().text
    SOURCE.par.pixeldat.eval().text='''out vec4 fragColor; void main(){
        float m=gl_FragCoord.x<32.0?.2:.8;
        fragColor=TDOutputSwizzle(vec4(vec3(m),1.0));}'''
    reset()
    configure(Influencemode='chemistry',Maskmode='bright',Diffusiona=0,Diffusionb=0,
              Feedmin=.02,Feedmax=.08,Killmin=.04,Killmax=.07)
    result=evolve(1)
    expected=[]
    for mask in (.2,.8):
        a,b=.6,.2
        feed=.02+.06*mask; kill=.04+.03*mask
        for _ in range(16):
            reaction=a*b*b
            a,b=max(0,min(1,a-reaction+feed*(1-a))),max(0,min(1,b+reaction-(feed+kill)*b))
        expected.append([a,b])
    actual=np.array([result[32,16,:2],result[32,48,:2]])
    diff=float(np.max(np.abs(actual-np.array(expected))))
    check('chemistry_matches_local_rate_oracle', diff<TOL, max_abs=diff, values=actual.tolist())
    check('chemistry_spatially_different', np.max(np.abs(actual[0]-actual[1]))>.001)
    reset()
    configure(Influencemode='chemistry',Chemistryblend=0)
    zero=evolve(30)
    reset()
    baseline=evolve(30)
    check('chemistry_zero_blend_uniform_baseline', np.max(np.abs(zero-baseline))<TOL)
    reset()
    configure(Influencemode='chemistry',Sourcetop='')
    absent=evolve(30)
    reset()
    configure(Sourcetop='')
    uniform=evolve(30)
    check('chemistry_no_source_uniform_baseline', np.max(np.abs(absent-uniform))<TOL)
    SOURCE.par.pixeldat.eval().text='out vec4 fragColor; void main(){fragColor=TDOutputSwizzle(vec4(.8,.8,.8,0));}'
    reset()
    configure(Influencemode='chemistry')
    transparent=evolve(30)
    check('chemistry_transparent_uniform_baseline', np.max(np.abs(transparent-uniform))<TOL)
    # Descending ranges and fractional blend, with fractional source alpha.
    SOURCE.par.pixeldat.eval().text='out vec4 fragColor; void main(){fragColor=TDOutputSwizzle(vec4(.8,.8,.8,.5));}'
    reset()
    configure(Influencemode='chemistry',Maskmode='bright',Diffusiona=0,Diffusionb=0,
              Chemistryblend=.6,Feedmin=.08,Feedmax=.02,Killmin=.07,Killmax=.04)
    result=evolve(1)[32,32,:2]
    a,b=.6,.2
    feed=.0545*(1-.3)+(.08+(.02-.08)*.4)*.3
    kill=.062*(1-.3)+(.07+(.04-.07)*.4)*.3
    for _ in range(16):
        reaction=a*b*b
        a,b=a-reaction+feed*(1-a),b+reaction-(feed+kill)*b
    check('chemistry_reversed_ranges_alpha_blend', np.max(np.abs(result-np.array([a,b])))<TOL)
    SOURCE.par.pixeldat.eval().text=old_source
    set_seed(SEED)


def domain_checks():
    original_domain=DOMAIN.par.pixeldat.eval().text
    # Closed outer rim and full-height one-cell partition, both local and wrap tests.
    for edge in ('clear','wrap'):
        for boundary in ('noflux','empty'):
            for mode in ('continuous','stamp','chemistry'):
                reset()
                configure(Domaintop=DOMAIN.path,Domainboundary=boundary,Transformedge=edge,
                          Influencemode=mode,Ambient=True)
                C.op('clock').module.reset(C)
                mask=image('domain_mask')[:,:,0]>.5
                initial=image('state')
                check('domain_seed_'+edge+'_'+boundary+'_'+mode,
                      np.max(np.abs(initial[~mask]-np.array([1,0,0,0])))<TOL and initial[:,:,1].max()>0)
                if mode=='stamp': C.op('clock').module.stamp(C)
                result=evolve(20)
                check('domain_empty_'+edge+'_'+boundary+'_'+mode,
                      np.max(np.abs(result[~mask]-np.array([1,0,0,0])))<TOL and np.isfinite(result).all())
    # Independent initial state on the left. Nothing can arrive on the right.
    set_seed('''out vec4 fragColor; void main(){
        bool seeded=gl_FragCoord.x>25.0 && gl_FragCoord.x<32.0;
        fragColor=TDOutputSwizzle(seeded?vec4(.5,.25,-.12,.08):vec4(1,0,0,0));}''')
    for boundary in ('noflux','empty'):
        for moving in (False,True):
            reset()
            configure(Domaintop=DOMAIN.path,Domainboundary=boundary,Transformedge='clear',
                      Transform=moving,Grow=0,Scalex=0,Scaley=0,Rotate=0,Translatex=240,Translatey=0,
                      Dyespread=665,Feed=0,Kill=0)
            C.op('clock').module.reset(C)
            initial=image('state')
            check('barrier_shader_'+boundary+str(moving), 'Compiled Successfully' in C.op('seed_info').text and 'ERROR' not in C.op('seed_info').text)
            check('barrier_fixture_active_'+boundary+str(moving), initial[2:62,26:32,1].max()>0)
            result=evolve(30)
            leaked=float(np.max(np.abs(result[2:62,33:62,1:])))
            check('impermeable_'+boundary+('_moving' if moving else '_diffusion'), leaked<TOL,
                  max_leaked=leaked)
    # No Flux conserves a pure B diffusion impulse; Empty Exterior drains it.
    seed_uniform(0,.2,-.12,.08)
    totals={}
    for boundary in ('noflux','empty'):
        reset()
        configure(Domaintop=DOMAIN.path,Domainboundary=boundary,Feed=0,Kill=0,
                  Diffusiona=0,Diffusionb=.5,Transformedge='clear')
        C.op('clock').module.reset(C)
        # First tick empties outside the domain for this intentionally unconstrained test seed.
        evolve(1)
        before=image('state')[:,:,1].sum()
        totals[boundary]=float(evolve(30)[:,:,1].sum())
        if boundary=='noflux':
            check('noflux_pure_diffusion_mass', before>0 and abs(totals[boundary]-float(before))<.001,
                  before=float(before),after=totals[boundary])
    check('empty_exterior_is_sink', totals['empty']<totals['noflux']*.95, totals=totals)
    # Two diagonally touching pixels cannot communicate through blocked corners.
    DOMAIN.par.pixeldat.eval().text='''out vec4 fragColor;void main(){ivec2 p=ivec2(gl_FragCoord.xy);
        float open=(p==ivec2(16,16)||p==ivec2(17,17))?1.0:0.0;
        fragColor=TDOutputSwizzle(vec4(vec3(open),1));}'''
    set_seed('''out vec4 fragColor;void main(){ivec2 p=ivec2(gl_FragCoord.xy);
        fragColor=TDOutputSwizzle(p==ivec2(16,16)?vec4(0,.25,-.12,.08):vec4(1,0,0,0));}''')
    reset()
    configure(Domaintop=DOMAIN.path,Dyespread=665,Transformedge='clear')
    C.op('clock').module.reset(C)
    result=evolve(20)
    check('diagonal_corner_no_leak', np.max(np.abs(result[17,17]-np.array([1,0,0,0])))<TOL)
    DOMAIN.par.pixeldat.eval().text=original_domain
    set_seed(SEED)
    # Paused domain changes do not mutate evolving state until deliberate work.
    reset()
    configure(Pause=True,Domaintop=DOMAIN.path)
    before=image('state')
    for _ in range(3): C.op('clock').module.advance(C,elapsed=10)
    check('domain_change_pause_holds', np.array_equal(before,image('state')))
    # Threshold/invert and normalized UV work for rectangular/coarse grids.
    reset()
    configure(Rectangle=True,Canvaswidth=192,Canvasheight=128,Cellsize=2,
              Domaintop=DOMAIN.path,Domaininvert=False)
    C.op('clock').module.reset(C)
    normal=image('domain_mask')[:,:,0]
    configure(Domaininvert=True)
    inverse=image('domain_mask')[:,:,0]
    check('domain_rectangular_coarse_inversion', normal.shape==(64,96) and np.array_equal(normal+inverse,np.ones_like(normal)))


def color_checks():
    original=SOURCE.par.pixeldat.eval().text
    SOURCE.par.pixeldat.eval().text='out vec4 fragColor;void main(){fragColor=TDOutputSwizzle(vec4(.9,.1,.1,.5));}'
    cases={}
    for gate in ('alpha','mask'):
        for mode in ('continuous','stamp','chemistry'):
            reset()
            configure(Influencemode=mode,Dyesource=gate,Maskmode='alpha',Maskgain=0,
                      Strength=0,Dyeinject=5)
            result=evolve(4)
            cases[gate+'_'+mode]=float(np.max(np.abs(result[:,:,2:])))
    check('color_alpha_independent_injection', all(v>.001 for k,v in cases.items() if k.startswith('alpha')), values=cases)
    check('color_mask_gate_zero', all(v==0 for k,v in cases.items() if k.startswith('mask')))
    reset()
    configure(Dyesource='mask',Maskmode='alpha',Dyeinject=5,Strength=0,Stampamount=1,Pause=True)
    C.op('clock').module.stamp(C)
    check('stamp_preserves_carried_color', np.array_equal(image('state')[:,:,2:],np.zeros((64,64,2))))
    configure(Pause=False)
    colored=evolve(4)
    check('color_mask_injects_with_strength_zero', np.max(np.abs(colored[:,:,2:]))>.001)
    SOURCE.par.pixeldat.eval().text=original


def sample(c,tick,seconds):
    SOURCE.par.vec0valuex=tick


def replay_checks():
    rows=[]
    for mode in ('continuous','stamp','chemistry'):
        for gate in ('alpha','mask'):
            values=[]
            for fps in (30,60):
                reset()
                configure(Influencemode=mode,Dyesource=gate,Domaintop=DOMAIN.path,
                          Rectangle=True,Canvaswidth=192,Canvasheight=128,Cellsize=2,
                          Renderfps=fps,Dyeinject=3,Dyespread=665,Maskmode='bright',
                          Transform=True,Grow=3,Rotate=6,Translatex=3,Translatey=-2)
                SOURCE.par.vec0valuex=0
                C.op('clock').module.reset(C)
                if mode=='stamp': C.op('clock').module.stamp(C)
                for _ in range(fps): C.op('clock').module.advance(C,sample=sample)
                values.append({name:image(name) for name in OUTPUTS})
            diffs={name:float(np.max(np.abs(values[0][name]-values[1][name]))) for name in OUTPUTS}
            rows.append(dict(mode=mode,color_source=gate,max_abs=diffs))
            check('replay_30_60_'+mode+'_'+gate, all(v<TOL for v in diffs.values()), max_abs=diffs)
            state=values[1]['state']
            check('finite_bounded_'+mode+'_'+gate, np.isfinite(state).all() and state[:,:,:2].min()>=0 and state[:,:,:2].max()<=1)
    REPORT['replays']=rows


def pulse_start():
    reset()
    configure(Pause=True,Influencemode='stamp')
    C.op('clock').module.reset(C)
    C.store('Stampbefore',image('state'))
    run('args[0].module.pulse_stamp()',me,delayFrames=3)


def pulse_stamp():
    C.par.Stamp.pulse()
    run('args[0].module.pulse_finish()',me,delayFrames=3)


def pulse_finish():
    check('actual_stamp_pulse_once', not np.array_equal(image('state'),C.fetch('Stampbefore')) and C.fetch('Clockstate')['ticks']==0)
    C.store('Stampafter',image('state'))
    run('args[0].module.finish()',me,delayFrames=3)


def finish():
    check('actual_stamp_pulse_holds', np.array_equal(image('state'),C.fetch('Stampafter')))
    for n in C.children:
        if n.family=='TOP': n.cook(force=True)
    REPORT['errors']={n.name:n.errors() for n in C.children if n.errors()}
    REPORT['shaders']={n.name:n.text for n in C.children if n.family=='DAT' and n.name.endswith('_info')}
    check('no_unexpected_operator_errors', not any(n!='movie' for n in REPORT['errors']))
    check('all_shaders_compile', all('Compiled Successfully' in t for t in REPORT['shaders'].values()))
    REPORT['passed']=all(row['passed'] for row in REPORT['checks'].values())
    (ROOT/'report.json').write_text(json.dumps(REPORT,indent=2))
    C.op('out1').save(str(ROOT/'preview.png'))
    print('PHASE3_COMPLETE',REPORT['passed'])
