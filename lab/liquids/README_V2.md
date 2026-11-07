# Fluid Solver V2 — shaded liquid surface

V2 adds a raised, glossy **2.5D surface** and a colored residue layer to the existing GPU fluid solver. It keeps the same CHOP source formats, staggered velocity grid, pressure projection, and dye transport. V1 builders and TOX files remain separate.

## Open the demo

Load **`fluid_demo_v2.tox`** into TouchDesigner and play the timeline. Or paste all of **`create_fluid_demo_v2.py`** into a Text DAT and Run Script. It builds a new `fluid_demo_v2` component, preserving existing networks.

The demo uses broader sources (radius .06), a dye rate of 18, motion speed .75, and reduced stirring to make the relief easy to see. It includes four independently colored, moving droppers driven by visible Constant CHOPs, merged into a `DROPPERS` Null and wired into the nested **`fluid_solver_v2`**. Select the outer demo for Pause, Step, Reset, motion controls, and the four dropper pages. Select the nested solver's **Surface** and **Residue** pages to change the material.

For the solver alone, use **`fluid_solver_v2.tox`** or **`create_fluid_solver_v2.py`**. Both Python builders are self-contained: no external GLSL files, pip packages, Matcap asset, or TDAPI component is required. The demo embeds the V2 solver builder. Construction verifies required TouchDesigner parameters and compiles all shaders before enabling simulation.

Tested on **TouchDesigner 2025.33230 on macOS**. Other builds are unvalidated. Input layouts and the original simulation parameters are described in [README.md](README.md).

## Try these controls first

1. View `out1` and allow the moving sources to draw trails.
2. Increase **Maximum Height** to exaggerate rounded edges and ridges.
3. Turn **Light Azimuth** to move light around the surface. **Light Elevation** controls how grazing the light becomes.
4. Lower **Roughness** for tighter, shinier highlights; raise it for a softer material.
5. Adjust **Studio Reflection Strength** to change the broad reflected highlights.
6. Increase **Residue Opacity** to retain a colored film as the wet dye moves away.
7. Choose **Appearance → View → Height**, **Surface Normals**, or **Residue** to inspect the fields.
8. Compare **Surface → Render Style → Flat Dye** with **Shaded Surface**. Disable residue for a direct comparison with V1's flat presentation.

## Rendering pipeline

```text
advected dye density
    → bounded height mapping
    → separable Gaussian height smoothing
    → aspect-correct central-difference normals
    → diffuse + GGX specular + studio reflections / optional Matcap
    → wet color composited over colored residue and background
```

Height is an artistic interpretation of density:

```text
height = Maximum Height × (1 − exp(−density × Density to Height))
```

This bounds height and makes accumulated dye round off gently. Height uses domain-height units: the domain is 1 unit tall and Width/Height units wide. Normals use grid spacing `1/Height` in both axes, so non-square grids preserve the surface proportions.

Height smoothing is a separable Gaussian with sigma in simulation cells and a 25-tap kernel per axis. Zero bypasses smoothing within each pass. Normals are computed after smoothing. All fields remain RGBA32F to avoid quantized highlight contours.

The renderer uses an orthographic view along +Z, a directional colored light, a GGX specular lobe, Schlick Fresnel, and an analytic studio environment with two soft reflected lights. These are adjustable artistic material controls, not a calibrated energy-conserving material. The default material needs no external images.

An optional **Matcap TOP** supplies another reflected-light layer, sampled using the XY components of the surface normal. Assign a TOP showing the appearance of a lit sphere, tune Matcap Reflection Strength, and rotate it to change its orientation. A blank binding uses the internal black fallback. Use linear RGB textures for predictable color. Avoid referencing the solver's own outputs as its Matcap, which would create a cook loop.

## Surface parameters

| Control | Default | Meaning |
| --- | --- | --- |
| Render Style | Shaded Surface | Surface lighting or flat dye color. Does not change simulation state. |
| Maximum Height | .025 | Maximum relief in domain-height units, range 0–.15. Zero produces flat normals. Demo uses .035. |
| Density to Height | 1.5 | How quickly density approaches maximum height. |
| Height Smoothing | 1.25 cells | Gaussian sigma, 0–4. Larger values soften ridges and highlight noise. Demo uses 1.3. |
| Surface Roughness | .28 | Specular spread, .08–1. Smaller values sharpen highlights. Demo uses .25. |
| Specular Strength | 1 | Strength of the directional light's glossy highlight. |
| Edge Fresnel Strength | 1 | Additional environment reflection as the surface turns away from the view. |
| Studio Reflection Strength | 1 | Strength of the analytic reflected environment. |
| Ambient Light | .42 | Broad illumination of the colored material. |
| Diffuse Strength | .65 | Directional shading strength. |
| Light Azimuth | 135° | Angle in the XY plane: 0° lights from +X, 90° from +Y. |
| Light Elevation | 55° | Angle above the surface plane, 5–89°. |
| Light Intensity | 1.4 | Directional light intensity. |
| Light Red / Green / Blue | 1 / 1 / 1 | Light color. |
| Optional Matcap TOP | Blank | External sphere-lighting texture. |
| Matcap Reflection Strength | .35 | Adds the Matcap layer to the wet material when assigned. |
| Matcap Rotation | 0° | Rotates the Matcap lookup. |

Appearance's existing Exposure, Density to Opacity, transparency, and background controls remain available. Exposure applies to fluid and residue, while background color is independent. Transparent display output is **premultiplied RGBA**. Values remain HDR and can exceed 1; lower Exposure or use downstream tone mapping as needed.

Changes to height, smoothing, lighting, and material update the rendered surface while paused, without advancing the fluid or modifying raw dye. Height does not feed back into velocity or pressure.

## Colored residue

Residue is a stationary pigment history. Each substep converts local dye density into coverage, retains the larger of current coverage and faded prior coverage, and gradually recolors existing film where fresh wet dye passes over it. New coverage immediately takes the wet dye's mean color. It stays fixed to the canvas as dye moves, rather than being advected with the velocity field.

```text
current coverage = 1 − exp(−density × Residue Sensitivity)
remaining history = previous coverage × exp(−Fade × substep seconds)
new coverage = max(current coverage, remaining history)
```

The film is composited beneath the raised wet layer with matte, flat-surface shading. It carries its own RGB history, so a red trail can remain red after the active dye has moved on. Overpainting can recolor the film at a controllable rate.

| Control | Default | Meaning |
| --- | --- | --- |
| Enable Residue | On | Records and displays residue. Off hides and freezes the existing history; re-enabling resumes it. |
| Residue Opacity | .35 | Display strength of the stored film. Demo uses .25. |
| Density to Residue Coverage | .7 | Coverage response to wet density. |
| Residue Fade | .08 / s | Exponential decay per simulation second. Zero preserves coverage indefinitely. |
| Residue Recolor Rate | 4 / s | Rate of recoloring existing film beneath wet dye. |
| Clear Residue / Keep Fluid | Pulse | Clears residue only. Wet dye can deposit new film on the next step. |

Pause freezes film history along with the fluid. Step advances both. Reset, grid-size changes, boundary changes, and TOE/TOX load clear the history. **Clear Dye** preserves residue and velocity. The outer demo exposes a Clear Residue button as well.

## Six outputs

The outer demo and standalone solver expose the same outputs:

| Output | Content |
| --- | --- |
| `out1` | Final display, including the selected diagnostic view. Premultiplied when transparent. |
| `out2` | Original raw dye: RGB color densities and A total dye density. |
| `out3` | Original reconstructed signed UV velocity/second in RG; B=0, A=1. |
| `out4` | Smoothed height in R, G/B=0, A=1. Values are domain-height units. |
| `out5` | Surface normals encoded as `normal × .5 + .5` in RGB; A contains smoothed height. Decode and normalize RGB for custom rendering. |
| `out6` | Residue's **straight RGB** and coverage in A. This data output is not premultiplied and excludes Residue Opacity. History remains available here when disabled. |

Internal fields include `height_source`, `height_blur_x`, `height_field`, `surface_normals`, `residue_read`, and two explicit residue GPU caches. Residue is updated once per substep when enabled; the height/normal/render chain is evaluated on demand from the current dye. All full-grid work stays on the GPU; normal simulation adds no GPU-to-CPU readback.

## Scope and reference

This integrates the height/normal/material and persistent-film ideas from [mofu's Spreading Liquid article](https://mofu-dev.com/en/blog/fluid-foundation/). It derives relief from the existing advected dye instead of adopting the article's separate artistic thickness-redistribution rule. Residue is adapted to preserve multiple colors in one film history. Color mixing remains V1's density-weighted linear RGB mixing.

The result is a top-down 2.5D material treatment. It does not introduce a deforming mesh, a free surface, real volume conservation for the apparent thickness, cast shadows, or a 3D liquid simulation. It is intended to make the existing interactive dye read as raised paint or gel.

## Validation

Recorded checks are in `validation/v2/`:

- `core_validation.json`: existing fluid/CHOP regression checks run against V2.
- `surface_validation.json`: height bounds, normalized normals, lighting/roughness/Matcap response, preservation of raw dye, residue color/fade/clear/pause, diagnostics, resize, and saved solver reload.
- `demo_v2_validation.json`: four independent dropper colors and movement, pause/step/reset, editable source controls, and saved demo reload.

Load `validate_surface_td.py` or `validate_demo_v2_td.py` into a Text DAT, then call `module.validate(component, '/absolute/output/directory')`. Use a fresh test copy with default scalar source bindings; validators change parameters and create fixtures. The surface validator expects a standalone V2 solver, while the demo validator expects the outer V2 demo.

All **78 recorded checks passed**: 23 core fluid checks, 33 surface/residue checks, and 22 demo checks.
