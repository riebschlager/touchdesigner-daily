"""Actual parameter pulses/edits across frames with both product callback DATs enabled."""
from pathlib import Path
import json
import traceback
import numpy as np


def image():
    C.op('state').cook(force=True)
    return C.op('state').numpyArray(delayed=False).copy()


def check(name,passed):
    REPORT['checks'][name]=bool(passed)
    print('PHASE5_FRAME_CHECK',name,bool(passed))


def later(fn):
    def safe():
        try:
            fn()
        except Exception:
            REPORT['exception']=traceback.format_exc()
            finish()
    run('args[0]()',safe,delayFrames=5)


def start(c,output_dir):
    global C,OUT,REPORT,V,BEFORE,AGE,COUNT
    C=c;OUT=Path(output_dir);REPORT={'checks':{}}
    V=C.parent().op('validate_phase5').module
    V.settings(Pause=True)
    C.op('controls').par.active=True;C.op('controls').cook(force=True)
    C.op('clock').par.active=True
    # Drain deferred construction/start and prior disabled-control notifications.
    later(begin)


def begin():
    global BEFORE,AGE,COUNT
    V.reset();V.ticks(5);V.sentinel()
    BEFORE=image();AGE=V.CLOCK._clock(C)['ticks'];COUNT=C.fetch('Resetcount')
    C.par.Seed=12;C.par.Seedradius=6;C.par.Ambient=False
    later(seed_edit)


def seed_edit():
    check('hand seed edits keep state age reset count',np.array_equal(BEFORE,image())
          and AGE==V.CLOCK._clock(C)['ticks'] and COUNT==C.fetch('Resetcount'))
    C.par.Savestate.pulse()
    later(saved)


def saved():
    check('save state pulse creates snapshot',C.fetch('Snapshot',None) is not None)
    C.par.Step.pulse()
    later(stepped)


def stepped():
    check('step pulse advances exactly once while paused',V.CLOCK._clock(C)['ticks']==AGE+1 and bool(C.par.Pause))
    C.par.Restorestate.pulse()
    later(restored)


def restored():
    check('restore pulse exact state age pause no reset',np.array_equal(BEFORE,image()) and
          V.CLOCK._clock(C)['ticks']==AGE and bool(C.par.Pause) and C.fetch('Resetcount')==COUNT)
    C.par.Clearcolor.pulse()
    later(cleared)


def cleared():
    check('clear color pulse preserves chemistry age',np.array_equal(BEFORE[:,:,:2],image()[:,:,:2])
          and np.all(image()[:,:,2:]==0) and AGE==V.CLOCK._clock(C)['ticks'])
    C.par.Restorestate.pulse()
    later(reset_chemistry)


def reset_chemistry():
    C.par.Resetchemistry.pulse()
    later(reset_done)


def reset_done():
    check('reset chemistry pulse keeps color one reset',np.array_equal(BEFORE[:,:,2:],image()[:,:,2:])
          and V.CLOCK._clock(C)['ticks']==0 and C.fetch('Resetcount')==COUNT+1)
    C.store('Framebefore',image());C.store('Framecount',C.fetch('Resetcount'))
    C.par.Restartclip.pulse()
    later(restarted)


def restarted():
    check('restart media pulse retains state and reset count',np.array_equal(C.fetch('Framebefore'),image())
          and C.fetch('Resetcount')==C.fetch('Framecount'))
    C.par.Sourcetop=''
    later(source_changed)


def source_changed():
    check('hand source removal keeps chemistry by default',np.array_equal(C.fetch('Framebefore'),image())
          and C.fetch('Resetcount')==C.fetch('Framecount'))
    C.par.Resetonsource=True;C.par.Sourcetop=V.SOURCE.path
    later(source_reset)


def source_reset():
    check('opt in source change resets once across frames',C.fetch('Resetcount')==C.fetch('Framecount')+1)
    C.par.Resetonsource=False;C.par.Resizebehavior='resample'
    C.par.Rectangle=True;C.par.Canvaswidth=96;C.par.Canvasheight=80;C.par.Cellsize=2.
    C.store('Framecount',C.fetch('Resetcount'))
    later(resized)


def resized():
    check('automatic frame handles matching resized buffers',image().shape==(40,48,4) and
          all(C.op(n).numpyArray().shape==(40,48,4) for n in ('state_a','state_b','seed'))
          and C.fetch('Resetcount')==C.fetch('Framecount'))
    C.par.Step.pulse()
    later(resized_step)


def resized_step():
    check('step after automatic resize finite',np.isfinite(image()).all() and V.CLOCK._clock(C)['ticks']==1)
    C.par.Resetall.pulse()
    later(reset_all_done)


def reset_all_done():
    check('reset all pulse clears color age one reset',np.all(image()[:,:,2:]==0)
          and V.CLOCK._clock(C)['ticks']==0 and C.fetch('Resetcount')==C.fetch('Framecount')+1)
    finish()


def finish():
    C.op('clock').par.active=False
    REPORT['passed']=all(REPORT['checks'].values()) and 'exception' not in REPORT
    REPORT['errors']=C.errors(recurse=True)
    REPORT['passed']=REPORT['passed'] and not REPORT['errors']
    (OUT/'frame_report.json').write_text(json.dumps(REPORT,indent=2))
    print('PHASE5_FRAMES_COMPLETE',REPORT['passed'])
