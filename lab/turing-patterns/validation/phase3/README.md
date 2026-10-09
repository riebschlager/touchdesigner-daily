# Phase 3 — independent media influence

Implemented in `../../create_turing_media_v2.py`, still one standalone script
for a TouchDesigner Text DAT. V1 is unchanged; all six public outputs and unique
component naming remain. The embedded component README describes every control.

## Controls and behavior

| Influence Mode | Chemical behavior |
| --- | --- |
| Continuous Seed (default) | Existing time-based concentration-target blend toward A=.5/B=.25 every tick; Injection Rate controls strength. |
| Stamp Once | Press **Stamp Current Mask** to blend the live mask into current state exactly once. Stamp Amount is a direct 0–1 blend, independent of speed and solver quality. Selecting the mode or resetting does not stamp. |
| Chemistry Map | Map the selected influence mask into explicit feed/kill ranges; blend with uniform Turing Feed/Kill. No concentration injection. |

Stamp works while paused, without advancing age or media/palette history. It
preserves signed carried color. Step/resume lets the stamped chemistry evolve.
Repeated presses intentionally stamp again. For Motion masks, the live stamp
compares the current source with the last clock-sampled source.

Chemistry uses mask value `m` in [0,1]:

```text
mapped_feed = lerp(Feed Minimum, Feed Maximum, m)
mapped_kill = lerp(Kill Minimum, Kill Maximum, m)
local_rates = lerp(uniform_rates, mapped_rates, Chemistry Map Blend * source_alpha)
```

Descending ranges are supported. Transparent or missing sources retain uniform
chemistry. Blend=0 restores uniform chemistry. The mask already includes source
alpha according to its selected mode; the chemistry blend also uses alpha to
retain baseline rates outside the media.

Recovery Rate remains independent in all modes. Color > **Carried Color Source**
selects Source Alpha (default) or Influence Mask, with independent Color Injection
Rate. Carried color continues to inject during ticks in all chemical modes; set
its rate to zero when independent color evolution is wanted after stamping.

## Domain contract

Domain > **Domain Mask TOP** is separate from media influence and supports every
mode. Blank permits the full canvas. Red is sampled nearest at simulation-cell
centers in normalized canvas UV, optionally inverted, then thresholded. Alpha
is ignored; media fitting does not affect it. `value >= threshold` is open.
Make walls at least one simulation cell thick; coarse grids can miss small
features. `domain_mask` is an internal binary preview at simulation resolution.

Blocked cells are always A=1/B=0/colorless:

- **No Flux:** blocked stencil neighbors substitute the center cell, preventing
  chemical and color diffusion across the interface.
- **Empty Exterior:** blocked neighbors substitute empty state, creating a sink.
- Diagonal stencil taps require both orthogonal cells open, preventing leakage
  through blocked corners.
- Seeds, reset, continuous injection, stamps and transforms respect the domain.
- Every contributing transform interpolation tap checks a conservative supercover
  path through crossed cells. Blocked paths retain the destination in No Flux,
  or restore it empty in Empty Exterior. Paths exceeding 1024 cell crossings
  per tick are conservatively rejected. Near walls, transport may retain/erase
  state instead of sliding along the wall. This check adds GPU cost.
- Wrap repeats the domain across canvas seams. With a domain assigned, Clear
  treats out-of-canvas cells as blocked and Domain Boundary governs that interface.
  Without a domain, the inherited Phase 2 canvas-edge behavior is retained.
- Domain changes preserve time/state and apply on the next Step, tick, Stamp,
  or Reset. They do not mutate state merely because a viewer cooks while paused.

Confinement affects raw state, not output opacity. Coarse display reconstruction
can visually soften the boundary; Clip Patterns to Alpha still clips display only.
Complete canvas-edge unification remains Phase 6.

The GLSL TOP supports three inputs, so the internal `influence_field` packs
influence into R and domain into G at simulation resolution. Its influence
sampling preserves the existing nearest-at-cell-center behavior. Diffusion now
sums weighted neighbor differences, mathematically the same nine-cell stencil
but exactly stable for uniform fields. Floating-point rounding can differ from
Phase 2, especially after long nonlinear evolution.

## Recorded validation

**Passed live on TouchDesigner 2025.33230, macOS.** Other builds are not claimed.

`report.json` records **75 passing checks**, including:

- Exact one-shot live-mask blending, partial Stamp Amount, paused stamping,
  evolution after stamping stops, no automatic re-stamping, and actual pulse callbacks.
- Local feed/kill results against a CPU integration oracle, reversed ranges,
  fractional blend/alpha, zero blend, transparent and absent-source baselines.
- Ambient seed confinement and blocked-state enforcement across all three modes,
  both domain interfaces, and Wrap/Clear canvas edges.
- Active chemical and signed-color fixtures: **zero leakage** through a one-cell
  wall during diffusion and 240 cells/second translation; blocked diagonal corners.
- No Flux conservation of a pure diffusion field; Empty Exterior loss at the interface.
- Independent color injection and mask gating; rectangular coarse-grid domain inversion.
- Six controlled 30/60 FPS comparisons (three influence modes × two color sources),
  with transforms, changing media and confinement: all **36 public-output comparisons
  pixel-exact**, acceptance tolerance 1e-6. State is finite and A/B are bounded.
- Every product shader compiles, with no unexpected operator errors.

`clock_regression/report.json` reruns the existing Phase 2 suite on a fresh Phase 3
build: seven cases, all **42 public-output comparisons pixel-exact**, plus pause,
Step, fractional ticks, catch-up, reset, uniform empty stability and quality checks.
The pure-Python scheduler suite also passes all seven tests.

## Reproduce

Run the scheduler checks from the project root:

```sh
python3 validation/phase2/test_clock.py
```

In TouchDesigner Textport with `/project1` and playback enabled:

```python
PHASE3_ROOT = '/absolute/path/to/turing-patterns'
exec(compile(open(PHASE3_ROOT + '/validation/phase3/build_td.py').read(), 'build_td.py', 'exec'))
phase3_test = phase3_host.create(textDAT, 'validate')
phase3_test.text = (ROOT / 'validation/phase3/validate_td.py').read_text()
phase3_test.module.start(phase3, str(ROOT / 'validation/phase3'))
```

Wait for `PHASE3_COMPLETE True`, then run:

```python
exec(compile(open(PHASE3_ROOT + '/validation/phase3/regression_td.py').read(), 'regression_td.py', 'exec'))
```

Wait for `PHASE2_COMPLETE True`. Each complete run should use fresh builds. Test
fixtures require TouchDesigner's bundled NumPy for readback; the product does not.
The scripts create validation components, preserve existing components, and do
not save or overwrite a TOE. TDAPI is absent in the tested project, so parameter
names were verified against live inventories (`parameters.json`), retaining the
standalone-builder requirement.
