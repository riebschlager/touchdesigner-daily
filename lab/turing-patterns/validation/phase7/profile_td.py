"""Frame-separated profiling: last measured GPU cook * cooks, per group.
Counts are deltas within our explicit tick/display workload; timings sampled next frame.
"""
import json, time, statistics, hashlib, traceback
from pathlib import Path
ROOT=Path('/Users/criebschlager/Projects/touchdesigner-daily/lab/turing-patterns')
OUT=ROOT/'validation/phase7'
GROUPS={
 'simulation':('seed','state_a','state_b','state_read','reaction_diffusion','state_transform','state','domain_prepare','domain_mask','velocity_prepare','velocity_field'),
 'media':('blank','media_prepared','media_a','media_b','media_cache','media_previous','media_mask','mask_preview','influence_prepare','influence_field','sim_source','sim_previous','sim_live','sim_source_prepare','sim_previous_prepare','sim_live_prepare','stamp_mask'),
 'palette':('palette_cells','palette_sort','palette_init','palette_a','palette_b','palette_read','palette_samples','palette'),
 'display':('colorize','patterns','composite','out1')}
CASES=[('square_full',512,512,1,'fixed'),('rectangle_full',768,384,1,'fixed'),
       ('square_coarse',512,512,4,'fixed'),('rectangle_coarse_clip',768,384,4,'ramp'),
       ('square_full_no_carry',512,512,1,'fixed'),('rectangle_clip_interval4',768,384,4,'ramp')]

def start(label='before',filename='reference_v6.py'):
 global C,CLOCK,REPORT,INDEX,COUNT,ROWS,PENDING
 host=op('/project1').create(baseCOMP,'phase7_profile_'+label)
 builder=host.create(textDAT,'builder');builder.text=(OUT/filename if filename=='reference_v6.py' else ROOT/filename).read_text()
 ns=dict(globals(),me=builder);exec(compile(builder.text,filename,'exec'),ns)
 C=ns['turing_component'];C.op('clock').par.active=False;C.par.Pause=True
 C.op('controls').par.active=False
 fixture=host.create(constantTOP,'source');fixture.par.outputresolution='custom';fixture.par.resolutionw=768;fixture.par.resolutionh=512
 fixture.par.colorr=.9;fixture.par.colorg=.2;fixture.par.colorb=.6;fixture.par.alpha=.37
 C.par.Sourcetop=fixture
 CLOCK=C.op('clock').module
 REPORT={'label':label,'build':str(app.version)+'.'+str(app.build),'sha256':hashlib.sha256(builder.text.encode()).hexdigest(),'cases':{}}
 INDEX=-1;next_case()

def next_case():
 global INDEX,COUNT,ROWS,PENDING
 INDEX+=1
 if INDEX>=len(CASES):
  (OUT/('profile_'+REPORT['label']+'.json')).write_text(json.dumps(REPORT,indent=2));print('PHASE7_PROFILE_COMPLETE',REPORT['label']);return
 name,w,h,cell,color=CASES[INDEX]
 C.par.Rectangle=True;C.par.Canvaswidth=w;C.par.Canvasheight=h;C.par.Cellsize=cell;C.par.Colormode=color
 if getattr(C.par,'Carryhistory',None) is not None:
  C.par.Carryhistory='no_carry' not in name;C.par.Palettehistory=False;C.par.Paletteinterval=4 if 'interval4' in name else 1
 CLOCK.reset(C);COUNT=0;ROWS=[];PENDING=None
 run('args[0]()',frame,delayFrames=2)

def frame():
 global COUNT,PENDING
 try:
  nodes={name:C.op(name) for names in GROUPS.values() for name in names if C.op(name) is not None}
  if PENDING is not None:
   delta,wall=PENDING
   row={'tick_display_wall_ms':wall}
   for group,names in GROUPS.items():
    row[group+'_gpu_ms_estimate']=sum(float(nodes[n].gpuCookTime)*delta[n] for n in names if n in nodes)
    row[group+'_bytes']=sum(int(nodes[n].gpuMemory) for n in names if n in nodes)
    row[group+'_cooks']=sum(delta[n] for n in names if n in nodes)
   if COUNT>8:ROWS.append(row)
  if COUNT>=48:
   REPORT['cases'][CASES[INDEX][0]]={'median':{k:statistics.median(r[k] for r in ROWS) for k in ROWS[0]},'mean':{k:statistics.mean(r[k] for r in ROWS) for k in ROWS[0]},'samples':ROWS,'errors':C.errors(recurse=True)}
   next_case();return
  before={n:o.totalCooks for n,o in nodes.items()};t=time.perf_counter()
  CLOCK.tick(C);C.op('out1').cook(force=True)
  PENDING=({n:o.totalCooks-before[n] for n,o in nodes.items()},(time.perf_counter()-t)*1000)
  COUNT+=1;run('args[0]()',frame,delayFrames=1)
 except Exception:
  (OUT/('profile_'+REPORT['label']+'_error.txt')).write_text(traceback.format_exc());raise
