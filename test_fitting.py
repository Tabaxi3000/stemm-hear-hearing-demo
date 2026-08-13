"""Regression tests for the prescriptive fitting rules -- run with `pytest` from this directory.
Locks the CAM2/CAMFIT port to OpenMHA's own output and checks the WDRC gaintable behaves like a
compressor (soft sounds get more gain than loud, output rises monotonically with input)."""
import numpy as np
import pytest

import speech_resynth as sp
import fitting

FC = sp.band_centres(sp.band_edges(100.0, 12000.0, 32, "greenwood"))
BANDS = [250., 500, 1000, 2000, 4000]
LEVELS = [50., 65, 80]

SLOPING = {250: 20, 500: 25, 1000: 30, 2000: 40, 4000: 55, 8000: 65}
SKISLOPE = {250: 15, 500: 20, 1000: 30, 2000: 50, 4000: 70, 8000: 80}

# Golden CAMFIT gains straight out of OpenMHA's Octave gainrule_camfit_compr (rows = 50/65/80 dB,
# cols = 250/500/1000/2000/4000 Hz), captured from the Docker renders.
GOLDEN = {
    "sloping": np.array([[2.4083, 4.6014, 14.5605, 20.1558, 25.7799],
                         [0.0000, 3.8097, 14.0485, 17.4918, 20.6440],
                         [0.0000, 3.0180, 13.5365, 14.8277, 15.5081]]),
    "skislope": np.array([[0.9208, 1.0057, 14.5605, 24.9217, 32.6082],
                          [0.0000, 1.0057, 14.0485, 20.2051, 24.3933],
                          [0.0000, 1.0057, 13.5365, 15.4884, 16.1784]]),
}


@pytest.mark.parametrize("name,ag", [("sloping", SLOPING), ("skislope", SKISLOPE)])
def test_camfit_matches_openmha(name, ag):
    got = fitting.camfit(ag, BANDS, LEVELS)
    assert np.allclose(got, GOLDEN[name], atol=0.05), f"{name}: max Δ {np.abs(got - GOLDEN[name]).max():.3f} dB"


def test_camfit_any_audiogram_is_sane():
    rng = np.random.default_rng(0)
    for _ in range(20):
        ag = {f: float(rng.integers(0, 90)) for f in (250, 500, 1000, 2000, 4000, 8000)}
        g = fitting.camfit(ag, list(FC), LEVELS)
        assert np.all(np.isfinite(g))
        assert np.all(g >= -1e-9)                                   # non-negative gains
        assert np.all(g + np.array(LEVELS)[:, None] <= 100.0 + 1e-6)  # output capped at 100 dB SPL


def test_camfit_flat_normal_is_zero():
    ag = {f: 0.0 for f in (250, 500, 1000, 2000, 4000, 8000)}
    assert np.allclose(fitting.camfit(ag, BANDS, LEVELS), 0.0)


def test_gaintable_is_compressive():
    gt = fitting.GainTableWDRC(FC, SLOPING, "dsl_mio", levels=(40., 55, 65, 80, 95))
    # soft inputs get at least as much gain as loud inputs in every band (WDRC)
    assert np.all(gt.g[0] >= gt.g[-1] - 1e-6)
    # forward(): output rises with input, but gain falls (compression)
    L = np.tile(np.array([30., 50, 70, 90]), (len(FC), 1))
    out = gt.forward(L)
    assert np.all(np.diff(out, axis=1) >= -1e-6)                    # output monotonic up
    assert np.all(np.diff(out - L, axis=1) <= 1e-6)                 # insertion gain monotonic down


def test_dsl_prescribes_more_gain_than_nal():
    nal = fitting.prescribe("nal_nl2", SLOPING, list(FC), (65.,))[0]
    dsl = fitting.prescribe("dsl_mio", SLOPING, list(FC), (65.,))[0]
    assert dsl.mean() > nal.mean()
    assert np.all(nal >= -1e-9) and np.all(dsl >= -1e-9)
