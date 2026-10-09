"""Archive cadence integrity and complete performance preset serialization."""
import sys, unittest, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'validation/phase5'))
from test_snapshots import LIB,fixture
sys.path.insert(0,str(ROOT/'validation/phase4'))
from test_presets import LIB as PRESETS

class Performance(unittest.TestCase):
 def test_cadence_roundtrips_with_signed_state(self):
  s=fixture();s['metadata']['palette_last_tick']=32
  s['metadata']['settings'].update(Carryhistory=False,Palettehistory=False,Paletteinterval=7)
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'cadence.tstate';LIB['write_file'](p,s);self.assertEqual(LIB['read_file'](p),s)
 def test_bad_cadence_rejected(self):
  for value in (-1,38,True,3.5,'12'):
   with self.subTest(value=value):
    s=fixture();s['metadata']['palette_last_tick']=value
    with self.assertRaises(LIB['SnapshotError']):LIB['validate'](s)
 def test_legacy_cadence_readable(self):LIB['validate'](fixture())
 def test_new_controls_complete_preset_roundtrip(self):
  flat={name:0 for name in PRESETS['parameter_names']()}
  flat.update(Carryhistory=False,Palettehistory=True,Paletteinterval=13)
  doc=PRESETS['empty_document']();doc['presets']=[PRESETS['make_preset']('Performance',flat)]
  actual=PRESETS['flatten'](PRESETS['loads'](PRESETS['dumps'](doc))['presets'][0]['settings'])
  self.assertEqual(actual,flat)

if __name__=='__main__':unittest.main()
