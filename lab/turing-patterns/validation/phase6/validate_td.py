"""Live independent CPU references plus clock/preset/snapshot flow integration."""
import copy
import hashlib
import json
from pathlib import Path
import traceback
import numpy as np

EMPTY = np.array([1,0,0,0], dtype=np.float32)
TOL = 3e-5  # Affine CPU float64 vs GPU float32, including trig/exponentiation.


def image(name):
    C.op(name).cook(force=True)
    return C.op(name).numpyArray(delayed=False).copy()


def check(name, passed, **details):
    REPORT['checks'][name] = dict(passed=bool(passed), **details)
    print('PHASE6_CHECK', name, bool(passed))


def equal(name, expected, actual, tol=TOL, exact=False):
    delta = float(np.max(np.abs(expected-actual))) if expected.shape == actual.shape else float('inf')
    check(name, expected.shape == actual.shape and (np.array_equal(expected.view(np.uint32), actual.view(np.uint32))
          if exact else delta <= tol), max_error=delta, tolerance=0 if exact else tol)


def settings(**values):
    C.op('preset_lib').module.set_quietly(C,values)


def configure(**values):
    settings(Resolution=64, Rectangle=False, Cellsize=1, Clockmode='framestepped', Renderfps=60,
             Speed=1, Solverquality=1, Pause=True, Ambient=False, Sourcetop='', Moviefile='',
             Domaintop='', Domainboundary='noflux', Flow=False, Velocitytop='', Flowstrength=1,
             Flowmax=8, Transform=False, Grow=0, Scalex=0, Scaley=0, Rotate=0, Translatex=0,
             Translatey=0, Pivotx=.5, Pivoty=.5, Feed=0, Kill=0, Diffusiona=0, Diffusionb=0,
             Fade=0, Strength=0, Dyeinject=0, Dyedecay=0, Dyespread=0, Transformedge='wrap',
             Influencemode='stamp', Resizebehavior='reset', Resetonsource=False)
    settings(**values)
    CLOCK.reset(C)


def sentinel():
    w,h=C.fetch('Appliedsize')[2:]
    y,x=np.mgrid[0:h,0:w]
    state=np.empty((h,w,4), dtype=np.float32)
    state[:,:,0]=.55+x/(w*5.)
    state[:,:,1]=.08+y/(h*6.)
    state[:,:,2]=(x-w/2)/(w*2.)
    state[:,:,3]=(y-h/2)/h
    upload(state)
    return state


def upload(state):
    node=SNAP.upload(C,state.astype('<f4').tobytes(),list(state.shape))
    for name in ('state_a','state_b'):
        CLOCK.capture(C.op(name),node)
    CLOCK._clock(C)['buffer']=0
    C.op('state_read').par.top='state_a'


def fetch(a,x,y,mode):
    h,w=a.shape[:2]
    if mode=='wrap': return a[y%h,x%w]
    inside=(x>=0)&(x<w)&(y>=0)&(y<h)
    result=a[np.clip(y,0,h-1),np.clip(x,0,w-1)]
    return np.where(inside[:,:,None],result,EMPTY) if mode=='clear' else result


def bilinear(a,x,y,mode):
    ix,iy=np.floor(x).astype(int),np.floor(y).astype(int)
    fx,fy=(x-ix)[:,:,None],(y-iy)[:,:,None]
    lo=fetch(a,ix,iy,mode)*(1-fx)+fetch(a,ix+1,iy,mode)*fx
    hi=fetch(a,ix,iy+1,mode)*(1-fx)+fetch(a,ix+1,iy+1,mode)*fx
    return (lo*(1-fy)+hi*fy).astype(np.float32)


def transport(a,mode,translate=(0,0),scale=(0,0),grow=0,rotate=0,pivot=(.5,.5),flow=(0,0)):
    h,w=a.shape[:2];y,x=np.mgrid[0:h,0:w];dt=1/60
    px,py=pivot[0]*w,pivot[1]*h
    x=x+.5-flow[0]*dt-translate[0]*dt-px
    y=y+.5-flow[1]*dt-translate[1]*dt-py
    angle=np.deg2rad(rotate)*dt;c,s=np.cos(angle),np.sin(angle)
    sx=np.exp((grow+scale[0])*.01*dt);sy=np.exp((grow+scale[1])*.01*dt)
    qx=(c*x+s*y)/sx+px-.5;qy=(-s*x+c*y)/sy+py-.5
    return bilinear(a,qx,qy,mode)


def isolated_transport():
    C.op('state_transform').inputConnectors[0].connect(C.op('state_read'))


def ordinary_transport():
    C.op('state_transform').inputConnectors[0].connect(C.op('reaction_diffusion'))


def stationary():
    check('boundary on simulation page',C.par.Transformedge.page.name=='Turing')
    check('three explicit labels',list(C.par.Transformedge.menuLabels)==['Wrap','No Flux','Empty Exterior'])
    for mode in ('wrap','noflux','clear'):
        configure(Transformedge=mode,Diffusiona=1,Diffusionb=.5)
        CLOCK.tick(C)
        equal('uniform empty stable '+mode,np.tile(EMPTY,(64,64,1)),image('state'),exact=True)
        # A=0 prevents reaction in this one-pass pure-B diffusion impulse.
        a=np.zeros((64,64,4),np.float32);a[0,0,1]=.4;upload(a)
        solver=C.op('reaction_diffusion');solver.par.npasses=1
        expected=a.copy();lap=np.zeros((64,64,2),np.float32);y,x=np.mgrid[0:64,0:64]
        for dx,dy,weight in ((-1,0,.2),(1,0,.2),(0,-1,.2),(0,1,.2),
                              (-1,-1,.05),(1,-1,.05),(-1,1,.05),(1,1,.05)):
            lap+=weight*(fetch(a,x+dx,y+dy,mode)[:,:,:2]-a[:,:,:2])
        expected[:,:,:2]=np.clip(a[:,:,:2]+lap*np.array([1,.5]),0,1)
        equal('stationary stencil CPU '+mode,expected,image('reaction_diffusion'),tol=1e-6)
        solver.par.npasses.expr='16 * parent().par.Solverquality'


def global_transforms():
    cases=[('integer x',dict(translate=(60,0))),('negative y',dict(translate=(0,-120))),
           ('fractional diagonal',dict(translate=(25,-17))),('growth',dict(grow=80)),
           ('anisotropic scale',dict(scale=(120,-80))),('rotation',dict(rotate=450,pivot=(.3,.7))),
           ('combined',dict(translate=(97,-123),grow=20,scale=(70,-90),rotate=-400,pivot=(.2,.8)))]
    for mode in ('wrap','noflux','clear'):
        configure(Transformedge=mode,Rectangle=True,Canvaswidth=192,Canvasheight=128,Cellsize=2)
        a=sentinel();isolated_transport()
        for label,case in cases:
            translate=case.get('translate',(0,0));scale=case.get('scale',(0,0));pivot=case.get('pivot',(.5,.5))
            settings(Transform=True,Translatex=translate[0],Translatey=translate[1],Grow=case.get('grow',0),
                     Scalex=scale[0],Scaley=scale[1],Rotate=case.get('rotate',0),Pivotx=pivot[0],Pivoty=pivot[1])
            equal('global CPU '+mode+' '+label,transport(a,mode,**case),image('state_transform'))
        settings(Grow=0,Scalex=0,Scaley=0,Rotate=0,Translatex=0,Translatey=0)
        equal('global zero identity '+mode,a,image('state_transform'),exact=True)
        ordinary_transport()


def field(x=0,y=0,code=None,width=64,height=64):
    VELOCITY.par.resolutionw=width;VELOCITY.par.resolutionh=height
    VELOCITY.par.pixeldat.eval().text=code or ('out vec4 fragColor;void main(){fragColor=TDOutputSwizzle(vec4(%s,%s,9.,.13));}'%(float(x),float(y)))


def velocity_checks():
    for mode in ('wrap','noflux','clear'):
        configure(Transformedge=mode,Flow=True,Velocitytop=VELOCITY.path,
                  Rectangle=True,Canvaswidth=192,Canvasheight=128,Cellsize=2)
        a=sentinel();isolated_transport()
        for vx,vy in ((60,0),(-120,0),(0,60),(0,-60),(23,-19)):
            field(vx,vy,width=32,height=24)
            equal('velocity signed CPU '+mode+' '+str((vx,vy)),transport(a,mode,flow=(vx,vy)),image('state_transform'))
        field(120,60);settings(Flowstrength=.5)
        equal('velocity strength '+mode,transport(a,mode,flow=(60,30)),image('state_transform'))
        settings(Flowstrength=1,Flowmax=2);field(600,800)
        equal('velocity length bound '+mode,transport(a,mode,flow=(72,96)),image('state_transform'))
        field(1e30,-1e30);settings(Flowstrength=100)
        equal('finite extreme bounded '+mode,transport(a,mode,flow=(60*2/np.sqrt(2),-60*2/np.sqrt(2))),image('state_transform'))
        settings(Flowmax=0)
        equal('zero max exact '+mode,a,image('state_transform'),exact=True)
        settings(Flowmax=8,Flowstrength=0)
        equal('zero strength exact '+mode,a,image('state_transform'),exact=True)
        settings(Flowstrength=1)
        field(code='out vec4 fragColor;void main(){fragColor=TDOutputSwizzle(vec4(uintBitsToFloat(0x7fc00000u),uintBitsToFloat(0x7f800000u),0.,0.));}')
        equal('nonfinite velocity sanitized '+mode,a,image('state_transform'),exact=True)
        field(60,30);settings(Transform=True,Grow=50,Rotate=-360,Translatex=120,Translatey=-80)
        equal('global then flow CPU '+mode,transport(a,mode,flow=(60,30),grow=50,rotate=-360,translate=(120,-80)),image('state_transform'))
        ordinary_transport()
    # Linear raw TOP sampled at normalized centers, signed RG preserved and BA ignored.
    configure(Flow=True,Velocitytop=VELOCITY.path,Rectangle=True,Canvaswidth=192,Canvasheight=128,Cellsize=2,Transformedge='noflux')
    field(code='out vec4 fragColor;void main(){fragColor=TDOutputSwizzle(vec4(vUV.s*120.-60.,vUV.t*60.-30.,999.,0.));}',width=32,height=24)
    v=image('velocity_field');y,x=np.mgrid[0:64,0:96]
    expected=np.stack((np.clip((x+.5)/96, .5/32,1-.5/32)*120-60,
                       np.clip((y+.5)/64,.5/24,1-.5/24)*60-30),axis=2)
    equal('velocity normalized bilinear signed RG',expected.astype(np.float32),v[:,:,:2],tol=1e-5)
    check('velocity BA ignored',np.all(v[:,:,2:]==0))


def zero_replay():
    field(0,0)
    for mode in ('wrap','noflux','clear'):
        for global_motion in (False,True):
            configure(Transformedge=mode,Rectangle=True,Canvaswidth=192,Canvasheight=128,Cellsize=2,
                      Ambient=True,Feed=.0545,Kill=.062,Diffusiona=1,Diffusionb=.5,
                      Transform=global_motion,Grow=12,Rotate=60,Translatex=-45)
            sentinel();snap=SNAP.capture(C)
            for _ in range(6): CLOCK.tick(C)
            expected={n:image(n) for n in OUTPUTS}
            SNAP.restore(C,snap);settings(Flow=True,Velocitytop=VELOCITY.path)
            for _ in range(6): CLOCK.tick(C)
            for n in OUTPUTS:
                equal('zero field ordinary '+mode+' '+str(global_motion)+' '+n,expected[n],image(n),exact=True)
    for mode in ('wrap','noflux','clear'):
        results=[]
        for fps in (30,60):
            configure(Transformedge=mode,Ambient=True,Feed=.0545,Kill=.062,Diffusiona=1,Diffusionb=.5,
                      Pause=False,Renderfps=fps,Flow=True,Velocitytop=VELOCITY.path,
                      Transform=True,Grow=10,Rotate=12,Translatex=3)
            for _ in range(fps):
                CLOCK.advance(C,sample=lambda c,t,s:field(12*np.sin(t*.1),9*np.cos(t*.07)))
            results.append({n:image(n) for n in OUTPUTS})
        for n in OUTPUTS:
            equal('flow 30 60 replay '+mode+' '+n,results[0][n],results[1][n],exact=True)


def domain_checks():
    for mode in ('wrap','noflux','clear'):
        for wall in ('noflux','empty'):
            configure(Transformedge=mode,Domaintop=DOMAIN.path,Domainboundary=wall,
                      Flow=True,Velocitytop=VELOCITY.path,Flowmax=64)
            a=np.tile(EMPTY,(64,64,1));a[:,10:31]=[.5,.25,-.12,.08];upload(a)
            field(360,0);isolated_transport()
            result=image('state_transform')
            equal('flow wall no leak '+mode+' '+wall,np.tile(EMPTY,(64,30,1)),result[:,33:63],exact=True)
            # Wrap seam at column 0 is also blocked by a wall in this fixture.
            field(-360,0);result=image('state_transform')
            equal('flow seam wall no leak '+mode+' '+wall,np.tile(EMPTY,(64,1,1)),result[:,63:64],exact=True)
            ordinary_transport()
    # Empty canvas remains empty at exterior even with independent No Flux walls.
    DOMAIN.par.pixeldat.eval().text='out vec4 fragColor;void main(){fragColor=vec4(1);}'
    configure(Transformedge='clear',Domaintop=DOMAIN.path,Domainboundary='noflux',
              Flow=True,Velocitytop=VELOCITY.path)
    sentinel();field(120,0);isolated_transport()
    equal('canvas empty independent wall noflux',np.tile(EMPTY,(64,1,1)),image('state_transform')[:,1:2],exact=True)
    ordinary_transport();DOMAIN.par.pixeldat.eval().text=DOMAIN_CODE
    # A diagonal backtrace cannot cut between two blocked orthogonal cells.
    DOMAIN.par.pixeldat.eval().text='out vec4 fragColor;void main(){ivec2 p=ivec2(gl_FragCoord.xy);float v=(p==ivec2(16,16)||p==ivec2(17,17))?1.:0.;fragColor=TDOutputSwizzle(vec4(vec3(v),1));}'
    configure(Domaintop=DOMAIN.path,Flow=True,Velocitytop=VELOCITY.path)
    a=np.tile(EMPTY,(64,64,1));a[16,16]=[.5,.25,-.12,.08];upload(a);field(60,60);isolated_transport()
    equal('flow diagonal blocked corner',EMPTY,image('state_transform')[17,17],exact=True)
    ordinary_transport();DOMAIN.par.pixeldat.eval().text=DOMAIN_CODE


def display_checks():
    configure(Rectangle=True,Canvaswidth=128,Canvasheight=128,Cellsize=2)
    a=np.tile(EMPTY,(64,64,1));a[:,-1]=[.5,.4,-.2,.1];upload(a)
    # Use the actual reconstruction functions, exporting raw reconstructed state
    # before the color conversion to compare the defined display edge policy.
    code=C.op('display_pixel').text.rsplit('void main()',1)[0]+'void main(){fragColor=TDOutputSwizzle(sampleState(vUV.st));}'
    dat=C.create(textDAT,'reconstruction_pixel');dat.text=code
    top=C.create(glslTOP,'reconstruction');top.par.pixeldat=dat.name
    top.par.glslversion='glsl460';top.par.format='rgba32float';top.par.outputresolution='custom';top.par.resolutionw=128;top.par.resolutionh=128
    for i,n in enumerate(('state_read','media_cache','palette')):top.inputConnectors[i].connect(C.op(n))
    info=C.create(infoDAT,'reconstruction_info');info.par.op=top.name
    top.seq.vec.numBlocks=2;top.par.vec0name='uBoundary';top.par.vec1name='uUpscale'
    for filter_index in (0,1,2):
        top.par.vec1valuex=filter_index
        rows={}
        for index,mode in enumerate(('wrap','noflux','clear')):
            top.par.vec0valuex=index;top.cook(force=True);rows[mode]=top.numpyArray(delayed=False).copy()
        equal('display closed modes identical '+str(filter_index),rows['noflux'],rows['clear'],exact=True)
        equal('display closed left holds edge '+str(filter_index),np.tile(EMPTY,(128,1,1)),rows['noflux'][:,:1],tol=1e-6)
        if filter_index!=2:
            check('display wrap connects edges '+str(filter_index),np.max(np.abs(rows['wrap'][:,0,1]))>.01)
    check('reconstruction shader compiled',not top.errors(),errors=top.errors())


def integration():
    configure(Transformedge='noflux',Flow=True,Velocitytop=VELOCITY.path,Flowstrength=.7,Flowmax=3)
    field(30,15);sentinel();snap=SNAP.capture(C)
    check('snapshot flow settings binding',snap['metadata']['settings']['Flow'] and snap['metadata']['bindings']['Velocitytop']==VELOCITY.path)
    for _ in range(4):CLOCK.tick(C)
    future=image('state');settings(Flow=False,Velocitytop='',Flowstrength=4,Flowmax=12)
    SNAP.restore(C,snap)
    for _ in range(4):CLOCK.tick(C)
    equal('flow snapshot deterministic replay',future,image('state'),exact=True)
    LIB=C.op('preset_lib').module
    settings(Presetname='Phase6 Flow',Presetbindings=True)
    before=image('state');LIB.on_save(C)
    settings(Flow=False,Flowstrength=1,Flowmax=8,Velocitytop='',Transformedge='wrap')
    LIB.on_apply(C)
    check('preset roundtrip flow binding boundary',bool(C.par.Flow) and abs(C.par.Flowstrength-.7)<1e-6 and C.par.Flowmax==3 and C.par.Velocitytop.eval()==VELOCITY and C.par.Transformedge=='noflux')
    equal('flow preset apply keeps state',before,image('state'),exact=True)
    legacy=copy.deepcopy(snap)
    for n in ('Flow','Flowstrength','Flowmax'):legacy['metadata']['settings'].pop(n)
    legacy['metadata']['bindings'].pop('Velocitytop')
    SNAP.restore(C,legacy)
    check('phase5 snapshot disables flow',not C.par.Flow and C.par.Velocitytop.eval() is None)
    broken=copy.deepcopy(snap);broken['metadata']['settings'].pop('Flowmax')
    try:SNAP.restore(C,broken);refused=False
    except SNAP.SnapshotError:refused=True
    check('partial new flow snapshot refused',refused)
    configure(Flow=True,Velocitytop=VELOCITY.path);field(30,15);sentinel();before=image('state')
    age=CLOCK._clock(C)['ticks'];CLOCK.advance(C,elapsed=10)
    equal('pause freezes flow',before,image('state'),exact=True)
    check('pause freezes flow age',CLOCK._clock(C)['ticks']==age)
    CLOCK.step(C)
    check('step moves one flow tick',CLOCK._clock(C)['ticks']==age+1 and not np.array_equal(before,image('state')))
    configure(Flow=True,Velocitytop='',Transform=False);a=sentinel();isolated_transport()
    equal('blank velocity exact bypass',a,image('state_transform'),exact=True);ordinary_transport()


def fixture(name,code):
    n=C.parent().create(glslTOP,name);d=C.parent().create(textDAT,name+'_pixel');d.text=code
    n.par.pixeldat=d.name;n.par.format='rgba32float';n.par.outputresolution='custom'
    n.par.resolutionw=64;n.par.resolutionh=64;n.viewer=True
    return n

DOMAIN_CODE='out vec4 fragColor;void main(){ivec2 p=ivec2(gl_FragCoord.xy);float v=(p.x!=32 && p.x!=0)?1.:0.;fragColor=TDOutputSwizzle(vec4(vec3(v),1));}'
OUTPUTS=('state','palette','out1','patterns','mask_preview','source_preview')


def start(c,output_dir):
    global C,OUT,CLOCK,SNAP,VELOCITY,DOMAIN,REPORT,TASKS
    C=c;OUT=Path(output_dir);OUT.mkdir(parents=True,exist_ok=True)
    C.op('clock').par.active=False;C.op('controls').par.active=False;C.op('controls').cook(force=True)
    CLOCK=C.op('clock').module;SNAP=C.op('snapshot_lib').module
    REPORT=dict(build=str(app.version)+'.'+str(app.build),checks={},affine_tolerance=TOL,
                source_sha256=hashlib.sha256((OUT.parents[1]/'create_turing_media_v2.py').read_bytes()).hexdigest())
    VELOCITY=fixture('phase6_velocity','out vec4 fragColor;void main(){fragColor=vec4(0);}')
    DOMAIN=fixture('phase6_domain',DOMAIN_CODE)
    # Global transforms are validated before any velocity input is enabled.
    TASKS=[stationary,global_transforms,velocity_checks,zero_replay,domain_checks,display_checks,integration]
    run('args[0].module.next_test()',me,delayFrames=3)


def next_test():
    if TASKS:
        fn=TASKS.pop(0)
        try:fn()
        except Exception:check(fn.__name__+' completed',False,exception=traceback.format_exc());print(traceback.format_exc());ordinary_transport()
        (OUT/'progress.json').write_text(json.dumps(REPORT,indent=2))
        run('args[0].module.next_test()',me,delayFrames=3)
    else:
        for n in C.children:
            if n.family=='TOP':n.cook(force=True)
        run('args[0].module.finish()',me,delayFrames=3)


def finish():
    check('no shader or operator errors',not C.errors(recurse=True),errors=C.errors(recurse=True))
    REPORT['shaders']={n.name:n.text for n in C.children if n.family=='DAT' and n.name.endswith('_info')}
    check('all shaders compiled',all('Compiled Successfully' in s for s in REPORT['shaders'].values()))
    REPORT['passed']=all(v['passed'] for v in REPORT['checks'].values())
    (OUT/'report.json').write_text(json.dumps(REPORT,indent=2))
    print('PHASE6_COMPLETE',REPORT['passed'],len(REPORT['checks']))


def start_frames(c,output_dir):
    """Real parameter edits and Step pulses across timeline frames."""
    global C,OUT,CLOCK,SNAP,VELOCITY,REPORT
    C=c;OUT=Path(output_dir);C.op('clock').par.active=False
    CLOCK=C.op('clock').module;SNAP=C.op('snapshot_lib').module
    C.op('controls').par.active=False;C.op('controls').cook(force=True)
    configure(Transformedge='wrap')
    VELOCITY=fixture('frame_velocity','out vec4 fragColor;void main(){fragColor=TDOutputSwizzle(vec4(30.,-15.,9.,.01));}')
    y,x=np.mgrid[0:64,0:64];a=np.zeros((64,64,4),np.float32)
    a[:,:,1]=.05+x/200.;a[:,:,2]=(x-32)/128.;a[:,:,3]=(y-32)/128.;upload(a)
    C.op('controls').par.active=True;C.op('controls').cook(force=True)
    REPORT=dict(build=str(app.version)+'.'+str(app.build),checks={},source_sha256=hashlib.sha256(C.parent().op('builder').text.encode()).hexdigest())
    run('args[0].module.frame_edits()',me,delayFrames=4)


def frame_edits():
    C.store('Phase6frame_before',image('state'));C.store('Phase6frame_resets',C.fetch('Resetcount'))
    C.par.Flow=True;C.par.Velocitytop=VELOCITY.path;C.par.Flowstrength=.8;C.par.Flowmax=3
    C.par.Transformedge='clear'
    run('args[0].module.frame_boundary()',me,delayFrames=3)


def frame_boundary():
    equal('paused flow and boundary edits retain state',C.fetch('Phase6frame_before'),image('state'),exact=True)
    check('flow and boundary edits cause no reset',C.fetch('Resetcount')==C.fetch('Phase6frame_resets'))
    C.par.Transformedge='noflux';C.par.Step.pulse()
    run('args[0].module.frame_after_step()',me,delayFrames=3)


def frame_after_step():
    check('actual Step pulse one flow tick',CLOCK._clock(C)['ticks']==1)
    equal('actual Step uses latest flow and boundary',transport(C.fetch('Phase6frame_before'),'noflux',flow=(24,-12)),image('state'),tol=1e-6)
    C.store('Phase6frame_after',image('state'));C.par.Flow=False
    run('args[0].module.frame_finish()',me,delayFrames=3)


def frame_finish():
    equal('disable flow while paused holds',C.fetch('Phase6frame_after'),image('state'),exact=True)
    check('flow controls keep pause and age',bool(C.par.Pause) and CLOCK._clock(C)['ticks']==1)
    check('real controls no shader errors',not C.errors(recurse=True),errors=C.errors(recurse=True))
    REPORT['passed']=all(v['passed'] for v in REPORT['checks'].values())
    (OUT/'frame_report.json').write_text(json.dumps(REPORT,indent=2))
    print('PHASE6_FRAMES_COMPLETE',REPORT['passed'],len(REPORT['checks']))
