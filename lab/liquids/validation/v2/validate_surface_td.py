"""Inside TouchDesigner: module.validate(component, directory). Use a test copy."""
def validate(c, directory):
    import json
    import math
    from pathlib import Path
    import numpy as np
    dest=Path(directory)
    dest.mkdir(parents=True,exist_ok=True)
    r=c.op('runtime').module
    c.op('clock').par.active=False
    c.par.Pause=True
    checks={}
    def check(name,condition):
        checks[name]=bool(condition)
        if not condition: raise AssertionError(name)
    def img(name):
        c.op(name).cook(force=True)
        return c.op(name).numpyArray(delayed=False).copy()
    def setpar(name,value): getattr(c.par,name).val=value
    for name,value in [('Width',64),('Height',48),('Emit',False),('Dyedecay',0),('Buoyancy',0),
                       ('Vorticity',0),('Jetx',0),('Jety',0),('Windx',0),('Windy',0),('Residue',True)]:
        setpar(name,value)
    r.reset(c)
    check('six public TOP outputs',len(c.outputConnectors)==6)
    check('empty height zero',not img('out4')[:,:,0].any())
    check('empty normals face camera',np.allclose(img('out5')[:,:,:3],[.5,.5,1.]))
    check('empty residue zero',not img('out6').any())
    # Use the production dye-injection path to build a controlled Gaussian mound.
    # This exercises the real source upload, transport, and state caches together.
    for name,value in [('X',.5),('Y',.5),('R',.1),('G',.4),('B',.8),('Radius',.12),('Dyerate',36),('Residue',False),('Emit',True)]:
        setpar(name,value)
    for _ in range(10): r.tick(c)
    c.par.Emit=False
    c.par.Residue=True
    density=img('out2').copy()
    height=img('out4')[:,:,0]
    normals=img('out5')[:,:,:3]*2-1
    check('height positive and bounded',height.max()>0 and height.max()<=c.par.Heightscale.eval()+1e-6)
    check('unit surface normals',np.allclose(np.linalg.norm(normals,axis=2),1,atol=2e-6))
    check('normals slope outward',normals[24,37,0]>.01 and normals[24,26,0]<-.01)
    c.par.Renderstyle='flat'; flat=img('out1')
    c.par.Renderstyle='surface'; shaded=img('out1')
    check('surface visibly differs from flat',np.max(np.abs(shaded-flat))>.03)
    c.par.Heightscale=0
    check('zero height flattens normals',np.allclose(img('out5')[:,:,:3],[.5,.5,1.]))
    c.par.Heightscale=.025
    c.par.Heightsmoothing=0
    sharp=np.linalg.norm(img('out5')[:,:,:2]*2-1,axis=2).max()
    c.par.Heightsmoothing=3
    smooth=np.linalg.norm(img('out5')[:,:,:2]*2-1,axis=2).max()
    check('smoothing reduces surface slopes',smooth<sharp)
    c.par.Heightsmoothing=1.25
    c.par.Roughness=.12; glossy=img('out1')
    c.par.Roughness=.8; rough=img('out1')
    check('roughness changes highlights',np.max(np.abs(glossy-rough))>.005)
    c.par.Roughness=.28
    c.par.Lightazimuth=-45; left=img('out1')
    c.par.Lightazimuth=135; right=img('out1')
    check('light direction changes shading',np.max(np.abs(left-right))>.03)
    mat=c.parent().create(constantTOP,'v2_matcap_fixture')
    mat.par.colorr=1; mat.par.colorg=.1; mat.par.colorb=0; mat.par.alpha=1
    mat.cook(force=True)
    c.par.Matcapstrength=1
    without=img('out1')
    c.par.Matcaptop=mat
    with_mat=img('out1')
    check('external Matcap contributes',np.max(np.abs(with_mat-without))>.1)
    c.par.Matcaptop=''
    c.par.Matcapstrength=.35
    check('surface controls preserve dye state',np.array_equal(img('out2'),density))
    c.par.Residuefade=.6
    r.tick(c)
    stain=img('out6')
    check('wet dye records colored residue',stain[:,:,3].max()>.1 and np.allclose(stain[24,32,:3],[.1,.4,.8],atol=1e-5))
    r.capture(c,'d_a','zero'); r.capture(c,'d_b','zero')
    check('dye clear removes relief',not img('out4')[:,:,0].any())
    check('residue survives dye clearing',np.array_equal(img('out6'),stain))
    c.par.Transparent=True
    residual=img('out1')
    expected_alpha=stain[:,:,3]*c.par.Residueopacity.eval()
    check('transparent residue alpha',np.allclose(residual[:,:,3],expected_alpha,atol=1e-6))
    check('transparent RGB premultiplied',np.all(residual[residual[:,:,3]==0,:3]==0))
    c.par.Residue=False
    check('residue toggle hides film',not img('out1').any())
    c.par.Residue=True
    r.tick(c,dt=.1)
    faded=img('out6')
    check('residue fades in simulation seconds',np.allclose(faded[:,:,3],stain[:,:,3]*math.exp(-.6*.1),atol=2e-6))
    check('residue remains stationary',np.unravel_index(np.argmax(stain[:,:,3]),stain.shape[:2])==np.unravel_index(np.argmax(faded[:,:,3]),faded.shape[:2]))
    old=faded.copy()
    r.advance(c,elapsed=10)
    check('pause preserves residue',np.array_equal(img('out6'),old))
    c.op('controls').module.onPulse(c.par.Clearresidue)
    check('Clear Residue clears history',not img('out6').any())
    for mode in ('height','normals','residue'):
        c.par.View=mode
        check(mode+' diagnostic finite',np.isfinite(img('out1')).all())
    c.par.View='dye'; c.par.Boundary='wrap'
    r.reset(c); r.tick(c)
    check('periodic surface fields finite',np.isfinite(img('out5')).all())
    c.par.Width=80; c.par.Height=40
    r.reset(c)
    check('surface and history resize',img('out4').shape==(40,80,4) and img('out6').shape==(40,80,4))
    check('no operator errors',not c.errors(recurse=True))
    # Restore default standalone parameters and create a reusable V2 TOX.
    for name,value in [('Width',384),('Height',256),('Boundary','closed'),('Emit',True),('Dyedecay',.2),
                       ('Buoyancy',.2),('Vorticity',12),('Jety',1),('X',.5),('Y',.25),('R',.08),('G',.5),('B',1),('Radius',.045),('Dyerate',12),('Residuefade',.08),('Transparent',False)]:
        setpar(name,value)
    r.reset(c)
    c.par.Pause=False
    c.op('clock').par.active=True
    c.save(str(dest/'fluid_solver_v2.tox'))
    c.op('clock').par.active=False
    c.par.Pause=True
    loaded=c.parent().loadTox(str(dest/'fluid_solver_v2.tox'))
    loaded.op('clock').par.active=False; loaded.par.Pause=True
    lr=loaded.op('runtime').module
    loaded.op('out6').cook(force=True)
    check('TOX load clears residue',not loaded.op('out6').numpyArray(delayed=False).any())
    lr.tick(loaded)
    loaded.op('out4').cook(force=True)
    loaded.op('out6').cook(force=True)
    check('TOX reload generates relief and residue',loaded.op('out4').numpyArray(delayed=False)[:,:,0].max()>0 and loaded.op('out6').numpyArray(delayed=False)[:,:,3].max()>0)
    check('reloaded solver error free',not loaded.errors(recurse=True))
    result={'build':str(app.build),'component':c.path,'checks':checks}
    (dest/'surface_validation.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
