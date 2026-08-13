"""Regression tests for the shared listening metrics (SII / STOI / dB-to-target) and the
resynthesis pipeline. Keeps the numbers the website reports in a sane, self-consistent range."""
import numpy as np
import pytest

import speech_resynth as sp
import metrics

SR = 16000
FC = sp.band_centres(sp.band_edges(100.0, 7200.0, 28, "greenwood"))
AG = {250: 30, 500: 40, 1000: 50, 2000: 55, 4000: 65, 8000: 70}
COMMON = dict(backend="stft", n_bands=28, flo=100.0, fhi=7200.0, carrier="original",
              loud_ref=sp.dbfs_ref_for_spl(100.0), match_rms=False, gate_db=-45.0, gate_knee_db=18.0)


def _speechlike(seconds=1.5, seed=0):
    """A flat broadband signal at ~65 dB SPL -- energy in every band (incl. the highs the fit
    amplifies), enough for SII/STOI to be meaningful."""
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(int(seconds * SR))
    return x / (np.sqrt(np.mean(x ** 2)) + 1e-12) * 10 ** ((65 - 100) / 20)


def test_all_metrics_ranges():
    clean = _speechlike()
    m = metrics.all_metrics(clean, clean, SR, AG)
    assert 0.0 <= m["sii"] <= 1.0
    assert -1.0 <= m["stoi"] <= 1.0
    assert m["err"] >= 0.0


def test_stoi_of_clean_against_itself_is_high():
    clean = _speechlike()
    assert metrics.all_metrics(clean, clean, SR, AG)["stoi"] >= 0.99


def test_a_fit_amplifies_highs_and_never_lowers_sii():
    import sii as sii_mod
    clean = _speechlike()
    aided = sp.run(clean, SR, gain=fitting_gain("dsl_mio"), attack_ms=5, release_ms=150, **COMMON)["waveform"]
    # a fit must not make speech LESS audible than unaided
    assert sp.official_sii(aided, clean, SR, AG) >= sp.official_sii(clean, clean, SR, AG) - 1e-6
    # and it must genuinely boost the impaired highs (real insertion gain around 1.5-4 kHz)
    mbf = np.asarray(sii_mod.mid_band_freqs, float)
    ig = metrics.band_levels(aided, SR, mbf) - metrics.band_levels(clean, SR, mbf)
    assert ig[(mbf >= 1500) & (mbf <= 4000)].mean() > 3.0


def fitting_gain(rule="camfit"):
    import fitting
    return fitting.GainTableWDRC(FC, AG, rule)


def test_poorer_ear_is_the_worse_of_two():
    clean = _speechlike()
    good = {f: 5.0 for f in AG}                              # near-normal ear
    stereo = np.stack([clean, clean], 1)
    p = metrics.poorer_ear_metrics(stereo, clean, SR, good, AG)
    assert p["sii"] == min(p["l"]["sii"], p["r"]["sii"])
    assert p["err"] == max(p["l"]["err"], p["r"]["err"])
    assert p["l"]["sii"] >= p["r"]["sii"] - 1e-9             # the near-normal ear is at least as audible


def test_resynth_roundtrip_shape_and_finiteness():
    clean = _speechlike()
    y = sp.run(clean, SR, gain=fitting_gain(), attack_ms=5, release_ms=150, **COMMON)["waveform"]
    assert np.all(np.isfinite(y))
    assert abs(len(y) - len(clean)) <= 1
    assert np.max(np.abs(y)) < 4.0                           # no runaway gain
