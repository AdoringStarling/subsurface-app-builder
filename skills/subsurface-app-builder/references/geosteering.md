# Geosteering and horizontal wells

Geosteering is adjusting a horizontal well while it is drilled so that it stays in the target layer. The only information arriving in real time is the survey (where the bit is) and a few logging-while-drilling (LWD) curves, usually gamma ray. The geosteerer compares those curves with the log of a nearby vertical well and works out where in the layering the bit must be.

Helpers: `scripts/geosteering.py`. Test data: `python scripts/make_synthetic.py out --geosteer` writes a type log, a lateral with gamma ray, a survey and the true dips.

## Contents

- Vocabulary
- Inputs and how to check them
- The model
- Workflow
- Display
- Pitfalls
- Extensions and open data

## Vocabulary

- **MD / TVD**: measured depth along the hole, and true vertical depth.
- **Inclination**: 0 is vertical, 90 is horizontal, above 90 the well climbs. **Azimuth**: compass direction.
- **Survey station**: one (MD, inclination, azimuth) measurement, typically every 30 m. Positions between stations are computed, not measured.
- **Vertical section (VS)**: horizontal distance along the planned direction. The x-axis of every geosteering display.
- **Type log / offset well**: the reference log, from a vertical or pilot well, giving the signature of each bed.
- **Landing**: the point where the well reaches the target and turns horizontal. **Lateral**: the horizontal part.
- **Apparent dip**: formation dip seen along the well's direction. In `geosteering.py` positive means beds get deeper ahead, so the well is parallel to bedding at inclination `90 - dip`. Other tools use the opposite sign; state the convention in the app.
- **Stratigraphic depth**: where a point of the lateral sits in the type well's depth scale, after removing structure.
- **Dogleg severity (DLS)**: how sharply the well bends, in degrees per 30 m. Steering changes are limited by it, commonly to a few degrees per 30 m.
- **Curtain section**: a cross-section along the well showing the layers and the well path.

## Inputs and how to check them

| Input | Usual form | Check |
|---|---|---|
| Survey | CSV or text with MD, inclination, azimuth | Units (m or ft), MD increasing, inclination near 90 in the lateral, the TVD of the first station |
| LWD log | LAS indexed by MD | `inspect_las.py`; the log ends some metres behind the bit because the sensor sits behind it |
| Type log | LAS of the offset well | Indexed by TVD, or MD of a vertical well. If the offset well is deviated, convert to TVD first |
| Target zone | Top and base in type-log depth | Ask the user; do not guess from the log |

Compute the path with `geosteering.minimum_curvature(md, inc, azi, tvd0=...)`, which is the industry-standard method, then `path_at(path, log_md)` for TVD and VS at each log sample. Simple averaging of angles drifts by metres over a long lateral, and a few metres is the whole target.

## The model

The beds are assumed parallel and of constant thickness. Their depth relative to the type well changes along VS as straight segments, each with one dip:

```
structure_shift(vs)       depth of the beds relative to the type well
stratigraphic depth    =  TVD of the well  -  structure_shift(vs)
modelled log           =  type log read at the stratigraphic depth
```

Change the dips until the modelled log matches the measured one. `geosteering.fit_dips(vs, tvd, log, type_depth, type_log)` does this with a beam search over one dip per segment and a penalty on dip changes. It returns the segment nodes, dips, the modelled log and the misfit.

Then:

- `zone_status(strat_depth, top, base)`: share of the lateral in the zone and the distance from the bit to top and base.
- `steering_advice(dip_ahead, strat_depth_at_bit, top, base)`: inclination to stay parallel, and to return to the zone centre within a given distance.

## Workflow

1. Inspect and load the three inputs; compute the path.
2. Fit using only data behind the bit. A slider for "drilled to" that replays the well is the natural interface and the natural demo.
3. Show the curtain section, the measured and modelled log, and the type log with the bit's interpreted position.
4. Let the user override: at minimum the dip of the last segment, and the offset to the type well (`start_shifts` in `fit_dips`). An automatic fit that cannot be corrected by the expert will not be trusted.
5. State the recommendation in drilling terms: current inclination, formation dip, target inclination, distance to the zone boundaries.

When the tie between the two wells is uncertain (different datum, a fault between them), pass a range to `start_shifts`, or `--shift-range 15` on the command line.

## Display

- Curtain section: VS on x, TVD increasing downward, heavy vertical exaggeration (a 10 m zone over 1500 m is invisible at true scale). Say that it is exaggerated.
- Gamma ray colours: low (clean sand) yellow, high (shale) grey-green or brown. `geosteering.GR_SCALE` does this.
- Draw the target top and base following the structure, the well path, the bit, and the projection ahead of the bit with the last dip.
- Under it, measured and modelled log on the same VS axis. The mismatch is the evidence for or against the interpretation.

`geosteering.curtain_figure(...)` builds the combined figure.

## Pitfalls

- **The answer is not unique.** Inside a thick uniform bed the log is flat and any dip that keeps the well in the bed fits equally well. The interpretation tightens only at boundaries and markers. Show the misfit, and do not present the fit as fact.
- **Up or down?** Leaving a sand through the top and through the base can look the same on gamma ray if the shales above and below are alike. Azimuthal (up and down) gamma ray, images, or the sequence of beds resolve it. With a single curve, say the ambiguity exists.
- **Thickness changes and faults** break the parallel-beds assumption. A fault appears as a sudden jump in stratigraphic position; a single very steep segment in the fit is the hint. A model with a separate throw per fault is the extension.
- **LWD and wireline gamma ray differ** in level and scale (tool type, hole size, mud). If the modelled log is consistently offset from the measured one, rescale the type log to the lateral using readings in the same beds before fitting.
- **Position uncertainty grows along the well**; the absolute TVD at the toe can be off by several metres. Relative position in the layering, which is what the log match gives, is the reliable quantity.
- **Feet and metres** are mixed freely in drilling data. Check the survey and both logs.
- Segment length trades resolution for stability: 50 to 150 m is a reasonable range. Shorter segments invent dips from noise.

## Extensions and open data

- More curves: resistivity and density constrain the fit where gamma ray is flat. Fit on a weighted sum of normalised misfits.
- Deep-reading resistivity tools map boundaries metres away from the well; their inversions come as images, not curves.
- Seismic: a depth horizon along the well path gives a first guess of the dips, which the log match then refines.
- Open data:
  - Geosteering World Cup 2021, about 10 000 interpretations and trajectories from 349 participants (CSV and JSON, CC BY 4.0, 210 MB and 51 MB): https://zenodo.org/records/15190744. Whether raw LWD curves are included was not confirmed.
  - Geosteering World Cup 2020 type log, a synthetic gamma-ray log (CSV, 236 KB, CC BY 4.0): https://doi.org/10.18710/20VIVT
  - NORCE geosteering repositories, including an interactive benchmark: https://github.com/geosteering-no
  - Kaggle "ROGII - Wellbore Geology Prediction": reportedly several hundred horizontal wells each with a type well; needs a Kaggle account, and the licence was not checked.
  - Volve contains real horizontal wells with LWD logs and surveys, inside the large Volve data set.
