# Phase 1 baseline

Historical baseline: current V2 implements Phase 2 and intentionally no longer
matches this phase's source/structure assertions. Use `../phase2` for current
validation; retain these captures as the V1 reference.

**Passed on TouchDesigner 2025.33230, macOS.** V2 reproduces V1 exactly in
12 live cases, with 288 exact floating-point output comparisons. No tolerance
was needed. The unchanged reference file has SHA-256
`35cdaf8e19c849b4316b8678e355b13bc0715a357734440a55c757b975ae0aba`.

The deliverable is `../../create_turing_media_v2.py`. Paste that entire file
into a Text DAT and run it. No validation files, external Python packages,
shader files, or TDAPI component are required. Repeated runs create
`turing_media_v2`, `turing_media_v2_2`, etc. All six output names are retained.

The source is divided into configuration, shared GLSL, simulation shaders,
media processing, display/palette shaders, presets, callbacks, network
construction, and embedded help. Legacy preset clauses are embedded unchanged
into the callback string. The versioned preset system remains phase 4 work.

## Recorded results

| Cases | Configuration |
| --- | --- |
| Coral, dividing spots | No media; 512 × 512; default seed 1 |
| Fixed, source tint, clip palette, carried color | Continuous alpha-mask influence from a colored, partially transparent procedural TOP; clipping enabled |
| Rectangle | 384 × 216 canvas and simulation |
| Coarse smooth, linear, nearest | 384 × 216 canvas; 96 × 54 simulation; Cell Size 4 |
| Transform wrap, clear | Growth/shrink, rotation, and translation together |

Every case uses 16 passes per frame, timestep 1, and 180 evolving project
frames. The harness schedules each tick on a separate frame; it does not
simulate elapsed frames by repeatedly forcing Feedback TOP cooks in one frame.
The initial seed and palette feedback are held in reset during setup, then
released together. Each case captures all six outputs at initialization,
after evolution, after 10 paused frames, and after reset while paused.

- All outputs match exactly between V1 and V2, including raw signed carried
  color channels. Captures use float NumPy arrays, not alpha-converted images.
- All cases evolve, remain finite, and keep chemical concentrations in [0, 1].
- Pause preserves the complete state exactly, including when transforms are enabled.
- Reset while paused restores the seed exactly.
- All operator names, types, input wiring, built-in parameters/expressions,
  custom parameter definitions/defaults, and menus match.
- A second V2 build creates a distinct component without overwriting the first.
- All nine GLSL TOPs compile successfully. No unexpected operator errors occur.
- V1's blank, unselected Movie File In TOP reports its existing empty-file
  diagnostic in both builds. The transparent fallback branch renders correctly;
  this inherited diagnostic is recorded separately rather than hidden.

`comparison.json` contains the comparison results. `structure.json` records the
live networks and parameter definitions. `parameters.json` records parameter
availability in the target build. `v1/report.json` and `v2/report.json` include
settings, shader compiler messages, dimensions, and state checks. PNGs in those
directories are visual references; the corresponding lossless `.npz` captures
are retained locally and excluded from Git because of their size.

## Reproduce

Run the source-preservation check from the project directory:

```sh
python3 validation/phase1/check_source.py
```

For the live comparison, use a fresh TouchDesigner project with `/project1`
and timeline playback enabled. In Dialogs → Textport and DATs, set the source
directory and build the reference:

```python
PHASE1_ROOT = '/absolute/path/to/turing-patterns'
exec(compile(open(PHASE1_ROOT + '/validation/phase1/probe_td.py').read(), 'probe_td.py', 'exec'))
capture = host.create(textDAT, 'capture')
capture.text = (ROOT / 'validation/phase1/capture_td.py').read_text()
capture.module.start(baseline, str(ROOT / 'validation/phase1/v1'))
```

Wait for `PHASE1_CAPTURE_COMPLETE`, then run:

```python
exec(compile(open(PHASE1_ROOT + '/validation/phase1/build_v2_td.py').read(), 'build_v2_td.py', 'exec'))
```

Wait for the second `PHASE1_CAPTURE_COMPLETE`, then compare:

```python
exec(compile(open(PHASE1_ROOT + '/validation/phase1/compare_td.py').read(), 'compare_td.py', 'exec'))
```

The capture helper uses NumPy bundled with TouchDesigner. The product builder
uses only TouchDesigner's native API. Capture components are left in the test
project; existing `.toe` files are never overwritten by these scripts.

These checks establish V1 parity in the stated build. They do not establish
frame-rate independence, movie decoding/restart behavior, motion-cache
correctness, or compatibility with untested TouchDesigner builds. Those areas
remain subject to the later phases of `update-plan.md`.

API references used for the harness:
[delayed run scheduling](https://docs.derivative.ca/Run_Command_Examples) and
[TOP float readback](https://docs.derivative.ca/TOP_Class).
