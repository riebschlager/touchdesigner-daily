"""Real timeline-frame checks. Load into an Execute DAT; call module.start(c, path)."""
import json
from pathlib import Path
import numpy as np


def img(name='state'):
    C.op(name).cook(force=True)
    return C.op(name).numpyArray(delayed=False).copy()


def start(c, output_dir):
    global C, ROOT, PHASE, FRAME, REPORT, FIRST, PAUSED, BEFORE_STEP
    C, ROOT = c, Path(output_dir)
    REPORT = {'checks': {}, 'frame_ticks': {'30': [], '60': []}}
    PHASE, FRAME = 'warmup', 0
    c.op('clock').par.active = False
    c.op('controls').par.active = False
    c.op('controls').cook(force=True)
    for name, value in dict(Pause=True, Clockmode='framestepped', Renderfps=30,
                            Speed=1, Sourcetop='', Rectangle=False, Resolution=64,
                            Cellsize=1, Ambient=True, Transform=True).items():
        c.par[name].val=value
    c.op('controls').par.active = True
    c.op('controls').cook(force=True)
    me.par.framestart = False
    me.par.frameend = True
    me.par.active = True


def onFrameEnd(frame):
    global PHASE, FRAME, FIRST, PAUSED, BEFORE_STEP
    if PHASE == 'warmup':
        FRAME += 1
        if FRAME < 3:
            return
        PHASE, FRAME = 'setup', 0
    if PHASE == 'setup':
        C.op('clock').module.reset(C)
        C.par.Pause=False
        C.op('clock').par.active=True
        PHASE='30'
        return
    if PHASE in ('30', '60'):
        FRAME += 1
        REPORT['frame_ticks'][PHASE].append(C.fetch('Clockstate')['ticks'])
        if FRAME == int(PHASE):
            if PHASE == '30':
                FIRST={name:img(name) for name in ('state','palette')}
                C.par.Renderfps=60
                C.op('clock').module.reset(C)
                PHASE, FRAME='60', 0
            else:
                REPORT['max_abs']={name:float(np.max(np.abs(a-img(name)))) for name,a in FIRST.items()}
                REPORT['checks']['actual_frames_30_60_match']=all(v<=1e-6 for v in REPORT['max_abs'].values())
                C.par.Pause=True
                PAUSED={name:img(name) for name in ('state','palette')}
                PHASE, FRAME='pause', 0
        return
    if PHASE=='pause':
        FRAME += 1
        # Repeated output demand must never clock the solver.
        for _ in range(3): C.op('out1').cook(force=True)
        if FRAME==10:
            REPORT['checks']['actual_pause_exact']=all(np.array_equal(a,img(name)) for name,a in PAUSED.items())
            BEFORE_STEP=C.fetch('Clockstate')['ticks']
            C.par.Step.pulse()
            PHASE='step'
        return
    if PHASE=='step':
        REPORT['checks']['actual_step_pulse_one_tick']=C.fetch('Clockstate')['ticks']==BEFORE_STEP+1
        REPORT['checks']['actual_step_evolves']=not np.array_equal(PAUSED['state'],img())
        C.par.Reset.pulse()
        PHASE='reset'
        return
    if PHASE=='reset':
        REPORT['checks']['actual_reset_seed']=np.array_equal(img(),img('seed'))
        REPORT['checks']['actual_reset_age']=C.fetch('Clockstate')['ticks']==0
        C.par.Rectangle=True
        C.par.Canvaswidth=128
        C.par.Canvasheight=64
        C.par.Cellsize=2
        PHASE='resize'
        return
    if PHASE=='resize':
        REPORT['checks']['paused_resize_seed']=np.array_equal(img(),img('seed'))
        REPORT['checks']['paused_resize_shape']=img().shape==(32,64,4)
        for fps in (30,60):
            REPORT['checks']['ticks_per_actual_frame_'+str(fps)]=REPORT['frame_ticks'][str(fps)]==list(range(60//fps,61,60//fps))
        REPORT['passed']=all(bool(x) for x in REPORT['checks'].values())
        REPORT['checks']={k:bool(v) for k,v in REPORT['checks'].items()}
        (ROOT/'frames.json').write_text(json.dumps(REPORT,indent=2))
        C.op('clock').par.active=False
        me.par.active=False
        print('PHASE2_FRAMES',REPORT['passed'],REPORT['checks'])
