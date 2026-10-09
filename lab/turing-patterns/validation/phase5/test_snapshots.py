"""Portable archive checks: raw float32 data, schema and corruption refusal."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
tree = ast.parse((ROOT / 'create_turing_media_v2.py').read_text())
source = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'SNAPSHOT_MODULE' for t in n.targets))
LIB = {}
exec(compile(source, '<snapshot_lib>', 'exec'), LIB)


def fixture():
    m = dict(schema=LIB['SCHEMA'], version=1, encoding='float32-le-rgba-bottom-up',
             dimensions=[16, 8, 8, 8], settings={}, bindings={}, pause=True,
             clock=dict(ticks=37, debt=.001, buffer=1, media=0), simulation_seconds=37/60,
             palette_ready=True, motion_ready=False, motion_tick_ready=False, palette_reader='palette_a',
             movie=dict(position=7.25, playmode='sequential', index=0, indexunit='frames',
                        cuepoint=0, cuepointunit='fraction'), textures={})
    textures = {}
    # Includes negative alpha, HDR, tiny values and signed zero, with asymmetric rows.
    values = (.5, .25, -.125, -.25, 1.25, 0., 1e-30, -0.)
    for name in LIB['TEXTURES']:
        shape = [8, 8, 4] if name.startswith('state') else [8, 16, 4] if name.startswith('media') else [2, 64, 4]
        count = __import__('math').prod(shape)
        raw = struct.pack('<' + 'f' * count, *(values[i % len(values)] for i in range(count)))
        textures[name] = raw
        m['textures'][name] = dict(shape=shape, sha256=hashlib.sha256(raw).hexdigest())
    return dict(metadata=m, textures=textures)


class Snapshots(unittest.TestCase):
    def setUp(self):
        self.snapshot = fixture()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state.tstate'

    def tearDown(self):
        self.tmp.cleanup()

    def reject(self):
        with self.assertRaises(LIB['SnapshotError']):
            LIB['validate'](self.snapshot)

    def test_bit_exact_disk_roundtrip(self):
        LIB['write_file'](self.path, self.snapshot)
        self.assertEqual(self.snapshot, LIB['read_file'](self.path))
        with zipfile.ZipFile(self.path) as z:
            self.assertEqual(len(z.namelist()), 7)
            self.assertNotIn('pickle', z.namelist())

    def test_version_refused(self):
        self.snapshot['metadata']['version'] = 2
        self.reject()

    def test_shape_refused(self):
        self.snapshot['metadata']['textures']['state_a']['shape'] = [8, 16, 4]
        self.reject()

    def test_truncated_refused(self):
        self.snapshot['textures']['state_a'] = self.snapshot['textures']['state_a'][:-4]
        self.reject()

    def test_corruption_refused(self):
        self.snapshot['textures']['state_a'] = b'bad!' + self.snapshot['textures']['state_a'][4:]
        self.reject()

    def test_nan_refused_even_with_matching_hash(self):
        raw = struct.pack('<f', float('nan')) + self.snapshot['textures']['state_a'][4:]
        self.snapshot['textures']['state_a'] = raw
        self.snapshot['metadata']['textures']['state_a']['sha256'] = hashlib.sha256(raw).hexdigest()
        self.reject()

    def test_metadata_nan_refused(self):
        self.snapshot['metadata']['settings']['Feed'] = float('nan')
        self.reject()

    def test_bad_dimensions(self):
        for dimensions in ([8,8,8], [8,8,0,8], [8,8,8.,8], [8192,8,8,8]):
            self.snapshot['metadata']['dimensions'] = dimensions
            self.reject()

    def test_bad_clock(self):
        for name, value in (('ticks', -1), ('buffer', 2), ('media', True), ('debt', float('inf'))):
            self.snapshot = fixture()
            self.snapshot['metadata']['clock'][name] = value
            self.reject()

    def test_time_matches_ticks(self):
        self.snapshot['metadata']['simulation_seconds'] = 2
        self.reject()

    def test_palette_parity_refused(self):
        self.snapshot['metadata']['palette_reader'] = '../something'
        self.reject()

    def test_movie_position_refused(self):
        self.snapshot['metadata']['movie']['position'] = float('inf')
        self.reject()

    def test_archive_entries_refused(self):
        LIB['write_file'](self.path, self.snapshot)
        with zipfile.ZipFile(self.path, 'a') as archive:
            archive.writestr('../extra', b'x')
        with self.assertRaises(LIB['SnapshotError']):
            LIB['read_file'](self.path)

    def test_failed_write_preserves_destination(self):
        LIB['write_file'](self.path, self.snapshot)
        old = self.path.read_bytes()
        self.snapshot['metadata']['version'] = 9
        with self.assertRaises(LIB['SnapshotError']):
            LIB['write_file'](self.path, self.snapshot)
        self.assertEqual(old, self.path.read_bytes())

    def test_invalid_zip_refused(self):
        self.path.write_bytes(b'bad')
        with self.assertRaises(LIB['SnapshotError']):
            LIB['read_file'](self.path)


if __name__ == '__main__':
    unittest.main()
