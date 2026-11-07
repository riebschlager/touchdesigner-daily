# GPU Fluid Solver

`create_fluid_solver.py` builds a portable TouchDesigner **2D incompressible dye solver**. All Python and GLSL are embedded in the builder and resulting component. Requires no pip packages or external shader files. NumPy is supplied by TouchDesigner. Tested on TouchDesigner **2025.33230, macOS**.

This is ink moving through a filled 2D fluid domain. It does not model a water surface, splashes, liquid particles, or 3D fluid volumes.

## Run

1. Create a Text DAT in your destination network.
2. Paste `create_fluid_solver.py` into it and choose **Run Script**.
3. Select the new `fluid_solver` Base COMP. Play the timeline and view `out1`.
4. Edit **Sources → X / Y / Dye Red / Green / Blue**, or connect a CHOP to the component's input.
5. Save as a `.tox` to reuse. A prebuilt `fluid_solver.tox` is included.

Each builder run creates a new component, preserving existing operators. You can also run it from a Text DAT with:

```python
exec(compile(open('/absolute/path/create_fluid_solver.py').read(), 'fluid', 'exec'))
```

Construction verifies required parameters and compiles every shader before enabling the clock. If a build fails, the partial component remains for inspection. TDAPI helpers are used when installed; the builder falls back to the same native operator APIs as the other project scripts.

## Source inputs

Use the component's CHOP input, or assign **Position / Source CHOP**. The parameter binding takes precedence over the wire. With neither, the scalar custom parameters supply one dropper. Inputs are sampled once per simulation tick.

Two CHOP layouts are supported:

- **Sample arrays:** `x` and `y` with N samples describe N simultaneous droppers. `r/g/b` can have N samples, or one sample broadcast to every dropper. A channel with one sample also broadcasts for positions and other optional attributes.
- **Numbered channels:** `x0/y0`, `x1/y1`, etc. Each pair can have one or more samples. Numeric suffixes are sorted numerically. Use `r0/g0/b0`, etc. for individual colors, or shared unsuffixed `r/g/b` channels. Total droppers across all pairs is limited to 64.

For multiple sample droppers, the samples are a list of simultaneous positions, **not a time slice of one moving dropper**. Use a single current sample per dropper for streamed tracking data. Sample ordering and numbered IDs must remain stable to derive motion correctly.

Optional **Color CHOP** overrides colors only, leaving positions and other attributes on the source CHOP. It accepts the same RGB names and broadcasting rules. Missing RGB channels use the scalar color parameters. RGB is linear, nonnegative, and may exceed 1 for HDR.

| Channel | Meaning | Missing-channel fallback |
| --- | --- | --- |
| `x`, `y` | Position; normalized coordinates by default | Scalar X/Y only when no source CHOP is assigned |
| `r`, `g`, `b` | Dye RGB | Scalar Red/Green/Blue |
| `radius` | Circular radius, fraction of domain height | Radius parameter |
| `amount` | Nonnegative dye-rate multiplier | 1 |
| `active` | Source weight, clamped to 0–1 | 1 |
| `vx`, `vy` | Source acceleration in height units/s² | Jet X/Y |

`vx/vy` describe force input; they do not replace the velocity field. Source motion adds acceleration separately. A zero `amount` stirs without adding dye. A zero `active` disables dye and force for that dropper. **Emit** disables all dropper dye and force, while existing flow, wind, buoyancy, and vorticity continue.

Position coordinates use a **bottom-left origin**, with positive Y upward. UV coordinates run from 0 to 1. Pixel mode maps `0..Width-1` and `0..Height-1` across the domain. Radius always remains a fraction of domain height. Closed boundaries clamp source positions; periodic boundaries wrap them. Malformed channel layouts, more than 64 droppers, nonfinite values that reach the parser, and incompatible sample counts raise an error. TouchDesigner itself may sanitize NaN CHOP samples to zero before the parser sees them. The automatic clock pauses on an input error and records it in **Status**; fix the input and unpause.

### Examples

Single dropper: connect a Constant CHOP with channels `x=.3`, `y=.4`, `r=1`, `g=.15`, `b=.05`. Animate X/Y to stir.

Three droppers: supply these arrays in a Script CHOP:

```python
def onCook(o):
    o.clear()
    o.numSamples = 3
    for name, values in [('x', [.25, .5, .75]), ('y', [.25, .3, .25]),
                         ('r', [1, .05, .1]), ('g', [.1, 1, .3]),
                         ('b', [.05, .25, 1])]:
        o.appendChan(name).vals = values
```

A separate RGB Constant CHOP assigned to **Color CHOP** recolors all three using one RGB triplet.

## Four-dropper CHOP demo

Load **`fluid_demo.tox`**, or paste **`create_fluid_demo.py`** into a Text DAT and Run Script. The demo builder is self-contained and embeds the current solver builder. Each run preserves existing networks and creates a new `fluid_demo` component.

Enter the component to see this native CHOP network:

```text
dropper_1_coral  ─┐
dropper_2_cyan   ─┼─ merge_droppers → DROPPERS → fluid_solver → out1
dropper_3_gold   ─┤
dropper_4_violet ─┘
```

Each colored **Constant CHOP** has one sample per channel. The first emits `x0/y0/r0/g0/b0/radius0/amount0/active0`; the others use suffixes `1`, `2`, and `3`. Merging preserves those distinct names, giving the solver four independent droppers. Inspect the X/Y value expressions on each Constant CHOP to see exactly how motion becomes CHOP channels. No export flags or hidden external source bindings are needed: `DROPPERS` is wired directly to the solver's CHOP input.

Select the outer **fluid_demo** component:

- **Demo** controls Pause, Simulation Speed, Dropper Motion Speed, Reset, Step, and Clear Dye.
- **Dropper 1–4** pages control each source's RGB, enable, orbit center, width/height, X/Y frequency, phase, radius, and amount.
- Dropper motion uses the nested solver's **simulation time**, so pause freezes both, Step advances both, and Reset returns the fluid and orbits to their starting positions. Dropper Motion Speed changes only the orbit rate; Simulation Speed changes the fluid clock and source motion together.

The source CHOPs use smooth Lissajous orbits. Motion-driven force stirs the dye; Jet X/Y are zero. Select the nested `fluid_solver` for its full simulation and appearance controls. Replace a dropper Constant CHOP with any tracker, LFO, MIDI, or OSC CHOP carrying the same channel names to supply your own control. Read the internal `READ_ME` DAT for a compact explanation.

The outer outputs match the solver: `out1` is display, `out2` is raw dye, and `out3` is signed UV velocity. Saving/loading the demo TOX preserves controls and relative wiring; fluid history restarts on load.

The demo passed **22 live GPU/CHOP checks** on TouchDesigner 2025.33230, including four independent RGB injections, motion, pause/step/reset, individual enable/color edits, and TOX reload. See `validation/demo_validation.json`, `validation/validate_demo_td.py`, and `validation/demo_preview.png`.

## Parameters

### Simulation

| Parameter | Default | Effect |
| --- | --- | --- |
| Grid Width / Height | 384 / 256 | Solver and output resolution, 32–2048 per axis. Changes reset all state. |
| Tick | 1/60 s | Fixed simulation interval. |
| Speed | 1 | Simulation seconds per clock second. Zero holds the simulation. |
| Substeps per Tick | 2 | Divides each tick into 1–8 full fluid solves. More improves fast-flow accuracy. |
| Pressure Iterations | 50 | Weighted Jacobi iterations per substep; 4–200. More reduces residual divergence. |
| Clock | Frame Stepped | Frame mode adds Speed / Frame Clock FPS seconds per played application frame. Real Time adds elapsed monotonic time × Speed. |
| Frame Clock FPS | 60 | Assumed render rate in frame mode; does not configure the project FPS. |
| Max Ticks per Frame | 2 | Limits work in either clock mode; unprocessed time remains as debt. |
| Boundary | Closed / Free Slip | Closed walls enforce zero normal velocity and allow tangential slip. Periodic joins opposite edges. Changing this resets state. |
| Pause | Off | Holds velocity, dye, source history, and age. Appearance can still change. |
| Step One Tick | Pulse | Advances one complete tick while paused, independent of Speed. |
| Reset All | Pulse | Clears velocity, dye, pressure, time debt, and source motion history. |
| Clear Dye | Pulse | Clears dye while preserving velocity and age. |

The clock updates at most once per application frame and only while the timeline plays. Viewer recooks never advance the simulation. Pause/resume and clock/speed/tick changes rebase timing and clear old debt. Playback resumes without catching up the stopped interval. Reset on TOE/TOX load initializes GPU textures; saving a component preserves controls and code, not a resumable fluid snapshot.

### Sources

| Parameter | Default | Effect |
| --- | --- | --- |
| Position / Source CHOP | Blank | Overrides wired source input. |
| Color CHOP | Blank | Optional separate RGB input. |
| Position Coordinates | Normalized | UV or grid-pixel positions. |
| Emit Dye and Source Force | On | Global dropper enable. |
| Dropper X / Y | .5 / .25 | Scalar source position; parameter range supports pixels, slider range is 0–1. |
| Dye Red / Green / Blue | .08 / .5 / 1 | Scalar linear RGB. |
| Radius | .045 | Fraction of height; aspect-correct circular source. |
| Dye Density / Second | 12 | Density injected per second at the source center, before per-source amount. |
| Jet X / Y | 0 / 1 | Stationary jet acceleration, height units/s². |
| Motion Force Gain | 8 | Acceleration = source speed × gain; gain has units 1/s. |
| Max Source Acceleration | 20 | Caps combined jet and motion acceleration before splat weighting. |
| Teleport Distance | .35 | Motion longer than this in one sample resets its history and deposits at the new position. |

Sources use smooth, compact Gaussian splats along the line between previous and current positions. Periodic motion follows the shortest wrapped displacement. New, re-enabled, rebound, or resumed droppers initialize without a motion impulse. Source force and injection scale with the substep time; increasing substeps does not multiply their rates. A moving swept source is an artistic brush approximation, not a conservative particle emitter.

### Fluid

| Parameter | Default | Effect |
| --- | --- | --- |
| Velocity Decay | .12 | Exponential velocity damping, 1/s. |
| Kinematic Viscosity | 0 | Implicit diffusion, height units²/s; zero skips the solve. |
| Viscosity Iterations | 20 | Jacobi iterations per substep when viscosity is positive. |
| Vorticity Confinement | 12 | Restores small swirling motion lost to numerical dissipation. |
| Density Buoyancy | .2 | Vertical acceleration per dye density; negative makes ink sink. |
| Wind X / Y Acceleration | 0 / 0 | Uniform body acceleration, height units/s². Closed walls project away uniform flow normal to the walls. |
| Max Speed | 2 | Caps velocity magnitude before projection, height units/s. Projection can locally change the magnitude afterward. |
| Dye Decay | .2 | Exponential dye-density and RGB decay, 1/s. |
| Maximum Dye Density | 20 | Density cap, with proportional RGB scaling to preserve hue. |
| Dye Advection | Limited MacCormack | Higher detail with a local extrema limiter, or cheaper semi-Lagrangian transport. |

### Appearance and Diagnostics

Exposure multiplies the mean dye color; Density to Opacity converts density to opacity with `1-exp(-density*opacity)`. Transparent outputs use **premultiplied RGB**. Otherwise dye composites over Background R/G/B. View selects Dye, Density, Velocity, or signed Divergence. All outputs retain floating point values.

Diagnostics report completed Simulation Seconds, retained Time Debt, source count, and Status. Persistent time debt means the requested clock is faster than the machine can solve. Reduce resolution, iterations, substeps, or dropper count, or lower Speed.

## Outputs and network

| Output | Content |
| --- | --- |
| `out1` | Display RGBA, controlled by Appearance and View. |
| `out2` | Raw dye: RGB are accumulated color densities; A is total dye density, not opacity. Divide RGB by A for the mean color. |
| `out3` | Reconstructed cell-centered signed UV velocity/second in RG; B=0, A=1. Multiply by elapsed seconds for UV displacement. |

Internal `velocity_read` stores a staggered MAC field: R is the right-face velocity and G the top-face velocity for each cell, in domain-height units/second. Domain height is 1, width is Width/Height, and cell spacing is `1/Height`. Internal pressure is a projection potential, not calibrated physical pressure. `divergence` shows the current post-projection divergence; `div_buffer` is the pre-projection field.

Each substep performs:

1. RK2 semi-Lagrangian staggered velocity advection and exponential drag.
2. Curl evaluation, confinement, buoyancy, wind, and dropper acceleration.
3. Optional implicit viscosity diffusion.
4. MAC divergence, weighted Jacobi pressure solve, and pressure-gradient subtraction.
5. RK2 dye transport; optional reverse pass and limited MacCormack correction.
6. Dye decay and swept source injection.

All full-grid calculations remain in GLSL TOPs and RGBA32F GPU caches. The CPU only schedules passes and uploads a 64×4 source texture. There is **no GPU-to-CPU readback during normal simulation**. Explicit inactive-cache ping-pong supports multiple substeps per frame; feedback is not tied to viewer cooks. Fourth shader inputs use the GLSL TOP's TOPs parameter because this build has three wired inputs.

## Accuracy and performance

The staggered divergence/gradient pair uses the same discrete Laplacian as the pressure solver. Weighted Jacobi avoids the alternating mode of undamped Jacobi on even periodic grids. The finite iteration budget leaves residual divergence; this is a visual real-time solver, not a converged CFD package. Very viscous cases may require more diffusion iterations.

For transport accuracy, aim for roughly **1–2 cells of displacement per substep**: `speed × Height × Tick / Substeps`. The default maximum-speed setting is a guard against strong forces, not an adaptive CFL guarantee. Reduce the tick, increase substeps, or reduce forcing when motion crosses many cells. MacCormack reduces diffusion but does not conserve total dye mass exactly. No obstacle-mask or free-surface boundary system is included.

A substep uses approximately `Pressure Iterations + 8` full-grid passes with MacCormack, plus optional viscosity iterations and GPU cache copies. Cost grows with pixels, pressure iterations, substeps, and sources. Start at the supplied grid; 2048² and 64 emitters is a supported input range, not a real-time performance promise. Pixel shaders were chosen for portability across TouchDesigner's GPU backends. Multigrid/PCG, adaptive GPU timestep reduction, cut-cell obstacles, and free surfaces would be separate extensions.

Numerical references: [NVIDIA GPU Gems fluid projection](https://developer.nvidia.com/gpugems/gpugems/part-vi-beyond-triangles/chapter-38-fast-fluid-dynamics-simulation-gpu), [GPU Gems 3 limited MacCormack transport](https://developer.nvidia.com/gpugems/gpugems3/part-v-physics-simulation/chapter-30-real-time-simulation-and-rendering-3d-fluids), and [Derivative GLSL TOP interfaces](https://derivative.ca/UserGuide/GLSL_TOP).

## Validation

`validation/validate_td.py` runs GPU behavioral checks inside TouchDesigner. Load it into a Text DAT and call its module:

```python
op('validator').module.validate(op('fluid_solver'), '/absolute/output/directory')
```

The validator changes parameters and creates source fixtures beside the component; use a test copy. It leaves the component paused and produces `validation.json` and `preview.png`. Checks cover pressure reduction, closed walls, dye limiting, reset/pause, scalar/sampled/numbered sources, separate RGB broadcast, source motion/teleport handling, both advection modes, viscosity, clocks, periodic boundaries, resizing, and shader/operator errors. Recorded results and a TOX reload check are in `validation/`.

Additional validators use the same `module.validate(component, output_directory)` interface: `validation/edge_cases_td.py` checks wired input and malformed source data; `validation/portability_td.py` saves and reloads a test TOX. Run each on a fresh test copy with the default scalar source. The core suite recorded 23 passing checks, source edge cases recorded 4 passing checks, and the reloaded component advanced for 12 simulation seconds under its automatic clock without operator errors.
