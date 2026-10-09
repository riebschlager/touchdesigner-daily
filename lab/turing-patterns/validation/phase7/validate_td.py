"""Phase 7 independent filtering, reference fidelity, histories and long-run precision."""
import copy, json, hashlib, traceback
from pathlib import Path
import numpy as np

OUTPUTS=('state','patterns','out1','source_preview','mask_preview','palette')

def image(c,n):
 c.op(n).cook(force=True);return c.op(n).numpyArray(delayed=False).copy()

def check(n,p,**detail):
 REPORT['checks'][n]={'passed':bool(p),**detail};print('PHASE7_CHECK',n,bool(p))

def equal(n,a,b,tol=0):
 e=float(np.max(np.abs(a-b))) if a.shape==b.shape else float('inf');check(n,e<=tol,max_error=e,tolerance=tol)

def settings(c,**v):c.op('preset_lib').module.set_quietly(c,v)

def reset(c,**v):
 settings(c,Resolution=64,Rectangle=False,Cellsize=1,Clockmode='framestepped',Renderfps=60,Speed=1,
  Solverquality=1,Pause=True,Ambient=True,Transform=False,Flow=False,Sourcetop='',Moviefile='',Domaintop='',
  Ramptop='',Feed=.0545,Kill=.062,Diffusiona=1,Diffusionb=.5,Strength=5.00289653634306,
  Fade=0,Dyeinject=3.0775976632530346,Dyedecay=0,Dyespread=665.4212933375475,
  Maskmode='alpha',Colormode='fixed',Influencemode='continuous',Transformedge='wrap')
 if c==C:settings(c,Carryhistory=True,Palettehistory=True,Paletteinterval=1)
 settings(c,**v);c.op('clock').module.reset(c)

def build(filename,name):
 host=C.parent().parent().create(baseCOMP,name);b=host.create(textDAT,'builder')
 b.text=Path(filename).read_text();ns=dict(globals(),me=b);exec(compile(b.text,filename,'exec'),ns)
 c=ns['turing_component'];c.op('clock').par.active=False;c.op('controls').par.active=False;c.op('controls').cook(force=True);return c

def reference():
 for mode in ('fixed','tint','ramp','dye'):
  for c in (C,REF):
   reset(c,Colormode=mode,Sourcetop=SOURCE.path)
   for i in range(24):c.op('clock').module.tick(c)
  for n in OUTPUTS:
   equal('full grid reference '+mode+' '+n,image(C,n),image(REF,n),8e-4 if n in ('out1','patterns') else 1e-6)
 for boundary in ('wrap','noflux','clear'):
  for c in (C,REF):
   reset(c,Rectangle=True,Canvaswidth=96,Canvasheight=64,Cellsize=3,Transformedge=boundary)
   for i in range(48):c.op('clock').module.tick(c)
  equal('no media coarse chemical reference '+boundary,image(C,'state'),image(REF,'state'),1e-6)


def filtering(cell=4):
 reset(C,Rectangle=True,Canvaswidth=96,Canvasheight=64,Cellsize=cell,Sourcetop=SOURCE.path,Palettehistory=False)
 fixture=C.create(glslTOP,'test_filter_source_'+str(cell));fixture.par.pixeldat=SOURCE.par.pixeldat.eval();fixture.par.format='rgba32float';fixture.par.outputresolution='custom';fixture.par.resolutionw=96;fixture.par.resolutionh=64
 C.op('sim_source_prepare').inputConnectors[0].connect(fixture)
 a=image(C,fixture.name);b=image(C,'sim_source');h,w=a.shape[:2];dh,dw=b.shape[:2]
 y,x=np.mgrid[:dh,:dw];prem=np.concatenate((a[:,:,:3]*a[:,:,3:],a[:,:,3:]),axis=2).astype(np.float64)
 expected=np.zeros((dh,dw,4))
 for j in range(4):
  for i in range(4):
   px=(x+(i+.5)/4)*w/dw-.5;py=(y+(j+.5)/4)*h/dh-.5
   ix=np.floor(px).astype(int);iy=np.floor(py).astype(int);fx=(px-ix)[:,:,None];fy=(py-iy)[:,:,None]
   def f(dx,dy):return prem[np.clip(iy+dy,0,h-1),np.clip(ix+dx,0,w-1)]
   expected+=((f(0,0)*(1-fx)+f(1,0)*fx)*(1-fy)+(f(0,1)*(1-fx)+f(1,1)*fx)*fy)/16
 expected[:,:,:3]=np.divide(expected[:,:,:3],expected[:,:,3:],out=np.zeros_like(expected[:,:,:3]),where=expected[:,:,3:]>1e-6)
 equal('coarse premultiplied box CPU reference cell '+str(cell),expected,b,2e-6)
 check('hidden transparent magenta excluded',float(np.max(b[:,:,0]))<1e-6 and float(np.max(b[:,:,2]))<1e-6)
 check('coarse fractional alpha retained',np.any((b[:,:,3]>0)&(b[:,:,3]<1)))
 check('simulation mask and influence dimensions',C.op('media_mask').width==dw and C.op('influence_field').width==dw)
 check('public mask preview canvas dimensions',C.op('mask_preview').width==96 and C.op('mask_preview').height==64)
 check('float32 state and field formats',C.op('reaction_diffusion').par.format.eval()=='rgba32float' and C.op('influence_prepare').par.format.eval()=='rg32float')
 C.op('sim_source_prepare').inputConnectors[0].connect(C.op('media_cache'))
 check('light visual formats',C.op('colorize').par.format.eval()=='rgba16float' and C.op('domain_prepare').par.format.eval()=='mono8fixed')


def histories():
 reset(C,Sourcetop=SOURCE.path,Palettehistory=False,Colormode='fixed')
 clock=C.op('clock').module
 cooks=C.op('palette_sort').totalCooks
 for i in range(10):clock.tick(C)
 check('unused palette does not extract',C.op('palette_sort').totalCooks==cooks)
 settings(C,Colormode='ramp',Paletteinterval=4)
 clock.tick(C);check('switch to clip initializes palette',C.fetch('Paletteready') and C.fetch('Palettelasttick')==11)
 cooks=C.op('palette_sort').totalCooks
 for i in range(3):clock.tick(C)
 check('palette interval holds history',C.op('palette_sort').totalCooks==cooks)
 clock.tick(C);check('palette interval updates on fourth tick',C.op('palette_sort').totalCooks>cooks and C.fetch('Palettelasttick')==15)
 check('smoothing elapsed uses four ticks',abs(C.fetch('Paletteelapsed')-4/60)<1e-12)
 snap=C.op('snapshot_lib').module.capture(C)
 for i in range(9):clock.tick(C)
 future={n:image(C,n) for n in OUTPUTS}
 C.op('snapshot_lib').module.restore(C,snap)
 for i in range(9):clock.tick(C)
 for n in OUTPUTS:equal('interval snapshot replay '+n,future[n],image(C,n))
 # Paused history and single step.
 before=image(C,'palette');t=clock._clock(C)['ticks'];clock.advance(C,elapsed=1)
 equal('pause holds palette',before,image(C,'palette'));check('pause holds age',clock._clock(C)['ticks']==t)
 clock.step(C);check('step advances one tick',clock._clock(C)['ticks']==t+1)
 # Disable carry: chemistry identical, signed channels hold without injection/decay/spread.
 reset(C,Sourcetop=SOURCE.path)
 for i in range(12):clock.tick(C)
 snap=C.op('snapshot_lib').module.capture(C);base=image(C,'state')
 settings(C,Carryhistory=False)
 for i in range(12):clock.tick(C)
 off=image(C,'state');equal('disabled carry retains signed channels',base[:,:,2:],off[:,:,2:])
 C.op('snapshot_lib').module.restore(C,snap)
 for i in range(12):clock.tick(C)
 on=image(C,'state');equal('carry option does not change A B',off[:,:,:2],on[:,:,:2])
 check('signed chroma retained',on[:,:,2:].min()<0 and on[:,:,2:].max()>0)
 # Complete phase6 snapshots default to continuous history; partial controls refuse.
 old=copy.deepcopy(snap)
 for k in ('Carryhistory','Palettehistory','Paletteinterval'):old['metadata']['settings'].pop(k)
 old['metadata'].pop('palette_last_tick',None)
 C.op('snapshot_lib').module.restore(C,old)
 check('legacy snapshot history defaults',bool(C.par.Carryhistory) and bool(C.par.Palettehistory) and int(C.par.Paletteinterval)==1)
 bad=copy.deepcopy(snap);bad['metadata']['settings'].pop('Paletteinterval')
 try:C.op('snapshot_lib').module.restore(C,bad);refused=False
 except Exception:refused=True
 check('partial performance metadata refused',refused)
 clock.reset_chemistry(C);check('chemistry reset rebases palette schedule',C.op('snapshot_lib').module.capture(C)['metadata']['palette_last_tick']==0)
 # Preset control roundtrip.
 lib=C.op('preset_lib').module;settings(C,Carryhistory=False,Palettehistory=False,Paletteinterval=7)
 flat,_=lib.capture(C);preset=lib.make_preset('Performance test',flat)
 settings(C,Carryhistory=True,Palettehistory=True,Paletteinterval=1);lib.apply(C,preset)
 check('performance preset roundtrip',not C.par.Carryhistory and not C.par.Palettehistory and int(C.par.Paletteinterval)==7)
 # Custom base ramp is consumed by fixed mode as well.
 settings(C,Ramptop=SOURCE.path,Colormode='fixed',Paletteinterval=1);cooks=C.op('palette_sort').totalCooks;cells=C.op('palette_cells').totalCooks;clock.tick(C)
 check('custom ramp requests palette row',C.op('palette_sort').totalCooks>cooks)
 check('custom base ramp skips clip extraction',C.op('palette_cells').totalCooks==cells)


def precision_start():
 global LOW,LONG,AGE,CASE
 LOW=build(ROOT/'create_turing_media_v2.py','phase7_half_experiment')
 CASE=-1;LONG=[];precision_case()


def precision_case():
 global CASE,AGE
 CASE+=1;AGE=0
 if CASE==2:
  REPORT['half_precision_experiment']=LONG
  check('half precision experiment completed',len(LONG)==8)
  finish();return
 for c in (C,LOW):
  settings(c,Carryhistory=True,Palettehistory=False,Paletteinterval=1)
  reset(c,Rectangle=True,Canvaswidth=96 if CASE==0 else 128,Canvasheight=64,Cellsize=1,
   Feed=.0545 if CASE==0 else .0367,Kill=.062 if CASE==0 else .0649,Seedradius=9 if CASE==0 else 5,Palettehistory=False)
 # All evolving textures/passes use half; chemical reference stays RGBA32F.
 for n in ('seed','reaction_diffusion','state_transform','state_a','state_b'):LOW.op(n).par.format='rgba16float'
 LOW.op('clock').module.reset(LOW)
 run('args[0].module.precision_chunk()',me,delayFrames=1)


def precision_chunk():
 global AGE
 try:
  for i in range(60):
   for c in (C,LOW):c.op('clock').module.tick(c)
  AGE+=60
  if AGE in (60,600,1800,3600):
   a=image(C,'state');b=image(LOW,'state');d=a[:,:,:2]-b[:,:,:2]
   LONG.append({'preset':'coral' if CASE==0 else 'spots','ticks':AGE,'max_error':float(np.max(np.abs(d))),
    'rmse':float(np.sqrt(np.mean(d*d))),'mean_B_error':float(abs(a[:,:,1].mean()-b[:,:,1].mean())),
    'coverage_error':float(abs(np.mean(a[:,:,1]>.1)-np.mean(b[:,:,1]>.1))),
    'finite_bounded':bool(np.isfinite(b).all() and b[:,:,:2].min()>=0 and b[:,:,:2].max()<=1),
    'pointwise_acceptable_1e3':bool(np.max(np.abs(d))<=.001)})
   (OUT/'precision_progress.json').write_text(json.dumps(LONG,indent=2))
  if AGE>=3600:precision_case()
  else:run('args[0].module.precision_chunk()',me,delayFrames=1)
 except Exception:check('precision completed',False,exception=traceback.format_exc());finish()


def start(c,output_dir):
 global C,OUT,ROOT,REF,SOURCE,REPORT,TASKS
 C=c;OUT=Path(output_dir);ROOT=OUT.parents[1]
 C.op('controls').par.active=False;C.op('controls').cook(force=True)
 REPORT={'checks':{},'sha256':hashlib.sha256(C.parent().op('builder').text.encode()).hexdigest()}
 REF=build(OUT/'reference_v6.py','phase7_reference_quality')
 SOURCE=C.parent().create(glslTOP,'source');d=C.parent().create(textDAT,'source_pixel')
 d.text='out vec4 fragColor;void main(){ivec2 p=ivec2(gl_FragCoord.xy); bool visible=(p.x%2)==0; fragColor=TDOutputSwizzle(visible?vec4(0,1,0,0.6):vec4(1,0,1,0));}'
 SOURCE.par.pixeldat=d.name;SOURCE.par.format='rgba32float';SOURCE.par.outputresolution='custom';SOURCE.par.resolutionw=96;SOURCE.par.resolutionh=64
 TASKS=[reference,filtering,lambda:filtering(7),histories,precision_start];next_task()


def next_task():
 if not TASKS:return
 fn=TASKS.pop(0)
 try:fn()
 except Exception:check(fn.__name__+' completed',False,exception=traceback.format_exc())
 (OUT/'progress.json').write_text(json.dumps(REPORT,indent=2))
 if TASKS:run('args[0].module.next_task()',me,delayFrames=2)


def finish():
 check('no shader or operator errors',not C.errors(recurse=True),errors=C.errors(recurse=True))
 REPORT['passed']=all(v['passed'] for v in REPORT['checks'].values())
 (OUT/'report.json').write_text(json.dumps(REPORT,indent=2));print('PHASE7_COMPLETE',REPORT['passed'],len(REPORT['checks']))
