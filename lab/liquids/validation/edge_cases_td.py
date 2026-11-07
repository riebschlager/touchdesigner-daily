"""Inside TD: module.validate(component, output_directory). Use a test copy."""
def validate(c, directory):
    import json
    from pathlib import Path
    import numpy as np
    host=c.parent()
    c.par.Pause=True; c.op('clock').par.active=False
    r=c.op('runtime').module
    checks={}
    def expect_error(name):
        try: r.read_sources(c,1/60)
        except (ValueError,FloatingPointError): checks[name]=True
        else: raise AssertionError(name)
    src=host.create(scriptCHOP,'fluid_edge_sources')
    cb=src.par.callbacks.eval()
    cb.text="def onCook(o):\n    o.clear(); o.numSamples=65\n    o.appendChan('x').vals=[.5]*65\n    o.appendChan('y').vals=[.5]*65\n"
    src.cook(force=True); c.par.Sourcechop=src
    expect_error('65 sources rejected')
    cb.text="def onCook(o):\n    o.clear(); o.numSamples=1\n    o.appendChan('x')[0]=float('nan')\n    o.appendChan('y')[0]=.5\n"
    src.cook(force=True)
    a=r.read_sources(c,1/60)
    checks['TD sanitizes NaN CHOP sample']=bool(np.isfinite(a).all() and src['x'][0]==0)
    cb.text="def onCook(o):\n    o.clear(); o.numSamples=2\n    o.appendChan('x').vals=[.3,.7]\n    o.appendChan('y').vals=[.4,.6]\n"
    src.cook(force=True)
    colors=host.create(scriptCHOP,'fluid_edge_colors')
    colors.par.callbacks.eval().text="def onCook(o):\n    o.clear(); o.numSamples=3; o.appendChan('r').vals=[1,0,1]\n"
    colors.cook(force=True); c.par.Colorschop=colors
    expect_error('incompatible RGB sample count rejected')
    c.par.Colorschop=''; c.par.Sourcechop=''
    c.inputConnectors[0].connect(src)
    a=r.read_sources(c,1/60)
    checks['wired CHOP input']=c.par.Sources.eval()==2 and np.allclose(a[0,:2,:2],[[.3,.4],[.7,.6]])
    assert all(checks.values()), checks
    c.inputConnectors[0].disconnect()
    r.reset(c)
    first=float(c.par.Simtime.eval())
    c.par.Pause=True; c.op('clock').par.active=False
    Path(directory,'edge_cases.json').write_text(json.dumps({'checks':checks,'live_start':first,'component':c.path},indent=2))
    return checks
