"""Verify phase-6 settings/bindings serialize and legacy boundary presets apply."""
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('preset_fakes',Path(__file__).parents[1]/'phase4/test_presets.py')
fakes=importlib.util.module_from_spec(spec);spec.loader.exec_module(fakes)
LIB=fakes.LIB


class FlowPresets(unittest.TestCase):
    def test_three_boundary_roundtrips(self):
        for mode in ('wrap','noflux','clear'):
            with self.subTest(mode=mode):
                c=fakes.build();c.par.Transformedge.val=mode
                c.par.Flow.val=True;c.par.Flowstrength.val=.75;c.par.Flowmax.val=3
                c.par.Presetname.val='Flow';LIB['on_save'](c)
                document=LIB['loads'](LIB['dumps'](LIB['document'](c)))
                preset=LIB['find'](document,'Flow');flat=LIB['flatten'](preset['settings'])
                self.assertEqual([flat[n] for n in ('Transformedge','Flow','Flowstrength','Flowmax')],[mode,True,.75,3])

    def test_velocity_binding_optional(self):
        c=fakes.build();c.par.Velocitytop.val='../velocity';c.par.Presetname.val='Portable'
        LIB['on_save'](c);self.assertNotIn('bindings',LIB['find'](LIB['document'](c),'Portable'))
        c.par.Presetname.val='Bound';c.par.Presetbindings.val=True;LIB['on_save'](c)
        self.assertEqual(LIB['find'](LIB['document'](c),'Bound')['bindings']['Velocitytop'],'../velocity')

    def test_old_transform_group_and_clear_token(self):
        c=fakes.build()
        preset=dict(name='Legacy',settings={'transform':{'Transformedge':'clear','Grow':3}})
        doc=LIB['empty_document']();doc['presets']=[preset]
        preset=LIB['loads'](LIB['dumps'](doc))['presets'][0]
        LIB['apply'](c,preset)
        self.assertEqual(c.par.Transformedge.eval(),'clear');self.assertEqual(c.par.Grow.eval(),3)

    def test_builtin_resets_disabled_flow_settings(self):
        c=fakes.build();c.par.Flow.val=True;c.par.Flowstrength.val=3;c.par.Flowmax.val=32
        fakes.select(c,'coral');LIB['on_apply'](c)
        self.assertFalse(c.par.Flow.eval());self.assertEqual(c.par.Flowstrength.eval(),1);self.assertEqual(c.par.Flowmax.eval(),8)

    def test_unknown_boundary_does_not_mutate_state(self):
        c=fakes.build();preset=dict(name='Bad',settings={'chemistry':{'Transformedge':'mirror'}})
        LIB['apply'](c,preset)
        self.assertEqual(c.par.Transformedge.eval(),'wrap');self.assertEqual(c.clock.resets,0)


if __name__=='__main__':unittest.main()
