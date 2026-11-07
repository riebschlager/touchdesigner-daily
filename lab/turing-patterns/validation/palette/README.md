# Palette generator validation

`../../create_color_palette.py` is a standalone Text DAT network builder.
Paste it into a Text DAT and choose Run Script. Select the new component and
press **New Random Palette**. No existing components are replaced.

Alternatively, drag `../../color_palette.tox` into any TouchDesigner network.
The exported component was reimported in a separate container: its five saved
colors and CHOP samples matched, with no operator errors.

- `ramp`: 1024 × 1 smooth Ramp TOP output.
- `palette_top`: 1024 × 64 equal-width swatch TOP output.
- `palette_chop`: RGBA channels, one sample per color, normalized sRGB values.
- `colors`: hex codes, API color names and normalized RGBA in API order.
- `ramp_keys`: position/RGBA table that can drive another Ramp TOP.

The component offers eight harmony modes, a 2–16 color count, repeatable seed
colors, and reversal. Parameter edits apply to the next requested palette;
reversal applies immediately. Requests run off the UI thread and preserve the
last successful palette on failure. Keep playback running, or press **Check
Request** to apply a finished request while paused. A saved TOE/TOX retains its
palette and never fetches automatically on reopen.

Palette source: [The Color API](https://www.thecolorapi.com/about), which requires
no key. Its [scheme documentation](https://www.thecolorapi.com/docs) lists the
available harmony modes. These are generated harmonies, not ranked popular
palettes. HTTPS certificate verification stays enabled; on macOS the builder
uses TD's bundled certifi roots when available to supplement Python's roots.

Run offline tests:

```sh
python3 validation/palette/test_palette.py
```

Five tests cover embedded Python compilation, input validation, malformed API
responses, network errors, stale responses, and palette preservation.

`report.json` records 20 passing live checks on TouchDesigner 2025.33230, including
a successful HTTPS API request triggered through the custom pulse, RGBA samples,
TOP dimensions, pixel equality at every swatch center, ramp endpoints, reversal,
invalid-seed preservation, and operator errors. The first pulse after constructing
a Parameter Execute DAT should happen on a later frame, after its observer starts.

To repeat live output validation, load `validate_td.py` into a Text DAT and call
its module's `validate(component, absolute_report_path)` after a successful API
fetch. It changes Reverse briefly and tests an invalid seed, then leaves the
palette in its original order. The report path should be this directory's
`report.json` so the validator can locate the builder for its SHA-256.
