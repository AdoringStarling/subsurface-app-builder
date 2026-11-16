# Time-lapse (4D) seismic

4D seismic is the same 3D survey shot again after production or injection. The difference between the surveys shows where fluids and pressure changed. The whole subject is separating a small real change from the larger differences caused by shooting the survey twice.

Helpers: `scripts/time_lapse.py`. Test data: `python scripts/make_synthetic.py out --monitor` writes a base and a monitor cube with a known planted effect and a truth file.

## Contents

- Vocabulary
- Workflow
- What the signals mean
- Display
- Pitfalls
- Open data

## Vocabulary

- **Base / monitor**: the first survey and a later one. Vintages are named by year.
- **Repeatability**: how alike the surveys are where nothing changed. Measured by NRMS.
- **NRMS**: `200 * rms(monitor - base) / (rms(monitor) + rms(base))` in percent. 0 is identical, about 141 is unrelated noise, 200 is reversed polarity. Dedicated marine 4D reaches roughly 10 to 30 % in the overburden; older surveys matched after the fact can be 40 to 80 %.
- **Time shift**: an event arrives earlier or later in the monitor because velocity or thickness changed above it. A few milliseconds at most. Positive in `time_lapse.py` means the monitor is later.
- **4D difference**: monitor minus base, after matching. State the order: some companies use base minus monitor, which flips every colour.

## Workflow

1. **Check the geometry.** `time_lapse.same_geometry(meta_base, meta_monitor)` must return an empty list. If the inline, crossline or sample ranges differ, crop both to the common range in `segy_to_npy.py` before anything else. Subtracting cubes that are offset by one trace produces a convincing and meaningless difference.
2. **Pick a quiet window**: an interval where no production effect is expected, normally the overburden well above the reservoir. All QC is measured there.
3. **Match.** `matched, report = time_lapse.match(base, monitor, k0, k1)` removes one bulk time shift and one amplitude scalar, and reports NRMS in the window before and after. If commercially processed 4D volumes are provided, they are already matched and this changes little; say so rather than skipping the check.
4. **Estimate time shifts.** `ts = time_lapse.time_shift(base, matched, window=25, max_lag=3)` in samples. Multiply by the sample interval.
5. **Difference twice.** `matched - base` mixes amplitude change with the effect of time shifts below the reservoir. `time_lapse.apply_shift(matched, ts) - base` removes the time-shift part and leaves the amplitude change. Show both; the contrast is the clearest way to explain 4D to an audience.
6. **Map it.** `time_lapse.rms_along_horizon(diff, horizon_samples, half=4)` gives the change at the reservoir; `value_along_horizon(ts, horizon_samples, offset=30)` gives the time shift just below it. A horizon in samples comes from `subsurface_utils.grid_horizon` or from picking the strongest event near a seed.
7. **Compare with the noise floor.** Call a change real only where it clearly exceeds the difference level outside the reservoir (the demo uses three times the survey median). Report NRMS next to every 4D map.

Command-line summary of two converted cubes: `python scripts/time_lapse.py data/base data/monitor --quiet-window 0 80`.

## What the signals mean

These are tendencies, and the sign depends on rock and polarity. Present them as interpretation aids, not conclusions.

| Change in the reservoir | Usual seismic effect |
|---|---|
| Water replaces oil (water flood, aquifer rise) | Impedance increases: a soft reservoir event dims |
| Gas comes out of solution, or gas or CO2 is injected | Impedance drops sharply: brightening, and a slow-down (positive time shift) below |
| Pressure rises (injection) | Velocity drops: softening and slow-down |
| Pressure falls (depletion) | Stiffening in the reservoir; compaction stretches the overburden, which slows it down |

Time shifts accumulate downward, so a change in the reservoir shifts every event below it by the same amount. That is why the unaligned difference continues beneath the reservoir with no geological meaning.

## Display

- Difference sections: the same diverging scale as amplitude, with the clip stated relative to the base (`clip = base clip / 3`). Never let the difference auto-scale, or pure noise will look like signal.
- Time-shift maps and sections: diverging scale centred on zero, units in ms, the sign convention in the title.
- NRMS and RMS-difference maps: sequential scale from zero with a fixed upper limit so before and after are comparable.
- Draw the reservoir horizon on sections so the viewer can see what lies above and below it.

## Pitfalls

- Two vintages are rarely delivered on the same grid. Different sample intervals, record lengths or line ranges are normal.
- Polarity and phase can differ between vintages. An NRMS near 200 % means reversed polarity; multiply one cube by -1 and say that you did.
- Cross-correlation time shifts are smeared over the correlation window and unreliable where reflections are weak. A result pinned at `max_lag` means the search range is too small or the surveys are misaligned.
- `time_shift` holds `2 * max_lag + 1` copies of the cube in memory. Crop to the interval of interest for real surveys.
- Acquisition footprints (stripes along the shooting direction) appear in difference maps and are not geology.
- More than two vintages: difference each monitor against the same base, and against the previous monitor, and keep the two families apart in the interface.

## Open data

- **Sleipner 4D** (CO2 injected into the Utsira Formation, the best-known CO2 plume images): https://co2datashare.org/dataset/sleipner-4d-seismic-dataset. Twelve SEG-Y archives of 1.5 to 3.2 GB each, under the Sleipner CO2 Reference Dataset License. The smallest base and monitor pair is the 1994 and 2001 vintages at 1.5 GB each. Download before travelling and crop both to the plume area with `segy_to_npy.py`.
- **Volve 4D** (ST0202 and ST10010 vintages): part of the Volve data set under the Equinor Open Data Licence. Access now goes through a marketplace that asks for sign-up, and the files are large.
- No small open base and monitor pair was found, which is why the bundled demo uses synthetic data. Label it as synthetic.
