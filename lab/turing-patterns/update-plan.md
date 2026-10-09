The new version should be **`create_turing_media_v2.py`**, with `create_turing_media.py` retained as the reference implementation. V2 should remain a single file that can be pasted into a TouchDesigner Text DAT and run without external Python packages or shader files.
 
1. **Establish the V2 structure and baseline**

   Copy the current implementation into the new file and organize it into clearly separated sections: configuration, shared GLSL, simulation shaders, media processing, display, callbacks, presets, network construction, and embedded help.

   Preserve the existing output names: `out1`, `patterns`, `mask_preview`, `source_preview`, `palette`, and `state`. Create a uniquely named `turing_media_v2` component on each run.

   Before changing behavior, capture reference results for:
   - Coral and dividing spots without media.
   - Continuous media influence with transparency.
   - All four color modes.
   - Rectangular canvases and coarse simulation grids.
   - Transform, pause, and reset behavior.

   **Completion criterion:** the initial V2 build reproduces the current network and runs without shader or parameter errors in the target TouchDesigner build.

2. **Introduce a consistent simulation clock**

   **Implemented and live-validated** in `create_turing_media_v2.py` on TouchDesigner 2025.33230 (macOS). See `validation/phase2/README.md` for the clock contract, migration units, reproducible checks, and controlled-source limitations. All 30/60 FPS comparisons are pixel-exact (acceptance tolerance 1e-6).

   Replace the mixture of per-pass and per-frame controls with an explicit simulation clock.

   | Control | Intended behavior |
   |---|---|
   | Clock Mode | Real Time or Frame Stepped |
   | Speed | Controls elapsed simulation time |
   | Solver Quality | Controls substep size, independently of speed |
   | Render FPS | Defines time advanced per output frame in Frame Stepped mode |
   | Pause | Freezes all evolving simulation state |
   | Step | Advances one simulation tick while paused |

   Use a fixed tick interval and bounded numerical substeps. The existing default—16 updates with timestep 1 per frame—should provide the reference behavior at a documented reference frame rate.

   Express injection, recovery, dye decay, palette smoothing, and transform rates in time-based units. Use exponential conversion for blending and decay rather than multiplying blend percentages directly by elapsed time. Apply transforms at a defined tick boundary.

   First prototype how TouchDesigner executes multiple simulation ticks in one rendered frame. Verify state advancement explicitly; do not assume repeatedly forcing a Feedback TOP to cook advances its history correctly. If necessary, implement staged GLSL passes or explicit texture ping-pong.

   Cap real-time catch-up work and expose simulation lag. Deterministic rendering must advance every required tick.

   **Completion criterion:** equivalent time and source samples produce consistent results at 30 and 60 output FPS within a defined tolerance. Increasing solver quality does not intentionally accelerate growth.

3. **Expand media influence into independent controls**

   **Implemented and live-validated** in `create_turing_media_v2.py` on TouchDesigner 2025.33230 (macOS). Includes Continuous Seed, an explicit Stamp Current Mask pulse, Chemistry Map with feed/kill ranges and alpha-weighted blend, independent Domain Mask TOP with No Flux/Empty Exterior interfaces, and selectable carried-color injection source. See `validation/phase3/README.md` for behavior, boundary contracts, reproducible checks, and recorded results.

   Add an Influence Mode menu:

   | Mode | Behavior |
   |---|---|
   | Continuous Seed | Applies the existing concentration-target blend using time-based strength |
   | Stamp Once | Applies the current mask once, then allows independent evolution |
   | Chemistry Map | Maps media values into local feed and kill rates |

   Give Chemistry Map explicit feed/kill ranges and a blend amount. Keep uniform feed/kill values as the baseline.

   Add a separate **Domain Mask** input for confining the simulation, so confinement can be combined with any influence mode. Define whether its boundary blocks diffusion or restores the outside to empty chemical state. Prevent stencil samples from transporting chemicals through blocked boundaries.

   Add a Carried Color Source option: source alpha or the influence mask. Preserve independent color injection strength.

   **Completion criterion:** a stamped shape evolves after stamping stops; chemistry maps produce spatially different behavior; confined simulations do not leak through impermeable boundaries.

4. **Add complete presets and a Feed/Kill explorer**

   Replace hard-coded preset callbacks with an embedded, versioned preset table.

   A preset should capture chemistry, seed, simulation dimensions, timing, influence, transforms, and display/color settings. Treat external media paths and TOP references as optional bindings so presets remain portable.

   Provide:
   - Apply Preset.
   - Apply Preset and Reset.
   - Save Current Preset.
   - Import/Export Presets.
   - An optional Feed/Kill XY panel with curated example thumbnails.

   Generate thumbnail examples using a fixed seed and simulation age. Label them as reference outcomes; initialization and media can change the result.

   Batch parameter application so loading one preset triggers at most one intentional reset.

   **Completion criterion:** presets round-trip without losing settings, and applying a preset without reset preserves the evolving state.

5. **Add state snapshots and deliberate reset behavior**

   Separate the current reset operation into:
   - Reset Chemistry.
   - Clear Carried Color.
   - Restart Media.
   - Reset All.
   - Save State / Restore State.

   A snapshot must preserve the raw signed floating-point state channels without color conversion or alpha premultiplication. Include dimensions, simulation time, settings, and schema version. For reproducible movie-backed playback, also capture media position and relevant palette/motion history.

   Provide an in-memory snapshot first, then disk persistence using a format verified to preserve those values. External live sources can restore chemical state but cannot promise identical future playback.

   Add:
   - **Reset on Source Change**, disabled by default.
   - **Resize Behavior:** Reset or Resample State.
   - Seed settings that take effect on the next explicit reset.

   When sources change, invalidate motion history even if chemical state is retained. Document that resizing preserves continuity but changes the discrete simulation and may alter its future behavior.

   **Completion criterion:** save/restore survives pause and subsequent evolution; source changes can preserve patterns; resizing never reads mismatched feedback textures.

6. **Make boundary and flow behavior explicit**

   Move boundary settings out of the Transform page into simulation controls.

   | Boundary mode | Meaning |
   |---|---|
   | Wrap | Opposite edges connect |
   | No Flux | Chemicals cannot diffuse across the boundary |
   | Empty Exterior | Exterior samples contain `A=1, B=0`, with no carried color |

   Share boundary helpers across simulation and state transport. Define display reconstruction separately where necessary so interpolation does not accidentally connect opposite edges.

   Retain global grow, scale, rotation, and translation, converted to time-based rates.

   After global transforms pass validation, add an optional Velocity TOP input. Define its channels, coordinate system, units, strength, and out-of-range behavior. Use bounded backtraced sampling and document its smoothing effect.

   **Completion criterion:** each boundary behaves consistently in stationary and moving fields; a zero velocity input reproduces the ordinary simulation path.

7. **Optimize measured costs**

   Profile representative square and rectangular projects before changing formats or shader structure.

   Implement these focused improvements:
   - Direct state sampling when simulation and output dimensions match.
   - Simulation-resolution influence data, with appropriate filtering from the full-resolution source.
   - Lighter texture formats for masks and visual intermediates where precision permits.
   - Optional carried-color history maintenance.
   - Palette extraction only when required, unless continuous history is enabled.
   - A configurable palette update interval.

   Keep RGBA32F chemical state as the initial reference. Evaluate a lower-precision simulation mode separately using long-running comparisons.

   Track GPU time and memory for simulation, media processing, palette extraction, and display independently.

   **Completion criterion:** optimizations show measured benefit without breaking alpha, signed chroma, boundary behavior, or acceptable pattern quality.

8. **Add diagnostics, validation, and embedded documentation**

   Include a compact status panel showing effective simulation dimensions, clock mode, tick/substep counts, simulation lag, source validity, and shader errors.

   Explicitly configure motion-cache cooking and history invalidation. Verify that motion influence settles to zero when the source stops.

   Add meaningful checks for:
   - Uniform empty-field stability.
   - Finite, bounded chemical concentrations.
   - Pause and single-step behavior.
   - Stamp-once versus continuous influence.
   - Boundary and domain-mask behavior.
   - Snapshot restoration and resize transitions.
   - Transparency and premultiplied output.
   - Preset serialization.
   - Deterministic replay with controlled media.

   Run shader checks outside TouchDesigner where useful, followed by live integration checks in each claimed supported build. Update the embedded help to describe units, reset behavior, snapshot limitations, and migration from V1.

   **Completion criterion:** the documented workflows pass live validation, and the script clearly reports unsupported parameters or shader failures.
 