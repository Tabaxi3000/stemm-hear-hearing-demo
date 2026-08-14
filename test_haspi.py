"""Validate the vendored HASPI against The PyClarity Team's own regression value (MIT), and the
`metrics` wrapper that gates HASPI behind full=True (so the Pyodide tool never imports numba)."""
import numpy as np
import pytest

import haspi_vendor as H
import metrics

AG = {250: 20, 500: 30, 1000: 40, 2000: 55, 4000: 70, 8000: 80}


def _gold_fixture():
    np.random.seed(0)
    sr = 16000
    x = np.random.uniform(-1, 1, int(sr * 0.5))
    y = np.random.uniform(-1, 1, int(sr * 0.5))
    ag = H.Audiogram(levels=np.array([45, 45, 35, 45, 60, 65]),
                     frequencies=np.array([250, 500, 1000, 2000, 4000, 6000]))
    return sr, x, y, ag


def test_haspi_matches_pyclarity_gold():
    # Exactly pyclarity's tests/evaluator/haspi/test_haspi.py::test_haspi_v2 fixture + expected value.
    sr, x, y, ag = _gold_fixture()
    score, _ = H.haspi_v2(x, sr, y + x, sr, ag, 65)
    assert score == pytest.approx(0.043808448934532965, abs=1e-3)


def test_hasqi_matches_pyclarity_gold():
    sr, x, y, ag = _gold_fixture()
    score, _, _, _ = H.hasqi_v2(x, sr, y, sr, ag, 1, 65)
    assert score == pytest.approx(0.002525809, abs=1e-3)


def test_haaqi_matches_pyclarity_gold():
    sr, x, y, ag = _gold_fixture()
    score, _, _, _ = H.haaqi_v1(x, sr, y, sr, ag, 1, 65)
    assert score == pytest.approx(0.111290948, abs=1e-3)


def test_metrics_music_gives_haaqi_not_haspi():
    sr = 16000
    rng = np.random.default_rng(3)
    clean = rng.uniform(-1, 1, sr * 2)
    m = metrics.all_metrics(clean, clean, sr, AG, full=True, music=True)
    assert "haaqi" in m and "haspi" not in m and "hasqi" not in m
    assert 0.0 <= m["haaqi"] <= 1.0


def test_metrics_full_adds_haspi_and_default_does_not():
    sr = 16000
    rng = np.random.default_rng(1)
    clean = rng.uniform(-1, 1, sr * 2)
    full = metrics.all_metrics(clean, clean, sr, AG, full=True)
    assert set(full) >= {"sii", "stoi", "err", "haspi", "hasqi"}   # speech -> HASPI + HASQI
    assert 0.0 <= full["haspi"] <= 1.0 and 0.0 <= full["hasqi"] <= 1.0
    # default must NOT compute HASPI (keeps the in-browser tool numba-free)
    assert "haspi" not in metrics.all_metrics(clean, clean, sr, AG)


def test_haspi_incorporates_the_loss():
    # HASPI models the impaired ear, so even a perfect (clean-vs-clean) clip scores below 1 under loss
    sr = 16000
    c = np.random.default_rng(2).uniform(-1, 1, sr * 3)
    heavy = {250: 60, 500: 60, 1000: 65, 2000: 70, 4000: 75, 8000: 80}
    assert metrics.haspi(c, c, sr, heavy) < 1.0
