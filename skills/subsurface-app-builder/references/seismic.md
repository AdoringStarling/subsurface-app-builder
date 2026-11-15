# Seismic (SEG-Y)

## Contents
- First look
- When the geometry is not found
- Convert once, then memory-map
- Display conventions
- Attributes
- Horizons and wells on seismic
- Size and memory
- Other formats and libraries

## First look

A SEG-Y file is a 3200-byte text header, a 400-byte binary header, then traces, each with a 240-byte header. Nothing in the format guarantees where inline and crossline numbers live, so always inspect before loading:

```bash
python scripts/inspect_segy.py survey.sgy
python scripts/inspect_segy.py survey.sgy --text-header     # all 40 header lines
```

When the line numbers are not in the standard bytes it says so in `note` (this is the usual reason other software "cannot open it as a cube") and prints the exact `convert_command` to run next.

It reads headers and a sample of traces only, so it is safe on files of many gigabytes. It reports trace count, samples per trace, sample interval, sample format, the first text-header lines (often containing the survey name, CRS and line ranges), approximate coordinate range, amplitude statistics with a suggested display clip, and the geometry it could detect (inline/crossline byte positions, ranges, sorting).

Read the text header: it frequently states the CRS, the inline/crossline ranges and the byte positions. Do not trust it blindly, since it is free text and sometimes copied from another survey; the binary and trace headers win when they disagree.

## When the geometry is not found

`inspect_segy.py` tries the SEG-Y rev1 positions (189/193) and then common vendor layouts. If none works it prints `header_scan`: how each candidate header word varies over the first traces. Pick the bytes by their pattern:

- crossline: increments every trace, resets periodically
- inline: constant for a run of traces, then steps
- CDP X/Y (181/185) or source X/Y (73/77): large numbers that change smoothly

Then rerun with `--iline-byte B1 --xline-byte B2` (both scripts take the same two options). Other cases:

- **2D line**: one section, no inline/crossline. Open with `segyio.open(path, ignore_geometry=True)` and stack traces: `np.stack([f.trace[i] for i in range(f.tracecount)])`. The horizontal axis is CDP number (byte 21) or trace sequence.
- **Irregular 3D** (missing traces, ragged edges): `strict=True` fails. Read headers for every trace with `f.attributes(byte)[:]`, build the grid yourself and fill a NaN cube by index.
- **Pre-stack**: a third key (offset, byte 37) exists; `n_offsets > 1`. Volumes get large quickly; work on single gathers or stack first.
- **Coordinates look 100 times too large**: apply the coordinate scalar (byte 71). Negative means divide by its absolute value, positive means multiply. The scripts do this.
- **Amplitudes are absurd (1e30)**: the sample format in the binary header is wrong (IBM float vs IEEE). Try `segyio.open(..., endian="little")` or override the format.
- **Depth vs time**: the format does not say reliably. Sample interval is in microseconds for time data, and the same field holds millimetres or similar for depth data. Check the text header and the range: 0 to 4000 with 4 ms steps is time; a `depth` in the file name is a hint.

## Convert once, then memory-map

segyio is fast but an app should not parse SEG-Y on every interaction:

```bash
python scripts/segy_to_npy.py survey.sgy data/survey
python scripts/segy_to_npy.py survey.sgy data/crop --ilines 10090 10150 --xlines 2150 2300 --samples 0 400
```

This writes `survey.npy` (float32, axes inline, crossline, sample) and `survey.json` with line numbers, sample values, `clip_p99`, corner coordinates and an affine `ilxl_to_xy`. In the app:

```python
from subsurface_utils import load_cube
cube, meta = load_cube("data/survey")     # memory-mapped: opening is instant, slices read on demand
inline = cube[i]                          # (crosslines, samples)
xline = cube[:, j]                        # (inlines, samples)
tslice = cube[:, :, k]                    # (inlines, crosslines)
```

Convert array positions with `np.searchsorted(meta["ilines"], inline_number)`; line numbers rarely start at zero or step by one.

## Display conventions

Geoscientists expect these, and a section that breaks them looks wrong to them immediately:

- Time or depth increases **downward**.
- Symmetric colour limits around zero for amplitude, clipped at about the 99th percentile of absolute amplitude (`clip_p99`). Without a clip, a few strong events flatten everything else. Offer a gain control that divides the clip.
- Diverging red-white-blue for amplitude (`RdBu`); grey scale is the other common choice. State which polarity is which if known, since conventions differ (SEG normal vs European).
- Non-signed attributes (envelope, RMS, similarity) use a sequential scale. Phase uses a cyclic scale.
- Label axes with real inline/crossline numbers and time in ms or depth in m, not array indices.

`subsurface_plots.seismic_section(data2d, x, samples, clip)` and `seismic_slice(...)` implement this, and downsample large sections for the browser.

## Attributes

`scripts/seismic_attributes.py` has the standard post-stack set, working on arrays with the sample axis last:

| Attribute | Shows | Display |
|---|---|---|
| `envelope` | Reflection strength, polarity-independent; bright spots | Sequential |
| `instantaneous_phase` | Reflector continuity, also in weak-amplitude zones | Cyclic, -180 to 180 |
| `instantaneous_frequency` | Bed thickness and attenuation changes | Sequential, clip to 0-80 Hz |
| `rms_amplitude` | Smoothed energy in a window | Sequential |
| `semblance` | Trace-to-trace similarity; faults and channel edges are low | Show `1 - semblance` with `DISCONTINUITY_SCALE` (white to black), `zmin=0` |

Compute an attribute for the whole cube once and cache it (`st.cache_data`): the Volve sub-cube (61 x 202 x 850) takes about a second each. For large volumes compute per displayed slice or precompute to `.npy` from the command line.

### Seeing faults

Display `1 - semblance(cube, window)` so discontinuities are high values, with `colorscale=sp.DISCONTINUITY_SCALE` and a fixed `zmin=0` so the scale does not shift between slices. Plotly's named `"Greys"` runs black to white, which would paint faults white; use the explicit scale.

- Faults show best on **time slices** as lineaments, and as vertical dark streaks on sections. Offer both.
- Window: 9 to 21 samples. Short windows are sharper and noisier; long windows are cleaner but smear dipping faults.
- Averaging the attribute over a few neighbouring slices (plus or minus 5 samples) strengthens steep faults and suppresses noise.
- Semblance is also low wherever the signal is weak (shallow noise, salt, below strong absorbers), not only at faults. Say so in the caption, and judge a lineament by its continuity across slices and lines.
- Steeply dipping reflectors lower semblance without any fault, because the 3x3 comparison is not dip-steered. Treat broad dark bands that follow structure with suspicion.

## Horizons and wells on seismic

- Horizons arrive as scattered `x y z` text. `grid_horizon(meta, x, y, z)` snaps them to the cube grid using the affine in the metadata and returns a 2D array aligned with the cube. Plot a row of it over an inline as a line; map it for structure.
- `amplitude_along_horizon(cube, meta, horizon, window, mode)` extracts amplitude on or around the horizon (value, RMS or maximum absolute), the usual first reservoir screen.
- Wells: `xy_to_ilxl(meta, x, y)` places a well head or trajectory on a time slice. Showing logs or the trajectory **on a time section** needs a time-depth relation (checkshots, or integrated sonic as a first guess). Without one, show wells in map view only and say so.
- Check that well, horizon and seismic share a CRS before overlaying. A constant offset of a few hundred metres usually means ED50 vs WGS84.

## Size and memory

`inspect_segy.py` prints `cube_gb_as_float32`. Rules of thumb:

- Under about 2 GB: convert whole and memory-map.
- Larger: crop with `--ilines/--xlines/--samples` to the area of interest, or decimate. A demo rarely needs more than a few hundred lines each way.
- Never `segyio.tools.cube()` or `np.asarray(cube)` on a volume larger than free RAM. Computing an attribute over a full large cube materialises it; restrict to the displayed slice.
- Copy large surveys to local disk before an event. Do not stream them from a shared network.

## Other formats and libraries

- **segyio**: reading and writing, used by the scripts here. `segyio.tools.from_array3D` writes a quick test file.
- **segysak**: SEG-Y to xarray/NetCDF with labelled dimensions; convenient for analysis notebooks.
- **MDIO, OpenVDS, ZGY**: chunked, cloud-friendly volume formats used for large surveys. Convert a crop to `.npy` for an app.
- **seismic-zfp**: compressed volumes with fast slice access when disk space is the constraint.
