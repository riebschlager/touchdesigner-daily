"""Diagnostics and additional numerical checks in the actual TD GPU runtime."""
import ast
import hashlib
import json
import traceback
from pathlib import Path
import numpy as np

OUTPUTS = ('state', 'patterns', 'out1', 'source_preview', 'mask_preview', 'palette')


def check(name, passed, **details):
    REPORT['checks'][name] = dict(passed=bool(passed), **details)
    print('PHASE8_CHECK', name, bool(passed))


def image(name):
    C.op(name).cook(force=True)
    return C.op(name).numpyArray(delayed=False).copy()


def settings(**values):
    C.op('preset_lib').module.set_quietly(C, values)


def reset(**values):
    settings(Resolution=64, Rectangle=False, Cellsize=1, Clockmode='framestepped',
             Renderfps=60, Speed=1, Solverquality=1, Pause=True, Ambient=False,
             Transform=False, Flow=False, Sourcetop='', Moviefile='', Domaintop='',
             Ramptop='', Feed=.0545, Kill=.062, Diffusiona=1, Diffusionb=.5,
             Strength=5, Fade=0, Dyeinject=3, Dyedecay=0, Dyespread=665,
             Maskmode='alpha', Colormode='fixed', Influencemode='continuous',
             Transformedge='wrap', Carryhistory=True, Palettehistory=False, Paletteinterval=1)
    settings(**values)
    CLOCK.reset(C)


def start(c, folder):
    global C, OUT, REPORT, CLOCK, DIAG, TASKS
    C, OUT = c, Path(folder)
    CLOCK, DIAG = C.op('clock').module, C.op('diagnostics').module
    C.op('controls').par.active = False
    C.op('controls').cook(force=True)
    C.op('clock').par.active = False
    REPORT = {'build': str(app.version)+'.'+str(app.build),
              'source_sha256': hashlib.sha256(C.parent().op('builder').text.encode()).hexdigest(),
              'checks': {}}
    TASKS = [diagnostics, numerics, begin_shader_failure]
    next_task()


def next_task():
    if not TASKS:
        return
    task = TASKS.pop(0)
    try:
        task()
    except Exception:
        check(task.__name__+' completed', False, exception=traceback.format_exc())
        finish()
        return
    (OUT/'progress.json').write_text(json.dumps(REPORT, indent=2))
    if TASKS:
        run('args[0].module.next_task()', me, delayFrames=2)


def diagnostics():
    reset(Rectangle=True, Canvaswidth=96, Canvasheight=64, Cellsize=3, Solverquality=2)
    CLOCK.step(C)
    CLOCK._clock(C)['debt'] = .125
    CLOCK._status(C, 1)
    DIAG.refresh(C, compile_shaders=True)
    rows = dict(DIAG.status_rows(C))
    check('status effective rectangular grid', rows['Canvas / grid']=='96 x 64 / 32 x 21')
    check('status mode and pause', rows['Clock']=='framestepped / paused')
    check('status tick and substeps', rows['Ticks']=='1 total / 1 last frame' and rows['Substeps']=='32 per tick / 32 last frame')
    check('status lag units', rows['Time / lag']=='0.0167 s / 0.1250 s')
    check('unassigned source valid ambient', rows['Source']=='No media (ambient simulation)')
    check('status table and panel', C.op('status').numRows==10 and '32 x 21' in C.op('status_panel').par.text.eval()
          and C.op('status_panel').par.type.eval()=='multiline')
    check('all shaders initially checked', bool(C.fetch('Shaderhealth')) and all(s=='ok' for _,s in C.fetch('Shaderhealth')))
    check('full per-shader logs retained', 'reaction_diffusion [ok]' in C.op('shader_diagnostics').text)
    before={n:image(n) for n in OUTPUTS}
    histories={n:image(n) for n in ('media_a','media_b','palette_a','palette_b')}
    age=C.fetch('Clockstate')['ticks']
    parity=C.fetch('Clockstate')['media']
    for _ in range(3):DIAG.refresh(C, compile_shaders=True)
    check('diagnostics preserves all six outputs',all(np.array_equal(a,image(n)) for n,a in before.items()))
    check('diagnostics preserves motion and palette histories',all(np.array_equal(a,image(n)) for n,a in histories.items()))
    check('diagnostics preserves age debt and reader',C.fetch('Clockstate')['ticks']==age and C.fetch('Clockstate')['debt']==.125 and C.fetch('Clockstate')['media']==parity)
    for name in ('media_a','media_b'):
        node=C.op(name)
        check(name+' explicit cache settings',not node.par.active and not node.par.cacheonce and not node.par.alwayscook and int(node.par.cachesize)==1 and node.par.format.eval()=='rgba32float')
    settings(Sourcetop='/project1/no_such_phase8_source')
    check('unresolved TOP reference reported','Invalid Source TOP' in DIAG.source_status(C),status=DIAG.source_status(C))
    settings(Sourcetop='',Moviefile='/no_such_phase8_movie.mp4')
    C.op('movie').cook(force=True)
    check('invalid movie reported','Movie error' in DIAG.source_status(C),status=DIAG.source_status(C))
    settings(Moviefile='')
    # Exercise actual builder guards without re-executing its Text DAT entry point.
    tree=ast.parse(C.parent().op('builder').text)
    guard=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('_set','_expression','_unsupported')],type_ignores=[])
    ns={};exec(compile(guard,'parameter_guards','exec'),ns)
    for label,func,args in [('required parameter',ns['_set'],('phase8_missing',1)),
                            ('expression parameter',ns['_expression'],('phase8_missing','0')),
                            ('unsupported menu',ns['_set'],('format','not_a_format'))]:
        try:func(C.op('seed'),*args);raised=False
        except RuntimeError as error:raised='seed' in str(error)
        check(label+' reports named failure',raised)
    DIAG.update(C)
    check('unsupported configuration visible in status',len(C.fetch('Buildissues'))==3 and 'seed' in dict(DIAG.status_rows(C))['Build issues'])
    C.store('Buildissues',[])
    C.store('Runtimeerror','Clock stopped: deliberate test')
    DIAG.update(C)
    check('runtime failure visible',dict(DIAG.status_rows(C))['Runtime']=='Clock stopped: deliberate test')
    reset()
    check('successful reset clears runtime failure',dict(DIAG.status_rows(C))['Runtime']=='OK')


def numerics():
    seed=C.op('seed_pixel');original=seed.text
    seed.text='out vec4 fragColor; void main(){fragColor=TDOutputSwizzle(vec4(1,0,0,0));}'
    for mode in ('wrap','noflux','clear'):
        reset(Transformedge=mode)
        initial=image('state')
        for _ in range(120):CLOCK.tick(C)
        check('uniform empty field stable '+mode,np.array_equal(initial,image('state')))
    seed.text=original
    for name,feed,kill,quality in [('coral',.0545,.062,1),('spots',.0367,.0649,1),('coral q4',.0545,.062,4),('spots q4',.0367,.0649,4)]:
        reset(Ambient=True,Rectangle=True,Canvaswidth=96,Canvasheight=64,Cellsize=2,
              Feed=feed,Kill=kill,Solverquality=quality)
        initial=image('state')
        for _ in range(240):CLOCK.tick(C)
        a=image('state')
        check('finite bounded evolved chemistry '+name,np.isfinite(a).all() and a[:,:,:2].min()>=0 and a[:,:,:2].max()<=1 and not np.array_equal(initial,a),
              ticks=240,minimum=float(a[:,:,:2].min()),maximum=float(a[:,:,:2].max()))


def begin_shader_failure():
    reset()
    C.store('Phase8maskshader',C.op('mask_pixel').text)
    C.op('mask_pixel').text='out vec4 fragColor; void main(){ deliberate_phase8_syntax_error }'
    C.op('media_mask').cook(force=True)
    run('args[0].module.observe_shader_failure()',me,delayFrames=3)


def observe_shader_failure():
    try:
        DIAG.refresh(C)
        check('shader failure named in panel','media_mask' in dict(DIAG.status_rows(C))['Shaders'] and ('media_mask','error') in C.fetch('Shaderhealth'))
        check('shader compiler failure retained','error' in C.op('shader_diagnostics').text.lower())
    finally:
        C.op('mask_pixel').text=C.fetch('Phase8maskshader')
        C.op('media_mask').cook(force=True)
        run('args[0].module.finish()',me,delayFrames=3)


def finish():
    DIAG.refresh(C,compile_shaders=True)
    check('shader repair clears diagnostic',all(s=='ok' for _,s in C.fetch('Shaderhealth')))
    check('final operator errors clear',not C.errors(recurse=True),errors=C.errors(recurse=True))
    REPORT['shaders'] = C.fetch('Shaderhealth')
    REPORT['passed'] = all(v['passed'] for v in REPORT['checks'].values())
    (OUT/'report.json').write_text(json.dumps(REPORT,indent=2))
    print('PHASE8_COMPLETE',REPORT['passed'],len(REPORT['checks']))
