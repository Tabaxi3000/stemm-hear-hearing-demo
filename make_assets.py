"""Generate all media (audiogram PNGs + AAC audio, base64) for the demo website.
Writes assets.json to the scratchpad."""
import os, sys, json, base64, subprocess, tempfile
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SC = "/private/tmp/claude-502/-Users-tabaxitft-Desktop-STEMM-HEAR/02cdbe4e-d460-4375-a16a-683a6e731aea/scratchpad"
sys.path.insert(0, "/Users/tabaxitft/Desktop/STEMM-HEAR/FILTER BANKS/speech_resynthesis/colab")
import speech_resynth as sp

SR = 32000                                     # 32 kHz -> 12 kHz filter bank (Nyquist 16 kHz)

# ---- 1. paragraph clip: 40.1..60.2 s of chapter 1 (cached 16 kHz decode -> 32 kHz) ----
# NOTE: the 64 kbps LibriVox source is band-limited to ~8 kHz, so the speech has little energy
# above 8 kHz; the wider bank matters for music / high-quality uploads, not this clip.
sr0, full = wavfile.read(os.path.join(SC, "frank_full.wav"))
full = full.astype(float) / 32768.0
clip16 = full[int(40.15 * sr0): int(60.15 * sr0)].copy()
clip = resample_poly(clip16, SR // sr0, 1)     # 16 kHz -> 32 kHz
nf = int(0.012 * SR); w = np.sin(np.linspace(0, np.pi / 2, nf)) ** 2
clip[:nf] *= w; clip[-nf:] *= w[::-1]
print("paragraph clip: %.2f s @ %d Hz" % (len(clip) / SR, SR))

# present at 65 dB SPL (loud_ref maps full-scale -> 100 dB SPL, so RMS -35 dBFS reads 65)
x65 = clip / (np.sqrt(np.mean(clip ** 2)) + 1e-12) * 10 ** ((65 - 100) / 20)
LOUD = sp.dbfs_ref_for_spl(100.0)

# ---- 2. three diverse audiograms (dB HL) ---------------------------------------------
AUDIOGRAMS = [
    dict(id="sloping", name="Mild-to-moderate sloping loss",
         blurb="Gentle high-frequency (presbycusis-like) slope. Lows near normal, highs down ~55-65 dB.",
         ag={250: 20, 500: 25, 1000: 30, 2000: 40, 4000: 55, 8000: 65}),
    dict(id="flat", name="Moderate flat loss (~40-45 dB)",
         blurb="Roughly equal loss across frequency — the 40 dB example: a 0 dB input is lifted to ~40 dB, louder sounds compress above it.",
         ag={250: 40, 500: 42, 1000: 45, 2000: 45, 4000: 48, 8000: 50}),
    dict(id="skislope", name="Steep ski-slope loss",
         blurb="Near-normal lows crashing to a severe high-frequency loss — lots of gain and heavy compression up top.",
         ag={250: 15, 500: 20, 1000: 30, 2000: 50, 4000: 70, 8000: 80}),
]

# ---- 3. audiogram PNGs ---------------------------------------------------------------
def audiogram_png(ag, path):
    freqs = sorted(ag); vals = [ag[f] for f in freqs]
    fig, axp = plt.subplots(figsize=(3.7, 3.0), dpi=150)
    axp.plot(range(len(freqs)), vals, "-", color="#2C7A7B", lw=2, zorder=3)
    axp.scatter(range(len(freqs)), vals, marker="x", s=70, color="#2C7A7B", lw=2.2, zorder=4)
    axp.set_xticks(range(len(freqs)))
    axp.set_xticklabels([f"{f//1000}k" if f >= 1000 else str(f) for f in freqs], fontsize=8)
    axp.set_ylim(120, -10); axp.set_yticks(range(0, 121, 20))
    axp.axhspan(-10, 20, color="#EAF3F3", zorder=0)          # normal-hearing band
    axp.set_ylabel("Hearing level (dB HL)", fontsize=8.5)
    axp.set_xlabel("Frequency (Hz)", fontsize=8.5)
    axp.tick_params(labelsize=8); axp.grid(True, alpha=0.25)
    for s in ("top", "right"): axp.spines[s].set_visible(False)
    fig.tight_layout(pad=0.4); fig.savefig(path, transparent=True); plt.close(fig)

# ---- 3b. compression input->output curve (illustrates "0 dB -> threshold, compress above") ----
def comp_png(ag, path):
    show = [500, 2000, 4000]
    cols = {500: "#7FB2B2", 2000: "#2C7A7B", 4000: "#123F40"}
    fig, axp = plt.subplots(figsize=(3.7, 3.0), dpi=150)
    x = np.linspace(0, 100, 200)
    axp.plot(x, x, "--", color="#9AA7A6", lw=1.2, zorder=1, label="unaided (y = x)")
    for f in show:
        thr = float(np.interp(np.log10(f), np.log10(sorted(ag)),
                              [ag[k] for k in sorted(ag)]))
        ucl = max(95.0, 100.0 + 0.25 * thr) - 5.0
        axp.plot(x, thr + (ucl - thr) / 100.0 * x, "-", color=cols[f], lw=2, zorder=3,
                 label=f"{f//1000}k Hz" if f >= 1000 else f"{f} Hz")
        axp.scatter([0], [thr], color=cols[f], s=22, zorder=4)      # the 0 dB -> threshold point
    axp.set_xlim(0, 100); axp.set_ylim(0, 125)
    axp.set_xlabel("Input level (dB SPL)", fontsize=8.5)
    axp.set_ylabel("Output level (dB SPL)", fontsize=8.5)
    axp.tick_params(labelsize=8); axp.grid(True, alpha=0.25)
    axp.legend(fontsize=7, loc="lower right", framealpha=0.9)
    for s in ("top", "right"): axp.spines[s].set_visible(False)
    fig.tight_layout(pad=0.4); fig.savefig(path, transparent=True); plt.close(fig)

# ---- 4. render one condition ---------------------------------------------------------
# gate_db adds an EXPANSION FLOOR: bands >45 dB below their own peak fade toward unity gain, so
# the aid stops boosting the between-word noise floor (esp. the heavily-amplified high bands of a
# steep loss) -- the main avoidable source of "spit"/roughness.
FLO, FHI, NB = 100.0, 12000.0, 32              # bank up to 12 kHz
FC32 = sp.band_centres(sp.band_edges(FLO, FHI, NB, "greenwood"))
COMMON = dict(backend="stft", n_bands=NB, flo=FLO, fhi=FHI, carrier="original", loud_ref=LOUD,
              match_rms=False, gate_db=-45.0, gate_knee_db=18.0)


def render(ag, attack=None, release=None, smooth=0.0, rx=False):
    gain = sp.PrescriptiveGain(FC32, ag) if rx else sp.PersonalizedGainMap(FC32, audiogram=ag)
    return sp.run(x65, SR, gain=gain, attack_ms=attack, release_ms=release, smooth_ms=smooth, **COMMON)["waveform"]

CONDITIONS = [
    ("static", "Without dynamics (static compression)", dict(smooth=0.0)),
    ("wdrc_fast", "WDRC · fast release (60 ms)", dict(attack=5, release=60)),
    ("wdrc_med", "WDRC · medium release (150 ms)", dict(attack=5, release=150)),
    ("wdrc_slow", "WDRC · slow release (400 ms)", dict(attack=5, release=400)),
    ("prescriptive", "Prescriptive fit (half-gain + rolloff + limiting)", dict(attack=5, release=150, rx=True)),
]

# render everything (raw)
raw = {}
for A in AUDIOGRAMS:
    for cid, _, kw in CONDITIONS:
        raw[f"{A['id']}__{cid}"] = render(A["ag"], **kw)

# Loudness-scale for a fair A/B on normal-hearing ears: the four processed clips in a section
# share ONE factor (so their mutual level/dynamics differences survive) set to mean RMS -20 dBFS;
# the unprocessed original sits at a fixed -26 dBFS (a gentle ~6 dB below "aided"). This lets you
# hear spectral shaping + compression dynamics rather than just raw loudness; the prescribed gain
# and the audiogram are shown separately.
def _rms(w): return float(np.sqrt(np.mean(w ** 2)) + 1e-12)
def _softknee(y, thr=0.92):     # transparent below thr; smooth knee only on the rare peaks above
    a = np.abs(y); out = y.copy(); m = a > thr
    out[m] = np.sign(y[m]) * (thr + (1.0 - thr) * np.tanh((a[m] - thr) / (1.0 - thr)))
    return out
# Loudness-MATCH every processed clip (RMS -18 dBFS) so the A/B is about spectral shaping and
# compression *dynamics* (pumping vs smooth), not the level differences the release time creates;
# the transparent soft-knee then catches only residual peaks. Original sits ~4 dB below as reference.
TARGET = 10 ** (-20 / 20)
clips = {"original": x65 / _rms(x65) * 10 ** (-24 / 20)}
for A in AUDIOGRAMS:
    for cid, _, _ in CONDITIONS:
        k = f"{A['id']}__{cid}"
        clips[k] = _softknee(raw[k] / _rms(raw[k]) * TARGET)
print("per-clip RMS/peak dBFS after scale:")
for k, w in clips.items():
    print(f"   {k:26s} rms {20*np.log10(_rms(w)):6.1f}   peak {20*np.log10(np.max(np.abs(w))+1e-12):6.1f}")

# ---- 5. encode wav(16k) -> 44.1k AAC m4a -> base64 -----------------------------------
WEB = "/Users/tabaxitft/Desktop/STEMM-HEAR/FILTER BANKS/speech_resynthesis/web"
AUD = os.path.join(WEB, "audio"); os.makedirs(AUD, exist_ok=True)

def write_aac(y, name):                                   # write a lazy-loaded .m4a file, return its URL
    y = np.clip(y, -0.985, 0.985)
    with tempfile.TemporaryDirectory() as d:
        wavfile.write(f"{d}/a.wav", SR, (np.clip(y, -1, 1) * 32767).astype(np.int16))
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "96000",
                        f"{d}/a.wav", os.path.join(AUD, name + ".m4a")], check=True, capture_output=True)
    return f"audio/{name}.m4a"

def png_b64(path):
    return base64.b64encode(open(path, "rb").read()).decode()

assets = {"original_file": write_aac(clips["original"], "shape_original"), "audiograms": []}
for A in AUDIOGRAMS:
    pth = os.path.join(SC, f"ag_{A['id']}.png"); audiogram_png(A["ag"], pth)
    cpth = os.path.join(SC, f"comp_{A['id']}.png"); comp_png(A["ag"], cpth)
    conds = [{"id": cid, "label": lbl, "sii": round(float(sp.audibility(raw[f"{A['id']}__{cid}"], SR, A["ag"])), 2),
              "file": write_aac(clips[f"{A['id']}__{cid}"], f"shape_{A['id']}_{cid}")}
             for cid, lbl, _ in CONDITIONS]
    assets["audiograms"].append(dict(id=A["id"], name=A["name"], blurb=A["blurb"],
                                     png=png_b64(pth), comp=png_b64(cpth),
                                     orig_sii=round(float(sp.official_sii(x65, x65, SR, A["ag"])), 2), conditions=conds))

json.dump(assets, open(os.path.join(SC, "assets.json"), "w"))
print("wrote assets.json  %.3f MB (files in web/audio)" % (os.path.getsize(os.path.join(SC, "assets.json")) / 1e6))
