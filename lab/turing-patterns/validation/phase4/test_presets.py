"""Phase 4 preset tests outside TouchDesigner; no external packages needed.

The embedded preset and explorer modules are extracted from the builder and run
against small fakes of the TouchDesigner objects they use.
"""
import ast
import copy
import json
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / 'create_turing_media_v2.py').read_text()
TREE = ast.parse(SOURCE)


def constant(name):
    return next(ast.literal_eval(node.value) for node in TREE.body
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in node.targets))


class ParMode:
    CONSTANT, EXPRESSION, EXPORT = 'constant', 'expression', 'export'


class AbsTime:
    frame = 100


class Project:
    folder = tempfile.mkdtemp()


def module(name):
    namespace = dict(ParMode=ParMode, absTime=AbsTime, project=Project)
    exec(compile(constant(name), '<{}>'.format(name), 'exec'), namespace)
    return namespace


LIB = module('PRESETS_MODULE')
BUILTINS = constant('BUILTIN_PRESETS')
EXCLUDED = constant('PRESET_EXCLUDED')

# Every custom parameter the builder declares: name -> (style, default, menu names).
DECLARED = {}
for match in re.finditer(r"_number\(\w+, '(\w+)', '[^']*', ([^,]+(?:\([^)]*\))?[^,]*), [^,]+, [^,)]+(, True)?\)", SOURCE):
    DECLARED[match.group(1)] = ('Int' if match.group(3) else 'Float', match.group(2))
for match in re.finditer(r"_toggle\(\w+, '(\w+)', '[^']*', (True|False)\)", SOURCE):
    DECLARED[match.group(1)] = ('Toggle', match.group(2))
for match in re.finditer(r"_menu\(\w+, '(\w+)', '[^']*', \[(.*?)\], '(\w+)'\)", SOURCE, re.S):
    names = tuple(re.findall(r"\('(\w+)', '", match.group(2)))
    DECLARED[match.group(1)] = ('Menu', match.group(3), names)
for kind in ('Str', 'File', 'TOP'):
    for match in re.finditer(r"append%s\('(\w+)'" % kind, SOURCE):
        DECLARED[match.group(1)] = (kind, '')
for match in re.finditer(r"appendPulse\('(\w+)'", SOURCE):
    DECLARED[match.group(1)] = ('Pulse', None)
for match in re.finditer(r"appendToggle\('(\w+)'", SOURCE):
    DECLARED.setdefault(match.group(1), ('Toggle', 'False'))
# Parameters the builder declares inside loops over tuples.
LOOP_DECLARED = {
    'Feedmin': ('Float', '.025'), 'Feedmax': ('Float', '.065'), 'Killmin': ('Float', '.045'),
    'Killmax': ('Float', '.070'), 'Chemistryblend': ('Float', '1.0'),
    'Simtime': ('Float', '0'), 'Simlag': ('Float', '0'), 'Tickcount': ('Int', '0'),
    'Substeps': ('Int', '0'),
}
for name, entry in LOOP_DECLARED.items():
    assert "('{}', '".format(name) in SOURCE, name
    DECLARED.setdefault(name, entry)


def default_value(entry):
    style, text = entry[0], entry[1]
    if style == 'Float':
        return float(eval(text, {'math': __import__('math'), '_rate': lambda b, f=60.0:
                                 -__import__('math').log1p(-b) * f}))
    if style == 'Int':
        return int(eval(text))
    if style == 'Toggle':
        return text == 'True'
    return text


class Par:
    def __init__(self, name, entry):
        self.name, self.style = name, entry[0]
        self.menuNames = list(entry[2]) if self.style == 'Menu' else []
        self.menuLabels = list(self.menuNames)
        self.mode = ParMode.CONSTANT
        self.expr = ''
        self._val = default_value(entry) if self.style != 'Pulse' else None

    @property
    def val(self):
        return self._val

    @val.setter
    def val(self, value):
        if self.style == 'Menu' and value not in self.menuNames:
            raise ValueError('bad menu value')
        self._val = value
        self.owner.changes.append(self.name)

    def eval(self):
        return self._val

    def __bool__(self):  # TouchDesigner Pars evaluate in boolean context
        return bool(self._val)


class Pars:
    def __init__(self, owner):
        object.__setattr__(self, '_pars', {})
        for name, entry in DECLARED.items():
            par = Par(name, entry)
            par.owner = owner
            self._pars[name] = par

    def __getattr__(self, name):
        if name in self._pars:
            return self._pars[name]
        raise AttributeError(name)

    def __getitem__(self, name):
        return self._pars[name]


class Clock:
    def __init__(self, owner):
        self.owner, self.resets, self.rebases = owner, 0, []

    def reset(self, c):
        self.resets += 1

    def rebase(self, c, clear_debt=False):
        self.rebases.append(clear_debt)


class Dat:
    def __init__(self, text=''):
        self.text = text


class Op:
    def __init__(self, module=None):
        self.module = module


class Component:
    path = '/project1/turing_media_v2'

    def __init__(self):
        self.changes, self.storage = [], {}
        self.par = Pars(self)
        self.clock = Clock(self)
        self.ops = {'clock': Op(self.clock), 'presets': Dat()}
        self.customPars = list(self.par._pars.values())
        self.changes.clear()

    def op(self, name):
        return self.ops.get(name)

    def store(self, key, value):
        self.storage[key] = value

    def fetch(self, key, default=None):
        return self.storage.get(key, default)


def build():
    """Mirror _build_presets without TouchDesigner."""
    c = Component()
    defaults, _ = LIB['capture'](c)
    document = LIB['empty_document']()
    for name, description, overrides in BUILTINS:
        values = dict(defaults)
        values.update(overrides)
        document['presets'].append(LIB['make_preset'](name, values, None, description, builtin=True))
    LIB['store_document'](c, document, select=BUILTINS[0][0])
    c.changes.clear()
    return c


def select(c, name):
    document = LIB['document'](c)
    keys = LIB['menu_keys'](document)
    c.par.Preset.val = keys[document['presets'].index(LIB['find'](document, name))]


class CoverageTests(unittest.TestCase):
    def test_every_custom_parameter_classified(self):
        grouped = set(LIB['parameter_names']())
        classified = grouped | set(LIB['BINDINGS']) | set(EXCLUDED)
        values = {n for n, e in DECLARED.items() if e[0] != 'Pulse'}
        self.assertEqual(sorted(values - classified), [])
        self.assertEqual(sorted(classified - values), [])
        self.assertFalse(grouped & set(EXCLUDED))
        self.assertGreater(len(grouped), 60)

    def test_builtins_valid(self):
        names = [b[0] for b in BUILTINS]
        self.assertEqual(len(names), len({n.casefold() for n in names}))
        kinds = LIB['spec'](Component())
        for name, _, overrides in BUILTINS:
            for key, value in overrides.items():
                self.assertIn(key, LIB['parameter_names'](), (name, key))
                self.assertEqual(LIB['coerce'](kinds[key], value), value)

    def test_legacy_pulses_removed_and_routed(self):
        self.assertNotIn('Coral', DECLARED)
        self.assertNotIn('Spots', DECLARED)
        callbacks = constant('CONTROL_CALLBACKS')
        for pulse in (n for n, e in DECLARED.items() if e[0] == 'Pulse'):
            self.assertIn("'{}'".format(pulse), callbacks, pulse)
        watched = re.search(r"_set\(callbacks, 'pars', ((?:'[^']*'\s*)+)\)", SOURCE).group(1)
        watched = set(''.join(re.findall(r"'([^']*)'", watched)).split())
        self.assertTrue({n for n, e in DECLARED.items() if e[0] == 'Pulse'} <= watched)

    def test_explorer_layout_matches_builder(self):
        explorer = module('EXPLORER_CALLBACKS')
        for name in ('MAP_SIZE', 'TILE', 'COLUMNS', 'ROWS'):
            self.assertEqual(explorer[name], constant('FK_' + name), name)
        self.assertEqual(len(constant('FK_EXAMPLES')), explorer['COLUMNS'] * explorer['ROWS'])


class DocumentTests(unittest.TestCase):
    def test_builtins_complete_and_grouped(self):
        c = build()
        document = LIB['document'](c)
        self.assertEqual(len(document['presets']), len(BUILTINS))
        for preset in document['presets']:
            flat = LIB['flatten'](preset['settings'])
            self.assertEqual(sorted(flat), sorted(LIB['parameter_names']()))
            self.assertTrue(preset['builtin'])
            self.assertNotIn('bindings', preset)
            self.assertEqual(list(preset['settings']), [g for g, _ in LIB['GROUPS']])

    def test_menu_matches_document(self):
        c = build()
        document = LIB['document'](c)
        self.assertEqual(c.par.Preset.menuNames, LIB['menu_keys'](document))
        self.assertEqual(c.par.Preset.eval(), 'coral')

    def test_serialization_round_trip_exact(self):
        c = build()
        c.par.Feed.val = 0.1 / 3
        c.par.Rotate.val = -123.456789012345
        LIB['on_save'](c)
        text = c.op('presets').text
        again = LIB['dumps'](LIB['loads'](text))
        self.assertEqual(text, again)
        saved = LIB['find'](LIB['loads'](text), 'User Preset 1')
        self.assertEqual(saved['settings']['chemistry']['Feed'], 0.1 / 3)

    def test_refuses_bad_documents(self):
        good = LIB['empty_document']()
        cases = [
            'not json', json.dumps({'schema': 'other', 'version': 1, 'presets': []}),
            json.dumps(dict(good, version=2)), json.dumps(dict(good, version=True)),
            json.dumps(dict(good, presets={})),
            json.dumps(dict(good, presets=[{'name': '', 'settings': {}}])),
            json.dumps(dict(good, presets=[{'name': 'a', 'settings': {}}, {'name': 'A', 'settings': {}}])),
            json.dumps(dict(good, presets=[{'name': 'a', 'settings': {'g': {'Feed': [1]}}}])),
            json.dumps(dict(good, presets=[{'name': 'a', 'settings': {'g': 3}}])),
            json.dumps(dict(good, presets=[{'name': 'a', 'settings': {'g': {'X': 1}, 'h': {'X': 2}}}])),
            '{"schema": "turing_media_v2.presets", "version": 1, "presets": '
            '[{"name": "a", "settings": {"g": {"Feed": NaN}}}]}',
        ]
        for text in cases:
            with self.assertRaises(LIB['PresetError'], msg=text):
                LIB['loads'](text)

    def test_newer_version_message(self):
        with self.assertRaisesRegex(LIB['PresetError'], 'newer'):
            LIB['loads'](json.dumps(dict(LIB['empty_document'](), version=99)))

    def test_slug_unique(self):
        doc = LIB['empty_document']()
        for name in ('My Look', 'my-look', 'MY LOOK!', '***'):
            doc['presets'].append({'name': name, 'settings': {}})
        self.assertEqual(LIB['menu_keys'](doc), ['my_look', 'my_look_2', 'my_look_3', 'preset'])


class ApplyTests(unittest.TestCase):
    def test_round_trip_preserves_every_setting(self):
        c = build()
        c.par.Feed.val = 0.0311
        c.par.Influencemode.val = 'chemistry'
        c.par.Colormode.val = 'dye'
        c.par.Ambient.val = False
        c.par.Solverquality.val = 3
        c.par.Grow.val = -12.5
        c.par.Presetname.val = 'Mine'
        LIB['on_save'](c)
        saved, _ = LIB['capture'](c)
        select(c, 'Worms')
        LIB['on_apply'](c)
        self.assertNotEqual(LIB['capture'](c)[0], saved)
        select(c, 'Mine')
        report = LIB['on_apply'](c)
        self.assertEqual(LIB['capture'](c)[0], saved)
        self.assertEqual(report['missing'], [])
        for name, value in saved.items():
            self.assertIs(type(c.par[name].eval()), type(value), name)

    def test_apply_without_reset_keeps_state(self):
        c = build()
        select(c, 'Chemistry Map')
        report = LIB['on_apply'](c, reset=False)
        self.assertEqual(c.clock.resets, 0)
        self.assertEqual(report['reset'], '')
        self.assertIn('Influencemode', report['changed'])
        self.assertIn('state kept', c.par.Presetstatus.eval())

    def test_seed_changes_do_not_reset_without_request(self):
        c = build()
        select(c, 'Dividing Spots')
        report = LIB['on_apply'](c)
        self.assertIn('Seedradius', report['changed'])
        self.assertEqual(c.clock.resets, 0)

    def test_apply_and_reset_resets_once(self):
        c = build()
        select(c, 'Wide Coarse')
        report = LIB['on_apply'](c, reset=True)
        self.assertEqual(c.clock.resets, 1)
        self.assertEqual(report['reset'], 'requested')

    def test_dimension_change_forces_one_reset(self):
        c = build()
        select(c, 'Wide Coarse')
        report = LIB['on_apply'](c, reset=False)
        self.assertEqual(c.clock.resets, 1)
        self.assertEqual(report['reset'], 'dimensions changed')

    def test_ineffective_dimension_change_keeps_state(self):
        c = build()
        c.par.Presetname.val = 'Hidden size'
        LIB['on_save'](c)
        doc = LIB['document'](c)
        preset = LIB['find'](doc, 'Hidden size')
        preset['settings']['dimensions']['Canvaswidth'] = 1000  # Rectangle is off
        report = LIB['apply'](c, preset)
        self.assertEqual(report['changed'], ['Canvaswidth'])
        self.assertEqual(c.clock.resets, 0)

    def test_equivalent_size_keeps_state(self):
        c = build()
        preset = {'name': 'same grid', 'settings': {'dimensions': {'Resolution': 1024, 'Cellsize': 2.0}}}
        report = LIB['apply'](c, preset)
        self.assertEqual(report['reset'], 'dimensions changed')  # canvas changed
        c = build()
        preset = {'name': 'same', 'settings': {'dimensions': {'Resolution': 512, 'Cellsize': 1.0}}}
        self.assertEqual(LIB['apply'](c, preset)['reset'], '')

    def test_pending_callbacks_consumed_once(self):
        c = build()
        select(c, 'Wide Coarse')
        report = LIB['on_apply'](c)
        par = c.par.Cellsize
        self.assertIn('Cellsize', report['changed'])
        self.assertTrue(LIB['consume_pending'](c, c.par.Rectangle))
        self.assertFalse(LIB['consume_pending'](c, c.par.Rectangle))
        self.assertFalse(LIB['consume_pending'](c, c.par.Seed))  # not part of the batch
        AbsTime.frame += 1000
        try:
            self.assertTrue(LIB['consume_pending'](c, par))
        finally:
            AbsTime.frame -= 1000

    def test_pending_batches_merge_and_hand_edits_reset(self):
        c = build()
        LIB['set_quietly'](c, {'Seed': 17})
        LIB['set_quietly'](c, {'Seedradius': 6.5})
        LIB['set_quietly'](c, {})
        self.assertTrue(LIB['consume_pending'](c, c.par.Seed))
        c.par.Seedradius.val = 8.0
        self.assertFalse(LIB['consume_pending'](c, c.par.Seedradius))
        self.assertEqual(c.fetch('Presetpending'), {})

    def test_clock_rebased_on_timing_changes(self):
        c = build()
        preset = {'name': 't', 'settings': {'timing': {'Clockmode': 'framestepped', 'Speed': 2.0}}}
        LIB['apply'](c, preset)
        self.assertEqual(c.clock.rebases, [True])

    def test_unknown_invalid_missing_reported(self):
        c = build()
        preset = {'name': 'future', 'settings': {
            'chemistry': {'Feed': 0.03, 'Kill': 'lots'},
            'influence': {'Maskmode': 'hologram'},
            'future': {'Wormholes': 3}}}
        before = LIB['capture'](c)[0]
        report = LIB['apply'](c, preset)
        self.assertEqual(report['changed'], ['Feed'])
        self.assertEqual(report['unknown'], ['Wormholes'])
        self.assertEqual(sorted(report['invalid']), ['Kill', 'Maskmode'])
        self.assertIn('Diffusiona', report['missing'])
        after = LIB['capture'](c)[0]
        self.assertEqual({k for k in before if before[k] != after[k]}, {'Feed'})
        text = LIB['summary']('future', report)
        self.assertIn('1 unknown: Wormholes', text)

    def test_int_float_coercion(self):
        c = build()
        preset = {'name': 'x', 'settings': {'a': {'Resolution': 512.0, 'Cellsize': 1, 'Ambient': 0}}}
        report = LIB['apply'](c, preset)
        self.assertEqual(report['invalid'], [])
        self.assertIs(type(c.par.Resolution.eval()), int)
        self.assertIs(type(c.par.Cellsize.eval()), float)
        self.assertIs(c.par.Ambient.eval(), False)
        bad = {'name': 'y', 'settings': {'a': {'Resolution': 512.5, 'Ambient': 2, 'Feed': True}}}
        self.assertEqual(sorted(LIB['apply'](c, bad)['invalid']), ['Ambient', 'Feed', 'Resolution'])

    def test_expression_and_export_modes(self):
        c = build()
        c.par.Feed.mode = ParMode.EXPRESSION
        c.par.Kill.mode = ParMode.EXPORT
        select(c, 'Worms')
        report = LIB['on_apply'](c)
        self.assertEqual(c.par.Feed.mode, ParMode.CONSTANT)
        self.assertEqual(c.par.Feed.eval(), 0.029)
        self.assertIn('Kill', report['blocked'])
        self.assertNotIn('Kill', report['changed'])

    def test_bindings_optional(self):
        c = build()
        c.par.Sourcetop.val = '../camera'
        c.par.Moviefile.val = 'clips/a.mov'
        c.par.Presetname.val = 'portable'
        LIB['on_save'](c)
        self.assertNotIn('bindings', LIB['find'](LIB['document'](c), 'portable'))
        c.par.Presetbindings.val = True
        c.par.Presetname.val = 'bound'
        LIB['on_save'](c)
        bound = LIB['find'](LIB['document'](c), 'bound')
        self.assertEqual(bound['bindings'], {'Moviefile': 'clips/a.mov', 'Sourcetop': '../camera',
                                             'Domaintop': '', 'Ramptop': ''})
        c.par.Sourcetop.val = ''
        c.par.Presetbindings.val = False
        select(c, 'bound')
        LIB['on_apply'](c)
        self.assertEqual(c.par.Sourcetop.eval(), '')
        c.par.Presetbindings.val = True
        report = LIB['on_apply'](c)
        self.assertEqual(c.par.Sourcetop.eval(), '../camera')
        self.assertEqual(report['reset'], '')  # bindings never force a reset
        self.assertEqual(c.clock.resets, 0)

    def test_clip_seed_partial_one_reset(self):
        c = build()
        c.par.Feed.val = 0.03
        LIB['clip_seed'](c)
        self.assertEqual(c.clock.resets, 1)
        self.assertEqual(c.par.Feed.eval(), 0.03)
        self.assertEqual(c.par.Strength.eval(), 600.0)
        self.assertIs(c.par.Ambient.eval(), False)


class LibraryTests(unittest.TestCase):
    def test_builtins_protected(self):
        c = build()
        c.par.Presetname.val = 'coral'
        self.assertIsNone(LIB['on_save'](c))
        self.assertIn('built-in', c.par.Presetstatus.eval())
        select(c, 'Coral')
        self.assertIsNone(LIB['on_delete'](c))
        self.assertEqual(len(LIB['document'](c)['presets']), len(BUILTINS))

    def test_save_replace_delete(self):
        c = build()
        LIB['on_save'](c)
        LIB['on_save'](c)
        names = [p['name'] for p in LIB['document'](c)['presets']]
        self.assertEqual(names[-2:], ['User Preset 1', 'User Preset 2'])
        self.assertTrue(c.par.Preset.eval().startswith('user_preset_2'))
        c.par.Presetname.val = 'User Preset 1'
        c.par.Feed.val = 0.02
        LIB['on_save'](c)
        self.assertIn('Replaced', c.par.Presetstatus.eval())
        self.assertEqual(LIB['find'](LIB['document'](c), 'User Preset 1')['settings']['chemistry']['Feed'], 0.02)
        LIB['on_delete'](c)
        self.assertIsNone(LIB['find'](LIB['document'](c), 'User Preset 1'))
        self.assertEqual(c.par.Preset.eval(), 'coral')  # selection falls back

    def test_export_import_round_trip(self):
        c = build()
        c.par.Feed.val = 0.0123
        c.par.Presetname.val = 'A'
        LIB['on_save'](c)
        c.par.Presetname.val = 'B'
        LIB['on_save'](c)
        original = c.op('presets').text
        c.par.Presetfile.val = 'sub/presets.json'
        LIB['on_export'](c)
        exported = Path(Project.folder, 'sub/presets.json').read_text()
        self.assertEqual(exported, original)
        other = build()
        other.par.Presetfile.val = str(Path(Project.folder, 'sub/presets.json'))
        other.par.Importmode.val = 'replace'
        report = LIB['on_import'](other)
        self.assertEqual(other.op('presets').text, original)
        self.assertEqual(report['added'], ['A', 'B'])
        self.assertEqual(len(report['skipped']), len(BUILTINS))
        LIB['on_import'](other)  # importing again in replace mode is idempotent
        self.assertEqual(other.op('presets').text, original)
        other.par.Importmode.val = 'merge'
        LIB['on_import'](other)
        self.assertEqual(other.op('presets').text, original)

    def test_import_merge_rename_and_unknown_preserved(self):
        c = build()
        c.par.Presetname.val = 'Keep'
        LIB['on_save'](c)
        incoming = LIB['empty_document']()
        future = {'name': 'Coral', 'settings': {'chemistry': {'Feed': 0.05}, 'future': {'Wormholes': 3}},
                  'bindings': {'Moviefile': 'x.mov'}}
        incoming['presets'] = [future, {'name': 'keep', 'settings': {'seed': {'Seed': 7}}}]
        path = Path(Project.folder, 'merge.json')
        path.write_text(json.dumps(incoming))
        c.par.Presetfile.val = str(path)
        report = LIB['on_import'](c)
        self.assertEqual(report['renamed'], [['Coral', 'Coral (imported)']])
        self.assertEqual(report['replaced'], ['keep'])
        doc = LIB['document'](c)
        imported = LIB['find'](doc, 'Coral (imported)')
        self.assertEqual(imported['settings']['future'], {'Wormholes': 3})
        self.assertEqual(imported['bindings'], {'Moviefile': 'x.mov'})
        self.assertTrue(LIB['find'](doc, 'Coral')['builtin'])
        LIB['on_import'](c)
        self.assertIsNotNone(LIB['find'](LIB['document'](c), 'Coral (imported 2)'))

    def test_failed_import_changes_nothing(self):
        c = build()
        before = c.op('presets').text
        path = Path(Project.folder, 'bad.json')
        path.write_text(json.dumps(dict(LIB['empty_document'](), version=7)))
        c.par.Presetfile.val = str(path)
        self.assertIsNone(LIB['on_import'](c))
        self.assertEqual(c.op('presets').text, before)
        self.assertIn('newer', c.par.Presetstatus.eval())
        c.par.Presetfile.val = str(Path(Project.folder, 'missing.json'))
        self.assertIsNone(LIB['on_import'](c))
        c.par.Presetfile.val = ''
        self.assertIsNone(LIB['on_export'](c))


class ExplorerTests(unittest.TestCase):
    def test_hit_testing(self):
        explorer = module('EXPLORER_CALLBACKS')
        at = explorer['example_at']
        width, height = explorer['PANEL_WIDTH'], explorer['PANEL_HEIGHT']
        self.assertIsNone(at(100 / width, .5))
        self.assertEqual(at((512 + 10) / width, (height - 10) / height), 0)   # top-left tile
        self.assertEqual(at((512 + 200) / width, (height - 10) / height), 1)
        self.assertEqual(at((512 + 10) / width, 10 / height), 6)              # bottom-left
        self.assertEqual(at((512 + 200) / width, 10 / height), 7)


if __name__ == '__main__':
    unittest.main()
