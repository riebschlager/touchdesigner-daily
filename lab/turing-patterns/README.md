# Turing Patterns / Turing Media V2

Generate growing coral, dividing spots, worms, holes, and media-driven patterns in TouchDesigner. The main entry point, [create_turing_media_v2.py](create_turing_media_v2.py), builds a complete GPU reaction-diffusion component from one Text DAT. It includes media masks, four color modes, state motion, optional velocity fields, presets, a Feed/Kill explorer, and saveable simulation snapshots.

This guide describes the **V2 builder and its seven current parameter pages**. The older `create_turing_patterns.py` and `create_turing_media.py` builders are retained as earlier versions; their controls differ.

## Contents

- [Getting started](#getting-started)
- [How the simulation works](#how-the-simulation-works)
- [Example workflows](#example-workflows)
- [Simulation parameters](#simulation-parameters)
- [Media parameters](#media-parameters)
- [Motion parameters](#motion-parameters)
- [Appearance parameters](#appearance-parameters)
- [Presets parameters](#presets-parameters)
- [State parameters](#state-parameters)
- [Advanced parameters](#advanced-parameters)
- [Outputs and internal network](#outputs-and-internal-network)
- [Troubleshooting](#troubleshooting)
- [Validation and older versions](#validation-and-older-versions)

## Getting started

### Requirements

Use TouchDesigner with support for the GLSL TOPs, Cache TOPs, and Python APIs used by the builder. The repository's recorded live validation is for **TouchDesigner 2025.33230 on macOS**. Other builds are unvalidated; construction reports missing required parameters or unsupported menu values.

There are no separate shader files, pip dependencies, or required TDAPI `.tox` components. Python and shaders are embedded in the builder. Manual snapshots and state resampling use NumPy bundled with TouchDesigner. Running this file with ordinary command-line Python only prints instructions; it does not create or render the network.

### Build and view the component

1. Open a TouchDesigner project and create a **Text DAT** in the network where you want the component.
2. Paste the entire contents of `create_turing_media_v2.py` into that DAT.
3. Right-click the DAT and choose **Run Script**.
4. The script creates a Base COMP named `turing_media_v2` beside the DAT. Select it to access its custom parameters.
5. Play the timeline. The default ambient seeds grow without any media input. View the component or enter it and view `out1`.
6. Try **Presets → Preset → Dividing Spots**, then press **Apply Preset + Reset**. Allow time for the spots to develop.
7. Save the project as a `.toe`, or save the generated component as a `.tox` for reuse.

Each script run creates a **new** component (`turing_media_v2_2`, `_3`, etc.) and preserves existing operators. Rerunning the builder does not update a previously generated component.

Saving a TOE/TOX preserves the network, settings, and preset table. GPU histories initialize afresh on load. To resume a particular evolving pattern, save and restore a snapshot on the **State** page.

### Add media

On **Media**, choose **Movie File** or drag an existing TOP into **Source TOP**. A valid Source TOP takes priority over Movie File. Clear both to remove media influence. Source TOP can be a camera, generator, render, or other image network; avoid referencing this component's own outputs, which creates a cook loop.

Use **Appearance → Output View → Source on Checkerboard** to check fitting and transparency, then **Influence Mask** to check what will affect the simulation. Return to **Final** to see the composite. For a fully opaque clip, **Silhouette Edges** outlines the fitted video rectangle; use **Texture Edges**, **Bright Texture**, or **Motion** to react to content inside it.

## How the simulation works

Each simulation cell stores two chemical concentrations: **A** is replenished by Feed, and **B** grows through the reaction `A × B²` and is removed by Feed + Kill. A and B diffuse to neighboring cells at different rates. The balance between reaction, replenishment, removal, and diffusion produces the patterns.

The solver uses the Gray–Scott equations:

```text
dA = Diffusion A × laplacian(A) - A × B² + Feed × (1 - A)
dB = Diffusion B × laplacian(B) + A × B² - (Feed + Kill) × B
```

Each update clamps A/B to `0..1`. Empty state is `A=1, B=0`. Initial patches and media seeding target `A=0.5, B=0.25`. Feed/Kill changes can strongly alter morphology; their effects depend on the pair of values, existing state, and seed layout, so increasing one does not guarantee a particular shape. Start from presets and explore nearby values.

### Canvas pixels, simulation cells, and time

The **canvas** is the output image size. The **simulation grid** is calculated separately:

```text
grid width  = max(8, round(canvas width  / Cell Size))
grid height = max(8, round(canvas height / Cell Size))
```

A 512×512 canvas at Cell Size 1 has 512×512 simulation cells. At Cell Size 4, it has 128×128 cells, reconstructed to 512×512 for display. Patterns become thicker in output pixels, with less solver work and less fine detail. Changing cell size changes the discrete simulation, not just its appearance.

**One tick is always 1/60 simulation second.** At Solver Quality 1, a tick contains 16 chemistry updates with chemistry `dt=1`. Quality 2 uses 32 updates at `dt=0.5`; quality 4 uses 64 at `dt=0.25`. Speed controls how much simulation time passes; quality controls numerical accuracy and cost. Quality changes can still produce different long-term patterns because the reaction is nonlinear.

Most rates use **simulation seconds**. At Speed 2, chemical influence, color evolution, and motion advance twice as fast relative to wall time. Movie playback is controlled independently by Media Speed.

### Three kinds of masks

| Control | Purpose |
| --- | --- |
| Media → Mask Mode | Derives an influence field from media. It seeds chemicals, maps local Feed/Kill, or supplies a carried-color injection mask. |
| Motion → Domain Mask TOP | Defines which simulation cells are open and which are walls. It constrains chemistry and state transport. |
| Appearance → Clip Patterns to Alpha | Makes the final pattern transparent outside media alpha. This changes display only. |

Media influence and domain confinement are independent. A silhouette seed can spread beyond its original silhouette unless a domain prevents it. A domain wall holds empty chemical state but does not automatically make the output transparent.

## Example workflows

### Grow patterns without media

Leave Movie File and Source TOP blank. Apply **Coral**, **Dividing Spots**, **Worms**, or **Holes** using **Apply Preset + Reset**. Keep Ambient Seeds on. Try Cell Size 2–4 for thicker forms, or change Seed and press Reset Chemistry for a different starting layout.

### Seed a silhouette continuously

Assign media, then press **Media → Seed From Clip Only**. This turns off ambient seeds, selects Continuous Seed and Silhouette, sets Injection Rate to 600 and Recovery Rate to 0, and resets the state without rewinding the movie. Reduce Injection Rate afterward to allow the seeded shape to evolve more freely. Use Source Overlay 0 to see only the pattern.

### Stamp once, then let the pattern evolve

Assign media and apply **Stamp and Evolve** with **Apply Preset + Reset**. Press **Stamp Current Mask** once. Resume or Step to evolve the stamped chemicals. Selecting the preset or resetting does not automatically stamp. For a completely independent chemical evolution, leave Recovery Rate at 0. Carried color can still receive media color each tick; set Color Injection Rate to 0 after stamping if you want to stop subsequent color injection too.

### Turn image brightness into different local patterns

Assign media and apply **Chemistry Map** with **Apply Preset + Reset**. Brightness determines local Feed/Kill between the map endpoints. Adjust Chemistry Map Blend to move between uniform chemistry and media-driven chemistry. Ambient seeds help start growth: Chemistry Map does not inject B into an otherwise empty field.

### Carry color through a moving pattern

Assign colorful media and apply **Color Swirl**. This selects Carried Color and enables growth/rotation. Color is stored with the chemical state and spreads through B-weighted neighbors. Reduce Color Injection Rate for slower recoloring; add Color Decay Rate to gradually return chroma toward gray. These require Maintain Carried Color to be on.

### Use a velocity field

Assign a floating-point TOP to **Motion → Velocity TOP** and enable **Enable Velocity**. Supply signed red/green values in simulation cells/second: `(60, 0)` moves right by one cell per tick at Velocity Strength 1. `(0, -60)` moves down. Start with small values and inspect Max Displacement if the field seems slower than expected.

## Parameter reference

The tables list **UI labels**, internal Python parameter names, builder defaults, allowed numeric ranges, and effects. Names are useful for expressions, automation, and preset JSON. Approximate defaults marked `≈` come from exponential-rate conversions in the builder. Numeric controls are clamped to the listed ranges. A button is a pulse action; a read-only field is a diagnostic. Defaults describe a newly built component; applying a preset changes them.

## Simulation parameters

### Canvas, chemistry, and seeds

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Resolution (square) (`Resolution`) | 512; integer 64–2048 | Sets both canvas dimensions in square mode. Disabled when Rectangular Canvas is on. |
| Rectangular Canvas (`Rectangle`) | Off | Uses independent Width and Height instead of Resolution. |
| Width (`Canvaswidth`) | 768; integer 64–4096 | Output width in rectangular mode. Inactive in square mode. |
| Height (`Canvasheight`) | 432; integer 64–4096 | Output height in rectangular mode. Inactive in square mode. |
| Cell Size (pixels) (`Cellsize`) | 1; 1–8 | Canvas pixels per simulation cell, approximately. Larger values make thicker patterns and reduce grid size. Fractional values are allowed; grid dimensions round to integers. |
| Feed (`Feed`) | 0.0545; 0–0.1 | Replenishes A and also contributes to B removal. Together with Kill, determines the chemical regime. |
| Kill (`Kill`) | 0.062; 0–0.1 | Additional removal of B. Try small changes around a known preset. |
| Diffusion A (`Diffusiona`) | 1; 0–1 | A's spatial diffusion coefficient. Lower values reduce A's spreading. |
| Diffusion B (`Diffusionb`) | 0.5; 0–1 | B's spatial diffusion coefficient. The relative A/B diffusion rates affect pattern structure. |
| Boundary (`Transformedge`) | Wrap | Canvas-edge policy for diffusion and state transport; see below. |
| Seed (`Seed`) | 1; integer 0–1,000,000 | Controls repeatable ambient patch positions. Takes effect on the next chemistry reset. |
| Seed Radius (cells) (`Seedradius`) | 9; 3–32 | Radius of initial B patches in simulation cells. Takes effect on the next chemistry reset. |
| Ambient Seeds (`Ambient`) | On | Adds ten initial patches, including a central one. Off starts from empty A/B on reset; media injection or stamping can then seed it. Editing this does not erase existing patterns. |
| Reset All (`Reset`) | Button | Same operation as State → Reset All: reseeds chemistry, clears carried color, restarts the movie, initializes histories, and resets age/debt. |
| Reseed + Reset Chemistry (`Reseed`) | Button | Increments Seed and resets chemistry/age/debt, preserving carried color and movie position. |

Dimension edits follow **State → Resize Behavior**. Seed controls only change initialization; Feed/Kill and diffusion changes affect the next tick without automatically resetting.

| Boundary option / token | Behavior |
| --- | --- |
| Wrap / `wrap` | Opposite edges connect for diffusion and transport. Useful for repeating patterns. |
| No Flux / `noflux` | Exterior samples hold the nearest edge cell, preventing diffusion across the canvas edge. Transport backtraces hold edge values. |
| Empty Exterior / `clear` | Exterior samples use empty, colorless state. Acts as a sink and fills exposed areas during state transport with A=1/B=0. |

For display reconstruction, both closed modes hold edge values. They do not visually join opposite edges or add an empty border. `Transformedge` and the `clear` token are legacy names retained for file compatibility.

### Clock and inspection

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Clock Mode (`Clockmode`) | Real Time (`realtime`) | Real Time advances from monotonic wall time. Frame Stepped (`framestepped`) advances `Speed / Render FPS` simulation seconds per output frame. Changing modes clears accumulated fractional time/debt while preserving pattern and age. |
| Speed (`Speed`) | 1; 0–8 | Simulation seconds per elapsed second in Real Time; multiplier in Frame Stepped. Zero holds state and existing time debt. |
| Solver Quality (`Solverquality`) | 1; integer 1–4 | Uses `16 × quality` chemistry updates/tick at `dt=1/quality`. Higher quality costs more; it does not increase elapsed simulation time. |
| Render FPS (`Renderfps`) | 60; 1–240 | Assumed output frame rate in Frame Stepped mode. This control does not configure TouchDesigner's actual project FPS. |
| Pause (`Pause`) | Off | Freezes chemical state, carried color, palette updates, and sampled media history. Live source previews/overlay and movie playback can still change. |
| Step (one tick) (`Step`) | Button | While paused, advances exactly one tick, including influence/color/transport. Works even at Speed 0; preserves Pause and existing debt. Does nothing when running. |
| Max Catch-up Ticks / Frame (`Maxcatchup`) | 4; integer 1–32 | Real Time work limit per output frame. Excess time is retained as lag. Frame Stepped ignores this limit and executes all required ticks. |
| Simulation Time (seconds) (`Simtime`) | Read-only | Completed ticks divided by 60; chemical age since the last chemistry reset. |
| Simulation Lag (seconds) (`Simlag`) | Read-only | Unprocessed simulation time, including fractional tick remainder. Persistent growth indicates overload. |
| Ticks Last Frame (`Tickcount`) | Read-only | Number of ticks executed by the last advance/step. |
| Substeps / Tick (`Substeps`) | Read-only | `16 × Solver Quality`; normally 16, 32, 48, or 64. |

At Speed 1, Frame Stepped with Render FPS 30 runs two ticks/frame; Render FPS 120 alternates zero and one. Pause/resume rebases wall time so the paused interval is not caught up. Viewer recooks do not advance the simulation.

## Media parameters

### Source, playback, fitting, and alpha

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Movie File (blank = none) (`Moviefile`) | Blank | Clip or image-sequence input to the internal Movie File In TOP. Playback loops. |
| Source TOP (overrides Movie File) (`Sourcetop`) | Blank | External TOP image input. A valid binding overrides the movie. |
| Play Media (`Mediaplay`) | On | Enables movie playback. Does not pause chemistry or control an external Source TOP. |
| Media Speed (`Mediaspeed`) | 0.5; −2–2 | Movie playback multiplier; default half speed. Negative values request reverse playback. Independent of simulation Speed. |
| Restart Media (`Restartclip`) | Button | Cues the movie and invalidates motion history; preserves chemicals, carried color, palette, and age. |
| Reset on Source Change (`Resetonsource`) | Off | On resets chemistry/color/age/histories when the source binding/file or detected Source TOP identity/dimensions changes. It does not rewind the movie. Off preserves chemicals and invalidates motion history. |
| Override FPS (image sequences) (`Overridefps`) | Off | Enables the movie source's sample-rate override for image sequences. |
| Sequence FPS (`Sequencefps`) | 30; 1–120 | Sequence sample rate when Override FPS is enabled. |
| Scale (`Mediascale`) | 0.9; 0.05–3 | Fits source to canvas preserving aspect, then scales around center. 1 is the fitted size; smaller values leave more transparent padding. |
| Offset X (`Offsetx`) | 0; −1–1 | Horizontal shift as a fraction of canvas width; positive moves right. |
| Offset Y (`Offsety`) | 0; −1–1 | Vertical shift as a fraction of canvas height; positive moves up. |
| Rotation (degrees) (`Rotation`) | 0; −180–180 | Rotates fitted media about its center; positive is counterclockwise. This transforms the source image, not stored chemicals. |
| Source Premultiplied (`Sourcepremult`) | Off | Unpremultiplies incoming RGB by original alpha before processing. Enable for an already premultiplied input to avoid dark fringes. |
| Ignore Source Alpha (`Ignorealpha`) | Off | Makes the fitted source rectangle opaque. Padding outside the fitted/transformed rectangle remains transparent. |

Prepared media is straight RGBA with RGB clamped to 0–1; transparent RGB is cleared. Coarse grids use alpha-weighted low-pass sampling before masks and chemical/color injection. Fine source details can disappear as Cell Size increases. Source Preview and motion-history textures remain at canvas resolution.

### Chemical influence

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Influence Mode (`Influencemode`) | Continuous Seed (`continuous`) | Chooses continuous concentration injection, a manual stamp, or mapped local chemistry; see below. |
| Stamp Current Mask (`Stamp`) | Button | In Stamp Once mode, blends current live mask into chemicals once. Works paused and does not advance time or sampled histories. |
| Stamp Amount (`Stampamount`) | 1; 0–1 | Stamp blend fraction multiplied by the mask. 1 fully sets target A/B where mask is 1; 0 does nothing. Stamp mode only. |
| Map Feed Minimum (`Feedmin`) | 0.025; 0–0.1 | Feed mapped from mask value 0. Chemistry Map only. |
| Map Feed Maximum (`Feedmax`) | 0.065; 0–0.1 | Feed mapped from mask value 1. Chemistry Map only. |
| Map Kill Minimum (`Killmin`) | 0.045; 0–0.1 | Kill mapped from mask value 0. Chemistry Map only. |
| Map Kill Maximum (`Killmax`) | 0.070; 0–0.1 | Kill mapped from mask value 1. Chemistry Map only. |
| Chemistry Map Blend (`Chemistryblend`) | 1; 0–1 | Blends uniform Feed/Kill toward mapped values, multiplied by source alpha. 0 uses uniform chemistry. |
| Injection Rate (1 / second) (`Strength`) | ≈5.003; 0–600 | Rate of blending chemicals toward A=0.5/B=0.25 through the mask. Continuous Seed only. 0 disables injection; 600 nearly imposes the target each tick for a full mask. |
| Recovery Rate (1 / second) (`Fade`) | 0; 0–60 | Blends A/B toward empty state everywhere in the open domain, independently of mask and influence mode. Strong recovery can suppress growth. |
| Seed From Clip Only (`Clipseed`) | Button | Partial preset: Ambient Seeds off, Continuous Seed, Silhouette, Injection Rate 600, Recovery Rate 0, then one reset. Retains other settings and movie position. |

**Continuous Seed** injects every tick. **Stamp Once** (`stamp`) disables automatic chemical injection; only the Stamp button introduces concentration through media. Selecting Stamp Once or resetting does not stamp. A stamp leaves carried color unchanged. **Chemistry Map** (`chemistry`) disables concentration injection and varies the reaction's Feed/Kill instead:

```text
mapped feed = Feedmin + mask × (Feedmax - Feedmin)
mapped kill = Killmin + mask × (Killmax - Killmin)
local rates = mix(uniform Feed/Kill, mapped rates, Chemistryblend × source alpha)
```

Endpoints may descend to reverse a map. Transparent areas and absent media use uniform chemistry. Recovery and carried-color injection remain independent in all three modes.

Continuous injection uses `blend = 1 - exp(-rate × mask × 1/60)` once per tick. Recovery uses the same form without a mask. At rate 5 with a full mask, the blend is about 8% per tick. These are rates, not direct blend percentages; larger values approach the target faster.

### Mask shaping

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Mask Mode (`Maskmode`) | Silhouette Edges (`edgealpha`) | Chooses the source feature that drives influence; options below. |
| Mask Gain (`Maskgain`) | 1; 0–8 | Multiplies the processed mask, then clamps it to 0–1. 0 removes influence from this mask. |
| Edge Width (cells) (`Edgewidth`) | 3; 1–12 | Sampling distance used by the two edge modes. Larger values detect broader differences. |
| Mask Smoothing (cells) (`Smoothing`) | 1; 0–8 | Nine-tap spatial smoothing distance. 0 bypasses smoothing. |
| Motion Gain (`Motiongain`) | 4; 0.1–20 | Amplifies frame-difference signal in Motion mode before Mask Gain. |

| Mask option / token | Signal |
| --- | --- |
| Silhouette / `alpha` | Source alpha. |
| Bright Texture / `bright` | Alpha × luminance. |
| Dark Texture / `dark` | Alpha × (1 − luminance). |
| Silhouette Edges / `edgealpha` | Differences in alpha across horizontal/vertical offsets. |
| Texture Edges / `edgetexture` | Differences in alpha-weighted luminance, multiplied by local alpha. |
| Motion / `motion` | Change in alpha or alpha-weighted luminance from the previous sampled tick. This measures change, not optical-flow direction. |

Luminance uses RGB weights `0.2126, 0.7152, 0.0722`. Motion suppresses changes ≤1e−6 as numerical noise. It becomes zero on the next unchanged sampled tick. Source changes, media restart, and canvas resizing invalidate its history and suppress the first difference. Pause holds the last sampled mask even if the live preview changes.

## Motion parameters

### Global state transform

These controls move the stored chemicals **and** carried color after the solver, once per tick. They are independent of Media's source-fitting transform.

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Enable Transform (`Transform`) | Off | Enables global state scale/rotate/translate. |
| Grow / Shrink (% / second) (`Grow`) | ≈5.997; −300–300 | Continuous uniform scale rate. Positive expands; negative shrinks. Adds to both axis-specific rates. |
| Scale X (% / second) (`Scalex`) | 0; −300–300 | Additional horizontal continuous scale rate. |
| Scale Y (% / second) (`Scaley`) | 0; −300–300 | Additional vertical continuous scale rate. |
| Translate X (cells / second) (`Translatex`) | 0; −480–480 | Positive moves state right. Units are simulation cells, including on coarse grids. |
| Translate Y (cells / second) (`Translatey`) | 0; −480–480 | Positive moves state up. |
| Rotate (degrees / second) (`Rotate`) | 6; −600–600 | Positive rotates state counterclockwise around the pivot. |
| Pivot X (`Pivotx`) | 0.5; 0–1 | Horizontal pivot in normalized canvas coordinates. |
| Pivot Y (`Pivoty`) | 0.5; 0–1 | Vertical pivot in normalized canvas coordinates; 0 is bottom. |
| Zero Motion (`Transformzero`) | Button | Sets Grow, Scale X/Y, Translate X/Y, and Rotate to zero. Keeps state, pivot, and enable toggle. Does not zero a Velocity TOP. |

Scale per tick is `exp((Grow + axis rate) × 0.01 / 60)`. These are continuous rates: Grow 100 multiplies size by `e` over one simulation second, rather than simply doubling it. The transform preserves geometric proportions on rectangular grids. Fractional transport uses bilinear interpolation and can soften small features; exact zero movement bypasses resampling.

### Velocity flow

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Enable Velocity (`Flow`) | Off | Enables local transport when a Velocity TOP is assigned. Independent of Enable Transform. |
| Velocity TOP (RG cells / second) (`Velocitytop`) | Blank | Signed red=X, green=Y velocity field. Blue/alpha are ignored. Zero RG is stationary. |
| Velocity Strength (`Flowstrength`) | 1; 0–100 | Multiplies the field; 0 disables displacement. |
| Max Displacement (cells / tick) (`Flowmax`) | 8; 0–64 | Caps the length of each tick's flow displacement vector. 0 disables flow displacement. Larger inputs are slowed by the cap. |

Velocity is read over normalized canvas UV with explicit bilinear interpolation, without media fitting, color conversion, premultiplication, or a 0.5 bias. Use a floating-point TOP for negative values. Invalid channels become zero; finite components are clamped to ±1,000,000 before interpolation.

At Cell Size 4, velocity 60 means one **simulation cell**, approximately four canvas pixels, per tick at strength 1. The field is sampled at destination cell centers once per tick; Solver Quality does not change flow. Forward order is global transform, then local flow. This is first-order semi-Lagrangian image transport, not a fluid solver, and it is not mass conserving. Repeated fractional displacement can blur the state.

### Domain confinement

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Domain Mask TOP (red; blank = all) (`Domaintop`) | Blank | Red-channel image defining open cells. Blank leaves the entire canvas open. Fills normalized canvas UV with nearest sampling; ignores alpha and Media fitting controls. |
| Domain Threshold (`Domainthreshold`) | 0.5; 0–1 | Red values ≥ threshold are open; lower values are blocked. |
| Invert Domain (`Domaininvert`) | Off | Replaces red with `1 − red` before thresholding. |
| Domain Boundary (`Domainboundary`) | No Flux (`noflux`) | No Flux substitutes center state at wall taps, preventing chemical/color diffusion through walls. Empty Exterior (`empty`) substitutes empty state, acting as a sink along walls. |

Blocked cells hold A=1/B=0/colorless. Seeds, injection, stamps, diffusion, and transport respect the domain. Diagonal neighbors require both orthogonal cells to be open, and transport tests crossed cells to prevent jumping through walls, including wrap seams. Rejected transport retains destination state with No Flux or empties it with Empty Exterior. Paths exceeding 1024 cell crossings/tick are rejected conservatively.

Use walls at least one simulation cell thick; coarse grids can miss thin features. Domain changes while paused take effect when state is next operated on (Step, resume, Stamp, or reset). Simulation's canvas Boundary and Domain Boundary are separate policies. Wrap repeats the domain across canvas seams; closed canvas modes hold its edge values.

## Appearance parameters

These controls color and composite the state. Changing display or color mode does not reset chemistry.

### Display and output

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Color Amount (`Coloramount`) | 1; 0–1 | Mixes grayscale concentration display (0) with the selected palette/color mode (1). |
| Contrast (`Contrast`) | 2.5; 0.1–6 | Multiplies chemical B before clamping to 0–1 for palette lookup. Higher values reach brighter ramp colors at lower B. |
| Invert (`Invert`) | Off | Reverses the concentration-to-color lookup after Contrast. Does not invert chemistry. |
| Source Overlay (`Overlay`) | 0.2; 0–1 | Alpha-composites live fitted media over patterns. 0 hides it; 1 fully covers patterns wherever source alpha is 1. |
| Clip Patterns to Alpha (`Clipalpha`) | 0; 0–1 | Pattern opacity is `mix(1, source alpha, value)`. 1 fully clips to source alpha. With no media, 1 makes Final transparent. |
| Output View (`Viewmode`) | Final (`final`) | Final composite, Patterns (`patterns`), Influence Mask (`mask`), or Source on Checkerboard (`source`). Diagnostic views bypass final overlay/clipping. |
| Upscale Filter (`Upscale`) | Smooth (Cubic) (`smooth`) | Reconstructs coarse state at canvas size: cubic for smooth forms, Linear (`linear`) for simpler interpolation, Nearest (Pixels) (`nearest`) for visible grid cells. Matching canvas/grid sizes bypass reconstruction. |

Final output is **premultiplied RGBA**. Source Preview is straight RGBA. Patterns is the opaque colored simulation before overlay/clipping.

### Palettes and carried color

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Color Mode (`Colormode`) | Fixed Palette (`fixed`) | Selects a color strategy; options below. |
| Ramp TOP (blank = teal/gold) (`Ramptop`) | Blank | Replaces the base dark/teal/gold ramp with an external horizontal ramp, sampled left to right at its middle row. |
| Tint Spread (cells) (`Tintspread`) | 6; 0–24 | Source Tint's alpha-weighted color averaging radius. 0 uses local source color; larger values soften spatial color changes. Converted to canvas pixels using Cell Size. |
| Palette Smoothing (seconds) (`Palettesmooth`) | ≈0.1582; 0–10 | Clip-palette temporal smoothing time constant. 0 is immediate; larger values respond more slowly to cuts/color changes. |
| Palette Anchoring (`Paletteanchor`) | 0.5; 0–1 | In Clip Palette mode, borrows base-ramp lightness to improve contrast. 0 keeps clip lightness; 1 uses base-ramp lightness while retaining clip hue. |
| Color Spread Rate (1 / second) (`Dyespread`) | ≈665.421; 0–4000 | Blends stored chroma toward B-weighted neighbors each solver substep. Higher values distribute color faster; 0 disables spreading. |
| Carried Color Source (`Dyesource`) | Source Alpha (`alpha`) | Uses source alpha or Influence Mask (`mask`) to gate color injection. Independent of the chemical influence mode. |
| Color Injection Rate (1 / second) (`Dyeinject`) | ≈3.078; 0–600 | Blends stored chroma toward sampled source chroma once per tick. 0 prevents new color injection. |
| Color Decay Rate (1 / second) (`Dyedecay`) | 0; 0–60 | Fades stored chroma toward zero/gray once per tick. 0 retains color without decay. |
| Color Saturation (`Dyesaturation`) | 1.5; 0–4 | Multiplies stored chroma for Carried Color display only. 0 displays gray at the base ramp's lightness; does not erase stored color. |

| Color option / token | Result |
| --- | --- |
| Fixed Palette / `fixed` | Maps B to the base ramp: dark blue → teal → gold, or Ramp TOP. |
| Source Tint / `tint` | Uses nearby live media color as the middle of the ramp, with dark/light endpoints and alpha-aware blending. No visible source falls back to the base ramp. |
| Clip Palette / `ramp` | Samples an 8×8 grid of averaged media regions, ignores cells below 25% alpha coverage, sorts visible colors by luminance, and builds a 64-step ramp. No visible cells use the base ramp as the extraction target. |
| Carried Color / `dye` | Uses hue/chroma stored in the chemical state, with lightness from the base ramp. Color can remain after the source moves away. |

Carried color stores signed **Oklab a/b** values in state blue/alpha; it does not store RGB or source opacity. Its update blends use exponential rates:

```text
spread blend    = 1 - exp(-Color Spread Rate × substep seconds)
injection blend = 1 - exp(-Color Injection Rate × color mask × tick seconds)
chroma decay    = exp(-Color Decay Rate × tick seconds)
palette history retention = exp(-elapsed simulation seconds / Palette Smoothing)
```

The Advanced page determines whether carried color is maintained and when palette history updates. Source Tint and Source Overlay read live prepared media, so they may change while chemistry is paused.

## Presets parameters

### Save and apply settings

| Parameter (`name`) | Default | How it works |
| --- | --- | --- |
| Preset (`Preset`) | Coral (`coral`) | Chooses an entry. Selection alone does not apply it. User entries are marked `(user)`. |
| Apply Preset (keep state) (`Applypreset`) | Button | Applies settings in one batch, normally preserving chemicals, color, age, and histories. Dimension/source changes may trigger their configured reset policies. |
| Apply Preset + Reset (`Applyreset`) | Button | Applies settings and initializes chemistry/color/age/histories once. Keeps movie position and Pause. |
| Save As Name (`Presetname`) | Blank | Name for saving; blank chooses the next available `User Preset N`. |
| Save Current Preset (`Savepreset`) | Button | Saves current settings in the component's preset table. Same user name replaces that entry. Built-in names cannot be overwritten. |
| Delete User Preset (`Deletepreset`) | Button | Deletes the selected user entry. Built-ins cannot be deleted. |
| Include Media/TOP Bindings (`Presetbindings`) | Off | When on, saving includes Movie File, Source TOP, Domain Mask TOP, Ramp TOP, and Velocity TOP paths; applying restores saved bindings. Off neither saves nor applies bindings. |
| Preset File (.json) (`Presetfile`) | `turing_media_v2_presets.json` | Import/export path. Relative paths resolve from the project folder. |
| Import Mode (`Importmode`) | Merge (`merge`) | Merge adds/replaces same-named user entries. Replace User Presets (`replace`) removes existing user entries before importing. Built-ins remain. |
| Import Presets (`Importpresets`) | Button | Reads and validates JSON, then merges/replaces the table. Does not apply a preset. |
| Export Presets (`Exportpresets`) | Button | Writes the entire table, including built-ins, to Preset File. |
| Preset Status (`Presetstatus`) | Read-only | Last operation's result, including changed, missing, unknown, invalid, or blocked settings. |

Presets save **settings**, not evolving textures. Current complete presets contain 78 settings; Pause, read-only runtime diagnostics, snapshot paths/status, and preset/explorer controls are excluded. The table lives in the generated `presets` Text DAT with schema `turing_media_v2.presets`, version 1, and is saved with the TOE/TOX.

Built-ins start from **all builder defaults** and override the following values. Applying one can change dimensions, clocks, display, and performance controls as well as chemistry. All built-ins use Resize Behavior Reset and omit media/TOP bindings.

| Built-in | Changes from defaults |
| --- | --- |
| Coral | None: Feed 0.0545, Kill 0.062. |
| Dividing Spots | Feed 0.0367, Kill 0.0649, Seed Radius 5. |
| Worms | Feed 0.029, Kill 0.057, Seed Radius 6. |
| Holes | Feed 0.039, Kill 0.058. |
| Clip Seed | Ambient off, Continuous Seed, Silhouette, Injection Rate 600, Recovery Rate 0. |
| Stamp and Evolve | Feed 0.0367, Kill 0.0649, Ambient off, Stamp Once, Silhouette, Carried Color, Carried Color Source=Influence Mask. Requires pressing Stamp. |
| Chemistry Map | Chemistry Map influence, Bright Texture, Source Tint. |
| Color Swirl | Carried Color, Enable Transform on, Rotate 30 degrees/second; default Grow remains ≈6. |
| Wide Coarse | Rectangular Canvas on, 768×432, Cell Size 3 (256×144 grid). |

For **keep state**, new seed settings wait until a reset. Size changes use the Resize Behavior **stored in the preset**, so applying a built-in after changing dimensions can reset even with the keep-state button. Use a user preset with Resample State to preserve continuity across size changes. Source binding changes invalidate motion history and follow Reset on Source Change.

Import refuses invalid JSON, duplicate names, nonfinite settings, and newer schema versions without changing the table. Imported built-in copies are skipped; user entries colliding with built-in names are renamed. Unknown settings are retained and reported when applied; missing settings retain current values. Expression-driven changed settings become constants; exported parameters remain untouched and are reported as blocked.

### Feed/Kill explorer

Enter the component and open **`fk_explorer` as a panel/viewer**. The left side maps Kill horizontally and Feed vertically, with a current-value crosshair and colored example rings. The right side holds eight reference thumbnails. Click/drag the map to change Feed/Kill; click a thumbnail to select its exact pair. Thumbnail selection changes Feed/Kill only, rather than applying a complete preset.

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Panel Click Sets Feed/Kill (`Explorerclick`) | On | Enables map/thumbnail input. Off leaves the panel for viewing. |
| Reset When Choosing Example (`Explorerreset`) | Off | Resets chemistry/color/age/histories on a thumbnail click. Map dragging does not reset. |
| Map Feed Minimum (`Fkfeedmin`) | 0; 0–0.1 | Bottom of plotted Feed range. Separate from Media's chemistry-map endpoints. |
| Map Feed Maximum (`Fkfeedmax`) | 0.08; 0–0.1 | Top of plotted Feed range. |
| Map Kill Minimum (`Fkkillmin`) | 0.04; 0–0.1 | Left of plotted Kill range. |
| Map Kill Maximum (`Fkkillmax`) | 0.07; 0–0.1 | Right of plotted Kill range. |
| Thumbnail Seed (`Thumbseed`) | 1; integer 0–1,000,000 | Shared seed layout used when generating all reference tiles. Independent of the main Seed. |
| Thumbnail Age (seconds) (`Thumbage`) | 10; 0.5–60 | Reference simulation age; 10 seconds means 600 ticks. |
| Generate Thumbnails (`Generatethumbs`) | Button | Regenerates the reference atlas across frames; does not modify the main simulation. |
| Explorer Status (`Explorerstatus`) | Read-only | Generation progress and completed reference seed/age. |

Keep map maxima greater than minima to avoid a degenerate plotted range. The map also draws `Kill = sqrt(Feed)/2 − Feed`, a reference line for uniform reacted states; it is not a guaranteed pattern classifier.

| Reference thumbnail | Feed | Kill |
| --- | ---: | ---: |
| Coral | 0.0545 | 0.062 |
| Dividing Spots | 0.0367 | 0.0649 |
| Worms | 0.029 | 0.057 |
| Holes | 0.039 | 0.058 |
| Chaos | 0.026 | 0.051 |
| Moving Spots | 0.014 | 0.054 |
| Waves | 0.014 | 0.045 |
| U-Skate | 0.062 | 0.0609 |

Each reference uses a 128×128 independently wrapping tile, radius-5 seeds, diffusion 1/0.5, and 16 chemistry updates/tick, without media. Different main seeds, dimensions, ages, diffusion, domains, and media can produce different results at the same Feed/Kill. Generation can continue while the main simulation is paused, as timeline frames process the thumbnail job.

## State parameters

### Reset and resize controls

| Parameter (`name`) | Default | How it works |
| --- | --- | --- |
| Reset Chemistry (`Resetchemistry`) | Button | Applies current seed to A/B and resets age/debt; keeps carried color, palette, media samples, and movie position. |
| Clear Carried Color (`Clearcolor`) | Button | Zeros stored Oklab a/b; keeps chemicals, age/debt, palette, media history, and movie position. |
| Reset All (`Resetall`) | Button | Resets chemistry, color, age/debt, palette/media histories, and restarts the movie. Same as Simulation → Reset All. |
| Resize Behavior (`Resizebehavior`) | Reset (`reset`) | Reset initializes state/color/histories/age on effective canvas/grid changes. Resample State (`resample`) interpolates raw state to the new grid while preserving age/debt, color, and palette. |

Resampling uses normalized pixel centers and bilinear interpolation with held edges, regardless of canvas Boundary, then respects the new domain. Motion history is invalidated. Resampling preserves visual continuity but can smooth away features and changes future evolution. Inactive Width/Height edits in square mode do not resize the state. Size resets do not rewind the movie.

The following comparison assumes unchanged dimensions/source bindings and an initialized component. All these actions retain Pause:

| Action | Chemicals | Carried color | Age/debt | Palette | Motion history | Movie |
| --- | --- | --- | --- | --- | --- | --- |
| Reset Chemistry / Reseed | Reseeded | Kept | Zeroed | Kept | Kept | Kept |
| Clear Carried Color | Kept | Cleared | Kept | Kept | Kept | Kept |
| Restart Media | Kept | Kept | Kept | Kept | Invalidated | Restarted |
| Reset All | Reseeded | Cleared | Zeroed | Initialized | Initialized | Restarted |
| Apply Preset + Reset / Seed From Clip Only | Reseeded | Cleared | Zeroed | Initialized | Initialized | Position kept |
| Stamp Current Mask | Blended through mask | Kept | Kept | Kept | Kept | Kept |

### Snapshots

| Parameter (`name`) | Default | How it works |
| --- | --- | --- |
| Save State (memory) (`Savestate`) | Button | Captures one snapshot in component storage; a later save replaces it. |
| Restore State (memory) (`Restorestate`) | Button | Restores that snapshot, including saved settings and Pause. Snapshot remains available for repeated restore. |
| State File (.tstate) (`Statefile`) | `turing_media_v2.tstate` | Disk snapshot path; relative paths resolve from the project folder. |
| Save State to Disk (`Exportstate`) | Button | Captures the current state directly, verifies the written archive, and atomically replaces the destination. Does not require a previous memory save. |
| Restore State from Disk (`Importstate`) | Button | Validates and restores the file, and retains it as the memory snapshot. |
| Status (`Statestatus`) | Read-only | Snapshot/reset-resampling result or error; starts as `No state saved`. |

A snapshot includes six float32 textures (both chemical, media, and palette buffers), active readers, dimensions, completed ticks/debt, all preset settings, all five source/TOP bindings, saved Pause, history readiness/cadence, and movie position/playback metadata. It excludes the preset table and explorer thumbnails. Restore returns to the snapshot's original dimensions/settings; exported settings cause restoration to be refused before application.

`.tstate` is a ZIP archive containing versioned JSON and checksummed little-endian float32 RGBA payloads, with rows bottom-to-top. It preserves signed chroma without image conversion, quantization, or premultiplication. Save/restore and resampling transfer textures between GPU and CPU and can stall playback. Memory snapshots also consume CPU memory.

To preserve a moment reliably: pause, save state to disk, save the TOE/TOX, then use Restore State from Disk after reopening. A stored memory snapshot can also be restored after load; the GPU cache itself does not resume automatically.

Snapshots reference external files/TOPs and **do not embed their assets or producer history**. A live camera cannot rewind. Exact future replay requires the same subsequent media and velocity samples per tick; ordinary sequential movie playback depends on output timing and decoder scheduling. A restored chemical state can match exactly while live overlay/preview and later evolution differ.

## Advanced parameters

| Parameter (`name`) | Default / range | How it works |
| --- | --- | --- |
| Maintain Carried Color (`Carryhistory`) | On | Updates stored chroma in every color mode. Off skips color spreading/injection/decay while retaining existing chroma and unchanged A/B behavior. Transform/velocity still transport all channels. |
| Continuous Palette History (`Palettehistory`) | Off | On extracts clip palettes even in other color modes, keeping history warm. Off extracts when Clip Palette is selected; other modes hold the last clip ramp. |
| Palette Update Interval (ticks) (`Paletteinterval`) | 1; integer 1–600 | Tick cadence for needed palette updates. 60 means once per simulation second after initialization. Larger intervals reduce extraction frequency and hold colors between samples. Independent of render FPS and Solver Quality. |
| Check Shaders / Refresh (`Refreshdiagnostics`) | Button | Demands compilation/cooking of all shaders, including explorer shaders, and refreshes diagnostics without committing a simulation tick or sampled history. |

Turning Maintain Carried Color back on resumes retained chroma; it cannot reconstruct missed media history. Use Clear Carried Color to erase it. A custom Ramp TOP can refresh the base row without extracting a clip palette. Palette cadence freezes with simulation Pause; temporal smoothing accounts for elapsed simulation time between updates. The first needed palette update initializes immediately.

### Status and shader logs

Inside the component, view **`status_panel`** for build, canvas/grid, clock/Pause, ticks/substeps, age/lag, source validity, shader health, build issues, and runtime errors. **`status`** holds the full untruncated table. **`shader_diagnostics`** holds compiler logs with operator names; individual shaders also have compiler Info DATs.

Status updates each frame; existing shader logs/errors are inspected at most twice a wall-clock second, including while simulation Pause is on. With the timeline stopped, use Check Shaders / Refresh. Unchecked shaders are distinguished from successful compilation. An unassigned source is valid ambient operation.

## Outputs and internal network

All six public TOPs live inside the generated component:

| Output | Size / contents | Use |
| --- | --- | --- |
| `out1` | Canvas-sized; selected Output View, normally premultiplied final RGBA | Connect downstream for display, compositing, or recording. |
| `patterns` | Canvas-sized opaque colored simulation | Pattern before source overlay and alpha clipping. |
| `mask_preview` | Canvas-sized grayscale influence mask | Last sampled tick mask, linearly reconstructed from the simulation grid. |
| `source_preview` | Canvas-sized live fitted straight RGBA | Inspect transformed media and original alpha without the checkerboard. |
| `palette` | 64×2 color ramp | Bottom row 0 is extracted clip palette; row 1 is base/custom ramp. |
| `state` | Simulation-grid RGBA32F | Red=A, green=B, blue=Oklab a, alpha=Oklab b. Raw numeric state. |

**State alpha is signed color data, not opacity.** Preserve all four channels as float data; do not premultiply, color-convert, or save the state through an ordinary image codec to resume simulation. Use snapshots for that.

The embedded `README` Text DAT contains further implementation notes. Important internal operators/modules include:

```text
movie or Source TOP → media_prepared → media_a / media_b
                       ↓                 ↓
                 live display       sim_source / sim_previous → media_mask

state_a / state_b → state_read → reaction_diffusion → state_transform
       ↑                                                  │
       └──────── explicit inactive-buffer capture ────────┘

sampled media → palette_cells → palette_sort → palette_a / palette_b
state + live source + palette → colorize → patterns → composite → out1
```

`clock` is the fixed-tick Execute DAT scheduler. `controls` dispatches custom-parameter actions. `preset_lib` manages preset JSON; `snapshot_lib` manages raw state persistence; `state_upload`/`state_resize` handle restoration/resampling. `explorer` manages the Feed/Kill panel and reference atlas. `diagnostics` maintains status/logs.

State, palette, and media histories use explicit double-buffered Cache TOPs, rather than repeated Feedback TOP cooks. Normal ticks remain on the GPU. Signed chemical state stays RGBA32F; display uses an RGBA16F intermediate before final compositing. Half-float chemical simulation is not a supported option.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Nothing grows | Play the timeline; turn Pause off; set Speed above 0. With Ambient off, supply continuous injection or press Stamp. Chemistry Map alone cannot seed an empty field. Check domain openness and Recovery Rate. |
| The clip is visible but influences nothing | Source Overlay displays media independently. Inspect Influence Mask; check Mask Gain, the selected influence mode, Injection Rate, and source alpha. |
| Only a rectangular border appears from video | Default Silhouette Edges uses alpha, so opaque video gives a rectangle. Select Texture Edges, Bright/Dark Texture, or Motion. |
| A silhouette spreads outside its shape | Influence seeds chemicals. Use Domain Mask TOP to confine them, or Clip Patterns to Alpha to clip display. |
| Changing the seed does nothing | Seed, Seed Radius, and Ambient Seeds take effect on the next chemistry reset. |
| A stamp preset stays empty | Apply/reset does not stamp automatically. Press Stamp Current Mask. |
| The image disappears after enabling alpha clipping | Clear media gives zero alpha. Restore media or reduce Clip Patterns to Alpha. |
| Changing Color Saturation does nothing | It affects Carried Color display only. Check Color Mode and Color Amount. |
| Carried color stops responding | Enable Maintain Carried Color; check Color Injection Rate and its Source Alpha/Influence Mask gate. |
| Frozen chemistry still shows changing media | Pause freezes sampled state/history. Source Tint, preview, and overlay use live media. Disable Play Media or pause the external source separately. |
| Growing Simulation Lag / poor performance | Increase Cell Size, reduce canvas size/Speed, or lower Solver Quality. Disable unused carried-color maintenance/continuous palette history; increase Palette Update Interval if extraction is expensive. Raising Max Catch-up increases work per frame and may worsen interactive FPS. |
| Pattern jumps after a resize or preset | Default Resize Behavior is Reset; built-ins restore that policy. Use a saved user preset with Resample State where continuity matters. |
| Velocity seems clamped or wrong | Use signed RG float values in cells/second, without a 0.5 bias. Check Strength, Max Displacement, Cell Size, domain walls, and canvas Boundary. |
| Movie/TOP fails to load | Check source validity in status_panel/status. Resolve paths and upstream operator errors. A blank unused movie can report an empty-file diagnostic; the transparent fallback is intentional. |
| Clock stopped | Read Runtime and shader logs, fix the named cause, press Reset All, then enable the internal `clock` Execute DAT's **Active** parameter. Reset clears the message but does not automatically re-enable a failed clock. |
| Builder fails on another TD build | Inspect Textport/Build issues for a missing parameter or unsupported token. The partial component is retained; compare against the recorded supported build. |

## Validation and older versions

[validation/phase8/README.md](validation/phase8/README.md) documents the consolidated live/offline suite and reproduction workflow. Earlier phase folders retain detailed evidence for the fixed clock, media/domain behavior, presets, snapshots, boundaries/velocity, and performance. Recorded reports describe their tested builder/build; they are not a substitute for running checks after code changes.

The standard-library offline suites can run outside TouchDesigner:

```sh
python3 validation/phase2/test_clock.py
python3 validation/phase4/test_presets.py
python3 validation/phase5/test_snapshots.py
python3 validation/phase6/test_flow_presets.py
python3 validation/phase7/test_performance.py
python3 validation/phase8/test_diagnostics.py
```

Live runners require TouchDesigner and timeline playback; follow the phase-8 guide. Validation files are optional for ordinary use of the standalone builder.

For V1 migration, Passes/Timestep/Running are replaced by the clock controls. At the old 60 FPS reference, `Speed = passes × timestep / 16`. Convert old per-frame blend `p` to a rate with `−60 × ln(1−p)`, old per-pass Color Spread with `−960 × ln(1−p)`, and translation/rotation per-frame values by multiplying by 60. Old palette retention `s` becomes `−1 / (60 × ln(s))` seconds (`s=0` means instant). Old per-frame growth `p` percent becomes `6000 × ln(1+p/100)` continuous percent/second. Old Clear boundary now means Empty Exterior consistently for diffusion and transport; choose No Flux for held-edge diffusion. See the component's embedded README for the complete migration notes.
