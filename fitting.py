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


# ----------------------------------------------------------------------------------------
# CAM2 / CAMFIT (compressive Cambridge rule, Moore et al. 1999, Brit. J. Audiol. 33:157-170)
# Faithful Python port of OpenMHA's `gainrule_camfit_compr.m` (+ camfit_linear, isothr,
# freq_interp_sh, LTASS_speech_level_in_frequency_bands). Reproduces OpenMHA's own CAMFIT gains
# to <0.1 dB (validated in openmha/validate_camfit_py.py) but for ANY audiogram, with no Octave/
# Docker -- so the live tool and the subject fits can use the real Cambridge rule.
# Ported from openMHA (AGPLv3, (c) HoerTech gGmbH); attribution retained.
_ISO_F = np.array([0, 20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500,
                   630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000,
                   10000, 12500, 14000, 16000, 18000, 20000.])
_ISO_THR = np.array([80, 78.5, 68.7, 59.5, 51.1, 44, 37.5, 31.5, 26.5, 22.1, 17.9, 14.4, 11.4,
                     8.6, 6.2, 4.4, 3.0, 2.2, 2.4, 3.5, 1.7, -1.3, -4.2, -6.0, -5.4, -1.5, 6.0,
                     12.6, 13.9, 12.3, 18.4, 40.2, 73.2, 70.0])
_LTASS_FREQ = np.array([63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250,
                        1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000.])
_LTASS_LEV = np.array([38.6, 43.5, 54.4, 57.7, 56.8, 60.2, 60.3, 59.0, 62.1, 62.1, 60.5, 56.8,
                       53.7, 53.0, 52.0, 48.7, 48.1, 46.8, 45.6, 44.5, 44.3, 43.7, 43.4, 41.3, 40.7])
_CAM_INT_F = np.array([125, 250, 500, 750, 1000, 1500, 2000, 3000, 4000, 5000, 5005.])
_CAM_INT = np.array([-11, -10, -8, -6, 0, -1, 1, -1, 0, 1, 1.])


def _freq_interp_sh(f_in, y_in, f):
    """Linear interpolation on log-frequency with sample-and-hold on the edges (openMHA
    freq_interp_sh) -- np.interp clamps outside the range, matching the held endpoints."""
    f_in = np.maximum(np.asarray(f_in, float), np.finfo(float).eps)
    return np.interp(np.log(np.asarray(f, float)), np.log(f_in), np.asarray(y_in, float))


def _isothr(f):
    """ISO 226/389 HL->SPL threshold conversion at frequencies f (openMHA isothr)."""
    return np.interp(np.maximum(np.asarray(f, float), 50.0), _ISO_F, _ISO_THR)


def _ltass_band_levels(edge_freqs, target):
    """Physical band levels of an LTASS-shaped signal of broadband `target` dB SPL, summed by
    intensity across the fitmodel bands defined by `edge_freqs` (openMHA LTASS_..._bands)."""
    lf = _LTASS_FREQ
    ledge = np.concatenate([[0.0], np.sqrt(lf[:-1] * lf[1:]), [16000 * 2 ** (1 / 6)]])
    lint = 10 ** (_LTASS_LEV / 10)
    edge = np.asarray(edge_freqs, float)
    out = np.zeros(len(edge) - 1)
    for b in range(len(out)):
        lo, hi = edge[b], edge[b + 1]
        inter_lo = np.maximum(lo, ledge[:-1]); inter_hi = np.minimum(hi, ledge[1:])
        portion = np.maximum(inter_hi - inter_lo, 0.0) / (ledge[1:] - ledge[:-1])
        out[b] = 10 * np.log10(np.sum(lint * portion)) + (target - 70)
    return out


def _camfit_linear_ig(htl, fc):
    """Linear Cambridge insertion gains: 0.48*HL + intercept, non-negative (Moore 1998, part I)."""
    intercepts = _freq_interp_sh(_CAM_INT_F, _CAM_INT, fc)
    ig = np.maximum(htl * 0.48 + intercepts, 0.0)
    return ig * (1.0 if np.any(htl) else 0.0)


def camfit(audiogram, freqs, levels=(50., 65., 80.), max_output_level=100.0):
    """AUTHORITATIVE CAMFIT / CAM2 compression gains (Moore et al. 1999) -- the one
    non-proprietary clinical rule, ported from OpenMHA's own `gainrule_camfit_compr.m`.

    Reproduces OpenMHA's Octave CAMFIT to <0.1 dB but for arbitrary audiograms, so the tool
    and the binaural subject fits can use the real Cambridge rule without Docker. Returns
    gains[len(levels), len(freqs)] in dB (non-negative, limited to `max_output_level` output)."""
    fc = np.asarray(freqs, float)
    edge = np.concatenate([[0.1], np.sqrt(fc[:-1] * fc[1:]), [1e7]])
    speech65 = _ltass_band_levels(edge, 65.0)
    minima_distance = 38.0
    Lmin = speech65 - minima_distance
    Conv = _isothr(fc)
    af = np.array(sorted(audiogram), float); ah = np.array([audiogram[k] for k in sorted(audiogram)], float)
    htl = _freq_interp_sh(af, ah, fc)
    Gmin = htl + Conv - Lmin
    Gmid = _camfit_linear_ig(htl, fc)                                   # Lmid = speech65
    cr = np.maximum(minima_distance / np.maximum(speech65 + Gmid - Lmin - Gmin, 13.0), 1.0)
    lev = np.asarray(levels, float)[:, None]
    g = ((lev - Lmin[None, :]) / cr[None, :] + (Lmin + Gmin)[None, :]) - lev   # gains() helper
    g = (g + np.abs(g)) / 2                                              # no negative gain
    out_levels = g + lev
    g = g - (out_levels - np.minimum(out_levels, max_output_level))      # cap band output level
    return g * (1.0 if np.any(htl) else 0.0)


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
