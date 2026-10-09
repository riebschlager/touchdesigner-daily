"""Live phase 5 checks. Execute start(component, output_dir) from a Text DAT."""
import copy
import hashlib
import json
from pathlib import Path
import traceback
import numpy as np


def image(name):
    node = C.op(name)
    node.cook(force=True)
    return node.numpyArray(delayed=False).copy()


def check(name, passed, **details):
    REPORT['checks'][name] = dict(passed=bool(passed), **details)
    print('PHASE5_CHECK', name, bool(passed))


def equal(name, a, b):
    delta = float(np.max(np.abs(a-b))) if a.shape == b.shape else float('inf')
    check(name, a.shape == b.shape and np.array_equal(a.view(np.uint32), b.view(np.uint32)),
          max_error=delta if np.isfinite(delta) else 'shape mismatch')


def settings(**values):
    C.op('preset_lib').module.set_quietly(C, values)


def reset(**values):
    settings(Resolution=64, Rectangle=False, Cellsize=1, Clockmode='framestepped',
             Renderfps=60., Speed=1., Pause=True, Resizebehavior='reset', Resetonsource=False,
             Moviefile='', Sourcetop=SOURCE.path, Ambient=True, Maskmode='motion',
             Influencemode='continuous', Strength=5., Dyeinject=3., Dyespread=100.,
             Dyedecay=0., Fade=0., Transform=False, Mediascale=1., Smoothing=0.)
    settings(**values)
    CLOCK.reset(C)


def ticks(n, offset=0):
    for i in range(n):
        SOURCE.par.vec0valuex = offset+i
        CLOCK.tick(C)
    CLOCK.rebase(C)


def sentinel():
    y, x = np.mgrid[0:64, 0:64]
    a = np.empty((64,64,4), dtype=np.float32)
    a[:,:,0] = .7 + x / 500.
    a[:,:,1] = .1 + y / 700.
    a[:,:,2] = (x - 32) / 128.
    a[:,:,3] = (y - 32) / 64.
    raw = a.astype('<f4').tobytes()
    node = SNAP.upload(C, raw, list(a.shape))
    for name in ('state_a','state_b'):
        CLOCK.capture(C.op(name), node)
    CLOCK._clock(C)['buffer'] = 0
    C.op('state_read').par.top = 'state_a'
    return a


def saved_images():
    return {name:image(name) for name in SNAP.TEXTURES + ('state','palette','mask_preview','patterns','out1')}


def snapshots():
    reset()
    ticks(5)
    original = sentinel()
    equal('signed upload preserves raw rgba including negative alpha', image('state'), original)
    CLOCK._clock(C)['debt'] = .003
    snap = SNAP.capture(C)
    before = saved_images()
    SNAP.action(C, 'Savestate')
    ticks(8, 20)
    settings(Feed=.032, Contrast=1.1, Pause=False, Rectangle=True, Canvaswidth=96,
             Canvasheight=64, Cellsize=2.)
    CLOCK.ensure_size(C)
    check('state changed after subsequent evolution', not np.array_equal(image('state'), before['state']))
    check('memory restore action succeeds', SNAP.action(C, 'Restorestate'))
    for name, old in before.items():
        if name != 'out1':
            equal('memory restore exact '+name, old, image(name))
    check('external live source overlay continues independently', not np.array_equal(before['out1'],image('out1')))
    SOURCE.par.vec0valuex = 4
    equal('controlled source restores final output',before['out1'],image('out1'))
    check('pause dimensions settings clock restored', bool(C.par.Pause) and
          tuple(C.fetch('Appliedsize')) == (64,64,64,64) and C.par.Feed.eval() == snap['metadata']['settings']['Feed']
          and CLOCK._clock(C)['ticks'] == 5 and CLOCK._clock(C)['debt'] == .003)
    # Test state parity differing from palette parity (clear/stamp don't update palette).
    CLOCK.clear_color(C)
    snap = SNAP.capture(C)
    old = saved_images()
    ticks(4,30)
    SOURCE.par.vec0valuex = 4
    SNAP.restore(C, snap)
    for name, array in old.items():
        equal('independent palette parity restore '+name, array, image(name))
    # Replay with equal per-tick source samples.
    ticks(10,40)
    future = saved_images()
    SNAP.restore(C, snap)
    ticks(10,40)
    for name, array in future.items():
        equal('deterministic replay '+name, array, image(name))
    SNAP.restore(C, snap)
    C.par.Statefile = str(OUT / 'roundtrip.tstate')
    check('disk save action succeeds', SNAP.action(C,'Exportstate'))
    disk = SNAP.read_file(OUT/'roundtrip.tstate')
    check('disk payload bit exact', disk == SNAP.capture(C))
    ticks(3,80)
    check('disk restore action succeeds', SNAP.action(C,'Importstate'))
    equal('disk restores signed raw state', old['state'], image('state'))
    # Refuse invalid metadata without changing state/settings/time.
    before_state = image('state')
    before_clock = dict(CLOCK._clock(C))
    bad = copy.deepcopy(snap)
    bad['metadata']['version'] = 99
    try:
        SNAP.restore(C,bad)
        refused = False
    except SNAP.SnapshotError:
        refused = True
    check('newer snapshot refused without mutation', refused and np.array_equal(before_state,image('state'))
          and CLOCK._clock(C)['ticks'] == before_clock['ticks'])
    bad = copy.deepcopy(snap)
    bad['metadata']['settings']['Feed'] = 'wrong'
    try:
        SNAP.restore(C,bad)
        refused = False
    except SNAP.SnapshotError:
        refused = True
    check('invalid settings refused without mutation', refused and np.array_equal(before_state,image('state')))


def resets():
    reset()
    ticks(3)
    old = sentinel()
    palette = image('palette')
    count = C.fetch('Resetcount')
    seed = image('seed')
    CLOCK.reset_chemistry(C)
    now = image('state')
    equal('reset chemistry uses seed ab', seed[:,:,:2], now[:,:,:2])
    equal('reset chemistry preserves signed color', old[:,:,2:], now[:,:,2:])
    equal('reset chemistry keeps palette history', palette,image('palette'))
    check('reset chemistry age zero one reset pause preserved', CLOCK._clock(C)['ticks']==0 and
          C.fetch('Resetcount')==count+1 and bool(C.par.Pause))
    ticks(3)
    before = image('state')
    age = CLOCK._clock(C)['ticks']
    palette = image('palette')
    CLOCK.clear_color(C)
    equal('clear color preserves chemistry',before[:,:,:2],image('state')[:,:,:2])
    check('clear color zeros only ba keeps age', np.all(image('state')[:,:,2:]==0) and CLOCK._clock(C)['ticks']==age)
    equal('clear color keeps palette',palette,image('palette'))
    before = image('state')
    C.par.Seed = 7
    C.par.Seedradius = 4
    C.par.Ambient = False
    CLOCK.advance(C)
    equal('seed edits defer until explicit reset',before,image('state'))
    CLOCK.reset_chemistry(C)
    check('explicit reset reads latest seed settings', np.all(image('state')[:,:,0]==1) and np.all(image('state')[:,:,1]==0))
    ticks(2)
    before = image('state')
    age = CLOCK._clock(C)['ticks']
    palette = image('palette')
    CLOCK.restart_media(C)
    equal('restart media preserves chemistry and color',before,image('state'))
    equal('restart media preserves palette',palette,image('palette'))
    check('restart media preserves age',CLOCK._clock(C)['ticks']==age)
    CLOCK.reset_all(C)
    check('reset all clears color and age',np.all(image('state')[:,:,2:]==0) and CLOCK._clock(C)['ticks']==0)


def sources():
    reset()
    ticks(4)
    before = image('state')
    age = CLOCK._clock(C)['ticks']
    count = C.fetch('Resetcount')
    palette = image('palette')
    C.par.Sourcetop = ''
    CLOCK.advance(C)  # Transition must run even while paused.
    equal('source removal preserves raw patterns by default',before,image('state'))
    equal('source removal preserves palette',palette,image('palette'))
    check('source removal keeps age reset count',age==CLOCK._clock(C)['ticks'] and count==C.fetch('Resetcount'))
    check('motion invalidated on removal',np.all(image('mask_preview')[:,:,0]==0))
    C.par.Sourcetop = SOURCE.path
    CLOCK.advance(C)
    check('motion invalidated on reassignment',np.all(image('mask_preview')[:,:,0]==0))
    SOURCE.par.vec0valuex = 50
    CLOCK.tick(C)
    check('first new source tick has no stale motion',np.all(image('mask_preview')[:,:,0]==0))
    SOURCE.par.vec0valuex = 20
    CLOCK.tick(C)
    check('subsequent source motion detected',np.max(image('mask_preview')[:,:,0])>.01)
    CLOCK.tick(C)
    check('motion settles to zero on stopped source',np.all(image('mask_preview')[:,:,0]==0))
    settings(Resetonsource=True)
    count = C.fetch('Resetcount')
    C.par.Sourcetop = ''
    CLOCK.advance(C)
    check('opt in reset on source change once',C.fetch('Resetcount')==count+1 and CLOCK._clock(C)['ticks']==0)
    # Preset bindings follow the same source policy.
    settings(Resetonsource=False)
    ticks(2)
    before=image('state')
    preset=C.op('preset_lib').module.make_preset('bound', {}, {'Sourcetop':SOURCE.path})
    report=C.op('preset_lib').module.apply(C,preset,include_bindings=True)
    equal('preset source binding preserves patterns',before,image('state'))
    check('preset binding invalidates motion',np.all(image('mask_preview')[:,:,0]==0))


def resizing():
    reset()
    sentinel()
    ticks(2)
    before=image('state')
    age=CLOCK._clock(C)['ticks']
    count=C.fetch('Resetcount')
    settings(Resizebehavior='resample',Rectangle=True,Canvaswidth=96,Canvasheight=64,Cellsize=1.)
    # Requested parameters cannot change live texture sizes before transaction.
    check('requested resize does not expose mismatched grid',image('state').shape==(64,64,4)
          and image('seed').shape==(64,64,4))
    CLOCK.ensure_size(C)
    check('resample commits matching state buffers',all(image(n).shape==(64,96,4) for n in ('state','state_a','state_b','seed','influence_field')))
    check('resample retains age and reset count',age==CLOCK._clock(C)['ticks'] and count==C.fetch('Resetcount'))
    # Exact expected linear interpolation at pixel centers, clamped at image edges.
    xs=(np.arange(96)+.5)*64/96-.5
    lo=np.floor(xs).astype(int); f=(xs-lo).astype(np.float32)
    expected=before[:,np.clip(lo,0,63)]*(1-f)[None,:,None]+before[:,np.clip(lo+1,0,63)]*f[None,:,None]
    delta=float(np.max(np.abs(expected-image('state'))))
    check('resample raw channels matches bilinear reference',delta<1e-6,max_error=delta)
    check('resample signed chroma preserved',np.min(image('state')[:,:,2:])<0)
    for w,h,cell in ((128,80,2.),(64,96,3.),(96,64,1.)):
        settings(Canvaswidth=w,Canvasheight=h,Cellsize=cell)
        CLOCK.tick(C)
        shape=(max(8,round(h/cell)),max(8,round(w/cell)),4)
        check('resize then tick {}x{} cell {}'.format(w,h,cell),image('state').shape==shape and
              image('state_a').shape==shape and image('state_b').shape==shape and np.isfinite(image('state')).all())
    # Preset apply without reset uses Resize Behavior, same transaction.
    count=C.fetch('Resetcount'); age=CLOCK._clock(C)['ticks']
    p=C.op('preset_lib').module.make_preset('resample',{'Canvaswidth':128,'Cellsize':2.})
    report=C.op('preset_lib').module.apply(C,p)
    check('preset resize resamples without reset',not report['reset'] and C.fetch('Resetcount')==count
          and CLOCK._clock(C)['ticks']==age and image('state').shape==(32,64,4))
    settings(Resizebehavior='reset',Canvaswidth=96)
    CLOCK.ensure_size(C)
    check('reset resize zeros age and resets once',C.fetch('Resetcount')==count+1 and CLOCK._clock(C)['ticks']==0
          and image('state').shape==(32,48,4))


def movie():
    reset(Sourcetop='',Moviefile=str(OUT/'fixture.mp4'),Maskmode='motion',Mediaplay=False)
    node=C.op('movie')
    node.par.playmode='specify'
    node.par.indexunit='indices'
    for i in range(5):
        node.par.index=i*4
        CLOCK.tick(C)
    node.par.index=23
    node.cook(force=True)
    snap=SNAP.capture(C)
    pixels=image('source_preview')
    histories=saved_images()
    for i in range(5):
        node.par.index=30+i
        CLOCK.tick(C)
    SNAP.restore(C,snap)
    equal('movie position restores fitted source',pixels,image('source_preview'))
    check('movie index and mode restored',node.par.index.eval()==23 and node.par.playmode.eval()=='specify')
    for name,old in histories.items():
        equal('movie histories restored '+name,old,image(name))
    for i in range(6):
        node.par.index=24+i
        CLOCK.tick(C)
    future=saved_images()
    SNAP.restore(C,snap)
    for i in range(6):
        node.par.index=24+i
        CLOCK.tick(C)
    for name,old in future.items():
        equal('movie deterministic replay '+name,old,image(name))
    # Sequential position uses the fractional current frame index and seeks on restore.
    node.par.playmode='sequential'
    node.par.cuepointunit='indices';node.par.cuepoint=37;node.par.cue=True
    node.cook(force=True);node.par.cue=False
    snap=SNAP.capture(C)
    node.par.cuepoint=70;node.par.cue=True;node.cook(force=True);node.par.cue=False
    SNAP.restore(C,snap)
    check('sequential movie frame restored',abs(float(node.index)-snap['metadata']['movie']['position'])<1e-5,
          expected=snap['metadata']['movie']['position'],actual=float(node.index))


def start(c,output_dir):
    global C,OUT,CLOCK,SNAP,SOURCE,REPORT
    C=c;OUT=Path(output_dir);OUT.mkdir(parents=True,exist_ok=True)
    C.op('clock').par.active=False
    C.op('controls').par.active=False
    C.op('controls').cook(force=True)
    CLOCK=C.op('clock').module;SNAP=C.op('snapshot_lib').module
    REPORT=dict(build=str(app.version)+'.'+str(app.build),checks={},
                source_sha256=hashlib.sha256((OUT.parents[1]/'create_turing_media_v2.py').read_bytes()).hexdigest())
    SOURCE=C.parent().create(glslTOP,'phase5_source')
    dat=C.parent().create(textDAT,'phase5_source_pixel')
    dat.text='''out vec4 fragColor; uniform vec4 uSample;
    void main(){float t=uSample.x;vec2 p=vUV.st-vec2(.5+.2*sin(t*.17),.5);
    float a=1.-smoothstep(.15,.22,length(p));
    fragColor=TDOutputSwizzle(vec4(.2+.6*vUV.s,.1+.8*vUV.t,.35,a*.7));}'''
    SOURCE.par.pixeldat=dat.name;SOURCE.par.format='rgba32float'
    SOURCE.par.outputresolution='custom';SOURCE.par.resolutionw=64;SOURCE.par.resolutionh=64
    SOURCE.seq.vec.numBlocks=1;SOURCE.par.vec0name='uSample';SOURCE.par.vec0valuex=0
    for fn in (snapshots,resets,sources,resizing,movie):
        try:
            fn()
        except Exception:
            check(fn.__name__+' completed',False,exception=traceback.format_exc())
            print(traceback.format_exc())
    # Cook shader checks in a later TD frame, after compiler/error caches settle.
    def finish():
        errors=C.errors(recurse=True)
        check('no operator or shader errors',not errors,errors=errors)
        REPORT['passed']=all(v['passed'] for v in REPORT['checks'].values())
        (OUT/'report.json').write_text(json.dumps(REPORT,indent=2))
        print('PHASE5_COMPLETE',REPORT['passed'],len(REPORT['checks']))
    run('args[0]()',finish,delayFrames=3)
