"""Text DAT module: start(component, output_dir, chain=None). Product needs no NumPy; tests do."""
import json
import hashlib
import time
from pathlib import Path
import numpy as np

TOL = 1e-6
OUTPUTS = ('state', 'palette', 'out1', 'patterns', 'mask_preview', 'source_preview')


def image(name):
    C.op(name).cook(force=True)
    return C.op(name).numpyArray(delayed=False).copy()


def configure(**settings):
    controls = C.op('controls')
    controls.par.active = False
    controls.cook(force=True)
    try:
        for name, value in settings.items():
            C.par[name].val = value
    finally:
        controls.par.active = True
        controls.cook(force=True)


def resets():
    return C.fetch('Resetcount', 0)


def ticks():
    return C.fetch('Clockstate')['ticks']


def lib():
    return C.op('preset_lib').module


def select(name):
    doc = lib().document(C)
    keys = lib().menu_keys(doc)
    C.par.Preset.val = keys[doc['presets'].index(lib().find(doc, name))]


def baseline():
    """Coral preset + reset through the product; preset dimensions, so applying
    other same-size presets never forces a resize reset."""
    select('Coral')
    lib().on_apply(C, reset=True)
    configure(Clockmode='framestepped', Renderfps=60, Speed=1, Pause=False)
    C.op('clock').module.reset(C)


def evolve(count):
    for _ in range(count):
        # Presets include Clockmode and can restore Real Time. Supply controlled
        # elapsed time so repeated calls in one TD frame still advance ticks.
        C.op('clock').module.advance(C, elapsed=1.0 / 60.0)
    return image('state')


def check(name, passed, **metrics):
    REPORT['checks'][name] = dict(passed=bool(passed), **metrics)
    print('PHASE4_CHECK', name, bool(passed))


def later(function, frames=4):
    run('args[0].module.{}()'.format(function), me, delayFrames=frames)


def start(c, output_dir, chain=None):
    global C, ROOT, REPORT, TASKS, CHAIN
    C, ROOT, CHAIN = c, Path(output_dir), chain
    ROOT.mkdir(parents=True, exist_ok=True)
    C.op('clock').par.active = False
    REPORT = {'build': str(app.version) + '.' + str(app.build), 'tolerance': TOL, 'checks': {}}
    REPORT['source_sha256'] = hashlib.sha256(C.parent().op('builder').text.encode()).hexdigest()
    TASKS = [build_checks, round_trip_checks, file_checks, apply_checks, thumbnail_checks,
             explorer_checks, keep_state_pulse]
    later('next_test', 2)


def next_test():
    task = TASKS.pop(0)
    task()
    (ROOT / 'progress.json').write_text(json.dumps(REPORT, indent=2, default=str))
    # Pulse tasks schedule their own continuation.
    if TASKS and task.__name__ != 'keep_state_pulse':
        later('next_test', 2)


def build_checks():
    for n in C.children:
        if n.family == 'TOP':
            n.cook(force=True)
    doc = lib().document(C)
    check('preset_table_versioned', doc['schema'] == 'turing_media_v2.presets' and doc['version'] == 1)
    check('builtins_present', len(doc['presets']) == 9 and all(p.get('builtin') for p in doc['presets']),
          names=[p['name'] for p in doc['presets']])
    check('menu_matches_table', list(C.par.Preset.menuNames) == lib().menu_keys(doc))
    names = lib().parameter_names()
    flat, _ = lib().capture(C)
    check('capture_complete', sorted(flat) == sorted(names), count=len(flat))
    check('builtins_complete', all(sorted(lib().flatten(p['settings'])) == sorted(names)
                                   for p in doc['presets']))
    check('legacy_preset_pulses_removed', getattr(C.par, 'Coral', None) is None
          and getattr(C.par, 'Spots', None) is None)
    check('outputs_present', all(C.op(n) is not None for n in OUTPUTS)
          and C.op('state').width == 512 and C.op('palette').width == 64)
    check('explorer_panel_built', C.op('fk_explorer') is not None and C.op('explorer').par.active.eval(),
          status=C.par.Explorerstatus.eval())
    check('explorer_background_resolves', C.op('fk_explorer').par.top.eval() == C.op('fk_panel'))
    check('fk_panel_size', (C.op('fk_panel').width, C.op('fk_panel').height) == (768, 512))


def round_trip_checks():
    baseline()
    odd = dict(Feed=0.1 / 3, Kill=0.0611, Diffusionb=0.4375, Seed=42, Seedradius=7.25, Ambient=False,
               Solverquality=2, Speed=0.75, Influencemode='chemistry', Maskmode='edgetexture',
               Feedmin=0.031, Killmax=0.069, Domainboundary='empty', Transform=True, Grow=-3.5,
               Rotate=17.125, Transformedge='clear', Colormode='ramp', Dyesource='mask',
               Palettesmooth=0.3, Viewmode='patterns', Upscale='linear', Mediascale=1.25)
    configure(**odd)
    saved, _ = lib().capture(C)
    C.par.Presetname = 'Phase4 Round Trip'
    preset = lib().on_save(C)
    check('save_reports', preset is not None and 'Saved' in C.par.Presetstatus.eval(),
          status=C.par.Presetstatus.eval())
    select('Worms')
    lib().on_apply(C)
    check('other_preset_differs', lib().capture(C)[0] != saved)
    select('Phase4 Round Trip')
    report = lib().on_apply(C)
    restored, _ = lib().capture(C)
    mismatched = {k: [saved[k], restored.get(k)] for k in saved if restored.get(k) != saved[k]
                  or type(restored.get(k)) is not type(saved[k])}
    check('preset_round_trip_exact', not mismatched and not report['missing'], mismatched=mismatched)
    for name, value in odd.items():
        if C.par[name].eval() != value:
            mismatched[name] = [value, C.par[name].eval()]
    check('round_trip_matches_configured', not mismatched, mismatched=mismatched)
    # Saving through the real table survives a reload of the DAT text.
    text = C.op('presets').text
    check('table_text_stable', lib().dumps(lib().loads(text)) == text)


def file_checks():
    path = ROOT / 'exported_presets.json'
    C.par.Presetfile = str(path)
    lib().on_export(C)
    exported = path.read_text()
    check('export_matches_table', exported == C.op('presets').text)
    original = C.op('presets').text
    C.par.Importmode = 'replace'
    report = lib().on_import(C)
    check('import_replace_round_trip', C.op('presets').text == original and report['added'] == ['Phase4 Round Trip'],
          report=report)
    bad = ROOT / 'bad_presets.json'
    bad.write_text(json.dumps({'schema': 'turing_media_v2.presets', 'version': 99, 'presets': []}))
    C.par.Presetfile = str(bad)
    check('newer_version_refused', lib().on_import(C) is None and C.op('presets').text == original
          and 'newer' in C.par.Presetstatus.eval())
    bad.unlink()
    C.par.Presetfile = str(path)
    C.par.Importmode = 'merge'


def apply_checks():
    # Direct API: apply without reset keeps state; dimension changes reset once.
    baseline()
    evolve(30)
    before, age, count = image('state'), ticks(), resets()
    select('Chemistry Map')
    report = lib().apply(C, lib().selected(C, lib().document(C)), reset=False)
    check('apply_keeps_state_direct', np.array_equal(before, image('state')) and ticks() == age
          and resets() == count and report['reset'] == '', changed=report['changed'])
    after = evolve(10)
    check('evolves_after_apply', not np.array_equal(before, after) and np.isfinite(after).all()
          and after[:, :, :2].min() >= 0 and after[:, :, :2].max() <= 1,
          ticks_before=age, ticks_after=ticks(), max_abs=float(np.max(np.abs(before - after))))
    count = resets()
    select('Dividing Spots')
    lib().on_apply(C, reset=True)
    check('apply_reset_once_direct', resets() == count + 1 and ticks() == 0)
    count = resets()
    select('Wide Coarse')
    report = lib().on_apply(C, reset=False)
    shape = image('state').shape
    check('resize_forces_one_reset', resets() == count + 1 and report['reset'] == 'dimensions changed'
          and shape[:2] == (144, 256) and C.op('seed').width == 256, shape=list(shape))
    check('resize_no_errors', not any(n.errors() for n in C.children if n.name != 'movie'))
    # Bindings are optional; without the toggle a bound preset leaves sources alone.
    configure(Sourcetop='')
    # Custom TOP parameters resolve paths from the owner's parent network.
    preset = lib().make_preset('bound', lib().capture(C)[0], {'Sourcetop': 'fixture_source'})
    C.par.Presetbindings = False
    lib().apply(C, preset)
    unbound = C.par.Sourcetop.eval() is None
    C.par.Presetbindings = True
    count = resets()
    lib().apply(C, preset, include_bindings=True)
    check('bindings_optional', unbound and C.par.Sourcetop.eval() == C.parent().op('fixture_source')
          and C.par.Sourcetop.val == 'fixture_source' and resets() == count,
          unbound=unbound, resolved=str(C.par.Sourcetop.eval()), resets_before=count, resets_after=resets())
    C.par.Presetbindings = False
    configure(Sourcetop='')


def thumbnail_checks():
    baseline()
    evolve(5)
    main_state = image('state')
    explorer = C.op('explorer').module
    started = time.perf_counter()
    done = explorer.generate(C, synchronous=True)
    seconds = time.perf_counter() - started
    first = image('fk_read')
    explorer.generate(C, synchronous=True)
    second = image('fk_read')
    tiles = [first[r * 128:(r + 1) * 128, col * 128:(col + 1) * 128, 1] for r in range(4) for col in range(2)]
    means = [float(t.mean()) for t in tiles]
    distinct = all(not np.array_equal(tiles[i], tiles[j]) for i in range(8) for j in range(i + 1, 8))
    reference = C.fetch('Fkreference')
    check('thumbnails_generated', done and C.fetch('Fkready') == 1 and reference['ticks'] == 600,
          seconds=seconds, reference=reference)
    check('thumbnails_finite_bounded', np.isfinite(first).all() and first[:, :, :2].min() >= 0
          and first[:, :, :2].max() <= 1)
    check('thumbnails_deterministic', np.array_equal(first, second))
    check('thumbnails_distinct', distinct, mean_b=means)
    check('thumbnails_evolved', sum(m > 0.01 for m in means) >= 4, mean_b=means)
    check('thumbnails_leave_main_state', np.array_equal(main_state, image('state')))
    check('thumbnail_status_labels_reference', 'Reference outcomes' in C.par.Explorerstatus.eval())
    C.op('fk_panel').save(str(ROOT / 'explorer.png'))
    C.store('Phase4thumbs', first)


def explorer_checks():
    explorer = C.op('explorer').module
    baseline()
    evolve(5)
    before, count = image('state'), resets()
    width, height = explorer.PANEL_WIDTH, explorer.PANEL_HEIGHT
    result = explorer.pick(C, 256 / width, 0.5)
    expected = (round(0.0 + 0.08 * 0.5, 5), round(0.04 + 0.03 * 0.5, 5))
    check('map_pick_sets_feed_kill', result == 'map' and (C.par.Feed.eval(), C.par.Kill.eval()) == expected,
          values=[C.par.Feed.eval(), C.par.Kill.eval()])
    result = explorer.pick(C, (512 + 200) / width, (height - 10) / height, pressed=True)
    check('tile_pick_selects_example', result == 'Dividing Spots'
          and (C.par.Feed.eval(), C.par.Kill.eval()) == (0.0367, 0.0649))
    check('explorer_never_resets', resets() == count and np.array_equal(before, image('state')))
    C.par.Explorerreset = True
    explorer.pick(C, (512 + 10) / width, (height - 10) / height, pressed=True)
    check('explorer_optional_reset', resets() == count + 1 and C.par.Feed.eval() == 0.0545)
    C.par.Explorerreset = False
    # Asynchronous generation via the real pulse must match the synchronous reference.
    C.par.Generatethumbs.pulse()


def keep_state_pulse():
    # The asynchronous generation needs about 15 frames; poll until complete.
    C.store('Phase4wait', 0)
    later('wait_thumbs', 5)


def wait_thumbs():
    waited = C.fetch('Phase4wait', 0) + 1
    C.store('Phase4wait', waited)
    if C.fetch('Fkready') != 1 and waited < 60:
        later('wait_thumbs', 5)
        return
    check('async_thumbnails_match', C.fetch('Fkready') == 1
          and np.array_equal(image('fk_read'), C.fetch('Phase4thumbs')))
    # Real pulses: Parameter Execute callbacks may arrive after the batch.
    baseline()
    evolve(30)
    configure(Pause=True)
    C.store('Phase4before', dict(state=image('state'), ticks=ticks(), resets=resets()))
    select('Dividing Spots')  # changes Seedradius (a reset parameter) and chemistry
    C.par.Applypreset.pulse()
    later('after_apply_pulse', 6)


def after_apply_pulse():
    before = C.fetch('Phase4before')
    check('apply_pulse_keeps_state', np.array_equal(before['state'], image('state'))
          and ticks() == before['ticks'] and resets() == before['resets']
          and C.par.Seedradius.eval() == 5.0, status=C.par.Presetstatus.eval())
    C.store('Phase4before', dict(resets=resets()))
    C.par.Applyreset.pulse()
    later('after_apply_reset_pulse', 6)


def after_apply_reset_pulse():
    check('apply_reset_pulse_once', resets() == C.fetch('Phase4before')['resets'] + 1 and ticks() == 0,
          resets_before=C.fetch('Phase4before')['resets'], resets_after=resets(), ticks=ticks(),
          status=C.par.Presetstatus.eval())
    C.store('Phase4before', dict(resets=resets()))
    select('Wide Coarse')
    C.par.Applypreset.pulse()
    later('after_resize_pulse', 6)


def after_resize_pulse():
    check('resize_pulse_once', resets() == C.fetch('Phase4before')['resets'] + 1
          and image('state').shape[:2] == (144, 256))
    C.store('Phase4before', dict(resets=resets()))
    C.par.Reseed.pulse()
    later('after_reseed_pulse', 6)


def after_reseed_pulse():
    check('reseed_pulse_once', resets() == C.fetch('Phase4before')['resets'] + 1)
    C.store('Phase4before', dict(resets=resets()))
    C.par.Clipseed.pulse()
    later('after_clipseed_pulse', 6)


def after_clipseed_pulse():
    check('clipseed_pulse_once', resets() == C.fetch('Phase4before')['resets'] + 1
          and C.par.Strength.eval() == 600.0 and not C.par.Ambient.eval())
    # Hand edits keep the inherited reset behavior.
    C.store('Phase4before', dict(resets=resets()))
    C.par.Seedradius = 6.5
    later('after_manual_edit', 6)


def after_manual_edit():
    check('manual_seed_edit_resets_once', resets() == C.fetch('Phase4before')['resets'] + 1)
    finish()


def finish():
    for n in C.children:
        if n.family == 'TOP':
            n.cook(force=True)
    REPORT['errors'] = {n.name: n.errors() for n in C.children if n.errors()}
    REPORT['shaders'] = {n.name: n.text for n in C.children if n.family == 'DAT' and n.name.endswith('_info')}
    check('no_unexpected_operator_errors', not any(n != 'movie' for n in REPORT['errors']))
    check('all_shaders_compile', all('Compiled Successfully' in t for t in REPORT['shaders'].values())
          and len(REPORT['shaders']) >= 15, count=len(REPORT['shaders']))
    REPORT['passed'] = all(row['passed'] for row in REPORT['checks'].values())
    (ROOT / 'report.json').write_text(json.dumps(REPORT, indent=2, default=str))
    C.op('out1').save(str(ROOT / 'preview.png'))
    print('PHASE4_COMPLETE', REPORT['passed'])
    if CHAIN:
        CHAIN()
