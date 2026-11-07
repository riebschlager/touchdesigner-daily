"""Run in TouchDesigner after building: validate(component, output_directory)."""
def validate(c, directory):
    import json
    import math
    from pathlib import Path
    import numpy as np
    r=c.op('runtime').module
    checks={}
    metrics={}
    def check(name, condition):
        checks[name]=bool(condition)
        if not condition: raise AssertionError(name)
    def array(name):
        c.op(name).cook(force=True)
        return c.op(name).numpyArray(delayed=False).copy()
    c.op('clock').par.active=False
    c.par.Pause=True
    c.par.Width=64; c.par.Height=48; c.par.Substeps=1
    c.par.Pressureiterations=100
    c.par.Vorticity=0; c.par.Buoyancy=0
    r.reset(c)
    check('reset is empty',np.max(np.abs(array('out2')))==0)
    r.tick(c)
    dye=array('out2')
    check('scalar source injects color',dye[:,:,3].max()>0 and np.allclose(dye[:,:,0],dye[:,:,3]*c.par.R.eval(),atol=1e-6))
    before=array('div_buffer')[:,:,0]
    after=array('divergence')[:,:,0]
    a=float(np.sqrt(np.mean(before*before))); b=float(np.sqrt(np.mean(after*after)))
    metrics['projection_rms_before']=a; metrics['projection_rms_after']=b
    check('projection reduces divergence',b<a*.3)
    vel=array('velocity_read')
    check('closed wall normal velocity',np.all(vel[:,-1,0]==0) and np.all(vel[-1,:,1]==0))
    saved=array('out2'); age=r.state(c)['age']
    r.advance(c,elapsed=10)
    check('pause holds state',np.array_equal(array('out2'),saved) and r.state(c)['age']==age)
    for _ in range(8): r.tick(c)
    check('finite evolving state',np.isfinite(array('out2')).all() and np.isfinite(array('velocity_read')).all())
    metrics['dye_density_max']=float(array('out2')[:,:,3].max())
    # Script CHOP represents a channel of independent droppers, not a time history.
    src=c.parent().create(scriptCHOP,'fluid_test_sources')
    cb=src.par.callbacks.eval()
    cb.text="""def onCook(o):
    o.clear(); o.numSamples=3
    for n,v in [('x',[.2,.5,.8]),('y',[.3,.5,.7]),('r',[1,0,0]),('g',[0,1,0]),('b',[0,0,1])]:
        o.appendChan(n).vals=v
"""
    src.cook(force=True)
    c.par.Sourcechop=src
    a=r.read_sources(c,1/60)
    check('sample sources and RGB',c.par.Sources.eval()==3 and np.allclose(a[0,:3,0],[.2,.5,.8]) and np.allclose(a[1,:3,:3],np.eye(3)))
    # A separate one-sample RGB CHOP broadcasts across sample droppers.
    colors=c.parent().create(constantCHOP,'fluid_test_color')
    colors.par.name0='r'; colors.par.value0=.9
    colors.par.name1='g'; colors.par.value1=.2
    colors.par.name2='b'; colors.par.value2=.1
    c.par.Colorschop=colors
    a=r.read_sources(c,1/60)
    check('separate RGB broadcasts',np.allclose(a[1,:3,:3],[[.9,.2,.1]]*3))
    c.par.Colorschop=''
    cb.text="""def onCook(o):
    o.clear(); o.numSamples=1
    for n,v in [('x0',.1),('y0',.2),('x1',.7),('y1',.8),('r',.6),('g',.3),('b',.1)]:
        o.appendChan(n)[0]=v
"""
    src.cook(force=True)
    a=r.read_sources(c,1/60)
    check('numbered sources and shared RGB',c.par.Sources.eval()==2 and np.allclose(a[0,:2,:2],[[.1,.2],[.7,.8]]) and np.allclose(a[1,:2,:3],[[.6,.3,.1]]*2))
    # Invalid input must fail explicitly rather than dropping a source silently.
    cb.text="""def onCook(o):
    o.clear(); o.numSamples=1; o.appendChan('x0')[0]=.5
"""
    src.cook(force=True)
    try: r.read_sources(c,1/60)
    except ValueError: check('missing Y rejected',True)
    else: check('missing Y rejected',False)
    c.par.Sourcechop=''
    c.par.Emit=False
    r.reset(c); r.tick(c)
    check('emit off is empty',np.max(np.abs(array('out2')))==0)
    # Check transport limiter and exponential decay on a controlled state.
    seed=c.parent().create(scriptTOP,'fluid_test_seed')
    seed.par.callbacks.eval().text="""import numpy as np
def onCook(o):
    a=np.zeros((48,64,4),np.float32); a[16:32,20:40,:]=1; o.copyNumpyArray(a)
"""
    seed.par.format='rgba32float'
    seed.cook(force=True)
    r.capture(c,'d_a',seed); r.bind(c,'dye_read','d_a')
    c.par.Windx=1.; c.par.Jety=0; c.par.Dyedecay=.5
    r.tick(c)
    a=array('out2')
    check('MacCormack remains bounded',a.min()>=0 and a.max()<=math.exp(-.5/60)+1e-6)
    c.par.Transparent=True
    output=array('out1')
    check('transparent output finite',np.isfinite(output).all() and output[:,:,3].min()>=0 and output[:,:,3].max()<=1)
    c.par.Boundary='wrap'; c.par.Windx=0.; c.par.Emit=True
    r.reset(c)
    for _ in range(3): r.tick(c)
    check('periodic solver finite',np.isfinite(array('out2')).all())
    c.par.Width=80; c.par.Height=40
    r.reset(c); r.tick(c)
    check('rectangular resize',array('out2').shape==(40,80,4))
    check('all shaders error free',not any(c.op(n).errors() for n in (
        'zero','advect_velocity','curl','forces','diffuse','divergence','pressure','project',
        'dye_forward','dye_reverse','dye_correct','dye_inject','display','velocity_output')))
    c.par.Viscosity=.0001; c.par.Advection='semi'
    r.tick(c)
    check('viscosity and semi-Lagrangian finite',np.isfinite(array('out2')).all() and np.isfinite(array('velocity_read')).all())
    c.par.Viscosity=0; c.par.Advection='maccormack'
    c.par.Coordinates='pixels'; c.par.X=40; c.par.Y=20
    a=r.read_sources(c,1/60)
    check('pixel coordinates',np.allclose(a[0,0,:2],[40/79,20/39]))
    c.par.Coordinates='uv'; c.par.X=.5; c.par.Y=.25
    r.reset(c); r.read_sources(c,1/60)
    c.par.X=.51
    a=r.read_sources(c,1/60)
    check('motion stirs fluid',a[2,0,0]>0)
    c.par.X=.99
    a=r.read_sources(c,1/60)
    check('teleport suppresses motion impulse',a[2,0,0]==0 and a[3,0,0]==a[0,0,0])
    c.par.X=.5
    r.reset(c); c.par.Pause=False
    r.advance(c,elapsed=0)
    check('frame clock advances one tick',abs(r.state(c)['age']-1/60)<1e-8)
    c.par.Clock='realtime'; r.reset(c)
    r.advance(c,elapsed=1.)
    check('real-time catch-up is bounded',abs(r.state(c)['age']-2/60)<1e-8 and c.par.Simlag.eval()>.9)
    c.par.Pause=True; c.par.Clock='frame'
    # Save preview, then restore scalar defaults.

    c.par.Sourcechop=''; c.par.Colorschop=''; c.par.Transparent=False
    c.par.Width=384; c.par.Height=256; c.par.Substeps=2
    c.par.Pressureiterations=50; c.par.Jety=1; c.par.Vorticity=12
    c.par.Buoyancy=.2; c.par.Dyedecay=.2; c.par.Boundary='closed'
    r.reset(c)
    for _ in range(120): r.tick(c)
    c.op('out1').cook(force=True)
    c.op('out1').save(str(Path(directory)/'preview.png'))
    check('component has no operator errors',not c.errors(recurse=True))
    c.par.Status='Validated; unpause to run'
    result={'build':str(app.build),'component':c.path,'checks':checks,'metrics':metrics}
    Path(directory,'validation.json').write_text(json.dumps(result,indent=2))
    return result
