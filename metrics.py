"""Shared listening metrics so the static gallery and the live 'try your own' tool report the SAME
three numbers for every clip:

  * sii  -- official ANSI S3.5 Speech Intelligibility Index (0-1, higher = more audible)
  * stoi -- Short-Time Objective Intelligibility (0-1, higher = better; vs the clean reference)
  * err  -- dB RMS distance of the achieved insertion gain from the NAL-NL2 target (0 = on target)

`aided` is the processed clip, `clean` the undegraded speech presented at the same level.
"""
import numpy as np

ORDER = ["original", "static", "wdrc", "rx", "nal", "dsl", "cam", "per"]


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


def all_metrics(aided, clean, sr, audiogram):
    """dict(sii, stoi, err) for one clip, rounded for display."""
    import speech_resynth as sp
    import stoi_vendor
    return dict(sii=round(float(sp.official_sii(aided, clean, sr, audiogram)), 2),
                stoi=round(float(stoi_vendor.stoi(clean, aided, sr)), 2),
                err=round(fit_error_db(aided, clean, sr, audiogram), 1))


def poorer_ear_metrics(stereo, clean, sr, ag_l, ag_r):
    """Binaural: metrics of the poorer ear -- min SII/STOI, max (worst) dB-to-target."""
    L = all_metrics(stereo[:, 0], clean, sr, ag_l)
    R = all_metrics(stereo[:, 1], clean, sr, ag_r)
    return dict(sii=min(L["sii"], R["sii"]), stoi=min(L["stoi"], R["stoi"]),
                err=max(L["err"], R["err"]),
                l=L, r=R)                                    # keep per-ear too, for display
