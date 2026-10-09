import json,hashlib
from pathlib import Path
import numpy as np

def check(n,p):REPORT['checks'][n]={'passed':bool(p)}
def image(n):C.op(n).cook(force=True);return C.op(n).numpyArray(delayed=False).copy()
def start(c,folder):
 global C,OUT,REPORT,BEFORE,AGE,RESETS
 C=c;OUT=Path(folder);C.par.Pause=True;C.op('clock').par.active=True
 C.op('preset_lib').module.set_quietly(C,{'Resolution':64,'Palettehistory':True})
 C.op('clock').module.reset(C)
 a=image('state');a[:,:,2]=-.1;a[:,:,3]=.2
 upload=C.op('snapshot_lib').module.upload(C,a.astype('<f4').tobytes(),list(a.shape))
 for n in ('state_a','state_b'):C.op('clock').module.capture(C.op(n),upload)
 BEFORE=image('state');AGE=C.fetch('Clockstate')['ticks'];RESETS=C.fetch('Resetcount')
 REPORT={'checks':{},'sha256':hashlib.sha256(C.parent().op('builder').text.encode()).hexdigest()}
 C.par.Carryhistory=False;C.par.Palettehistory=False;C.par.Paletteinterval=5
 run('args[0].module.edited()',me,delayFrames=4)
def edited():
 check('performance edits paused preserve state',np.array_equal(BEFORE,image('state')))
 check('performance edits preserve reset count',RESETS==C.fetch('Resetcount'))
 check('performance edits preserve age',AGE==C.fetch('Clockstate')['ticks'])
 C.par.Step.pulse();run('args[0].module.stepped()',me,delayFrames=4)
def stepped():
 check('Step pulse one tick',C.fetch('Clockstate')['ticks']==AGE+1)
 check('Step disabled carry holds signed chroma',np.array_equal(BEFORE[:,:,2:],image('state')[:,:,2:]))
 snap=C.op('snapshot_lib').module.capture(C)
 check('snapshot sees real performance edits',snap['metadata']['settings']['Paletteinterval']==5 and not snap['metadata']['settings']['Carryhistory'])
 check('no errors after frames',not C.errors(recurse=True))
 REPORT['passed']=all(v['passed'] for v in REPORT['checks'].values());(OUT/'frame_report.json').write_text(json.dumps(REPORT,indent=2))
 print('PHASE7_FRAMES_COMPLETE',REPORT['passed'])
