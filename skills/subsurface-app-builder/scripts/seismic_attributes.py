"""Basic post-stack seismic attributes on numpy arrays. The sample (time/depth) axis is last.

Import in an app, or run on a .npy cube made by segy_to_npy.py:
    python seismic_attributes.py data/survey.npy envelope data/survey_envelope.npy
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter, uniform_filter1d
from scipy.signal import hilbert


def envelope(x: np.ndarray) -> np.ndarray:
    """Reflection strength (instantaneous amplitude). Highlights bright spots regardless of polarity."""
    return np.abs(hilbert(x, axis=-1)).astype(np.float32)


def instantaneous_phase(x: np.ndarray) -> np.ndarray:
    """Phase in degrees (-180..180). Emphasises reflector continuity; use a cyclic colour scale."""
    return np.degrees(np.angle(hilbert(x, axis=-1))).astype(np.float32)


def instantaneous_frequency(x: np.ndarray, dt_ms: float) -> np.ndarray:
    """Instantaneous frequency in Hz. Low values can indicate attenuation (gas) or thick beds."""
    phase = np.unwrap(np.angle(hilbert(x, axis=-1)), axis=-1)
    return (np.gradient(phase, axis=-1) / (2 * np.pi * dt_ms / 1000.0)).astype(np.float32)


def rms_amplitude(x: np.ndarray, window: int = 9) -> np.ndarray:
    """RMS amplitude in a sliding window of `window` samples."""
    return np.sqrt(uniform_filter1d(np.asarray(x, dtype=np.float32) ** 2, size=window, axis=-1))


def semblance(cube: np.ndarray, window: int = 9) -> np.ndarray:
    """Discontinuity-style attribute for a 3D cube (inline, crossline, sample), 3x3 traces.

    Returns semblance in 0..1: near 1 on continuous reflectors, low at faults and channel edges.
    Display 1 - semblance or use a reversed grey scale so faults appear dark.
    """
    c = np.asarray(cube, dtype=np.float32)
    size = (3, 3, window)
    num = uniform_filter(c, size=(3, 3, 1)) ** 2          # (mean over traces)^2
    num = uniform_filter(num, size=(1, 1, window))
    den = uniform_filter(c ** 2, size=size)               # mean of squares
    return np.clip(num / (den + 1e-12), 0, 1)


ATTRIBUTES = {
    "envelope": envelope,
    "phase": instantaneous_phase,
    "rms": rms_amplitude,
    "semblance": semblance,
}

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("attribute", choices=sorted(ATTRIBUTES))
    ap.add_argument("dst")
    a = ap.parse_args()
    out = ATTRIBUTES[a.attribute](np.load(a.src, mmap_mode="r"))
    np.save(a.dst, out.astype(np.float32))
    print(f"wrote {a.dst} shape={out.shape} min={out.min():.4g} max={out.max():.4g}")
