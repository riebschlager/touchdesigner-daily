# Phase 8 diagnostics, motion history and consolidated validation

The standalone `../../create_turing_media_v2.py` implements phase 8. It still runs
from one Text DAT without external Python packages, shader files or a TDAPI TOX.
All six public outputs retain their names. Live evidence is for **TouchDesigner
2025.33230 on macOS**; other builds are unvalidated.

## Diagnostics

View `status_panel` inside the generated component as a panel. Its ten rows show
the actual build, effective canvas and simulation grid dimensions, clock mode and
pause state, total and last-frame ticks, substeps per tick and last-frame numerical
work, simulation seconds and retained lag, source validity, shader health, build
issues and runtime errors. `status` is the full, untruncated table.
`shader_diagnostics` retains every shader's named compiler log.

The separate diagnostics Execute DAT updates status at frame start, including
while simulation Pause is on. It scans existing shader logs/errors at most twice
a wall-clock second. The scan does not explicitly cook simulation or download
textures. Build completion and **Diagnostics > Check Shaders / Refresh** explicitly
cook all 24 shaders, including the optional explorer. Those checks compute outputs
without committing a simulation tick or history sample. With the TD timeline
stopped, use this pulse for a fresh observation. Unchecked shaders are distinguished
from successful and failed shaders.

Blank media means valid ambient operation. An unresolved Source TOP reference is
reported even if rendering falls back to the transparent source. TOP validity
includes dimensions and current operator errors. Movie errors include missing
literal local paths and decoder-reported failures. Sequence patterns, variables
and URLs rely on decoder diagnostics, which can arrive asynchronously. A bound
Source TOP takes priority over an unused movie.

Required parameter names and unsupported menu values fail with a named Textport
error and remain in `Build issues` storage; the partial component is retained.
An exception in the clock's frame callback disables its Execute DAT and records
`Clock stopped: …` in Runtime. Fix the named cause, use Reset All, and re-enable
`clock > Active`. Successful reset clears the runtime message. Diagnostics does
not automatically resume a failed clock.

Actual parameter inventories are in `parameters.json`. No TDAPI component was
present in the tested project; native inventory and the established standalone
builder API were used. The parameter guards are also tested with deliberate
missing names and invalid menu tokens.

## Motion history and the edge correction

`media_a` and `media_b` are RGBA32F Cache TOPs, with cache size one, Active off,
Cache Once off, Always Cook off and Replace off except during explicit capture.
Ticks alternate replacement and reader selection; diagnostics and viewer recooks
retain history. Pause holds the last sampled mask even when the live source changes.
Step samples once. A stopped source settles to exactly zero on the next unchanged
tick, including with smoothing and a coarse rectangular simulation grid.

Live validation found a stationary-source edge artifact: smoothing looked outside
the canvas, where the current sample was transparent but the previous sample was
clamped to the edge. The motion branch now treats both histories as transparent
outside the canvas. Edge and other mask modes retain their existing rules.

Source identity/file changes, source TOP dimension changes, Restart Media and
canvas resizing invalidate both samples and suppress the first new tick difference.
Source changes retain chemical state by default. Snapshot restore reinstates both
media samples, reader parity and readiness. Raw state alpha remains signed chroma
data rather than image opacity.

## Evidence

All reports include the builder SHA-256 and actual build. `analyze.py` rejects
missing, stale, failing or wrong-build results, including failed replay cases.

| Suite | Passing checks |
| --- | ---: |
| Phase 8 status, errors and numerical stability | 32 |
| Phase 8 real timeline and custom parameter pulses | 23 |
| Clock regression | 20, plus 7 replay cases / 42 output comparisons |
| Influence, chemistry map and domain regression | 75 |
| Presets and explorer regression | 44 |
| Snapshots, resets and resizing regression | 104 |
| Canvas/domain boundaries and velocity regression | 159 |
| Performance filtering, precision reference and histories | 59 |

This is **516 passing live checks**, plus the seven controlled 30/60-FPS replay
cases. The new numerical checks run uniform empty fields for 120 ticks under all
three canvas boundaries and coral/spot fields for 240 ticks at Solver Quality 1
and 4, asserting finite, bounded, evolving concentrations. Diagnostics tests verify
all six outputs and both motion/palette histories remain unchanged by explicit
shader checks. A shader is deliberately broken, observed across frame boundaries,
repaired and checked again. Timeline checks cover Pause/Step, recooks, live-source
changes, motion settling, source resizing and clock exception recovery.

The reused suites supply independent expected-state calculations for stamping,
chemistry maps, diffusion barriers, canvas/domain transport, signed raw snapshot
restore, resampling and transparency/premultiplied compositing. Presets round-trip
all 78 settings and five optional bindings. Controlled-source replay covers all
six outputs, all four color modes, coarse rectangular grids and motion/transforms.

Phase 7's 3,600-tick half-float experiment and before/after cost measurements remain
historical evidence in `../phase7`; they are not rerun or relabeled here. The phase
8 performance regression reruns its filtering, reference fidelity, color/palette
history and snapshot-cadence checks against the final builder. It omits only the
half-float experiment completion check. The preset regression retains the phase 5
deferred-seed-edit expectation.

Offline checks use standard-library Python and test scheduling, preset/archive
serialization, migration, shader-log classification, source validity, compatibility
guards and compilation of all embedded Python modules: **77 passing tests**.
`glslangValidator` was unavailable on this host; no external GLSL compilation is
claimed. All 24 embedded shaders compile in the actual supported TD build, and
operator/compiler checks follow separate frame boundaries after error repair.

## Reproduce

From the checkout:

```sh
python3 validation/phase2/test_clock.py
python3 validation/phase4/test_presets.py
python3 validation/phase5/test_snapshots.py
python3 validation/phase6/test_flow_presets.py
python3 validation/phase7/test_performance.py
python3 validation/phase8/test_diagnostics.py
```

Live scripts require `/project1` and timeline playback. Set `ROOT` to your checkout
in the runners and probe, then run from Textport:

```python
ROOT = '/absolute/path/to/turing-patterns'
exec(compile(open(ROOT + '/validation/phase8/probe_td.py').read(), 'phase8_probe', 'exec'))
exec(compile(open(ROOT + '/validation/phase8/run_td.py').read(), 'phase8', 'exec'))
```

Wait for `PHASE8_COMPLETE True`, then run:

```python
exec(compile(open(ROOT + '/validation/phase8/run_frames_td.py').read(), 'phase8_frames', 'exec'))
```

Wait for `PHASE8_FRAMES_COMPLETE True`, then run:

```python
exec(compile(open(ROOT + '/validation/phase8/regressions_td.py').read(), 'phase8_regressions', 'exec'))
```

Wait for `PHASE8_ALL_COMPLETE True`, then run
`python3 validation/phase8/analyze.py` from the shell. Each runner creates its own
component and retains existing project components. It does not save or overwrite
the TOE. `build_td.py` is the common standalone live builder helper; use it when
only a fresh test component is needed. `component.json` records its latest path.

Embedded `README` contains the complete units, reset/snapshot limitations, V1
migration, controls and recovery workflow. Snapshot reproducibility still requires
identical future source/velocity samples; ordinary decoder/live-camera scheduling
cannot promise that. Resizing preserves continuity under Resample State but changes
the discrete simulation and its future evolution.

API references: [Execute DAT](https://docs.derivative.ca/Execute_DAT),
[Text COMP](https://derivative.ca/UserGuide/Text_COMP), and
[OP Class](https://derivative.ca/UserGuide/OP_Class).
