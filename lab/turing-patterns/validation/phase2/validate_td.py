"""Run as a Text DAT module: op('validate').module.start(component, output_dir)."""
import json
import math
from pathlib import Path
import numpy as np

OUTPUTS = ('state', 'palette', 'out1', 'patterns', 'mask_preview', 'source_preview')
TOLERANCE = 1e-6


def image(c, name):
    c.op(name).cook(force=True)
    return c.op(name).numpyArray(delayed=False).copy()


def configure(c, **values):
    c.op('controls').par.active = False
    c.op('controls').cook(force=True)
    try:
        for key, value in values.items():
            c.par[key].val = value
    finally:
        c.op('controls').par.active = True
        c.op('controls').cook(force=True)


def source_sample(c, tick, seconds):
    c.parent().op('clock_source').par.vec0valuex = tick


def run_case(c, settings, fps, quality=1):
    configure(c, Clockmode='framestepped', Renderfps=fps, Speed=1, Pause=False,
              Solverquality=quality, **settings)
    source_sample(c, 0, 0)
    clock = c.op('clock').module
    clock.reset(c)
    initial = image(c, 'state')
    for _ in range(fps * 2):
        clock.advance(c, sample=source_sample)
    arrays = {name: image(c, name) for name in OUTPUTS}
    return arrays, {'ticks': c.fetch('Clockstate')['ticks'], 'seconds': float(c.par.Simtime),
                    'evolved': not np.array_equal(initial, arrays['state']),
                    'finite': all(np.isfinite(a).all() for a in arrays.values()),
                    'bounded': bool(np.min(arrays['state'][:,:,:2]) >= 0 and np.max(arrays['state'][:,:,:2]) <= 1)}


def start(c, output_dir):
    global C, ROOT, REPORT, CASES, RESULTS
    C, ROOT = c, Path(output_dir)
    ROOT.mkdir(exist_ok=True, parents=True)
    c.op('clock').par.active = False
    c.viewer = False
    source = c.parent().create(glslTOP, 'clock_source')
    source.par.outputresolution = 'custom'
    source.par.resolutionw = 96
    source.par.resolutionh = 64
    source.par.format = 'rgba32float'
    dat = c.parent().create(textDAT, 'clock_source_pixel')
    dat.text = '''out vec4 fragColor;
    uniform float uSample;
    void main() {
        vec2 p = vUV.st - vec2(.5 + .17*sin(uSample*.09), .5);
        float a = (1.0-smoothstep(.16,.22,length(p))) * .65;
        fragColor=TDOutputSwizzle(vec4(.1+.7*vUV.s,.2+.6*vUV.t,.3+.2*sin(uSample*.07),a));
    }'''
    source.par.pixeldat = dat.name
    source.seq.vec.numBlocks = 1
    source.par.vec0name = 'uSample'
    source.par.vec0valuex = 0
    configure(c, Resolution=64, Rectangle=False, Cellsize=1, Seedradius=5,
              Mediascale=1, Maskmode='alpha', Overlay=0, Smoothing=0,
              Grow=6, Scalex=-2, Scaley=3, Translatex=3, Translatey=-2, Rotate=12,
              Strength=5, Fade=.05, Dyedecay=.2, Clipalpha=1)
    REPORT = {'build': str(app.version)+'.'+str(app.build), 'tolerance': TOLERANCE,
              'duration_seconds': 2, 'cases': [], 'checks': {}}
    CASES = [
        ('coral', dict(Sourcetop='', Feed=.0545, Kill=.062, Colormode='fixed', Transform=False, Rectangle=False, Cellsize=1)),
        ('spots', dict(Sourcetop='', Feed=.0367, Kill=.0649, Colormode='fixed', Transform=False, Rectangle=False, Cellsize=1)),
        *[(mode, dict(Sourcetop=source.path, Feed=.0545, Kill=.062, Colormode=mode,
                     Transform=True, Rectangle=True, Canvaswidth=192, Canvasheight=128, Cellsize=2))
          for mode in ('fixed', 'tint', 'ramp', 'dye')],
        ('motion', dict(Sourcetop=source.path, Maskmode='motion', Transform=True,
                        Rectangle=True, Canvaswidth=192, Canvasheight=128, Cellsize=2))]
    RESULTS = []
    run("args[0].module.next_case()", me, delayFrames=1)


def next_case():
    if not CASES:
        additional()
        return
    name, settings = CASES.pop(0)
    a, sa = run_case(C, settings, 30)
    b, sb = run_case(C, settings, 60)
    diffs = {key: float(np.max(np.abs(a[key]-b[key]))) for key in OUTPUTS}
    REPORT['cases'].append(dict(name=name, fps30=sa, fps60=sb, max_abs=diffs,
                                passed=all(v <= TOLERANCE for v in diffs.values())))
    RESULTS.append(b['state'])
    (ROOT / 'progress.json').write_text(json.dumps(REPORT, indent=2))
    print('PHASE2_CASE', name, diffs, sa, sb)
    run("args[0].module.next_case()", me, delayFrames=1)


def additional():
    c=C
    clock=c.op('clock').module
    check=REPORT['checks']
    configure(c, Pause=True)
    frozen={key:image(c,key) for key in ('state','palette','media_cache','media_previous')}
    for i in range(5):
        source_sample(c, 150+i, 0)
        clock.advance(c, elapsed=10)
        for key, before in frozen.items():
            check['pause_'+key]=bool(np.array_equal(before,image(c,key)))
    before=c.fetch('Clockstate')['ticks']
    clock.step(c)
    check['step_exactly_one_tick']=c.fetch('Clockstate')['ticks']==before+1
    check['step_evolves']=not np.array_equal(frozen['state'],image(c,'state'))
    check['step_stays_paused']=bool(c.par.Pause)
    after=image(c,'state')
    for _ in range(3): clock.advance(c, elapsed=10)
    check['step_then_holds']=bool(np.array_equal(after,image(c,'state')))
    configure(c, Pause=False, Clockmode='realtime', Maxcatchup=3, Speed=1)
    clock.reset(c)
    count=clock.advance(c,elapsed=1)
    check['realtime_capped']=count==3
    check['lag_retained']=abs(float(c.par.Simlag)-.95)<1e-9
    configure(c, Speed=0)
    after=image(c,'state')
    clock.advance(c,elapsed=10)
    check['zero_speed_freezes_debt_and_state']=bool(np.array_equal(after,image(c,'state'))) and abs(float(c.par.Simlag)-.95)<1e-9
    configure(c, Clockmode='framestepped', Speed=1, Renderfps=10, Maxcatchup=1)
    clock.reset(c)
    check['deterministic_uncapped']=clock.advance(c)==6
    configure(c, Speed=.5, Renderfps=60)
    clock.reset(c)
    check['fractional_tick']=clock.advance(c)==0 and clock.advance(c)==1
    configure(c, Pause=True)
    clock.reset(c)
    check['reset_matches_seed']=bool(np.array_equal(image(c,'state'),image(c,'seed')))
    configure(c, Sourcetop='', Ambient=False, Transform=False, Strength=0, Fade=0, Dyedecay=0,
              Pause=False, Speed=1, Maskmode='alpha', Rectangle=False, Resolution=64, Cellsize=1)
    clock.reset(c)
    empty=image(c,'state')
    for _ in range(10): clock.advance(c)
    check['empty_stable']=bool(np.array_equal(empty,image(c,'state')))

    # Uniform B, with no reaction/feed/kill/diffusion, isolates exact recovery
    # and carried-color decay. No nonlinear pattern divergence masks timing errors.
    seed=c.op('seed').par.pixeldat.eval()
    original=seed.text
    seed.text='out vec4 fragColor; void main(){fragColor=TDOutputSwizzle(vec4(0,0.2,-0.1,0.05));}'
    configure(c, Feed=0, Kill=0, Diffusiona=0, Diffusionb=0, Fade=0, Dyedecay=.4, Dyespread=0,
              Dyeinject=0, Renderfps=60)
    quality=[]
    for q in (1,2,4):
        configure(c,Solverquality=q)
        clock.reset(c)
        for _ in range(60): clock.advance(c)
        value=image(c,'state')[0,0]
        quality.append({'quality':q,'ticks':c.fetch('Clockstate')['ticks'], 'value':value.tolist()})
    expected=np.array([0,.2,-.1*math.exp(-.4),.05*math.exp(-.4)])
    check['quality_same_elapsed_time']=all(row['ticks']==60 for row in quality)
    check['quality_decay_matches_analytic']=all(np.max(np.abs(np.array(row['value'])-expected))<1e-6 for row in quality)
    REPORT['quality']=quality
    seed.text=original
    configure(c, Ambient=True, Feed=.0545, Kill=.062, Diffusiona=1, Diffusionb=.5, Fade=0,
              Dyedecay=0, Dyespread=665.4212933375475, Dyeinject=3.0775976632530346,
              Strength=5.00289653634306, Solverquality=1, Pause=True)
    clock.reset(c)
    # Let queued setup value-change notifications finish before testing a pulse.
    run("args[0].module.pulse_step()",me,delayFrames=2)


def pulse_step():
    C.op('clock').module.reset(C)
    C.store('Pulsebefore', image(C, 'state'))
    C.par.Step.pulse()
    run("args[0].module.finish()",me,delayFrames=2)


def finish():
    REPORT['checks']['step_pulse_one_tick'] = C.fetch('Clockstate')['ticks'] == 1
    REPORT['checks']['step_pulse_evolves'] = not np.array_equal(C.fetch('Pulsebefore'), image(C, 'state'))
    errors={node.name:node.errors() for node in C.children if node.errors()}
    REPORT['errors']=errors
    REPORT['shaders']={node.name:node.text for node in C.children if node.name.endswith('_info') and node.family=='DAT'}
    REPORT['checks']['no_unexpected_errors']=not any(key!='movie' for key in errors)
    REPORT['passed']=all(row['passed'] and all(row[fps]['ticks']==120 and row[fps]['finite'] and row[fps]['bounded'] and row[fps]['evolved'] for fps in ('fps30','fps60')) for row in REPORT['cases']) and all(REPORT['checks'].values())
    (ROOT/'report.json').write_text(json.dumps(REPORT,indent=2))
    C.op('out1').save(str(ROOT/'preview.png'))
    print('PHASE2_COMPLETE',REPORT['passed'],REPORT['checks'])
