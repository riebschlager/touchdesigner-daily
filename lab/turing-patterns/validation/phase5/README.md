# Phase 5 — snapshots and deliberate resets

Implemented in `../../create_turing_media_v2.py`. It remains a single paste-and-run
TouchDesigner builder with embedded shaders/modules and the six original public
outputs. Ordinary ticks stay on the GPU. Manual save/restore and resampling use
NumPy bundled with TouchDesigner; nothing needs to be installed.

## Reset contract

| Control | Chemistry | Carried color | Simulation age/debt | Movie | Palette/motion history |
| --- | --- | --- | --- | --- | --- |
| Reset Chemistry | Current seed | Retained | Zero | Position retained | Retained |
| Clear Carried Color | Retained | Blue/alpha zeroed | Retained | Position retained | Retained |
| Restart Media (Media page) | Retained | Retained | Retained | Cued | Palette retained; motion invalidated |
| Reset All | Current seed | Zero | Zero | Cued | Initialized |
| Reseed | Increment Seed, then Reset Chemistry once | Retained | Zero | Position retained | Retained |

All actions retain Pause. Turing > Reset is a Reset All alias. Apply Preset +
Reset retains its Phase 4 behavior: chemistry/color/age/histories reset once,
without seeking the movie. Presets now cover 72 settings, including Resize
Behavior and Reset on Source Change. Existing schema-v1 presets with those two
settings missing keep the current policy and report them as missing.

Seed, Seed Radius and Ambient Seeds edits wait for the next explicit reset.
Source bindings retain chemistry by default; **Reset on Source Change** opts into
one reset without rewinding the movie. Either policy invalidates both motion
samples immediately, even while paused. The first new tick suppresses motion;
subsequent ticks compare source samples. Changes no larger than 1e-6 are treated
as float noise, so an unchanged source produces exactly zero motion.

## Snapshot contract

State page provides Save State / Restore State in memory, plus State File and
Save State to Disk / Restore State from Disk. Disk save captures the current
state; it does not require a previous memory save. Memory restore can be repeated.

A snapshot contains:

- All six **RGBA32F** buffers: `state_a/b`, `media_a/b`, `palette_a/b`.
- Active state/media buffer indices and the independent active palette reader.
- Canvas/grid dimensions, integer ticks, simulation seconds and fractional clock debt.
- All 72 settings, four external bindings, Pause and palette/motion readiness.
- Movie position, playback mode, index and cue settings; format schema/version.

State blue and alpha are **signed Oklab chroma data**, not RGB/opacity. Disk format
is `.tstate`: ZIP with `metadata.json` and six `.f32` payloads, raw little-endian
float32 RGBA in bottom-up row order. No color conversion, premultiplication,
quantization, image codec or pickle is used. Each texture has shape and SHA-256.
Disk writes use a temporary sibling file, verify the round trip, then atomically
replace the destination. Relative paths resolve against the project folder.

Restores validate schema/version, settings, ranges, dimensions, sizes, finite
values and hashes before writing settings/textures. Export-driven parameters are
refused; expression-driven settings restore as constants. Dimensions/settings
restore as one batch with no reset. Wall time rebases so time spent saving,
paused or restoring is not caught up. All GPU histories and their active readers
are restored, including palette parity after stamps/color clears.

Memory snapshots are component storage and can be saved with a TOE/TOX. GPU
buffers initialize afresh when loading; restore the memory or disk snapshot to
recover the saved evolving state. External media assets, operator implementations,
the preset table and explorer thumbnails are not embedded in snapshots.

Equal subsequent source samples/settings/ticks produce exact replay. Movie
position and both media/palette histories restore; the fixture validates indexed
movie replay and sequential seeking. Ordinary sequential movie scheduling still
depends on output timing and decoding. Live cameras/TOPs cannot rewind: raw
chemical/color state restores exactly, while preview/overlay and future input
can differ. Save/restore can stall for GPU downloads/uploads and needs CPU memory
for six raw arrays.

## Resize contract

Requested dimensions are separate from stored applied dimensions. All size-based
operators read the latter. The clock commits a transition before the next tick,
stamp, or manual snapshot, including when paused. Both state buffers always match
the applied grid before the solver runs.

- **Reset** (default): initializes chemistry/color and media/palette histories,
  zeroes age/debt and counts one reset.
- **Resample State**: preserves age/debt, signed color and palette history;
  explicitly interpolates all raw state channels at normalized pixel centers,
  with clamped edges and the new domain mask. Motion history is invalidated.

Resampling preserves visual continuity but changes the discrete simulation and
can alter future behavior. Cell/canvas changes can smooth away small features.
Hidden Width/Height edits while in square mode do not resize the applied state.
The policy stored in an applied preset controls its size transition; built-ins
use Reset. Multiple size/source edits in a preset batch cause at most one reset.

Live validation found that Cache TOP resampled its existing texture when changing
sizes even with Replace enabled. `clock.capture` now clears a mismatched-size
cache before copying, so restoring a smaller/larger texture remains bit-exact.
Restore disconnects old simulation inputs before applying new dimensions.

## Validation

Validated on **TouchDesigner 2025.33230, macOS, October 9, 2026**. Other builds are
not claimed. Reports include the builder source fingerprint and live parameter
inventories (`parameters.json`).

| Evidence | Result |
| --- | --- |
| `report.json` | 104 passing checks: signed float upload; exact memory/disk state restoration after evolution/pause/resize; six histories, settings and clock restoration; independent palette parity; deterministic controlled-source/movie replay; independent resets; source preservation/invalidation; bilinear resize reference and repeated resize/tick transitions; shader/operator errors |
| `frame_report.json` | 12 passing checks using real parameter pulses/hand edits across timeline frames, with both product callback DATs enabled |
| `clock_regression/report.json` | 20 passing Phase 2 checks plus seven 30/60-FPS cases with 42 exact public-output comparisons |
| `phase3_regression/report.json` | 75 passing Phase 3 checks, including 36 exact public-output comparisons |
| `presets_regression/report.json` | 44 passing Phase 4 preset/explorer checks |
| `test_snapshots.py` | 15 passing archive/schema/corruption tests |
| `../phase4/test_presets.py` | 31 passing preset tests |
| `../phase2/test_clock.py` | Seven passing clock tests |

Raw restore/replay comparisons require bit equality, including signed channels.
Resize comparison uses an independent CPU bilinear reference with tolerance 1e-6.
The Phase 4 regression changes only its old automatic-seed-reset expectation to
the explicit Phase 5 deferred-seed contract; historical Phase 4 results are intact.
The offline clock fake implements the new resize/source adapter interface.
`initial_report.json` retains the initial live failure evidence. The first frame
harness needed to drain construction/previous disabled-control notifications
before taking its baseline (`initial_frame_report.json`); the corrected harness
warms up first, as the Phase 2 frame harness does.

Reproduce offline:

```sh
python3 validation/phase5/test_snapshots.py
python3 validation/phase4/test_presets.py
python3 validation/phase2/test_clock.py
```

Reproduce live from Textport with `/project1` and playback enabled (update ROOT in
scripts if the checkout is elsewhere):

```python
ROOT = '/absolute/path/to/turing-patterns'
exec(compile(open(ROOT + '/validation/phase5/run_td.py').read(), 'phase5', 'exec'))
```

Wait for `PHASE5_COMPLETE True`, then run:

```python
exec(compile(open(ROOT + '/validation/phase5/run_frames_td.py').read(), 'phase5_frames', 'exec'))
exec(compile(open(ROOT + '/validation/phase5/regressions_td.py').read(), 'phase5_regressions', 'exec'))
```

Wait for `PHASE5_FRAMES_COMPLETE True` and `PHASE5_ALL_COMPLETE True`.
These create separate components without saving/overwriting the TOE or existing
components. The movie fixture is synthetic, reproducible with:

```sh
ffmpeg -f lavfi -i 'testsrc2=size=64x64:rate=30:duration=3' -c:v libx264 -pix_fmt yuv420p validation/phase5/fixture.mp4
```

API references: [Script TOP](https://derivative.ca/UserGuide/Script_TOP),
[Script TOP class](https://derivative.ca/UserGuide/ScriptTOP_Class),
[Cache TOP](https://derivative.ca/UserGuide/Cache_TOP),
[Movie File In TOP](https://derivative.ca/UserGuide/Movie_File_In_TOP).
