# Quick-look petrophysics

Deterministic quick-look formulas, good enough for an app or screening tool. They are implemented in `scripts/subsurface_utils.py`; use those functions instead of rewriting them. Always expose the parameters (matrix density, Rw, cutoffs) as user controls with these defaults, because the right values are formation-specific and a geoscientist in the audience will ask.

## Workflow

1. **Bad-hole flag** first. Density and neutron are pad tools and read mud in washouts. Flag samples where `CALI - BS > 2 in` or `|DRHO| > 0.15 g/cm3` (`flag_bad_hole`). Show the flag as a shaded track and exclude flagged samples from averages.
2. **Shale volume** from gamma ray (`vshale_gr`).
3. **Porosity** from density, or density-neutron when both exist.
4. **Water saturation** from Archie (`sw_archie`).
5. **Net pay** by applying cutoffs (`net_pay_summary`).

Two things about the helper functions that matter in an app:

- They clip results to physical ranges (Vsh 0 to 1, porosity 0 to 0.6, Sw 0 to 1). Clipped values look valid, so a column stuck at Sw = 1 or porosity = 0.6 signals a wrong parameter or unit, not rock.
- `vshale_gr` defaults its clean and shale lines to the P5 and P95 of whatever array it receives. Compute those once per well or zone and pass them in; otherwise Vsh shifts every time the user moves a depth slider.

`net_pay_flags` returns the reservoir and pay masks plus a table of pay intervals; pass the pay mask to `log_plot(flag=pay, flag_color="#2E7D32")`. `porosity_density_neutron` implements the density-neutron row below.

## Formulas

| Quantity | Formula | Defaults and notes |
|---|---|---|
| Gamma-ray index | `IGR = (GR - GR_clean) / (GR_shale - GR_clean)` | Clean and shale lines default to P5 and P95 of GR over the interval. Pick per zone or per well, not across a whole basin. |
| Vshale, linear | `Vsh = IGR` | Upper bound; overestimates shale. |
| Vshale, Larionov young rocks | `0.083 (2^(3.7 IGR) - 1)` | Tertiary clastics (much of the North Sea overburden and Paleogene reservoirs). |
| Vshale, Larionov old rocks | `0.33 (2^(2 IGR) - 1)` | Mesozoic and older (Jurassic Brent, Triassic). |
| Density porosity | `PHID = (rho_ma - RHOB) / (rho_ma - rho_fl)` | rho_ma: 2.65 sandstone, 2.71 limestone, 2.87 dolomite. rho_fl: 1.0 fresh mud filtrate, about 1.1 salt mud, lower in oil-based mud. |
| Density-neutron porosity | `PHIT = sqrt((PHID^2 + NPHI^2) / 2)` in gas; `(PHID + NPHI) / 2` otherwise | NPHI must be in v/v and on the matching matrix (limestone units are common). |
| Effective porosity | `PHIE = PHIT - Vsh * PHI_shale` | PHI_shale about 0.05 to 0.15. |
| Sonic porosity (Wyllie) | `(DT - DT_ma) / (DT_fl - DT_ma)` | DT_ma 55.5 us/ft sandstone, 47.5 limestone; DT_fl 189. Fallback when density is bad. |
| Water saturation (Archie) | `Sw = ((a Rw) / (PHI^m Rt))^(1/n)` | a=1, m=2, n=2. Rw is the big unknown: North Sea formation waters are typically 0.02 to 0.1 ohm.m at reservoir temperature. Valid in clean sands; too high in shaly sands (use Simandoux or Indonesia if needed). |
| Net reservoir | `Vsh <= 0.4 and PHIE >= 0.10` | Cutoffs are conventions; show them. |
| Net pay | net reservoir and `Sw <= 0.6` | Thickness = sum of sample spacing, which is measured depth, not true vertical thickness, in deviated wells. |

## Sanity ranges

Use these to catch unit errors before computing anything. `inspect_las.py` applies them automatically and flags the common cases.

| Curve | Typical range | Common trap |
|---|---|---|
| GR | 0 to 200 gAPI (hot shales to 400+) | Different tools/hole sizes give offsets between wells; normalise per well for ML. |
| RHOB | 1.9 to 2.9 g/cm3 | kg/m3 (values around 2300): divide by 1000. |
| NPHI | -0.05 to 0.6 v/v | Percent (values around 25): divide by 100. Limestone vs sandstone matrix units. |
| RDEP/RMED | 0.2 to 2000 ohm.m | Plot and average in log space. |
| DTC | 40 to 190 us/ft | us/m (values 130 to 600): multiply by 0.3048. |
| CALI | bit size to bit size + several inches | cm or mm instead of inches. |
| PEF | 1.8 sandstone, 5.1 limestone, about 3 shale | Barite mud swamps it. |

## Reading the logs (for labels and explanations in an app)

- Sand vs shale: low GR is clean, high GR is shale. Exceptions: feldspathic or micaceous sands (common in the Brent Group) are radioactive, so GR alone overestimates shale.
- Hydrocarbon indicators: high deep resistivity in a porous, clean interval. Gas: neutron drops and density drops, giving the neutron-density crossover.
- Standard display: track 1 GR (0-150, green fill to the left of a cutoff) with caliper and bit size; track 2 resistivity on a log scale (0.2-2000); track 3 RHOB (1.95-2.95) and NPHI (0.45 to -0.15, reversed) overlaid; track 4 sonic (140-40, reversed). Depth increases downward. Geoscientists read this layout at a glance, so keep it.

## Limits to state in the app

Quick-look results are not a formal petrophysical evaluation: no environmental corrections, no core calibration, a single Rw, measured-depth thickness. Say so in a caption near the results.
