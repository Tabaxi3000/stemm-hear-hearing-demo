"""speech_resynth -- flat, single-file version for Colab / GitHub.

A deliberately flat namespace so you can do:

    from speech_resynth import *

and call analyze(), run(), GenericGainMap(...) etc. with no package prefixes.
Depends only on numpy + scipy (both preinstalled in Colab).

This is the "first version" of the STEMM-HEAR filter-bank resynthesis: take the
ANALYSIS filterbank from egaudrain/vocoder (Greenwood place map + butterworth bands,
re-implemented in Python), drop the noise carrier so summing the bands rebuilds the
speech, and apply a non-linear gain that is a straight line in dB (so it inverts exactly).
"""

from __future__ import annotations

import numpy as np
from scipy import signal

__all__ = [
    "frq2mm", "mm2frq", "greenwood_hz", "greenwood_frac", "band_edges", "band_centres",
    "analyze", "analyze_butter_greenwood", "analyze_fir", "analyze_stft",
    "extract_envelope", "make_carrier",
    "LevelDB", "PerceptualLoudness", "get_measure", "dbfs_ref_for_spl",
    "GenericGainMap",
    "EXAMPLE_AUDIOGRAM", "audiogram_thresholds", "PersonalizedGainMap", "PrescriptiveGain", "PersonalizedWDRC",
    "time_stretch", "frequency_compress",
    "run", "binaural", "make_speech_like", "HearingLossSim", "audibility", "add_noise", "denoise", "official_sii", "reverb",
]

# --------------------------------------------------------------------------- #
# 1. Greenwood place map + analysis filterbanks (the egaudrain/vocoder analysis part)
# --------------------------------------------------------------------------- #
# Basilar-membrane place map, byte-for-byte the egaudrain/vocoder frq2mm.m / mm2frq.m
# (Greenwood integration constant = 1, spaced LINEARLY IN MM). Using the exact reference
# map -- not the classic normalised-[0,1] Greenwood (const 0.88) -- so our band edges
# match vocoder-master/greenwud.m to machine precision. See docs / parity test.
_GW_A, _GW_K = 0.06, 165.4      # a (per-mm slope), k (apex constant, Hz)


def frq2mm(f):
    """Frequency (Hz) -> basilar-membrane place (mm). egaudrain frq2mm.m."""
    return (1.0 / _GW_A) * np.log10(np.asarray(f, float) / _GW_K + 1.0)


def mm2frq(mm):
    """Basilar-membrane place (mm) -> frequency (Hz). egaudrain mm2frq.m."""
    return _GW_K * (10.0 ** (_GW_A * np.asarray(mm, float)) - 1.0)


# Back-compat aliases (older cells called these); same underlying reference map.
greenwood_frac = frq2mm
greenwood_hz = mm2frq


def band_edges(flo, fhi, n_bands, spacing="greenwood"):
    """Filter-bank band edges. 'greenwood' reproduces vocoder-master/greenwud.m:
    equal spacing in mm between frq2mm(flo) and frq2mm(fhi)."""
    if spacing == "greenwood":
        places = np.linspace(frq2mm(flo), frq2mm(fhi), n_bands + 1)
        return mm2frq(places)
    if spacing == "log":
        return np.geomspace(flo, fhi, n_bands + 1)
    if spacing == "linear":
        return np.linspace(flo, fhi, n_bands + 1)
    raise ValueError(f"unknown spacing {spacing!r}")


def band_centres(edges):
    return np.sqrt(edges[:-1] * edges[1:])


def analyze_butter_greenwood(x, sr, flo=100.0, fhi=8000.0, n_bands=16,
                             order=3, spacing="greenwood"):
    """Butterworth band-pass bank on a Greenwood map (port of filter_bands.m +
    greenwud.m from egaudrain/vocoder). Zero-phase via sosfiltfilt."""
    x = np.asarray(x, float)
    edges = band_edges(flo, fhi, n_bands, spacing)
    nyq = sr / 2.0
    bands = np.zeros((n_bands, x.shape[0]))
    for i in range(n_bands):
        lo = max(edges[i], 1.0) / nyq
        hi = min(edges[i + 1], nyq * 0.999) / nyq
        sos = signal.butter(order, [lo, hi], btype="bandpass", output="sos")
        bands[i] = signal.sosfiltfilt(sos, x)
    return bands, band_centres(edges)


def analyze_fir(x, sr, flo=100.0, fhi=8000.0, n_bands=16, spacing="greenwood",
                numtaps=513):
    """Linear-phase FIR band-pass bank, zero-phase via filtfilt (alternative bank)."""
    x = np.asarray(x, float)
    edges = band_edges(flo, fhi, n_bands, spacing)
    nyq = sr / 2.0
    numtaps = int(numtaps) | 1
    bands = np.zeros((n_bands, x.shape[0]))
    for i in range(n_bands):
        lo, hi = max(edges[i], 1.0), min(edges[i + 1], nyq * 0.999)
        b = signal.firwin(numtaps, [lo / nyq, hi / nyq], pass_zero="bandpass")
        bands[i] = signal.filtfilt(b, [1.0], x)
    return bands, band_centres(edges)


def analyze_stft(x, sr, flo=100.0, fhi=8000.0, n_bands=16, spacing="greenwood",
                 win=1024, hop=None):
    """Perfect-reconstruction STFT / overlap-add bank.

    Every FFT bin is assigned to exactly one band (bins below `flo` fold into the lowest
    band, bins above `fhi` into the highest), each band is inverse-transformed on its own,
    and the frames are COLA-normalised. Because the bins partition the spectrum, summing
    the (unmodified) band signals returns the input to ~machine precision -- the
    transparent-reconstruction bank, in contrast to the ~28 dB ceiling of the butterworth
    bank. Same (bands[n,T], centre_freqs[n]) contract as the other backends.
    """
    x = np.asarray(x, float)
    T = x.shape[0]
    win = int(win)
    hop = win // 4 if hop is None else int(hop)
    w = signal.windows.hann(win, sym=False)
    edges = band_edges(flo, fhi, n_bands, spacing)
    fbin = np.fft.rfftfreq(win, d=1.0 / sr)                 # bin centre freqs (Hz)
    # assign each bin to a band; clamp so nothing is dropped (perfect reconstruction)
    which = np.clip(np.searchsorted(edges, fbin, side="right") - 1, 0, n_bands - 1)

    pad = win
    xp = np.concatenate([np.zeros(pad), x, np.zeros(pad + win)])
    starts = np.arange(0, len(xp) - win, hop)
    acc = np.zeros((n_bands, len(xp)))
    norm = np.zeros(len(xp))                                # COLA normaliser (sum of w^2)
    for s in starts:
        frame = xp[s:s + win] * w
        spec = np.fft.rfft(frame)
        norm[s:s + win] += w * w
        for b in range(n_bands):
            sub = np.where(which == b, spec, 0.0)
            acc[b, s:s + win] += w * np.fft.irfft(sub, n=win)
    norm = np.where(norm > 1e-12, norm, 1.0)
    bands = acc[:, pad:pad + T] / norm[pad:pad + T]
    return bands, band_centres(edges)


BACKENDS = {"butter_greenwood": analyze_butter_greenwood, "fir": analyze_fir,
            "stft": analyze_stft}


def analyze(x, sr, backend="butter_greenwood", **kw):
    """Split x into bands. Returns (bands[n,T], centre_freqs[n])."""
    return BACKENDS[backend](x, sr, **kw)


# --------------------------------------------------------------------------- #
# 2. Envelope + carrier ('original' = noise removed)
# --------------------------------------------------------------------------- #
def extract_envelope(band, sr, method="hilbert", lpf_hz=160.0, order=2):
    band = np.asarray(band, float)
    env = np.abs(signal.hilbert(band)) if method == "hilbert" else np.abs(band)
    if lpf_hz and lpf_hz > 0:
        sos = signal.butter(order, lpf_hz / (sr / 2.0), btype="low", output="sos")
        env = signal.sosfiltfilt(sos, env)
    return np.maximum(env, 0.0)


def make_carrier(kind, band, fc, sr, rng=None, band_lo=None, band_hi=None):
    """'original' keeps the band's fine structure (natural speech); 'noise' = the
    classic CI noise-vocoder carrier (kept only for the before/after comparison).

    The 'noise' carrier is **band-limited** to [band_lo, band_hi] when those are given,
    so summing the bands yields a *canonical* channel vocoder (each channel's noise stays
    in its own frequency region) rather than broadband hiss. Without edges it falls back to
    white noise (the old behaviour)."""
    if kind == "original":
        return band
    if kind == "noise":
        rng = np.random.default_rng() if rng is None else rng
        noise = rng.standard_normal(band.shape[0])
        if band_lo is not None and band_hi is not None:          # -> canonical vocoder
            nyq = sr / 2.0
            lo, hi = max(float(band_lo), 1.0) / nyq, min(float(band_hi), nyq * 0.999) / nyq
            if 0.0 < lo < hi < 1.0:
                noise = signal.sosfiltfilt(
                    signal.butter(4, [lo, hi], btype="bandpass", output="sos"), noise)
        return noise
    if kind == "tone":
        f = fc if band_lo is None else float(np.clip(fc, band_lo, band_hi))
        return np.sin(2 * np.pi * f * np.arange(band.shape[0]) / sr)
    raise ValueError(f"unknown carrier {kind!r}")


# --------------------------------------------------------------------------- #
# 3. Loudness (exact, invertible) + gain (straight line in dB, optional knee)
# --------------------------------------------------------------------------- #
class LevelDB:
    """L = 20*log10(env/ref); inverse is exact. The 'straight line, trivial to
    invert' loudness domain."""

    def __init__(self, ref=1.0, floor_db=-80.0):
        self.ref, self.floor_db = float(ref), float(floor_db)

    def forward(self, env):
        floor = self.ref * 10.0 ** (self.floor_db / 20.0)
        return 20.0 * np.log10(np.maximum(np.asarray(env, float), floor) / self.ref)

    def inverse(self, L):
        return self.ref * 10.0 ** (np.asarray(L, float) / 20.0)


class PerceptualLoudness:
    """Stevens power-law loudness in phon-like units (monotone -> invertible).

    specific loudness  N = (env/ref)**exponent      (power law, exp ~0.3)
    loudness level      P = 40 + 33.22*log10(N)      (sone<->phon, ~10 phon/doubling)
    Analytic inverse (a power law inverts exactly). An alternative to LevelDB when you
    want the gain map drawn in perceptual (phon) units instead of raw dB.
    """

    def __init__(self, ref=1.0, floor_db=-80.0, exponent=0.3):
        self.ref, self.floor_db, self.exponent = float(ref), float(floor_db), float(exponent)
        self._k = 33.219280948873624  # 10/log10(2)

    def forward(self, env):
        floor = self.ref * 10.0 ** (self.floor_db / 20.0)
        p = np.maximum(np.asarray(env, float), floor) / self.ref
        return 40.0 + self._k * np.log10(p ** self.exponent)

    def inverse(self, P):
        P = np.asarray(P, float)
        return self.ref * 10.0 ** ((P - 40.0) / (self._k * self.exponent))


MEASURES = {"level_db": LevelDB, "perceptual": PerceptualLoudness}


def get_measure(name, **kw):
    if name not in MEASURES:
        raise ValueError(f"loudness must be one of {list(MEASURES)}, got {name!r}")
    return MEASURES[name](**kw)


def dbfs_ref_for_spl(full_scale_spl_db=100.0):
    """Loudness ref so a full-scale amplitude (1.0) reads `full_scale_spl_db` dB SPL.

    Pass as `loud_ref` to run() to work in real dB SPL: L = 20*log10(env/ref) with
    ref = 10**(-full_scale_spl/20). e.g. full_scale=100 -> a -40 dBFS sound reads 60 dB.
    This is what puts band levels in the [0,100] domain the audiogram map expects.
    """
    return 10.0 ** (-full_scale_spl_db / 20.0)


class GenericGainMap:
    """L_out = slope*L_in + offset (single line), or a WDRC knee (two joined lines).
    slope = 1/compression_ratio. Invertible by algebra."""

    def __init__(self, slope=0.5, offset=0.0, out_max=None, knee_db=None, gain_db=None):
        self.slope, self.offset, self.out_max = float(slope), float(offset), out_max
        self.knee_db = None if knee_db is None else float(knee_db)
        self.gain_db = float(offset if gain_db is None else gain_db)
        if self.knee_db is not None:
            self.knee_out = self.knee_db + self.gain_db
            self.offset_up = self.knee_out - self.slope * self.knee_db

    def forward(self, L):
        L = np.asarray(L, float)
        if self.knee_db is None:
            out = self.slope * L + self.offset
        else:
            out = np.where(L <= self.knee_db, L + self.gain_db,
                           self.slope * L + self.offset_up)
        return out if self.out_max is None else np.minimum(out, self.out_max)

    def inverse(self, Lo):
        Lo = np.asarray(Lo, float)
        if self.knee_db is None:
            return (Lo - self.offset) / self.slope
        return np.where(Lo <= self.knee_out, Lo - self.gain_db,
                        (Lo - self.offset_up) / self.slope)


# --------------------------------------------------------------------------- #
# 3b. Personalised gain: one straight line PER BAND, driven by an audiogram
# --------------------------------------------------------------------------- #
# Example: mild-to-moderate sloping high-frequency loss (dB HL).
EXAMPLE_AUDIOGRAM = {125: 15, 250: 20, 500: 25, 1000: 30, 2000: 45, 4000: 60, 8000: 70}


def audiogram_thresholds(fc, audiogram=None):
    """Interpolate an audiogram {freq_hz: threshold_db} onto band centres fc (Hz).

    Interpolation is in log-frequency (audiogram convention); returns dB HL per band.
    """
    audiogram = EXAMPLE_AUDIOGRAM if audiogram is None else audiogram
    ag_f = np.array(sorted(audiogram), dtype=float)
    ag_db = np.array([audiogram[f] for f in sorted(audiogram)], dtype=float)
    return np.interp(np.log10(fc), np.log10(ag_f), ag_db, left=ag_db[0], right=ag_db[-1])


class PersonalizedGainMap:
    """Per-band WDRC line driven by the listener's residual dynamic range.

    For band b: threshold T_b (from the audiogram) and uncomfortable level U_b bound the
    range the listener can use. We map the normal-hearing input range [in_lo, in_hi]
    linearly onto [T_b, U_b], so soft sounds are lifted to audibility and the whole band
    is compressed into the residual range -- exactly the hearing-aid fitting idea, and
    still a straight line per band (invertible by algebra). Pair with dB-SPL calibration
    (loud_ref=dbfs_ref_for_spl(...)) so L_in lands in [in_lo, in_hi]."""

    def __init__(self, fc, audiogram=None, in_lo=0.0, in_hi=100.0,
                 headroom_db=5.0, ucl_floor=95.0):
        self.fc = np.asarray(fc, float)
        self.in_lo, self.in_hi = float(in_lo), float(in_hi)
        thr = audiogram_thresholds(self.fc, audiogram)                 # T_b
        ucl = np.maximum(ucl_floor, 100.0 + 0.25 * thr) - headroom_db  # U_b
        self.threshold_db, self.ucl_db = thr, ucl
        self.slope = (ucl - thr) / (self.in_hi - self.in_lo)
        self.offset = thr - self.slope * self.in_lo

    def forward(self, L):
        L = np.asarray(L, float)
        return self.slope[:, None] * L + self.offset[:, None]

    def inverse(self, Lo):
        Lo = np.asarray(Lo, float)
        return (Lo - self.offset[:, None]) / self.slope[:, None]

    def describe(self):
        lines = ["per-band  L_out = slope*L_in + offset:"]
        for f, s, o, t in zip(self.fc, self.slope, self.offset, self.threshold_db):
            lines.append(f"  {f:7.0f} Hz : slope={s:.3f} offset={o:6.1f}  (thr={t:.0f} dB)")
        return "\n".join(lines)


class PrescriptiveGain:
    """A realistic fit instead of full lift-to-threshold. Rather than mapping soft input all the way
    up to threshold (which pours 40-60 dB into a steep high-frequency loss and over-amplifies
    sibilants), this prescribes HALF the loss (Lybarger half-gain rule) with a high-frequency rolloff
    and a gain cap, applies WDRC compression above a knee, and limits the output at UCL.

    Per band b: soft-speech insertion gain g0_b = clip(frac*T_b - rolloff(f_b), 0, gmax), where
    rolloff = roll_db_oct dB per octave above roll_from Hz. forward(L) reduces that gain above the
    compression knee (ratio cr) and caps the output at U_b. Pair with dB-SPL calibration like the
    other maps (loud_ref=dbfs_ref_for_spl(...))."""

    def __init__(self, fc, audiogram=None, frac=0.5, roll_from=2000.0, roll_db_oct=6.0,
                 gmax=42.0, cr=2.2, knee_db=45.0, ucl_floor=100.0, headroom_db=5.0):
        self.fc = np.asarray(fc, float)
        thr = audiogram_thresholds(self.fc, audiogram)
        roll = np.maximum(0.0, np.log2(np.maximum(self.fc, 1.0) / roll_from)) * roll_db_oct
        self.g0 = np.clip(frac * thr - roll, 0.0, gmax)                 # soft-speech insertion gain
        self.ucl = np.maximum(ucl_floor, 100.0 + 0.25 * thr) - headroom_db
        self.threshold_db, self.cr, self.knee = thr, float(cr), float(knee_db)

    def forward(self, L):
        L = np.asarray(L, float)
        g = self.g0[:, None] - np.maximum(0.0, L - self.knee) * (1.0 - 1.0 / self.cr)   # WDRC above knee
        return np.minimum(L + np.maximum(g, 0.0), self.ucl[:, None])                     # UCL limit


class PersonalizedWDRC:
    """Realistic per-band WDRC: a low-level EXPANSION knee + wide-dynamic-range compression +
    output limiting, driven by the audiogram, an (estimated) UCL, AND the conductive/sensorineural
    split of the loss. A more clinical gain application than the single straight line above.

    Regions in input level L (dB SPL), per band b:
      - below the expansion floor EF:      ~no gain (don't amplify mic hiss / room noise);
      - EF .. CT (the expansion knee):     gain ramps up to the soft-speech target (expansion);
      - CT .. in_hi:                       WDRC from threshold T_b toward UCL U_b, at a compression
                                           ratio CR_b set by the residual dynamic range AND the
                                           SENSORINEURAL fraction (a conductive loss has a healthy
                                           cochlea -> little recruitment -> CR ~ 1, i.e. more linear);
      - output capped at U_b:              limiting.
    Pass `airbone_gap` (dB, scalar or per-band) to personalise the conductive component. `forward(L)`
    returns the output level (used by run()); a monotone numeric `inverse()` is provided too."""

    def __init__(self, fc, audiogram=None, airbone_gap=0.0, ohc_health=None, in_lo=0.0,
                 in_hi=100.0, headroom_db=5.0, ucl_floor=95.0, expansion_floor=25.0,
                 expansion_knee=42.0, ref_level=65.0):
        self.fc = np.asarray(fc, float)
        thr = audiogram_thresholds(self.fc, audiogram)                     # T_b (dB HL ~ SPL)
        ucl = np.maximum(ucl_floor, 100.0 + 0.25 * thr) - headroom_db      # U_b (estimated)
        # conductive component from the (per-band) AIR-BONE GAP -> sensorineural fraction
        abg = np.clip(np.broadcast_to(np.asarray(airbone_gap, float), thr.shape), 0.0, None)
        snf = np.clip(1.0 - abg / np.maximum(thr, 1e-6), 0.0, 1.0)         # 1=pure SNHL, 0=conductive
        # recruitment (the need for compression) comes from OUTER-HAIR-CELL loss. If DPOAE says the
        # OHCs still work (ohc_health -> 1), the sensorineural loss is more neural/IHC -> less
        # recruitment -> a more linear fit, even with an elevated threshold.
        recruit = snf if ohc_health is None else snf * (1.0 - 0.6 * np.clip(
            np.broadcast_to(np.asarray(ohc_health, float), thr.shape), 0.0, 1.0))
        slope = (ucl - thr) / (in_hi - in_lo)                              # full-recruitment slope
        cr = 1.0 + (1.0 / np.maximum(slope, 1e-3) - 1.0) * recruit         # conductive/OHC-ok -> CR~1
        self.threshold_db, self.ucl_db, self.snf, self.cr = thr, ucl, snf, cr
        self.EF, self.CT, self.ref = float(expansion_floor), float(expansion_knee), float(ref_level)
        self.in_lo, self.in_hi = float(in_lo), float(in_hi)
        self.r_ref = np.maximum((thr + slope * self.ref) - self.ref, 0.0)  # insertion gain @ref_level

    def _bcast(self, a, L):
        return a[:, None] if (np.ndim(L) > 1 and np.ndim(a) == 1) else a

    def _gain(self, L):
        L = np.asarray(L, float)
        r, cr = self._bcast(self.r_ref, L), self._bcast(self.cr, L)
        g_wdrc = np.maximum(r + (self.ref - L) * (1.0 - 1.0 / cr), 0.0)    # compression gain
        g_ct = np.maximum(r + (self.ref - self.CT) * (1.0 - 1.0 / cr), 0.0)  # gain at the knee
        ramp = np.clip((L - self.EF) / (self.CT - self.EF), 0.0, 1.0)      # expansion ramp below CT
        return np.where(L < self.CT, g_ct * ramp, g_wdrc)

    def forward(self, L):
        L = np.asarray(L, float)
        return np.minimum(L + self._gain(L), self._bcast(self.ucl_db, L))  # gain then UCL limit

    def inverse(self, Lo):
        Lo = np.atleast_2d(np.asarray(Lo, float))
        grid = np.linspace(self.in_lo - 20, self.in_hi + 20, 512)
        fwd = self.forward(np.tile(grid, (len(self.fc), 1)))              # (n_bands, G), monotone
        out = np.array([np.interp(Lo[b], fwd[b], grid) for b in range(Lo.shape[0])])
        return out.reshape(np.asarray(Lo).shape)

    def insertion_gain(self, levels=(50.0, 65.0, 80.0)):
        """Per-band insertion gain (dB) at the given input levels -- so a WDRC fit is directly
        comparable to the OpenMHA prescriptions (rows = levels, cols = bands)."""
        return np.array([self._gain(np.full(len(self.fc), L)) for L in np.asarray(levels, float)])


# --------------------------------------------------------------------------- #
# 3c. Spectral-contrast enhancement + frequency lowering (non-causal / offline)
# --------------------------------------------------------------------------- #
def _smooth_bands(M, sigma_bands=1.5):
    """Smooth a (n_bands, T) level matrix ALONG the band axis (symmetric Gaussian in band index).
    Zero-phase across frequency -- fine for an offline aid."""
    n = M.shape[0]
    idx = np.arange(n)
    K = np.exp(-0.5 * ((idx[:, None] - idx[None, :]) / max(sigma_bands, 1e-6)) ** 2)
    K /= K.sum(1, keepdims=True)
    return K @ M


def frequency_compress(x, sr, f_start=1500.0, ratio=2.0, win=1024, hop=None):
    """Non-linear frequency compression / lowering (offline STFT). Frequencies above `f_start`
    are squeezed toward it by `ratio` (f_out = f_start + (f - f_start)/ratio), moving otherwise
    inaudible high-frequency cues (e.g. /s/, /sh/) into an audible region -- for high-frequency
    DEAD regions. A prototype: magnitudes are re-mapped and the original phase is reused, so it
    demonstrates the effect (with some artefacts), not a production frequency-lowering algorithm.
    Non-causal (whole-signal STFT)."""
    x = np.asarray(x, float)
    win = int(win); hop = win // 4 if hop is None else int(hop)
    w = signal.windows.hann(win, sym=False)
    f = np.fft.rfftfreq(win, 1.0 / sr)
    hi = f >= f_start
    tgt = f.copy()
    tgt[hi] = f_start + (f[hi] - f_start) / float(ratio)                # compressed target freqs
    src_bin = np.clip(np.round(tgt / (sr / win)).astype(int), 0, len(f) - 1)  # map src->target bin
    pad = win
    xp = np.concatenate([np.zeros(pad), x, np.zeros(pad + win)])
    starts = np.arange(0, len(xp) - win, hop)
    acc = np.zeros(len(xp)); norm = np.zeros(len(xp))
    for s in starts:
        spec = np.fft.rfft(xp[s:s + win] * w)
        mag = np.zeros_like(f); np.add.at(mag, src_bin, np.abs(spec))    # move magnitude down
        newspec = mag * np.exp(1j * np.angle(spec))                      # reuse phase (prototype)
        acc[s:s + win] += w * np.fft.irfft(newspec, n=win)
        norm[s:s + win] += w * w
    norm = np.where(norm > 1e-12, norm, 1.0)
    y = (acc / norm)[pad:pad + len(x)]
    return y * (np.sqrt(np.mean(x ** 2)) + 1e-12) / (np.sqrt(np.mean(y ** 2)) + 1e-12)


# --------------------------------------------------------------------------- #
# 3d. Pitch-preserving time-scale (playback speed) -- a personalisable listening aid
# --------------------------------------------------------------------------- #
def time_stretch(x, sr, rate, frame_ms=40.0, seek_ms=8.0):
    """Pitch-preserving time-scale modification (WSOLA). `rate` < 1 slows speech down (e.g. 0.85),
    > 1 speeds it up; pitch is unchanged. Slowing helps some hearing-impaired / older listeners with
    slower temporal processing -- an OFFLINE, per-patient listening aid (adds latency, so not for a
    real-time device). Overlap-add with a similarity search so successive frames stay phase-coherent."""
    x = np.asarray(x, float)
    if abs(rate - 1.0) < 1e-6:
        return x.copy()
    N = len(x)
    W = int(frame_ms * 1e-3 * sr); W += W % 2
    Hs = W // 2                                        # synthesis hop
    Ha = max(1, int(round(Hs * rate)))                # analysis hop (rate<1 -> slower)
    seek = int(seek_ms * 1e-3 * sr)
    win = np.hanning(W)
    xp = np.concatenate([np.zeros(seek), x, np.zeros(2 * W + Ha + seek)])
    out_len = int(N / rate) + W
    y = np.zeros(out_len + W); ow = np.zeros(out_len + W)
    a, s = seek, 0
    while s + W < len(y) and a + W + Ha + seek < len(xp):
        y[s:s + W] += xp[a:a + W] * win; ow[s:s + W] += win
        nat = xp[a + Hs:a + Hs + W]                   # natural continuation of this frame
        c0 = a + Ha                                   # search near here for the best-matching frame
        cand = np.lib.stride_tricks.sliding_window_view(xp[c0 - seek:c0 + seek + W], W)
        a = (c0 - seek) + int(np.argmax(cand @ nat))  # WSOLA similarity pick
        s += Hs
    ow[ow < 1e-6] = 1.0
    return (y / ow)[:out_len]


# --------------------------------------------------------------------------- #
# 4. Pipeline: analysis -> loudness -> gain -> resynthesis
# --------------------------------------------------------------------------- #
def _one_pole(g, alpha):
    return signal.lfilter([1.0 - alpha], [1.0, -alpha], g, axis=-1)


def _attack_release(g, sr, attack_ms, release_ms):
    """Asymmetric WDRC gain follower (a real hearing-aid attack/release), PER BAND.

    Standard convention: when the input rises the gain must come DOWN quickly (attack);
    when the input falls the gain comes back UP slowly (release). So we smooth g with the
    fast constant while it is decreasing and the slow one while it is increasing. Short
    release (~50-100 ms) = 'fast'/syllabic-plus compression (restores soft-consonant
    audibility, but pumps and flattens contrast); long release (~200-1000 ms) = 'slow'
    syllabic compression (preserves spectral/temporal contrast and naturalness). Causal,
    so -- like smooth_ms -- it makes the effective mapping time-varying (the static gain
    line still inverts; the follower does not).

    `attack_ms` / `release_ms` may be a scalar (same for every band) OR a per-band vector of
    length n_bands (like OpenMHA's per-channel tau_attack / tau_decay) -- e.g. a fast release
    in the high bands (consonant audibility) and a slow one in the low bands (stability)."""
    g = np.atleast_2d(np.asarray(g, float))
    n = g.shape[0]

    def _alpha(ms):
        ms = np.broadcast_to(np.asarray(ms, float), (n,))     # scalar -> per-band, or a vector
        return np.where(ms > 0, np.exp(-1.0 / (np.maximum(ms, 1e-6) * 1e-3 * sr)), 0.0)

    a_atk, a_rel = _alpha(attack_ms), _alpha(release_ms)       # per-band coefficients
    y = np.empty_like(g)
    prev = g[:, 0].copy()
    for t in range(g.shape[1]):
        target = g[:, t]
        a = np.where(target < prev, a_atk, a_rel)      # decreasing gain -> attack (fast), per band
        prev = a * prev + (1.0 - a) * target
        y[:, t] = prev
    return y


def run(x, sr, backend="butter_greenwood", n_bands=20, flo=100.0, fhi=None,
        carrier="original", gain=None, loudness="level_db", loud_ref=None,
        gate_db=None, gate_knee_db=12.0, smooth_ms=0.0, attack_ms=None, release_ms=None,
        contrast=0.0, contrast_sigma=1.5, match_rms=True, seed=0):
    """Full pipeline. `gain` is a GenericGainMap / PersonalizedGainMap (None => identity/
    reconstruction). `loudness` selects the invertible loudness domain ('level_db' |
    'perceptual'); `loud_ref` sets the 0-dB reference (default = signal peak; pass
    dbfs_ref_for_spl(...) to work in real dB SPL for the personalised map).

    Time constants: `smooth_ms` applies a single symmetric one-pole to the per-band gain
    (attack == release). Pass `attack_ms`/`release_ms` instead for a real asymmetric WDRC
    follower (fast attack, slow release); when either is given it overrides smooth_ms.
    `contrast` (>0) adds SPECTRAL-CONTRAST ENHANCEMENT: sharpen each frame's spectral peaks vs
    its cross-band average by that factor -- counters the peak/valley flattening multiband
    compression causes (zero-phase across frequency; offline). Returns dict with 'waveform'
    and per-band 'matrix' (level_in/out, gain_db)."""
    x = np.asarray(x, float)
    if fhi is None:
        fhi = 0.45 * sr
    bands, fc = analyze(x, sr, backend=backend, flo=flo, fhi=fhi, n_bands=n_bands)
    env = np.vstack([extract_envelope(b, sr) for b in bands])

    if loud_ref is None:
        loud_ref = float(np.max(env)) + 1e-9
    measure = get_measure(loudness, ref=loud_ref)
    L_in = measure.forward(env)
    gmap = gain if gain is not None else GenericGainMap(slope=1.0, offset=0.0)
    L_out = gmap.forward(L_in)
    if contrast and contrast > 0:                  # spectral-contrast enhancement (sharpen peaks)
        L_out = L_out + contrast * (L_out - _smooth_bands(L_out, contrast_sigma))

    eps = 1e-9
    g = measure.inverse(L_out) / (measure.inverse(L_in) + eps)

    if gate_db is not None:                       # fade boost toward unity in silence
        lvl = 20.0 * np.log10(np.maximum(env, eps) / (np.max(env) + eps))
        gate = np.clip((lvl - gate_db) / max(gate_knee_db, 1e-6), 0.0, 1.0)
        g = 1.0 + (g - 1.0) * gate
    if attack_ms is not None or release_ms is not None:   # asymmetric WDRC follower (per band)
        g = _attack_release(g, sr, 0.0 if attack_ms is None else attack_ms,
                            0.0 if release_ms is None else release_ms)
    elif smooth_ms and smooth_ms > 0:                     # single symmetric time constant
        g = _one_pole(g, float(np.exp(-1.0 / (smooth_ms * 1e-3 * sr))))

    rng = np.random.default_rng(seed)
    y_bands = np.zeros_like(bands)
    env_target = measure.inverse(L_out)
    edges = band_edges(flo, fhi, bands.shape[0])          # for band-limiting noise/tone carriers
    for b in range(bands.shape[0]):
        car = make_carrier(carrier, bands[b], fc[b], sr, rng=rng,
                           band_lo=edges[b], band_hi=edges[b + 1])
        if carrier == "original":
            y_bands[b] = g[b] * car
        else:
            car = car / (np.sqrt(np.mean(car ** 2)) + eps)
            y_bands[b] = env_target[b] * car
    y = y_bands.sum(axis=0)
    if match_rms:
        y *= (np.sqrt(np.mean(x ** 2)) + eps) / (np.sqrt(np.mean(y ** 2)) + eps)

    return {"waveform": y, "fc": fc, "sr": sr, "gain_map": gmap, "measure": measure,
            "matrix": {"level_in": L_in, "level_out": L_out,
                       "gain_db": 20.0 * np.log10(np.maximum(g, eps))}}


class HearingLossSim:
    """Make a NORMAL-hearing listener approximately experience the loss, so 'unaided-through-loss'
    vs 'aided-through-loss' shows the aid's actual BENEFIT (not just its output). Per band it applies
    threshold elevation + loudness RECRUITMENT as an expansion: the audible range [threshold, UCL]
    is mapped onto the normal range [0, UCL], so sounds below the impaired threshold become
    inaudible and loudness grows abnormally fast above it. Use as run()'s `gain` (it's the inverse
    idea of a compression fit). This is an illustrative simulator, not a validated model (e.g. MSBG)."""

    def __init__(self, fc, audiogram=None, ucl=100.0, floor_db=-15.0):
        self.fc = np.asarray(fc, float)
        self.thr = audiogram_thresholds(self.fc, audiogram)
        self.ucl = float(ucl); self.floor = float(floor_db)
        self.span = np.maximum(self.ucl - self.thr, 5.0)          # residual range (>=5 dB)

    def forward(self, L):
        L = np.asarray(L, float)
        per = (L - self.thr[:, None]) / self.span[:, None] * self.ucl   # recruit [thr,ucl] -> [0,ucl]
        return np.maximum(per, self.floor)                         # below threshold -> ~inaudible


def audibility(x, sr, audiogram, loud_ref=None, n_bands=24, flo=100.0, fhi=None):
    """A quick speech-audibility proxy (0..1, SII-like): the importance-weighted fraction of the
    speech's 30 dB dynamic range that sits ABOVE the listener's threshold, given the signal's
    long-term band levels at the ear. Unaided speech into a loss scores low; a good fit scores high.
    A proxy, not the ANSI SII (Malcolm's official package is used in the notebook)."""
    if fhi is None:
        fhi = 0.45 * sr
    bands, fc = analyze(x, sr, backend="stft", flo=flo, fhi=fhi, n_bands=n_bands)
    env = np.vstack([extract_envelope(b, sr) for b in bands])
    ref = dbfs_ref_for_spl(100.0) if loud_ref is None else loud_ref
    lvl = 20.0 * np.log10(np.sqrt(np.mean(env ** 2, axis=1)) / ref + 1e-9)   # long-term band level, dB SPL
    thr = audiogram_thresholds(fc, audiogram)
    aud = np.clip((lvl - thr) / 30.0, 0.0, 1.0)                     # fraction of 30 dB speech range audible
    imp = np.exp(-0.5 * ((np.log10(fc) - np.log10(1800.0)) / 0.42) ** 2)     # speech-importance ~ peak 1.8 kHz
    return float((imp * aud).sum() / imp.sum())


def official_sii(aided, unaided, sr, audiogram):
    """Authoritative ANSI S3.5 Speech Intelligibility Index (Malcolm Slaney's speech_intelligibility_index
    package) for a fit: feed the aid's per-band INSERTION GAIN (aided minus unaided band levels, so
    absolute calibration cancels) into the standard normal speech spectrum + the listener's audiogram.
    Falls back to the vendored `sii.py` (used in the browser) if the pip package isn't installed."""
    try:
        from speech_intelligibility_index import sii as _S
    except ImportError:
        import sii as _S
    mbf = np.asarray(_S.mid_band_freqs, float)                  # 18 one-third-octave bands
    def _blev(y):
        Y = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
        f = np.fft.rfftfreq(len(y), 1.0 / sr)
        return np.array([10.0 * np.log10(Y[(f >= fc / 2 ** (1/6)) & (f < fc * 2 ** (1/6))].sum() + 1e-12) for fc in mbf])
    ig = _blev(np.asarray(aided, float)) - _blev(np.asarray(unaided, float))
    thr = audiogram_thresholds(mbf, audiogram)
    E, N, T = _S.input_5p1('normal', insertion_gain=ig, hearing_threshold=thr)
    return float(_S.sii(E, N, T))


def add_noise(x, snr_db=5.0, kind="ssn", seed=0):
    """Mix noise at a given SNR (dB, re signal RMS). kind='ssn' = speech-shaped (white noise filtered
    to the signal's own long-term spectrum); 'babble' = multi-talker babble made by overlapping several
    shifted/reversed copies of the signal; 'white' = flat."""
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    if kind == "babble":
        n = np.zeros(len(x))
        for k in range(6):                                     # ~6 overlapping "talkers"
            n += np.roll(x[::-1] if k % 2 else x, int(rng.integers(len(x))))
    else:
        n = rng.standard_normal(len(x))
        if kind == "ssn":
            mag = np.abs(np.fft.rfft(x))
            n = np.fft.irfft(np.fft.rfft(n) * (mag / (np.max(mag) + 1e-9)), len(x))
    n *= (np.sqrt(np.mean(x ** 2)) + 1e-12) / (np.sqrt(np.mean(n ** 2)) + 1e-12) * 10.0 ** (-snr_db / 20.0)
    return x + n


def reverb(x, sr, rt60=0.5, seed=0):
    """Add reverberation: convolve with a synthetic exponentially-decaying room impulse response
    (rough Schroeder), RT60 in seconds. Level-matched to the input."""
    x = np.asarray(x, float)
    rng = np.random.default_rng(seed)
    L = int(max(0.05, rt60) * sr)
    ir = rng.standard_normal(L) * np.exp(-6.908 * np.arange(L) / (rt60 * sr))   # -60 dB by RT60
    ir[0] += 1.0                                                # direct path
    y = np.convolve(x, ir)[:len(x)]
    return y * ((np.sqrt(np.mean(x ** 2)) + 1e-12) / (np.sqrt(np.mean(y ** 2)) + 1e-12))


def denoise(x, sr, win=1024, hop=256, over=1.25, floor_db=-8.0):
    """Offline single-channel noise reduction (spectral Wiener). Estimates a per-frequency noise
    floor from the quietest 10% of frames and pulls each bin's gain toward silence where the SNR is
    low, floored so speech isn't gated out. Illustrative (a real aid uses a modulation/SNR estimate)."""
    x = np.asarray(x, float)
    w = np.hanning(win); nfr = max(1, 1 + (len(x) - win) // hop)
    S = np.stack([np.fft.rfft(x[i * hop:i * hop + win] * w) for i in range(nfr)])   # (nfr, nbins)
    P = np.abs(S) ** 2
    noise = np.quantile(P, 0.1, axis=0)                                             # per-bin noise floor
    snr = np.maximum(P / (over * noise + 1e-12) - 1.0, 0.0)
    g = np.maximum(snr / (snr + 1.0), 10.0 ** (floor_db / 20.0))                    # Wiener gain, floored
    Y = S * g
    y = np.zeros(len(x) + win); ws = np.zeros(len(x) + win)
    for i in range(nfr):
        seg = np.fft.irfft(Y[i], win) * w
        y[i * hop:i * hop + win] += seg; ws[i * hop:i * hop + win] += w ** 2
    y = y[:len(x)]; ws = ws[:len(x)]
    y[ws > 1e-9] /= ws[ws > 1e-9]
    return y


# --------------------------------------------------------------------------- #
# 4b. Two-ear (binaural) fit -- per-ear audiograms, with ILD-preserving link
# --------------------------------------------------------------------------- #
def binaural(xL, xR, sr, audiogram_L, audiogram_R, airbone_gap_L=0.0, airbone_gap_R=0.0,
             ohc_L=None, ohc_R=None, link=True, n_bands=21, flo=100.0, fhi=None,
             loud_ref=None, attack_ms=5.0, release_ms=120.0):
    """Fit BOTH ears from their own audiograms -> stereo (N, 2), each ear a `PersonalizedWDRC`.

    Binaural catch: run two independent compressors and the loud ear gets pulled down more than
    the quiet ear, shrinking the **interaural level difference (ILD)** that localises sound. With
    `link=True` the level that DRIVES compression is shared across ears (the max of the two), so
    both ears compress by the same amount and the ILD is preserved; `link=False` compresses each
    ear on its own level. Non-causal / offline. (A mono source is diotic -- pan it first to create
    an ILD to preserve.)"""
    fhi = 0.45 * sr if fhi is None else fhi
    loud_ref = dbfs_ref_for_spl(100.0) if loud_ref is None else loud_ref
    bL, fc = analyze(np.asarray(xL, float), sr, backend="stft", flo=flo, fhi=fhi, n_bands=n_bands)
    bR, _ = analyze(np.asarray(xR, float), sr, backend="stft", flo=flo, fhi=fhi, n_bands=n_bands)
    m = get_measure("level_db", ref=loud_ref)
    LinL = m.forward(np.vstack([extract_envelope(b, sr) for b in bL]))
    LinR = m.forward(np.vstack([extract_envelope(b, sr) for b in bR]))
    wL = PersonalizedWDRC(fc, audiogram=audiogram_L, airbone_gap=airbone_gap_L, ohc_health=ohc_L)
    wR = PersonalizedWDRC(fc, audiogram=audiogram_R, airbone_gap=airbone_gap_R, ohc_health=ohc_R)
    driveL = np.maximum(LinL, LinR) if link else LinL      # shared vs own level drives compression
    driveR = np.maximum(LinL, LinR) if link else LinR
    gL = _attack_release(wL.forward(driveL) - driveL, sr, attack_ms, release_ms)   # insertion gain, dB
    gR = _attack_release(wR.forward(driveR) - driveR, sr, attack_ms, release_ms)
    yL = (10.0 ** (gL / 20.0) * bL).sum(0)
    yR = (10.0 ** (gR / 20.0) * bR).sum(0)
    return np.stack([yL, yR], axis=1)                      # (N, 2) stereo, L / R


# --------------------------------------------------------------------------- #
# 5. Synthetic speech (Colab has no macOS `say`; upload your own WAV instead)
# --------------------------------------------------------------------------- #
def make_speech_like(sr=16000, seed=0):
    """A ~1.6 s synthetic voiced utterance (vowels + F0 glide + loud/soft swell)."""
    vowels = {"a": [(730, 90), (1090, 110), (2440, 120)],
              "i": [(270, 60), (2290, 110), (3010, 120)],
              "u": [(300, 60), (870, 90), (2240, 120)],
              "e": [(530, 80), (1840, 100), (2480, 120)]}

    def vowel(v, dur, f0):
        n = int(dur * sr); t = np.arange(n) / sr
        src = signal.lfilter([1, -0.97], [1], signal.sawtooth(2 * np.pi * f0 * t))
        out = np.zeros(n)
        for fc, bw in vowels[v]:
            r = np.exp(-np.pi * bw / sr); th = 2 * np.pi * fc / sr
            out += signal.lfilter([1 - r], [1, -2 * r * np.cos(th), r * r], src)
        return out / (np.max(np.abs(out)) + 1e-12)

    rng = np.random.default_rng(seed)
    seq = [("a", .28), (None, .06), ("i", .24), (None, .06), ("u", .30),
           (None, .05), ("e", .26), (None, .05), ("a", .30)]
    parts, f0 = [], 130.0
    for v, d in seq:
        if v is None:
            parts.append(np.zeros(int(d * sr)))
        else:
            f0 *= rng.uniform(0.92, 1.08)
            parts.append(vowel(v, d, f0))
    x = np.concatenate(parts)
    contour = 0.06 + 0.94 * np.sin(np.linspace(0, np.pi, x.shape[0])) ** 2
    x = x * contour
    return sr, x / (np.max(np.abs(x)) + 1e-12) * 0.9
