"""Inside TD: module.validate(demo, output_directory). Use a test copy."""
def validate(demo, directory):
    import json
    from pathlib import Path
    import numpy as np
    dest=Path(directory)
    solver=demo.op('fluid_solver')
    runtime=solver.op('runtime').module
    solver.op('clock').par.active=False
    demo.par.Pause=True
    checks={}
    def check(name,condition):
        checks[name]=bool(condition)
        if not condition:
            raise AssertionError(name)
    def sources():
        return runtime.read_sources(solver,1/60).copy()
    def image(name):
        demo.op(name).cook(force=True)
        return demo.op(name).numpyArray(delayed=False).copy()
    runtime.reset(solver)
    initial=sources()
    check('four CHOP sources',solver.par.Sources.eval()==4)
    check('one sample per channel',demo.op('DROPPERS').numSamples==1 and demo.op('DROPPERS').numChans==32)
    check('source wire reaches solver',solver.inputs[0]==demo.op('DROPPERS') and solver.par.Sourcechop.eval() is None)
    palette=np.array([[1.,.08,.025],[.02,.65,1.],[1.,.65,.04],[.45,.04,1.]])
    check('independent colors',np.allclose(initial[1,:4,:3],palette))
    check('UV source positions',np.all(initial[0,:4,:2]>0) and np.all(initial[0,:4,:2]<1))
    runtime.tick(solver)
    raw=image('out2')
    for i in range(4):
        x,y=initial[0,i,:2]
        j=int(round(y*(raw.shape[0]-1))); k=int(round(x*(raw.shape[1]-1)))
        rgba=raw[j,k]
        check('dropper '+str(i+1)+' injects own RGB',rgba[3]>0 and np.allclose(rgba[:3]/rgba[3],palette[i],atol=1e-4))
    for _ in range(8):
        runtime.tick(solver)
    moved=sources()
    check('every dropper moves',np.all(np.linalg.norm(moved[0,:4,:2]-initial[0,:4,:2],axis=1)>.001))
    age=solver.par.Simtime.eval()
    frozen=demo.op('DROPPERS').numpyArray().copy()
    runtime.advance(solver,elapsed=5)
    demo.op('DROPPERS').cook(force=True)
    check('pause holds motion and fluid time',solver.par.Simtime.eval()==age and np.array_equal(frozen,demo.op('DROPPERS').numpyArray()))
    demo.op('demo_controls').module.onPulse(demo.par.Step)
    check('demo Step advances one tick',abs(solver.par.Simtime.eval()-age-solver.par.Timestep.eval())<1e-6)
    demo.par.D2active=False
    check('individual dropper disabled',sources()[1,1,3]==0 and sources()[1,0,3]==1)
    demo.par.D2active=True
    demo.par.D3red=.25
    check('individual color editable',abs(sources()[1,2,0]-.25)<1e-6 and abs(sources()[1,0,0]-1)<1e-6)
    demo.par.D3red=1
    demo.op('demo_controls').module.onPulse(demo.par.Reset)
    reset=sources()
    check('Reset restores orbit positions',np.allclose(reset[0,:4,:2],initial[0,:4,:2]) and solver.par.Simtime.eval()==0)
    check('Reset clears dye',not image('out2').any())
    demo.par.Motionspeed=0
    stopped=sources()[0,:4,:2].copy()
    for _ in range(2): runtime.tick(solver)
    check('motion speed zero holds droppers',np.allclose(stopped,sources()[0,:4,:2]))
    demo.par.Motionspeed=1
    runtime.reset(solver)
    for _ in range(180): runtime.tick(solver)
    check('colored simulation finite',np.isfinite(image('out2')).all() and image('out2')[:,:,3].max()>0)
    check('demo error free',not demo.errors(recurse=True))
    demo.op('out1').save(str(dest/'demo_preview.png'))
    # Save an immediately playable, clean-state demo.
    runtime.reset(solver)
    demo.par.Pause=False
    solver.op('clock').par.active=True
    demo.save(str(dest/'fluid_demo.tox'))
    solver.op('clock').par.active=False
    demo.par.Pause=True
    loaded=demo.parent().loadTox(str(dest/'fluid_demo.tox'))
    loaded.op('fluid_solver/clock').par.active=False
    loaded.par.Pause=True
    lr=loaded.op('fluid_solver/runtime').module
    a=lr.read_sources(loaded.op('fluid_solver'),1/60)
    check('TOX reload retains relative CHOP wiring',loaded.op('fluid_solver').inputs[0]==loaded.op('DROPPERS') and np.allclose(a[1,:4,:3],palette))
    lr.tick(loaded.op('fluid_solver'))
    loaded.op('out2').cook(force=True)
    check('reloaded TOX injects dye',loaded.op('out2').numpyArray(delayed=False)[:,:,3].max()>0)
    check('reloaded TOX error free',not loaded.errors(recurse=True))
    result={'build':str(app.build),'component':demo.path,'checks':checks}
    (dest/'demo_validation.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
