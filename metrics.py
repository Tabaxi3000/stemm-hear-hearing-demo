"""Shared listening metrics so the static gallery and the live 'try your own' tool report the SAME
three numbers for every clip:

  * sii   -- official ANSI S3.5 Speech Intelligibility Index (0-1, higher = more audible)
  * stoi  -- Short-Time Objective Intelligibility (0-1, higher = better; vs the clean reference)
  * err   -- dB RMS distance of the achieved insertion gain from the NAL-NL2 target (0 = on target)
  * haspi -- (offline only, `full=True`) HASPI v2, a hearing-aid-specific intelligibility index that
             models the impaired periphery from the audiogram. Needs numba, so it is NOT computed in
             the in-browser tool (Pyodide) -- only in the static gallery / Colab.

`aided` is the processed clip, `clean` the undegraded speech presented at the same level.
"""
import numpy as np

ORDER = ["original", "static", "wdrc", "rx", "nal", "dsl", "cam", "per"]
_HASPI_FREQS = [250, 500, 1000, 2000, 4000, 6000]           # HASPI's fixed audiometric frequencies


def band_levels(y, sr, mbf):
    """One-third-octave band levels (dB) at the SII mid-band centres -- matches the tool's _bl18."""
    Y = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
    ff = np.fft.rfftfreq(len(y), 1 / sr)
    return np.array([10 * np.log10(Y[(ff >= f0 / 2 ** (1 / 6)) & (ff < f0 * 2 ** (1 / 6))].sum() + 1e-12)
                     for f0 in mbf])


def fit_error_db(aided, clean, sr, audiogram, rule="nal_nl2"):
    """dB RMS between the clip's insertion gain (aided - clean band levels) and the `rule` target."""
    import sii
    import fitting
    mbf = np.asarray(sii.mid_band_freqs, float)
    tgt = np.asarray(fitting.prescribe(rule, audiogram, list(mbf), (65.0,)))[0]
    ig = band_levels(aided, sr, mbf) - band_levels(clean, sr, mbf)
    return float(np.sqrt(np.mean((ig - tgt) ** 2)))


def haspi(aided, clean, sr, audiogram, cap_s=8.0):
    """HASPI v2 (Kates & Arehart) intelligibility (0-1) -- a hearing-aid-specific metric that models
    the impaired periphery from the audiogram (so even clean-vs-clean scores below 1 under a loss).
    Reference = clean (unamplified), processed = aided. Heavy (auditory model); analysed on the first
    `cap_s` s, where the score is already stable. Requires the vendored HASPI package + numba."""
    import haspi_vendor as H
    n = int(cap_s * sr)
    clean = np.asarray(clean, float); aided = np.asarray(aided, float)
    # HASPI calibration: RMS=1 <-> level1 (65) dB SPL. Our clips sit at ~-35 dBFS, so scale the CLEAN
    # reference to RMS=1 (= 65 dB SPL) and apply the SAME scale to the processed (keeps the aid's gain).
    scale = 1.0 / (np.sqrt(np.mean(clean ** 2)) + 1e-12)
    ref = clean[:n] * scale
    proc = aided[:n] * scale
    af = sorted(audiogram)
    hl = np.interp(np.log10(_HASPI_FREQS), np.log10(af), [audiogram[k] for k in af],
                   left=audiogram[af[0]], right=audiogram[af[-1]])
    ag = H.Audiogram(levels=np.asarray(hl, float), frequencies=np.asarray(_HASPI_FREQS))
    score, _ = H.haspi_v2(ref, sr, proc, sr, ag, level1=65.0)
    return round(float(score), 2)


def all_metrics(aided, clean, sr, audiogram, full=False):
    """dict(sii, stoi, err[, haspi]) for one clip, rounded for display. `full=True` adds HASPI
    (offline only -- needs numba, so callers in the Pyodide tool leave it False)."""
    import speech_resynth as sp
    import stoi_vendor
    out = dict(sii=round(float(sp.official_sii(aided, clean, sr, audiogram)), 2),
               stoi=round(float(stoi_vendor.stoi(clean, aided, sr)), 2),
               err=round(fit_error_db(aided, clean, sr, audiogram), 1))
    if full:
        out["haspi"] = haspi(aided, clean, sr, audiogram)
    return out


def poorer_ear_metrics(stereo, clean, sr, ag_l, ag_r, full=False):
    """Binaural: metrics of the poorer ear -- min SII/STOI/HASPI, max (worst) dB-to-target."""
    L = all_metrics(stereo[:, 0], clean, sr, ag_l, full=full)
    R = all_metrics(stereo[:, 1], clean, sr, ag_r, full=full)
    out = dict(sii=min(L["sii"], R["sii"]), stoi=min(L["stoi"], R["stoi"]),
               err=max(L["err"], R["err"]), l=L, r=R)        # keep per-ear too, for display
    if full:
        out["haspi"] = min(L["haspi"], R["haspi"])
    return out
