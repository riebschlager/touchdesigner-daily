"""Pure diagnostic decisions and builder compatibility guards; no TD install."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[2]
SOURCE=(ROOT/'create_turing_media_v2.py').read_text()
TREE=ast.parse(SOURCE)
CONSTANTS={n.targets[0].id:ast.literal_eval(n.value) for n in TREE.body
           if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and isinstance(n.targets[0],ast.Name)}
DIAG={};exec(CONSTANTS['DIAGNOSTICS_CALLBACKS'],DIAG)
GUARDS={};exec(compile(ast.Module(body=[n for n in TREE.body if isinstance(n,ast.FunctionDef)
    and n.name in ('_set','_expression','_unsupported')],type_ignores=[]),'guards','exec'),GUARDS)


class Par:
    def __init__(self,value=None,expr=None,menus=()):
        self.val,self.expr,self.menuNames=value,expr,list(menus)
    def eval(self):return self.val
    def __bool__(self):return bool(self.val)
    def __int__(self):return int(self.val)


class Component:
    def __init__(self):
        self.storage={'Appliedsize':(96,64,32,21),'Clockstate':{'ticks':9,'debt':.125},
                      'Diagnosticbuild':'099.2025.33230','Shaderhealth':[('sim','ok'),('display','unchecked')]}
        self.par=SimpleNamespace(Sourcetop=Par(),Moviefile=Par(''),Clockmode=Par('framestepped'),
                                 Pause=Par(True),Tickcount=Par(2),Substeps=Par(32))
    def fetch(self,name,default=None):return self.storage.get(name,default)
    def store(self,name,value):self.storage[name]=value


class Diagnostics(unittest.TestCase):
    def test_uncompiled_shader_never_reported_as_success(self):
        for log in ('','Vertex Shader Compile Results:\n','Compilation queued'):
            self.assertEqual(DIAG['shader_result'](log)[0],'unchecked')

    def test_compile_or_link_failure_wins_over_success_line(self):
        for log in ('Compiled Successfully\nERROR: invalid syntax','Failed to compile pixel shader',
                    'compile failed','Link failed'):
            self.assertEqual(DIAG['shader_result'](log)[0],'error')

    def test_operator_failure_wins_over_cached_success_log(self):
        self.assertEqual(DIAG['shader_result']('Compiled Successfully','Missing input')[0],'error')

    def test_success_allows_warnings(self):
        self.assertEqual(DIAG['shader_result']('Compiled Successfully\nWARNING: unused uniform')[0],'ok')

    def test_blank_top_none_and_no_expression_is_ambient(self):
        self.assertEqual(DIAG['source_status'](Component()),'No media (ambient simulation)')

    def test_unresolved_top_reference_is_named(self):
        c=Component();c.par.Sourcetop=Par('/missing')
        c.par.Sourcetop.eval=lambda:None
        self.assertIn('Invalid Source TOP',DIAG['source_status'](c))

    def test_expression_resolving_none_is_reported(self):
        c=Component();c.par.Sourcetop=Par(None,'op("/missing")')
        self.assertIn('unresolved reference',DIAG['source_status'](c))

    def test_source_errors_are_reported(self):
        c=Component();c.par.Sourcetop=Par(SimpleNamespace(family='TOP',path='/source',errors=lambda:'decode failed'))
        self.assertIn('decode failed',DIAG['source_status'](c))

    def test_valid_source_dimensions_reported(self):
        c=Component();c.par.Sourcetop=Par(SimpleNamespace(family='TOP',path='/source',width=80,height=64,errors=lambda:''))
        self.assertEqual(DIAG['source_status'](c),'Valid TOP: /source (80 x 64)')

    def test_missing_local_movie_reported_before_decoder_error(self):
        c=Component();c.par.Moviefile=Par('/no_such_phase8_movie.mp4');c.op=lambda n:SimpleNamespace(errors=lambda:'')
        self.assertIn('file not found',DIAG['source_status'](c))

    def test_status_preserves_effective_size_time_and_work_units(self):
        rows=dict(DIAG['status_rows'](Component()))
        self.assertEqual(rows['Canvas / grid'],'96 x 64 / 32 x 21')
        self.assertEqual(rows['Substeps'],'32 per tick / 64 last frame')
        self.assertEqual(rows['Time / lag'],'0.1500 s / 0.1250 s')
        self.assertEqual(rows['Shaders'],'0 errors / 1 unchecked / 2 shaders')

    def test_status_reports_multiple_shader_failures(self):
        c=Component();c.store('Shaderhealth',[('sim','error'),('display','error')])
        self.assertIn('sim, display',dict(DIAG['status_rows'](c))['Shaders'])

    def test_missing_parameter_reports_path_and_retains_issue(self):
        c=Component();node=SimpleNamespace(par=SimpleNamespace(),path='/component/shader',parent=lambda:c)
        with self.assertRaisesRegex(RuntimeError,'/component/shader.required'):GUARDS['_set'](node,'required',1)
        self.assertIn('required',c.fetch('Buildissues')[0])

    def test_unsupported_menu_never_silently_sets_invalid_token(self):
        c=Component();p=Par('rgba32float',menus=('rgba32float','rgba16float'))
        node=SimpleNamespace(par=SimpleNamespace(format=p),path='/component/shader',parent=lambda:c)
        with self.assertRaisesRegex(RuntimeError,'Unsupported value'):GUARDS['_set'](node,'format','wrong')
        self.assertEqual(p.val,'rgba32float')

    def test_all_embedded_python_compiles(self):
        for name,code in CONSTANTS.items():
            if name.endswith(('CALLBACKS','MODULE')):compile(code,name,'exec')


if __name__=='__main__':unittest.main()
