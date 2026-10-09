# Phase 7 performance optimization and validation

`../../create_turing_media_v2.py` implements all six phase 7 optimizations and remains
one standalone paste-and-run Text DAT script. RGBA32F chemical state remains the
reference. The six public output names are preserved. Validation uses TouchDesigner
2025.33230 on macOS; other builds are not claimed.

## Runtime behavior

- Display reads one state texel when grid and canvas sizes match. Coarse cubic,
  linear and nearest reconstruction retains the existing canvas boundary policy.
- Media masks and injection data run at simulation resolution. Prepared source,
  motion sample histories and Source Preview retain full canvas resolution. Small
  integer reductions use exact box averages (up to four cells per axis); other
  reductions use bounded 4x4 bilinear quadrature. RGB is premultiplied before
  filtering and unpremultiplied afterward, preserving fractional alpha and excluding
  hidden transparent colors. Full-size simulation sources bypass reduction.
  Previous-source reduction runs only for Motion masks. Mask Preview reconstructs
  the simulation mask to full canvas size with linear filtering.
- Influence and stamp masks use mono32float, packed influence/domain uses
  rg32float, and hard-threshold domains use mono8fixed. These retain the exact
  float mask values and binary walls. The colorized visual intermediate uses
  RGBA16F; final compositing, prepared sources, palette histories and all chemical
  state remain RGBA32F. Signed chroma is never put into an unsigned mask format.
- **Performance > Maintain Carried Color** defaults on. Turning it off skips dye
  diffusion, injection and decay while preserving stored signed chroma. A/B
  chemistry is unchanged. Global transforms and velocity still transport all state
  channels. Re-enabling resumes retained color; Clear Carried Color erases it.
- **Continuous Palette History** defaults off. Clip Palette requests extraction;
  other color modes hold the clip ramp. A custom Ramp TOP refreshes the base row
  without extracting media unless clip extraction is required. Enable continuous
  history to retain the former always-warm behavior.
- **Palette Update Interval** is 1–600 simulation ticks, default 1. It is independent
  of render FPS and Solver Quality. Updates use actual elapsed simulation time in
  exponential smoothing. Between updates the ramp is held. Required history
  initializes during reset; subsequent color-mode changes use the held ramp until
  the next eligible tick. Pause freezes updates; Step advances one tick.

Coarse filtering intentionally removes sub-cell detail and can change media-driven
patterns. Edge Width and Smoothing retain simulation-cell units. Domain walls
retain their independent nearest threshold sampling and impermeable boundary rules.

Presets capture 78 settings in twelve groups. Snapshots also save the last palette
update tick, independently of state-buffer parity. Restore replays palette cadence
exactly. Reset Chemistry rebases cadence while retaining palette values. Complete
older snapshots restore carried and continuous palette history on with interval 1;
partially missing new settings are rejected. Older presets leave missing settings
unchanged under the existing preset contract. State/archive schemas remain version 1.

## Measured costs

| Workload | GPU estimate before / after (ms) | Reported TOP memory before / after (MiB) |
| --- | ---: | ---: |
| 512 square, full grid | 5.026 / 4.478 | 76.01 / 66.26 |
| 768x384, full grid | 4.740 / 5.574 | 85.51 / 74.54 |
| 512 square, Cell Size 4 | 1.824 / 2.080 | 38.51 / 33.46 |
| 768x384, Cell Size 4, clip palette | 2.220 / 2.250 | 43.33 / 37.68 |
| 512 square, carried history off | 5.347 / 4.565 | 76.01 / 66.54 |
| 768x384, clip interval 4 | 2.259 / 1.997 | 43.33 / 37.68 |

The measurement covers a tick and final-image cook on square 512x512 and rectangular
768x384 canvases, at Cell Size 1 or 4. A controlled RGBA source has alpha 0.37.
Fixed color cases keep carried history on unless labeled otherwise; clip cases use
Clip Palette. The phase 6 reference always maintains both histories and updates its
palette every tick. `reference_v6.py` is the frozen pre-optimization builder.

`profile_before.json` and `profile_after.json` retain every sample and stage totals
for simulation, media, palette and display. Each case warms up for eight ticks and
records forty frame-separated samples. `profile_comparison.json` includes each
stage's GPU timing estimate and reported resident bytes independently.

GPU estimates sum each operator's last measured `gpuCookTime` multiplied by its
cook-count delta for the explicit workload, sampled on the next timeline frame.
This is an estimate, not an end-to-end GPU timestamp: repeated cooks can differ,
TD timing arrives asynchronously, and other rendering, scheduling and GPU clock
changes add noise. Reported bytes sum the named TOPs' `gpuMemory`, including held
allocations; they do not include external sources or the entire TD process. CPU
submission wall time is recorded separately and is not GPU elapsed time. The
comparison does not promise a universal FPS increase.

The shader structure retains the 16-update solver; chemical-state format has not
changed. Palette work can reach zero in unused color modes, interval 4 samples
one in four ticks, and display intermediate memory halves. The table retains
workloads where total estimated GPU cost increases as well as those that improve.

## Fidelity and lower precision

`report.json` contains 60 passing phase 7 checks. Full-grid raw state, masks,
source and warmed palette match phase 6 within 1e-6 in all four color modes;
final visuals use an 8e-4 acceptance bound for half-float intermediate rounding.
No-media coarse chemical state matches within 1e-6 for all three boundaries.
Independent NumPy filtering checks cover exact integer boxes and fractional
rectangular reductions, fractional alpha and invisible-color exclusion.

History checks cover held/continuous palettes, intervals, elapsed-time smoothing,
raw signed chroma, independent chemistry, pause/Step, custom-ramp extraction
avoidance, preset serialization, legacy snapshot defaults and deterministic
snapshot replay of all six outputs with a nontrivial interval. `frame_report.json`
adds seven checks using real parameter edits and a Step pulse over timeline frames.

The half-float chemical experiment runs coral and dividing spots for 3,600 ticks
(60 simulation seconds, 57,600 numerical updates each) on rectangular grids. It
records raw pointwise error, RMSE, mean B and occupied-area changes at ticks 60,
600, 1,800 and 3,600. Both experiments remain finite and bounded but fail the
1e-3 pointwise acceptance bound. `report.json` retains the full results. Half-float
chemical state is therefore not exposed as a supported mode.

Historical regression results are stored separately here:

| Suite | Passing checks |
| --- | ---: |
| Clock | 20, plus seven 30/60-FPS cases and 42 exact output comparisons |
| Influence and domain | 75 |
| Presets and explorer | 44 |
| Snapshots and resizing | 104 |
| Boundaries and velocity | 159 |

The preset regression retains the established deferred-seed-reset adaptation.
All reports carry final-source fingerprints; `analyze.py` rejects stale or failing
results. Historical phase 2–6 evidence remains unchanged.

## Reproduce

Offline checks require only Python's standard library:

```sh
python3 validation/phase7/test_performance.py
python3 validation/phase4/test_presets.py
python3 validation/phase5/test_snapshots.py
python3 validation/phase6/test_flow_presets.py
python3 validation/phase2/test_clock.py
```

These provide 62 passing tests. Live scripts require `/project1`, timeline playback,
and the checkout path configured as ROOT in each script. From Textport:

```python
ROOT = '/absolute/path/to/turing-patterns'
exec(compile(open(ROOT + '/validation/phase7/probe_td.py').read(), 'phase7_probe', 'exec'))
exec(compile(open(ROOT + '/validation/phase7/run_td.py').read(), 'phase7', 'exec'))
```

Wait for `PHASE7_COMPLETE True`, then run:

```python
exec(compile(open(ROOT + '/validation/phase7/run_frames_td.py').read(), 'phase7_frames', 'exec'))
exec(compile(open(ROOT + '/validation/phase7/regressions_td.py').read(), 'phase7_regressions', 'exec'))
```

Wait for `PHASE7_FRAMES_COMPLETE True` and `PHASE7_ALL_COMPLETE True`, then profile:

```python
exec(compile(open(ROOT + '/validation/phase7/run_profiles_td.py').read(), 'phase7_profiles', 'exec'))
```

Wait for both `PHASE7_PROFILE_COMPLETE before` and `after`; then run
`python3 validation/phase7/analyze.py` from the shell. Each live runner builds its
own paused component and retains existing project components. It does not save
or overwrite the TOE. The probe found no TDAPI component; native inventories in
`parameters.json` verify parameter names and supported formats.

Metrics follow the official [OP Class documentation](https://derivative.ca/UserGuide/OP_Class).
Channel formats follow the [GLSL TOP documentation](https://derivative.ca/UserGuide/GLSL_TOP).
