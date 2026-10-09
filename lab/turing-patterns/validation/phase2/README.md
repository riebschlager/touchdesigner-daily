# Phase 2 — consistent simulation clock

Implemented in `../../create_turing_media_v2.py`, still a standalone Text DAT
builder. `create_turing_media.py` remains unchanged. All six public output names
and unique component naming are preserved.

## Clock contract

- Fixed tick: **1/60 simulation second**, referenced to V1 at **60 FPS** with
  16 updates and chemistry timestep 1 per tick.
- **Real Time** accumulates monotonic wall time multiplied by Speed. Default
  maximum catch-up is four ticks per output frame. Remaining time is retained
  and displayed as Simulation Lag; it is never silently discarded.
- **Frame Stepped** advances Speed / Render FPS seconds per output frame.
  Fractional ticks accumulate, and every required tick executes regardless of
  the real-time cap. Slow rendering does not change simulated age.
- **Solver Quality** 1–4 gives 16–64 substeps per tick, with chemistry timestep
  1–0.25. Quality changes accuracy and GPU cost, independently of Speed.
- **Pause** freezes chemistry, carried color, palette, and sampled motion history.
  **Step** advances exactly one tick while paused, including at Speed zero.
  Live previews/overlay and externally controlled media can continue playing.
- Transforms apply once after each tick's solver. Injection, recovery, dye
  spreading/injection/decay, and palette smoothing use exponential time conversion.
- Reset clears GPU caches before initialization, including after dimension changes.
  Reset preserves Pause, resets simulation time/debt, and refreshes media/palette
  history. Clock-mode changes clear debt while preserving simulation state.

Source samples are part of the deterministic input. Ordinary movies and live
sources provide their currently available image to each tick; Frame Stepped
alone does not seek or resample a movie. An optional `sample(component, tick,
seconds)` callback to `clock.module.advance()` can supply controlled per-tick
images for offline replay. Movie-position restoration remains later-phase work.

## GPU execution prototype

Three approaches were considered: repeated Feedback TOP cooks, a fixed chain
of staged GLSL ticks, and explicit GPU ping-pong. The fixed chain would impose
a tick-count ceiling or require network reconstruction. Explicit ping-pong
supports arbitrary deterministic tick counts with a small fixed network.

The live prototype also tested ordinary Cache TOP active capture. Repeated
forced cooks within one TD frame did **not** advance that cache. Alternating
two caches with **Replace Single** enabled only during the explicit capture
correctly executed twelve dependent updates in one frame. The result includes
negative blue/alpha values, verifying signed state preservation. See
`prototype_td.py` and `prototype.json`.

The product uses RGBA32F cache pairs for state, palette, and sampled media.
Automatic cache cooking/capture is disabled. No CPU texture readback or external
Python packages are used by the product. NumPy readback is used only in validation.

## Recorded validation

**Passed on TouchDesigner 2025.33230, macOS.** Other builds are not claimed.

`report.json` records seven 30/60 FPS comparison cases, each advancing two
simulation seconds (120 ticks). All **42 output comparisons were pixel-exact**;
the acceptance tolerance was maximum absolute channel error **1e-6**.

| Cases | Coverage |
| --- | --- |
| Coral, dividing spots | No media, square canvas |
| Fixed, source tint, clip palette, carried color | Changing, partially transparent source supplied per tick; rectangular canvas and coarse grid; growth, nonuniform scale, rotation, translation |
| Motion mask | Same controlled moving source and transforms, with per-tick motion history |

All cases evolve, remain finite, and keep A/B within [0, 1]. Additional checks
cover exact paused chemistry/palette/media history, Step and its actual custom
parameter pulse, zero Speed, reset-to-seed, uniform empty-field stability,
fractional ticks, retained real-time lag, and uncapped deterministic work.
At Quality 1/2/4, elapsed time remains equal and signed carried-color decay
matches its analytic exponential within 1e-6. All GLSL shaders compile, with no
unexpected operator errors.

`frames.json` separately records **real timeline playback**, with the clock's
Execute DAT enabled: 30 output frames at Render FPS 30 and 60 at Render FPS 60
both execute 60 ticks, yielding pixel-exact state and palette. Ten paused frames
with repeated output recooks preserve state. Step advances once; Reset restores
the exact seed and zero age; resizing while paused produces the new seed at the
correct dimensions. Setup notifications settle before the measured epochs.

The pure-Python scheduler suite has seven tests covering multiple output rates
and speeds, jitter, retained backlog, deterministic work, fractional ticks, and
callback syntax. Phase 1 reports remain historical V1-parity evidence; Phase 2
intentionally changes both controls and network structure.

## Reproduce

From this directory's project root:

```sh
python3 validation/phase2/test_clock.py
```

In TouchDesigner Textport, with `/project1` and timeline playback enabled:

```python
PHASE2_ROOT = '/absolute/path/to/turing-patterns'
exec(compile(open(PHASE2_ROOT + '/validation/phase2/prototype_td.py').read(), 'prototype_td.py', 'exec'))
exec(compile(open(PHASE2_ROOT + '/validation/phase2/build_td.py').read(), 'build_td.py', 'exec'))
phase2_test = phase2_host.create(textDAT, 'validate')
phase2_test.text = (ROOT / 'validation/phase2/validate_td.py').read_text()
phase2_test.module.start(phase2, str(ROOT / 'validation/phase2'))
```

Wait for `PHASE2_COMPLETE True`, then run:

```python
phase2_frames = phase2_host.create(executeDAT, 'frame_validation')
phase2_frames.par.active = False
phase2_frames.text = (ROOT / 'validation/phase2/frames_td.py').read_text()
phase2_frames.module.start(phase2, str(ROOT / 'validation/phase2'))
```

Wait for `PHASE2_FRAMES True`. Use a fresh build for each complete comparison
run. The scripts create validation components; they do not save/overwrite a TOE.
The fixtures leave the tested component paused with its clock DAT disabled.

## Migration

The generated component's embedded `README` contains the complete control guide.
Useful conversions from V1 at 60 FPS:

| Old control | New value |
| --- | --- |
| Passes × Timestep | Speed = old product / 16 |
| Running | Pause = inverse |
| Per-frame blend p | Rate = −60 ln(1−p) per second |
| Per-pass color spread p | Rate = −960 ln(1−p) per second |
| Palette retention s | Smoothing time = −1 / (60 ln(s)) seconds; s=0 → 0 |
| Translation / rotation | Multiply per-frame value by 60 |
| Grow / scale p percent per frame | Continuous percent/second = 6000 ln(1+p/100) |

Finite rates approach the injection target exponentially. Rate 600 approximates
old full injection. Partial mask/alpha now multiplies the rate inside the
exponent, so intermediate masks can differ from V1 even at the reference FPS.

API references:
[Cache TOP](https://derivative.ca/UserGuide/Cache_TOP),
[GLSL TOP](https://derivative.ca/UserGuide/GLSL_TOP),
[Execute DAT](https://derivative.ca/UserGuide/Execute_DAT),
[Parameter Execute DAT](https://derivative.ca/UserGuide/Parameter_Execute_DAT).
