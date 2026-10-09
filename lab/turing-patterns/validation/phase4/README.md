# Phase 4 — complete presets and Feed/Kill explorer

Implemented in `../../create_turing_media_v2.py`, still one standalone script for
a TouchDesigner Text DAT. V1 is unchanged. All six public outputs and unique
component naming remain. The embedded component README describes every control.

## Preset table

- The `presets` Text DAT holds a JSON document saved with the TOE/TOX:
  `{"schema": "turing_media_v2.presets", "version": 1, "presets": [...]}`.
- Each preset has a `name`, a `description` and complete `settings`, grouped as chemistry, seed,
  dimensions, timing, media fitting, influence, domain, transform, display and color (70
  parameters). Optional `bindings` hold Movie File, Source TOP, Domain Mask TOP and
  Ramp TOP. Built-ins carry `"builtin": true`.
- The builder refuses to build if any non-pulse custom parameter is not classified as
  preset data, a binding, or deliberately excluded (Pause, diagnostics, preset/explorer
  controls). That keeps presets complete as parameters are added.
- Nine read-only built-ins are rebuilt from parameter defaults on every build: Coral,
  Dividing Spots, Worms, Holes, Clip Seed, Stamp and Evolve, Chemistry Map, Color Swirl
  and Wide Coarse. The former Turing > Coral/Dividing Spots pulses became presets.

| Control | Behavior |
| --- | --- |
| Apply Preset (keep state) | One batch with no reset. State, carried color, age and histories continue. Seed settings wait for the next reset. If the effective canvas or simulation size changes, exactly one reset happens, because state cannot survive a resize until resampling exists (Phase 5). |
| Apply Preset + Reset | One batch, then exactly one reset. |
| Save Current Preset | Captures every value under Save As Name. Blank picks `User Preset N`. A matching user preset is replaced. Built-in names are refused. |
| Delete User Preset | Built-ins cannot be deleted. |
| Include Media/TOP Bindings | Off by default: bindings are neither saved nor applied, so presets stay portable. When on, typed (relative) paths are saved and restored. Bindings never force a reset. |
| Import / Export Presets | Export writes the whole table to Preset File; relative paths resolve from the project folder. Import offers Merge (adds new presets, replaces same-named ones) or Replace User Presets. Imported copies of built-ins are skipped. A user preset named like a built-in becomes `<name> (imported)`. |

Every pulse that resets now resets exactly once: Apply, Reseed (previously reset
twice), Seed From Clip Only (now a partial preset), Restart Clip. Preset batches mark
the expected values they change, and the Parameter Execute DAT consumes those
notifications once, even when callbacks arrive after skipped absolute frames.
Overlapping batches merge their pending values; a hand edit to a different value
keeps the inherited reset behavior. `clock.reset` increments
`component.fetch('Resetcount')` so this can be tested.

Robustness:

- Files with a newer schema version, invalid JSON, duplicate names or non-finite
  values are refused. The table stays unchanged and Status explains why.
- Unknown settings (from a newer build, say) are kept verbatim and reported when applied.
- Missing settings keep their current values and are reported.
- Menu values this build doesn't offer, and values of the wrong type, are reported
  as invalid.
- Expression-driven parameters are set to constant. Exported parameters are
  left alone and reported as blocked.
- `migrate()` is the hook for future schema versions.

## Feed/Kill explorer

`fk_explorer` is a 768×512 Container COMP panel whose background is `fk_panel`:

- **Left:** the Feed/Kill plane. Kill runs along X (.04–.07) and feed along Y (0–.08), with a
  .01 grid, colored rings at curated examples, a crosshair at the current values, and the
  saddle-node line k = √F/2 − F.
- **Right:** eight reference thumbnails, with the first at top-left.

Clicking or dragging on the map sets Feed/Kill. Clicking a thumbnail selects that
example exactly. Neither resets, unless Reset When Choosing Example is on. Input is
polled by the `explorer` Execute DAT. If this TouchDesigner build lacks the
container parameters, the panel is skipped with a printed warning and a Status
message. The rest of the build continues.

Generate Thumbnails simulates all eight examples (Coral, Dividing Spots, Worms, Holes,
Chaos, Moving Spots, Waves, U-Skate) together:

- They run in a 256×512 atlas of independently wrapping 128-cell tiles.
- Every tile uses the same fixed seed layout (Thumbnail Seed, radius 5 cells).
- They use the reference solver: dt=1, diffusion 1/.5, 16 updates per tick.
- They run for Thumbnail Age (default 10 s = 600 ticks), using explicit ping-pong
  spread over frames.

They are labelled **reference outcomes** in Status, the `fk_examples` table and the
help. Initialization, media, domains, size and diffusion change results.
Generating never touches the main simulation state.

## Validation

### Offline (passes)

```sh
python3 validation/phase4/test_presets.py
python3 validation/phase2/test_clock.py
```

The 31 preset tests run the embedded modules against TouchDesigner fakes. They cover:

- parameter coverage and built-in validity
- exact serialization and round trips
- refusal of bad documents
- merge, replace and rename on import
- binding portability
- unknown, invalid and missing reporting
- int/float/bool coercion
- expression and export modes
- one reset per action, including forced resets on resize
- the pending-callback guard
- explorer hit-testing and layout constants

### Live (TouchDesigner 2025.33230, macOS)

**Passed live on TouchDesigner 2025.33230, macOS, October 8, 2026.**
Other builds are not claimed. `report.json` records 44 passing checks and the
SHA-256 fingerprint of the builder source loaded into TouchDesigner:

- All 70 settings round-trip exactly, including their types; file export/import
  round-trips and newer-version rejection preserve the embedded table.
- Both direct and real pulse applications preserve the evolving state and age
  without reset. Explicit Apply + Reset, resize, Reseed and Clip Seed reset once.
- Eight fixed-seed, fixed-age reference tiles are distinct, finite and bounded;
  repeated synchronous and asynchronous generation is pixel-exact and leaves
  the main state unchanged.
- Explorer map/example picking and optional reset work, and its background TOP
  resolves correctly. All 18 shaders compile with no operator errors.
- `phase3_regression/report.json`: 75 passing checks, including 36 pixel-exact
  public-output comparisons at 30/60 FPS.
- `clock_regression/report.json`: 20 passing checks plus seven cases with 42
  pixel-exact public-output comparisons at 30/60 FPS. Tolerance is 1e-6.
- `ui_report.json`: eight passing checks from actual mouse interaction with the
  opened panel. Thumbnail clicking and map dragging update Feed/Kill while
  preserving state, age and reset count. The panel was also visually inspected.

Validation found and fixed two product defects: a ten-absolute-frame callback
guard could expire during GPU work and cause a second reset; the panel's former
`../fk_panel` path resolved to no TOP. Expected-value tracking and the sibling
`fk_panel` reference fix these. The harness was also corrected to supply elapsed
time after a preset restores Real Time, and to reference its sibling fixture
using `fixture_source`, matching live custom TOP parameter resolution.
`initial_report.json` and `reset_trace.json` retain the initial failure evidence.

To reproduce, in Textport with `/project1` and playback enabled:

```python
PHASE4_ROOT = '/absolute/path/to/turing-patterns'
exec(compile(open(PHASE4_ROOT + '/validation/phase4/run_td.py').read(), 'run_td.py', 'exec'))
```

Wait for `PHASE4_ALL_COMPLETE True` (several minutes). The script does the following:

- records live parameter inventories for the operator types new in Phase 4 (`parameters.json`)
- builds a fresh component
- runs `validate_td.py`: build, round trip, file, apply, thumbnail and explorer
  checks, plus real-pulse checks that span frames
- reruns the Phase 3 suite on a fresh build (`phase3_regression/`)
- reruns the Phase 2 clock suite (`clock_regression/`)
- writes `summary.json`

Existing components are preserved and the TOE is not saved. Test fixtures need
TouchDesigner's bundled NumPy; the product does not.
