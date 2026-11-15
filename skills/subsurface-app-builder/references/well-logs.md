# Well logs (LAS)

## Contents
- First look: never read a LAS file into context
- Loading and harmonising
- What goes wrong in real files
- Depth, position and tops
- Performance
- Machine learning on logs
- Other formats

## First look: never read a LAS file into context

A LAS file is thousands of lines of numbers. Summarise it instead:

```bash
python scripts/inspect_las.py well.las            # header, index, per-curve stats, flags
python scripts/inspect_las.py data/wells --brief  # folder: curve coverage across wells, unmapped names
```

The output gives, per curve: mnemonic, canonical family, unit, coverage, min/P5/P50/P95/max, depth range with data, and flags (out of plausible range, constant, likely percent or kg/m3). For a folder, `family_coverage_wells` tells you which curves exist in enough wells to build on, and `unmapped` lists names the alias table does not know.

## Loading and harmonising

Use `subsurface_utils.py` rather than raw lasio, so every app gets the same cleaning:

```python
from subsurface_utils import las_to_frame, read_las
df = las_to_frame("well.las")          # WELL, DEPTH (metres), curves renamed to families
las = read_las("well.las")             # the lasio object, when header fields are needed
```

`las_to_frame` does five things that otherwise get forgotten: replaces the header NULL value and the common sentinels (-999.25, -9999) with NaN; converts a depth index in feet to metres; renames vendor mnemonics to canonical families using `CURVE_ALIASES`; converts clearly wrong units (NPHI in percent, RHOB in kg/m3, sonic in us/m, caliper in mm) and records what it changed in `df.attrs["unit_fixes"]`; and when two curves map to one family (RSHA and RXO, several GR passes) keeps the one with most valid samples under the canonical name and leaves the other with its raw name.

Canonical families: `GR CALI BS RDEP RMED RSHA RHOB DRHO NPHI PEF DTC DTS SP ROP`. Add project-specific aliases to `CURVE_ALIASES` rather than renaming columns ad hoc. For names the table cannot resolve, send only mnemonic, unit, description and the P5/P50/P95 values to an LLM and ask for a family; that is a few dozen tokens per curve.

For many wells, convert once:

```bash
python scripts/las_to_parquet.py data/wells data/wells.parquet
```

118 wells (2.3 million rows, 28 columns) take about 40 s to convert and load in 0.5 s afterwards. The script also writes `wells.notes.json` with the curves renamed and units converted per well (Parquet does not keep `df.attrs`); show it in the app so the user knows what was changed.

## What goes wrong in real files

| Symptom | Cause | Handling |
|---|---|---|
| Curve full of -999.25 | Null sentinel not applied | `las_to_frame` handles it; check the header NULL when reading manually |
| NPHI around 25, RHOB around 2300, DT around 300 | Percent, kg/m3, us/m | `inspect_las.py` flags these; `las_to_frame` / `fix_units` convert them. Tell the user which conversions were applied |
| Depth step irregular or decreasing | Merged runs, bottom-up files | Sort by depth; resample with `np.interp` onto a regular grid if a method needs it |
| RHOB far too low, CALI much larger than bit size | Washout: pad tools read mud | `flag_bad_hole()`; exclude from averages and from ML training |
| Same curve twice (`GR`, `GR:1`) | Several logging runs spliced | lasio adds `:1`; `canonical_name` strips it |
| Read fails or text is garbled | Encoding, wrapped LAS 1.2, broken header lines | `read_las` retries with latin-1 and ignores header errors; LAS 3.0 with multiple data sections needs manual handling |
| Well name differs between sources | `15/9-13`, `15_9-13`, `15/9-13 Sleipner East Appr` | Join on the leading quadrant/block-number token, normalising `_` to `/` |
| Gamma ray offsets between wells | Tool, hole size, mud | Normalise per well (P5/P95 scaling) before comparing or training across wells |

Curves are only trustworthy below the casing shoe for most open-hole tools, and density/neutron are often logged only over the deeper sections. Expect long null intervals at the top; this is normal, not an error.

## Depth, position and tops

- The index is measured depth (MD) along hole unless stated. In deviated wells MD thickness is larger than true vertical thickness; say which one is shown.
- Some datasets carry position as curves (`X_LOC`, `Y_LOC`, `Z_LOC` in FORCE 2020, in ED50 / UTM zone 31N; `Z_LOC` is negative below sea level). Convert with `utm_to_latlon(x, y, epsg=23031)`. Check the CRS in the header or documentation; the Barents Sea and Norwegian Sea use other UTM zones.
- Formation tops usually arrive separately (spreadsheet, or the FactPages `wellbore_formation_top` table). Pass them to `log_plot(tops={name: depth})`. Offer a zone selector built from tops: petrophysical summaries over a whole well mix unrelated rocks and are meaningless.

## Performance

- Plot through `subsurface_plots.log_plot`, which decimates to about 4000 points per curve. A raw 20 000-sample well with 10 curves makes the browser crawl.
- Read one well at a time from Parquet with `pd.read_parquet(path, filters=[("WELL", "==", name)])` (0.1 s) rather than holding all wells in memory.
- Store curves as float32 and compress with zstd; keep float64 for depth and for UTM coordinates (float32 loses sub-metre precision at 6 500 000 m northing).

## Machine learning on logs

- Split train and test **by well**, never by random rows. Adjacent samples are almost identical, so a random split leaks and inflates scores. Use `GroupKFold(groups=df["WELL"])`.
- Missing curves are the norm. Gradient-boosted trees (XGBoost, LightGBM, `HistGradientBoostingClassifier`) accept NaN directly; avoid dropping rows.
- Useful features: the raw curves, log10 of resistivity, depth, per-well normalised GR, and rolling-window mean or gradient to give vertical context.
- Classes are unbalanced (shale dominates). Report per-class recall and a confusion matrix, not only accuracy.
- FORCE 2020 labels are in `FORCE_2020_LITHOFACIES_LITHOLOGY`; the code-to-name-and-colour table is `FORCE_LITHOLOGY` in `subsurface_utils.py`.

## Other formats

- **DLIS / LIS** (binary, multi-frame, array data): `dlisio`. Much heavier than LAS; convert the channels needed to Parquet once.
- **CSV exports**: same harmonisation applies; pass columns through `canonical_name`.
- **Deviation surveys** (MD, inclination, azimuth): minimum-curvature to TVD and offsets with `wellpathpy`, or read X/Y/Z directly when the file already has them.
- **welly** wraps lasio with well and project objects and curve quality tests; useful for larger projects, unnecessary for a quick app.
