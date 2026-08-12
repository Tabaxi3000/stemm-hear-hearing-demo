"""Prescriptive hearing-aid fitting rules: audiogram -> per-frequency insertion gain.

Replaces the half-gain placeholder with the two standard clinical prescriptions, so the
OpenMHA (and our) comparison uses a real fitting philosophy.

    rule(audiogram, freqs, levels) -> gains[len(levels), len(freqs)]  (dB insertion gain)

FIDELITY (read this):
  * The AUTHORITATIVE NAL-NL2 is proprietary -- it needs NAL's `NAL-NL2.dll` (purchased
    from the National Acoustic Laboratories) driven through a wrapper; OpenMHA can use it
    but we don't have the DLL.
  * OpenMHA's DSL m[i/o] rule calls an external "DSL5 wrapper" we also don't have.
  So the two functions here are DOCUMENTED APPROXIMATIONS built from the *published*
  literature, good enough to drive an A/B comparison but NOT clinical fits:
    - `nal_nl2`  : NAL-RP linear target (Byrne & Dillon 1986; Byrne et al. 1990) made
                   level-dependent with modest WDRC compression, in the spirit of
                   NAL-NL1/NL2 (Dillon 1999; Keidser et al. 2011). Prescribes *less* gain
                   than DSL, rolled off at low frequencies.
    - `dsl_mio`  : DSL m[i/o] v5 philosophy (Scollie et al. 2005) -- loudness-normalisation
                   that maps the speech input range into the listener's residual dynamic
                   range (threshold -> UCL). Prescribes *more* gain, especially for soft
                   sounds. (This is close to our own PersonalizedGainMap.)
  For a fully self-contained, non-commercial rule that CAN be run authoritatively, OpenMHA
  ships CAMFIT (Moore et al.) -- see `run_octave_gainrule()`.
"""

from __future__ import annotations

import numpy as np

# NAL-RP real-ear insertion-gain frequency corrections k(f), dB (Byrne & Dillon).
_NALRP_F = np.array([250., 500., 750., 1000., 1500., 2000., 3000., 4000., 6000.])
_NALRP_K = np.array([-17., -8., -3., 1., 1., -1., -1., -2., -2.])


def _interp_hl(audiogram, freqs):
    """Interpolate an {Hz: dB HL} audiogram onto `freqs` in log-frequency (dB HL)."""
    af = np.array(sorted(audiogram), float)
    ah = np.array([audiogram[f] for f in sorted(audiogram)], float)
    return np.interp(np.log10(freqs), np.log10(af), ah, left=ah[0], right=ah[-1])


def _three_freq_avg(audiogram):
    """NAL 3-frequency average (mean of HL at 500/1000/2000 Hz), dB HL."""
    af = sorted(audiogram)
    hl = np.interp(np.log10([500., 1000., 2000.]), np.log10(af),
                   [audiogram[f] for f in af])
    return float(hl.mean())


def half_gain(audiogram, freqs, levels=(50., 65., 80.)):
    """Baseline first-fit: gain ~ 0.6*HL for soft, 0.3*HL for loud (linear in level)."""
    hl = _interp_hl(audiogram, freqs)
    frac = np.interp(np.asarray(levels, float), [50., 80.], [0.6, 0.3])
    return frac[:, None] * hl[None, :]                     # gains[level, freq]


def nal_nl2(audiogram, freqs, levels=(50., 65., 80.)):
    """NAL-NL2-style prescription (approximation -- see module docstring).

    REIG_65(f) = X + 0.31*HL(f) + k(f)   (NAL-RP), X = 0.15*H3FA (+ severe-loss term),
    then level-dependent via a modest WDRC ratio CR(f) that grows with loss:
        gain(L,f) = REIG_65(f) + (65 - L)*(1 - 1/CR(f)),  floored at 0.
    """
    freqs = np.asarray(freqs, float)
    hl = _interp_hl(audiogram, freqs)
    avg = _three_freq_avg(audiogram)                       # 3FA (mean of 500/1k/2k), dB HL
    X = 0.15 * avg + (0.2 * (avg - 60.0) if avg > 60.0 else 0.0)   # NAL-RP severe-loss term
    k = np.interp(np.log10(freqs), np.log10(_NALRP_F), _NALRP_K,
                  left=_NALRP_K[0], right=_NALRP_K[-1])
    reig65 = np.maximum(X + 0.31 * hl + k, 0.0)            # NAL-RP 65 dB insertion gain
    cr = np.clip(1.0 + hl / 45.0, 1.0, 2.5)    # NAL-NL2 uses modest compression
    levels = np.asarray(levels, float)
    g = reig65[None, :] + (65.0 - levels)[:, None] * (1.0 - 1.0 / cr)[None, :]
    return np.maximum(g, 0.0)


def dsl_mio(audiogram, freqs, levels=(50., 65., 80.)):
    """DSL m[i/o] v5-style prescription (approximation -- see module docstring).

    Same threshold-referenced form as `nal_nl2` so the two are directly comparable, but
    with DSL's known characteristics: MORE gain overall (~half the loss vs NAL's 0.31
    slope), little low-frequency roll-off (DSL prescribes relatively more LF gain), and
    stronger WDRC (more gain for soft sounds):
        gain(L,f) = 0.5*HL(f) + (65 - L)*(1 - 1/CR(f)),  CR(f) = 1 + HL/30, floored at 0.
    """
    freqs = np.asarray(freqs, float)
    hl = _interp_hl(audiogram, freqs)
    reig65 = 0.5 * hl                                  # more than NAL, no LF roll-off
    cr = np.clip(1.0 + hl / 30.0, 1.0, 3.0)            # stronger compression than NAL-NL2
    levels = np.asarray(levels, float)
    g = reig65[None, :] + (65.0 - levels)[:, None] * (1.0 - 1.0 / cr)[None, :]
    return np.maximum(g, 0.0)


def camfit(audiogram, freqs, levels=(50., 65., 80.)):
    """AUTHORITATIVE CAMFIT (Moore) compression gains -- the one non-proprietary rule we
    can run for real: precomputed by OpenMHA's own `gainrule_camfit_compr.m` (via
    `camfit_octave.m` in the OpenMHA container) and cached in `camfit_cache.json`.

    Unlike nal_nl2/dsl_mio (Python approximations), these are exactly what OpenMHA computes.
    Only the cached (audiogram, freqs, levels) are available -- regenerate the cache with
    `run_camfit.sh` for a different audiogram or band set.
    """
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), "camfit_cache.json")
    if not os.path.exists(path):
        raise RuntimeError("CAMFIT cache missing -- run openmha/run_camfit.sh to build it")
    c = json.load(open(path))
    if [float(f) for f in freqs] != [float(f) for f in c["freqs"]]:
        raise ValueError(f"CAMFIT cache is for freqs {c['freqs']}, got {list(freqs)} "
                         "-- rerun run_camfit.sh")
    if {str(k): v for k, v in dict(audiogram).items()} != c["audiogram"]:
        raise ValueError("CAMFIT cache is for a different audiogram -- rerun run_camfit.sh")
    g = np.array(c["gains"])
    idx = [c["levels"].index(int(L)) for L in levels]     # must be cached levels
    return g[idx, :]


def ours(audiogram, freqs, levels=(50., 65., 80.)):
    """Our own loudness-normalisation, expressed as a prescription for comparison: the
    per-band insertion gain of PersonalizedGainMap (which maps the input level range into
    the listener's residual dynamic range [threshold, UCL])."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "colab"))
    import speech_resynth as sp
    pm = sp.PersonalizedGainMap(np.asarray(freqs, float), audiogram=audiogram)
    L = np.asarray(levels, float)
    out = pm.slope[None, :] * L[:, None] + pm.offset[None, :]     # forward: output level
    return np.maximum(out - L[:, None], 0.0)                      # insertion gain


RULES = {"half_gain": half_gain, "nal_nl2": nal_nl2, "dsl_mio": dsl_mio,
         "camfit": camfit, "ours": ours}


def prescribe(rule, audiogram, freqs, levels=(50., 65., 80.)):
    if rule not in RULES:
        raise ValueError(f"rule must be one of {list(RULES)}, got {rule!r}")
    return RULES[rule](audiogram, freqs, levels)


class GainTableWDRC:
    """Apply a prescription's gaintable as WDRC through the resynthesis pipeline. Per band, the
    insertion gain is interpolated by input level (soft gets more, loud less), then the output is
    limited at an estimated UCL. `forward(L)` matches speech_resynth.run's gain interface, so this
    lets the in-browser tool render NAL-NL2 / DSL fits with the SAME compressor as everything else.
    Pure numpy (no speech_resynth import) so it runs under Pyodide."""

    def __init__(self, fc, audiogram, rule, levels=(40., 55., 65., 80., 95.), ucl_floor=100.):
        self.fc = np.asarray(fc, float)
        self.levels = np.asarray(levels, float)
        self.g = np.asarray(prescribe(rule, audiogram, list(self.fc), levels=levels))   # (n_lev, n_band)
        thr = _interp_hl(audiogram, self.fc)
        self.ucl = np.maximum(ucl_floor, 100.0 + 0.25 * thr) - 5.0

    def forward(self, L):
        L = np.asarray(L, float)
        out = np.empty((len(self.fc),) + L.shape[1:])
        for b in range(len(self.fc)):
            gb = np.interp(L[b], self.levels, self.g[:, b])          # gain drops with level = compression
            out[b] = np.minimum(L[b] + gb, self.ucl[b])              # UCL limiting
        return out
