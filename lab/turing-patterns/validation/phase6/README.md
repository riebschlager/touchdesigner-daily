# Phase 6 — explicit boundaries and flow

Implemented in `../../create_turing_media_v2.py`. The builder remains one standalone
paste-and-run file, with embedded shaders/modules and the six original public outputs.
Global transforms retain their fixed-tick, time-based rates. Optional velocity
transport uses the same GPU pass, after the numerical solver.

## Boundary contract

**Turing > Boundary** replaces Transform > Edges.

| Mode | Diffusion stencil and state transport | Display reconstruction |
| --- | --- | --- |
| Wrap | Opposite edges connect; integer addressing wraps both axes | Wraps coarse-grid cubic/linear taps |
| No Flux | Exterior samples hold the nearest edge cell, blocking outward diffusion | Holds the nearest edge cell |
| Empty Exterior | Exterior samples are `A=1, B=0`, with zero signed carried color | Holds the nearest edge cell |

`BOUNDARY_GLSL` shares addressing and exterior-state helpers across the simulation,
state transport and domain shaders. Display deliberately holds edge values in both
closed modes, preventing interpolation from joining opposite edges or adding a
visual empty border. Resizing retains the Phase 5 normalized bilinear, held-edge
contract independently of the simulation boundary.

Domain Mask remains independent. Its own Domain Boundary governs internal walls;
the canvas boundary governs the exterior. Wrap repeats the mask at seams; closed
modes extend its edge values. Diagonal diffusion taps cannot cut blocked corners.
Transport tests every contributing bilinear tap using the existing supercover wall
traversal. A wall crossing retains destination state with Domain No Flux, or clears
it with Domain Empty Exterior. Paths over 1024 cell crossings are conservatively
rejected. This wall policy can retain/erase state near a wall instead of sliding it.

Boundary edits retain state and age, including while paused. They apply at the next
Step/tick or explicit action. Display reconstruction responds immediately without
changing raw state.

For compatibility, the custom parameter name **Transformedge** and menu token
**clear** remain. Their UI label is now Boundary / Empty Exterior. Old Clear presets
and snapshots still load, but Clear now uses empty exterior for diffusion too.
Select No Flux for the former clamped diffusion behavior. Wrap is unchanged. Older
presets may keep Transformedge in their transform group; new captures group it with
chemistry. Preset schema remains version 1.

## Velocity contract

Flow page provides **Enable Velocity**, **Velocity TOP**, **Velocity Strength**, and
**Max Displacement (cells / tick)**. Flow and global transform enable independently.

- Red is signed X velocity; green is signed Y velocity in **simulation cells per
  simulation second**. Positive X moves right, positive Y moves up, with bottom-left
  UV origin. RG zero is still; blue/alpha are ignored. Use float textures for negative
  values. No 0.5 bias, color conversion, premultiplication or media fitting is applied.
- Any source resolution fills normalized canvas UV. Manual bilinear interpolation
  samples the field at simulation-cell centers. Wrap repeats field taps; closed modes
  hold its edge values. Cell Size changes the output-pixel size of one velocity unit.
- Each nonfinite channel becomes zero. Finite channels clamp to ±1,000,000 before
  interpolation to bound arithmetic. Strength is a multiplier from 0 to 100.
- Each fixed tick uses displacement `velocity * strength / 60`, bounded by its vector
  length. Max Displacement defaults to 8 cells/tick, ranges from 0 to 64, and zero
  disables displacement. Oversized input slows to this limit. Solver Quality does
  not alter the transport interval.
- Forward order is global scale/rotation/translation, then flow. The pass samples
  velocity at destination centers, backtraces flow, then applies the inverse global
  transform. Scale uses `exp((Grow + axis_scale) * .01 / 60)`; rotation is degrees per
  second, translation is cells per second, and pivot is normalized UV.
- Blank/disabled/zero-strength/zero-velocity input takes the ordinary path exactly.
  Global zero motion also bypasses identity resampling. Pause freezes flow; Step
  advances one tick. These controls cause no reset.

This is first-order semi-Lagrangian transport, not a fluid solver. Bilinear sampling
interpolates all four raw state channels, including signed chroma. Fractional motion
smooths features and is not mass conserving. Domain walls block velocity transport
through partitions, wrap seams and diagonal corners.

Presets now capture 75 settings in eleven groups. Velocity TOP is the fifth optional
binding. Snapshots capture flow settings and the binding, without copying external
velocity textures or producer history. Exact future replay requires identical
per-tick velocity samples. Complete Phase 5 snapshots restore with flow disabled,
strength 1, displacement limit 8, and no velocity binding. Incomplete new flow
metadata is rejected before writes. Snapshot/archive schema remains version 1.

## Validation

Validated on **TouchDesigner 2025.33230, macOS, October 9, 2026**. Other builds are
not claimed. The live probe found no TDAPI component, so parameter names/menu values
were verified against native operator inventories in `parameters.json`; the product
continues to require neither TDAPI nor validation files.

| Evidence | Result |
| --- | --- |
| `report.json` | 159 passing checks: independent CPU diffusion and affine transport references for all boundaries on rectangular/coarse grids; signed flow axes, strength, normalized interpolation, extreme/nonfinite inputs, displacement limits, transform/flow composition, walls/seams/corners, all display filters, preset and snapshot replay, legacy snapshot compatibility, pause/step |
| `frame_report.json` | Seven checks using real parameter edits and a Step pulse across timeline frames |
| `clock_regression/report.json` | 20 Phase 2 checks plus seven 30/60-FPS cases with 42 exact public-output comparisons |
| `phase3_regression/report.json` | 75 Phase 3 checks, including 36 exact public-output comparisons |
| `presets_regression/report.json` | 44 Phase 4 checks |
| `snapshots_regression/report.json` | 104 Phase 5 checks, including disk persistence, movie replay and resize |
| `test_flow_presets.py` | Five offline tests covering all boundary round trips, optional velocity bindings, legacy preset groups/tokens, disabled built-in flow, and invalid boundary refusal |
| Earlier offline suites | 31 preset tests, 15 snapshot tests, seven clock tests |

Zero-velocity equivalence compares **all six public outputs bit-for-bit**, with
and without global transforms, for all three boundaries. Controlled flow replay is
also bit-exact at 30/60 output FPS. CPU affine comparisons use tolerance 3e-5 for
float64 CPU versus float32 GPU trig/exponentiation; diffusion uses 1e-6. Reports
contain source SHA-256 fingerprints. `summary.json` combines integration/regression
results. Historical reports under phases 2–5 are unchanged. The old preset binding
expectation was extended to include Velocity TOP. The Phase 4 live regression retains
the documented Phase 5 deferred-seed-reset adaptation.

`initial_report.json` and `second_report.json` retain initial harness failures: one
fixture crossed an intentional No Flux wall before testing the canvas exterior;
another attempted cross-component wiring, yielding an unconnected reconstruction
shader. A report filter also included a movie Info CHOP as if it were a DAT. The
corrected fixture uses an open domain for the exterior check, wires reconstruction
at the same component level, and inspects only Info DATs. No shader assertions were
relaxed to pass these checks.

Reproduce offline:

```sh
python3 validation/phase6/test_flow_presets.py
python3 validation/phase4/test_presets.py
python3 validation/phase5/test_snapshots.py
python3 validation/phase2/test_clock.py
```

Reproduce live from Textport with `/project1` and timeline playback enabled (update
ROOT in scripts for another checkout):

```python
ROOT = '/absolute/path/to/turing-patterns'
exec(compile(open(ROOT + '/validation/phase6/probe_td.py').read(), 'phase6_probe', 'exec'))
exec(compile(open(ROOT + '/validation/phase6/run_td.py').read(), 'phase6', 'exec'))
```

Wait for `PHASE6_COMPLETE True`, then run:

```python
exec(compile(open(ROOT + '/validation/phase6/run_frames_td.py').read(), 'phase6_frames', 'exec'))
exec(compile(open(ROOT + '/validation/phase6/regressions_td.py').read(), 'phase6_regressions', 'exec'))
```

Wait for `PHASE6_FRAMES_COMPLETE True` and `PHASE6_ALL_COMPLETE True`. These create
separate components without saving/overwriting the TOE or existing components.
The snapshot regression copies the controlled movie fixture from Phase 5. All
ordinary transport runs on the GPU; NumPy is used only by validation and the
existing manual snapshot/resize workflow.

API references: [GLSL TOP](https://derivative.ca/UserGuide/GLSL_TOP),
[integer texture addressing](https://derivative.ca/UserGuide/Write_a_GLSL_TOP),
[Script TOP](https://derivative.ca/UserGuide/Script_TOP).
