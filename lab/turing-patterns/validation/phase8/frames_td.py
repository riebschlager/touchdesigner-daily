"""Real timeline, custom parameter pulses, and motion-cache demand behavior."""
import hashlib
import json
import traceback
from pathlib import Path
import numpy as np


def check(name, passed, **details):
    REPORT['checks'][name] = dict(passed=bool(passed), **details)
    print('PHASE8_FRAME_CHECK',name,bool(passed))


def image(name):
    C.op(name).cook(force=True)
    return C.op(name).numpyArray(delayed=False).copy()


def later(name):
    run('args[0].module.dispatch(args[1])',me,name,delayFrames=4)


def dispatch(name):
    try:globals()[name]()
    except Exception:
        check(name+' completed',False,exception=traceback.format_exc())
        finish()


def start(c,folder):
    global C,OUT,REPORT,SOURCE,CLOCK,BEFORE,AGE,RESETS
    C,OUT=c,Path(folder);CLOCK=C.op('clock').module
    REPORT={'build':str(app.version)+'.'+str(app.build),
            'source_sha256':hashlib.sha256(C.parent().op('builder').text.encode()).hexdigest(),'checks':{}}
    C.op('clock').par.active=False
    SOURCE=C.parent().create(glslTOP,'frame_source')
    d=C.parent().create(textDAT,'frame_source_pixel')
    d.text='''out vec4 fragColor; uniform float uSample;
    void main(){float v=.1+.7*mod(uSample,2.);fragColor=TDOutputSwizzle(vec4(v,.2,.1,.4));}'''
    SOURCE.par.pixeldat=d.name;SOURCE.par.format='rgba32float'
    SOURCE.par.outputresolution='custom';SOURCE.par.resolutionw=96;SOURCE.par.resolutionh=64
    SOURCE.seq.vec.numBlocks=1;SOURCE.par.vec0name='uSample';SOURCE.par.vec0valuex=0
    C.op('preset_lib').module.set_quietly(C,{'Resolution':64,'Rectangle':True,'Canvaswidth':96,
        'Canvasheight':64,'Cellsize':3,'Clockmode':'framestepped','Renderfps':60,'Speed':1,
        'Pause':True,'Maskmode':'motion','Sourcetop':SOURCE.path,'Moviefile':'','Mediascale':1,
        'Ambient':True,'Flow':False,'Transform':False,'Palettehistory':True,'Resetonsource':False})
    CLOCK.reset(C);BEFORE=image('state');AGE=C.fetch('Clockstate')['ticks'];RESETS=C.fetch('Resetcount')
    C.op('controls').par.active=True;C.op('controls').cook(force=True)
    C.op('clock').par.active=True
    later('paused')


def paused():
    global RESETS
    check('real frames pause chemistry',np.array_equal(BEFORE,image('state')) and C.fetch('Clockstate')['ticks']==AGE)
    check('diagnostics runs while paused','paused' in C.op('status_panel').par.text.eval(),
          text=C.op('status_panel').par.text.eval(),active=bool(C.op('diagnostics').par.active),
          resets=C.fetch('Resetcount'),initial_resets=RESETS)
    check('live source valid','Valid TOP:' in dict(C.op('diagnostics').module.status_rows(C))['Source'])
    # Newly created Execute DATs may deliver their Create callback on the first
    # frame; capture the settled baseline before testing later source transitions.
    RESETS=C.fetch('Resetcount')
    C.par.Step.pulse();later('warmed')


def warmed():
    check('first Step warms history without stale motion',np.max(image('media_mask')[:,:,0])==0)
    check('real Step one tick and stays paused',C.fetch('Clockstate')['ticks']==AGE+1 and bool(C.par.Pause))
    SOURCE.par.vec0valuex=1;C.par.Step.pulse();later('moving')


def moving():
    global MASK,HISTORY,COOKS,TICKS
    MASK=image('media_mask')
    check('changed source produces motion',float(MASK[:,:,0].max())>.05,max_motion=float(MASK[:,:,0].max()))
    HISTORY={n:image(n) for n in ('media_a','media_b')}
    COOKS={n:C.op(n).totalCooks for n in HISTORY};TICKS=C.fetch('Clockstate')['ticks']
    C.par.Refreshdiagnostics.pulse()
    SOURCE.par.vec0valuex=.5
    # Viewer-style demands may cook readers, but never recapture either history.
    for _ in range(4):
        for n in ('media_cache','media_previous','mask_preview','source_preview'):image(n)
    later('held')


def held():
    check('paused motion mask retained',np.array_equal(MASK,image('media_mask')))
    check('reader and diagnostics recooks preserve histories',all(np.array_equal(a,image(n)) for n,a in HISTORY.items()))
    check('live source changes cannot auto-capture while paused',all(np.array_equal(a,image(n)) for n,a in HISTORY.items()))
    check('diagnostics pulse preserves ticks',C.fetch('Clockstate')['ticks']==TICKS)
    SOURCE.par.vec0valuex=1
    C.par.Step.pulse();later('stopped')


def stopped():
    global SAVED,AGE
    check('stopped source motion exactly zero next tick',np.max(image('media_mask')[:,:,0])==0)
    check('stopped source histories identical',np.array_equal(image('media_a'),image('media_b')))
    SAVED=image('state');AGE=C.fetch('Clockstate')['ticks']
    SOURCE.par.resolutionw=80;later('resized_source')


def resized_source():
    check('source dimension edit invalidates during pause',not C.fetch('Motionready') and np.max(image('media_mask')[:,:,0])==0)
    check('source dimension edit keeps chemistry and age',np.array_equal(SAVED,image('state')) and C.fetch('Clockstate')['ticks']==AGE)
    check('source dimension edit captures matching samples',np.array_equal(image('media_a'),image('media_b')))
    check('source dimension change avoids chemistry reset',C.fetch('Resetcount')==RESETS,
          resets=C.fetch('Resetcount'),initial_resets=RESETS)
    SOURCE.par.vec0valuex=0;C.par.Step.pulse();later('invalidated_step')


def invalidated_step():
    check('first tick after dimension invalidation suppressed',np.max(image('media_mask')[:,:,0])==0)
    C.par.Pause=False;later('running')


def running():
    check('timeline running advances ticks',C.fetch('Clockstate')['ticks']>AGE+1)
    check('stationary running source settles',np.max(image('media_mask')[:,:,0])==0)
    C.par.Pause=True;later('begin_clock_failure')


def begin_clock_failure():
    global ORIGINAL_ADVANCE
    ORIGINAL_ADVANCE=CLOCK.advance
    def fail(*args,**kwargs):raise RuntimeError('deliberate phase8 clock failure')
    CLOCK.advance=fail
    later('observe_clock_failure')


def observe_clock_failure():
    check('clock exception disables scheduler',not C.op('clock').par.active)
    check('clock failure visible in panel','deliberate phase8 clock failure' in C.op('status_panel').par.text.eval())
    CLOCK.advance=ORIGINAL_ADVANCE
    C.par.Resetall.pulse();later('recovered')


def recovered():
    check('Reset All clears clock failure',not C.fetch('Runtimeerror') and C.fetch('Clockstate')['ticks']==0)
    C.op('clock').par.active=True
    later('finish')


def finish():
    C.par.Pause=True
    C.op('diagnostics').module.refresh(C,compile_shaders=True)
    check('final frame operator errors clear',not C.errors(recurse=True),errors=C.errors(recurse=True))
    REPORT['passed']=all(v['passed'] for v in REPORT['checks'].values())
    (OUT/'frame_report.json').write_text(json.dumps(REPORT,indent=2))
    print('PHASE8_FRAMES_COMPLETE',REPORT['passed'],len(REPORT['checks']))
