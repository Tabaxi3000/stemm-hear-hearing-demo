"""Incremental engine for the 'try your own' tool. The browser drives this one fit at a time
(tool_setup -> tool_fit per key -> tool_collect), yielding to the UI between calls so a long run
never blocks the main thread -- no 'page unresponsive' popups, and a progress bar can update.

State lives in the module-level _S dict between calls (one ear at a time)."""
import numpy as np
import speech_resynth as sp
import fitting
import metrics

_FC = sp.band_centres(sp.band_edges(100.0, 12000.0, 32, "greenwood"))
_CM = dict(backend="stft", n_bands=32, flo=100.0, fhi=12000.0, carrier="original",
           loud_ref=sp.dbfs_ref_for_spl(100.0), match_rms=False, gate_db=-45.0, gate_knee_db=18.0)
ORDER = ["original", "static", "wdrc", "rx", "nal", "dsl", "cam", "per"]
_S = {}


def _present(y, spl):
    return y / (np.sqrt(np.mean(y ** 2)) + 1e-12) * 10 ** ((spl - 100) / 20)


def tool_setup(xin, agf, agv, sr, spl, flow, noise, ntype, rev, nr, gap, ohc, prog, rel):
    """Build the clean/degraded signals + the fit objects for one ear. Returns the fit key order."""
    ag = {int(f): float(v) for f, v in zip(list(agf), list(agv))}
    x = np.asarray(xin.to_py() if hasattr(xin, "to_py") else xin, dtype=float)
    if flow > 1.01:
        x = sp.frequency_compress(x, sr, f_start=1500.0, ratio=flow)
    xclean = _present(x, spl)                                     # clean reference (for STOI / target)
    xn = x
    if rev > 0.05:
        xn = sp.reverb(xn, sr, rev)
    if noise >= 0:
        xn = sp.add_noise(xn, float(noise), ntype)
    xin2 = _present(xn, spl)                                      # degraded, presented at chosen SPL
    xfit = xin2
    if nr:
        xfit = _present(sp.denoise(xin2, sr), spl)               # aid-side denoiser
    pm = sp.PersonalizedGainMap(_FC, audiogram=ag)
    GAINS = {"static": (pm, False), "wdrc": (pm, True), "rx": (sp.PrescriptiveGain(_FC, ag), True),
             "nal": (fitting.GainTableWDRC(_FC, ag, "nal_nl2"), True),
             "dsl": (fitting.GainTableWDRC(_FC, ag, "dsl_mio"), True),
             "cam": (fitting.GainTableWDRC(_FC, ag, "camfit"), True),
             "per": (sp.PersonalizedWDRC(_FC, audiogram=ag, airbone_gap=gap, ohc_health=ohc), True)}
    _S.clear()
    _S.update(ag=ag, sr=int(sr), xclean=xclean, xfit=xfit,
              rel_eff=(800.0 if prog == "music" else float(rel)), GAINS=GAINS,
              OUT={"original": xin2.astype("float32")},
              MET={"original": metrics.all_metrics(xin2, xclean, int(sr), ag)})
    return ORDER


def tool_fit(k):
    """Process ONE fit (one full DSP pass + metrics) and stash it. Called once per key."""
    g, dyn = _S["GAINS"][k]
    y = sp.run(_S["xfit"], _S["sr"], gain=g, attack_ms=(5 if dyn else None),
               release_ms=(_S["rel_eff"] if dyn else None), **_CM)["waveform"]
    _S["OUT"][k] = y.astype("float32")
    _S["MET"][k] = metrics.all_metrics(y, _S["xclean"], _S["sr"], _S["ag"])


def tool_losssim():
    """Optionally play every clip back through a simulation of the loss ('hear as the patient')."""
    LS = sp.HearingLossSim(_FC, _S["ag"])
    for k in list(_S["OUT"]):
        _S["OUT"][k] = sp.run(np.asarray(_S["OUT"][k], dtype=float), _S["sr"], gain=LS,
                              **_CM)["waveform"].astype("float32")


def tool_get(k):
    return _S["OUT"][k]


def tool_metrics():
    return [[_S["MET"][k]["sii"] for k in ORDER],
            [_S["MET"][k]["stoi"] for k in ORDER],
            [_S["MET"][k]["err"] for k in ORDER]]
