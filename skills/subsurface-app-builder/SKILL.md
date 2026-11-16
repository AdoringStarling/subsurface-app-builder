---
name: subsurface-app-builder
description: Build working apps and analyses on subsurface (oil and gas, geoscience) data - well logs in LAS, seismic in SEG-Y, and public Norwegian continental shelf data such as Sodir/NPD FactPages, Diskos, Volve and FORCE datasets. Use this skill whenever the user mentions well logs, LAS or lasio files, log curves or mnemonics (GR, RHOB, NPHI, resistivity, sonic), petrophysics (shale volume, porosity, water saturation, net pay), lithology or facies prediction, SEG-Y or segyio, seismic sections, inlines/crosslines, horizons or attributes, 3D or 4D (time-lapse) seismic, base and monitor surveys, geosteering, horizontal wells, well trajectories or surveys, LWD logs, wellbores, fields, discoveries or production on the Norwegian shelf, or wants a viewer, dashboard, QC tool, map or LLM assistant for geoscientists, petrophysicists or reservoir and drilling engineers - also when they ask for project ideas for an energy or geoscience hackathon, or how to demo such an app, even if they do not name a file format.
---

# Subsurface app builder

Build apps that a geoscientist or engineer can use on real well-log, seismic and public shelf data, quickly and correctly. The skill bundles tested helper scripts, the domain conventions experts expect, and the pitfalls already hit so they are not hit again.

## How to work

**1. Find out what data exists before proposing anything.** Look on disk first. If there is none, the open datasets in `references/ncs-open-data.md` cover wells, seismic and the public register, with download commands. If the user has no idea yet, offer two or three options from `references/project-ideas.md` that fit their data and background, and recommend one.

**2. Inspect with the scripts, never by reading data files.** LAS and SEG-Y files are huge and mostly numbers; reading them wastes the context window and tells you less than a summary does.

```bash
python scripts/inspect_las.py <file or folder> [--brief]     # curves, families, coverage, value ranges, flags
python scripts/inspect_segy.py <file> [--text-header]         # geometry, byte positions, sampling, amplitude clip
python scripts/fetch_factpages.py --list | --core | --all     # public shelf tables, cached locally
```

A folder gives a brief overview (curve coverage, index unit, flags); run `inspect_las.py` on single files for full per-curve statistics. Read the output critically. Flags such as "looks like percent", "irregular depth step" or an unstructured geometry change what you build.

**3. Convert once to fast local formats.** Apps read these, not the originals:

```bash
python scripts/las_to_parquet.py <las folder> data/wells.parquet   # harmonised curve names, depth in metres
python scripts/segy_to_npy.py <file.sgy> data/survey               # memory-mappable cube + metadata JSON
```

**4. Build a thin end-to-end slice first**: one real file, one plot, running app. Start from `assets/app_template/` (`app.py` for wells, `seismic_app.py` for a cube) and copy the helper modules it imports next to it. Default stack is Streamlit + Plotly because it gives a working interactive app fastest; see `references/app-patterns.md` for when to use something else.

**5. Use the helper modules instead of rewriting them.**

| Module | Provides |
|---|---|
| `scripts/subsurface_utils.py` | Curve alias table and `canonical_name`, tolerant LAS reading, `las_to_frame`, unit fixing, quick-look petrophysics (`vshale_gr`, `porosity_density`, `porosity_density_neutron`, `sw_archie`, `net_pay_flags`, `net_pay_summary`, `flag_bad_hole`), FactPages loading into pandas or DuckDB, UTM to lat/lon, cube loading, horizon gridding and amplitude extraction |
| `scripts/subsurface_plots.py` | `log_plot` (standard multi-track layout), `crossplot`, `seismic_section`, `seismic_slice` |
| `scripts/seismic_attributes.py` | Envelope, instantaneous phase and frequency, RMS amplitude, semblance |
| `scripts/time_lapse.py` | 4D seismic: geometry check, NRMS repeatability, matching a monitor to a base, time shifts, aligned difference, change maps along a horizon |
| `scripts/geosteering.py` | Horizontal wells: minimum-curvature path, vertical section, structure model from a type log, automatic dip fit, in-zone statistics, steering advice, curtain section figure |
| `scripts/ask_data.py` | Natural-language questions over DuckDB tables (the model writes SQL; schema prompt is cached; read-only) |
| `scripts/screenshot_app.py` | Starts a Streamlit app, clicks through its tabs and saves a screenshot of each, for visual checking |
| `scripts/make_synthetic.py` | Plausible fake wells and a seismic cube for tests or when no data is available; `--monitor` adds a 4D monitor survey and `--geosteer` a horizontal well, both with known answers. Label synthetic data as such wherever it is shown |

**6. Verify by running and by looking.** Run the app headless with Streamlit's `AppTest`, and also look at it: `python scripts/screenshot_app.py app.py shots/` saves one image per tab to read. A chart can be blank or mis-scaled without any error. Check numbers against physical sense using the ranges in `references/petrophysics.md` - a porosity of 0.5 or a net pay of 300 m means something upstream is wrong.

## Conventions that make the result credible

Domain experts judge an app in seconds by whether it follows their conventions. The helpers implement these; keep them when customising.

- Depth and time increase downward. Log tracks use the standard order and scales (gamma ray, resistivity on a log scale, density with reversed neutron, sonic reversed).
- Seismic amplitude uses a symmetric colour scale clipped near the 99th percentile; axes show real line numbers and milliseconds or metres.
- Always state units, the depth reference (measured depth unless converted) and the coordinate system.
- Compute over a zone or interval, never a whole well, and exclude bad-hole intervals from averages.
- Expose assumptions (matrix density, Rw, cutoffs) as controls with sensible defaults, and say what the result is not (quick-look, uncalibrated).
- Split machine-learning data by well, not by random rows.
- Credit data sources and licences in the app and the README.

## Being economical

Many of these projects run on shared budgets and shared networks.

- Work from local copies; cache every download; never fetch inside an app rerun.
- Let scripts and SQL do the data work. Give a language model schemas, statistics and small result tables only, cache the stable part of the prompt, and choose the model tier per task. Details in `references/llm-features.md`.
- Keep data out of git (`data/` in `.gitignore`) and ship a download script instead.

## Reference files

Read the one that matches the task; each is self-contained.

| File | Read when |
|---|---|
| `references/well-logs.md` | Loading, harmonising and QC of LAS data; real-file failure modes; ML on logs |
| `references/petrophysics.md` | Any calculation of shale volume, porosity, saturation or net pay; sanity ranges; standard log display |
| `references/seismic.md` | Anything with SEG-Y: geometry problems, conversion, display, attributes, horizons, wells on seismic |
| `references/time-lapse-seismic.md` | Two or more vintages of the same survey (4D): repeatability, matching, time shifts, difference maps, what the signals mean |
| `references/geosteering.md` | Horizontal wells, surveys and trajectories, LWD logs against a type log, staying in a target zone, curtain sections |
| `references/ncs-open-data.md` | Finding or joining open data: FactPages tables and their quirks, FORCE 2020 wells, Volve, reports, Diskos, licences |
| `references/app-patterns.md` | Building or debugging the Streamlit app: caching, layout, plots, maps, known breakages, testing, deployment |
| `references/llm-features.md` | Adding a language model: where it helps, token discipline, text-to-SQL, extraction, failure handling |
| `references/project-ideas.md` | The user wants ideas, or an extension to an existing app |
| `references/demo-and-pitch.md` | The work will be presented or published: build order, demo-proofing, a 4-minute structure, open-repo checklist |

## Script dependencies

`lasio numpy pandas pyarrow` for wells; `segyio scipy` for seismic; `requests duckdb` for FactPages; `plotly streamlit` for apps; `pyproj` for coordinates; `anthropic` for `ask_data.py`. Install only what the task needs.
