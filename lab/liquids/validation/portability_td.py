"""Inside TD: module.validate(component, output_directory). Use a test copy."""
def validate(c, directory):
    import json
    from pathlib import Path
    host=c.parent()
    c.par.Pause=True
    c.op('runtime').module.reset(c)
    c.op('clock').par.active=True
    destination=str(Path(directory,'fluid_solver_test.tox'))
    c.save(destination)
    loaded=host.loadTox(destination)
    loaded.op('clock').par.active=False
    loaded.par.Pause=True
    loaded.op('out2').cook(force=True)
    result={'loaded':loaded.path,'errors':loaded.errors(recurse=True),
            'density_max_on_load':float(loaded.op('out2').numpyArray(delayed=False).max())}
    loaded.op('runtime').module.tick(loaded)
    loaded.op('out2').cook(force=True)
    result['density_after_tick']=float(loaded.op('out2').numpyArray(delayed=False)[:,:,3].max())
    assert not result['errors']
    assert result['density_max_on_load']==0
    assert result['density_after_tick']>0
    c.op('clock').par.active=False
    Path(directory,'portability.json').write_text(json.dumps(result,indent=2))
    return result
