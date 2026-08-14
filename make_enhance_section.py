"""Build the 'offline enhancement' gallery section -> enhance_section.json.
Two OFFLINE (non-causal / oracle) demos, clearly not live-aid processing:
  (a) Speech denoising CEILING: noisy -> blind spectral-Wiener -> ORACLE ideal ratio mask (built from
      the clean signal). The gap = the headroom a good DNN denoiser could recover.
  (b) MUSIC-specific: harmonic/percussive source separation (HPSS, Fitzgerald median-filter method)
      on the music clip -- harmonic (tonal), percussive (rhythm), and a harmonic-emphasised rebalance."""
import os, sys, json, base64, subprocess, tempfile
import numpy as np
from scipy.io import wavfile
from scipy.signal import stft, istft, resample_poly
from scipy.ndimage import median_filter, uniform_filter1d
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

SC = "/private/tmp/claude-502/-Users-tabaxitft-Desktop-STEMM-HEAR/02cdbe4e-d460-4375-a16a-683a6e731aea/scratchpad"
PROJ = "/Users/tabaxitft/Desktop/STEMM-HEAR/FILTER BANKS/speech_resynthesis"
sys.path.insert(0, os.path.join(PROJ, "colab")); sys.path.append(os.path.join(PROJ, "web"))
import speech_resynth as sp, metrics, buildkit
WEB = os.path.join(PROJ, "web"); AUD = os.path.join(WEB, "audio"); os.makedirs(AUD, exist_ok=True)

def present(z): return z / (np.sqrt(np.mean(z ** 2)) + 1e-12) * 10 ** ((65 - 100) / 20)
def _rms(w): return float(np.sqrt(np.mean(w ** 2)) + 1e-12)
def _softknee(y, thr=0.92):
    a = np.abs(y); o = y.copy(); m = a > thr
    o[m] = np.sign(y[m]) * (thr + (1.0 - thr) * np.tanh((a[m] - thr) / (1.0 - thr))); return o
def match(y, db): return _softknee(y / _rms(y) * 10 ** (db / 20))
def png_b64(p): return base64.b64encode(open(p, "rb").read()).decode()

def write_aac(y, name, srate):                                     # mono float @srate -> lazy .m4a
    y = np.clip(y, -0.985, 0.985)
    with tempfile.TemporaryDirectory() as d:
        wavfile.write(f"{d}/a.wav", srate, (np.clip(y, -1, 1) * 32767).astype(np.int16))
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "96000", f"{d}/a.wav",
                        os.path.join(AUD, name + ".m4a")], check=True, capture_output=True)
    return f"audio/{name}.m4a"

# ---------- (a) speech denoising ceiling ----------
SR = 16000
sr0, full = wavfile.read(os.path.join(SC, "frank_full.wav")); full = full.astype(float) / 32768.0
xclean = present(full[int(40.15 * sr0):int(60.15 * sr0)])
AG = {250: 15, 500: 20, 1000: 30, 2000: 50, 4000: 70, 8000: 80}    # ski-slope loss (HASPI models it)
NF, HOP = 1024, 256
def S(y): return stft(y, SR, nperseg=NF, noverlap=NF - HOP, window="hann")[2]
def iS(Z): return istft(Z, SR, nperseg=NF, noverlap=NF - HOP, window="hann")[1].astype(float)

noise = sp.add_noise(xclean, 5.0, "babble") - xclean
xn = present(xclean + noise)
irm = np.abs(S(xclean)) / (np.abs(S(xclean)) + np.abs(S(noise)) + 1e-9)
oracle = present(iS(S(xclean + noise) * irm)[:len(xn)])
blind = present(sp.denoise(xn, SR))
SPEECH = [("noisy", "Noisy", "unaided, +5 dB babble", "orig", xn),
          ("blind", "Blind NR", "spectral-Wiener (the tool's)", "dsl", blind),
          ("oracle", "Oracle mask", "uses the clean signal (ceiling)", "cam", oracle)]

def aud_png(ag, path):
    fr = sorted(ag); xs = range(len(fr))
    fig, ax = plt.subplots(figsize=(3.7, 3.0), dpi=150)
    ax.plot(xs, [ag[f] for f in fr], "-x", color="#2C7A7B", ms=7, mew=2, lw=1.8)
    ax.set_xticks(list(xs)); ax.set_xticklabels([f"{f//1000}k" if f >= 1000 else str(f) for f in fr], fontsize=8)
    ax.set_ylim(120, -10); ax.set_yticks(range(0, 121, 20)); ax.axhspan(-10, 20, color="#EAF3F3", zorder=0)
    ax.set_ylabel("dB HL", fontsize=8.5); ax.set_xlabel("Frequency (Hz)", fontsize=8.5)
    ax.tick_params(labelsize=8); ax.grid(alpha=.25)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(pad=0.4); fig.savefig(path, transparent=True); plt.close(fig)

p = os.path.join(SC, "enh_ag.png"); aud_png(AG, p)
_bar = buildkit.bar(len(SPEECH), "enh-speech")
sp_conds = []
for cid, lab, sub, cl, y in SPEECH:
    m = buildkit.metrics_cached(metrics.all_metrics, y, xclean, SR, AG, full=True); _bar.update()
    sp_conds.append(dict(id=cid, label=lab, sub=sub, cls=cl,
                         file=write_aac(resample_poly(match(y, -22), 2, 1), f"enh_sp_{cid}", 32000),
                         **{k: m[k] for k in ("sii", "stoi", "haspi", "hasqi")}))
_bar.close()

# ---------- (b) music: harmonic/percussive separation (HPSS) ----------
srm, mus = wavfile.read(os.path.join(SC, "placeholder_music.wav")); SRM = srm
music = present(mus.astype(float) / 32768.0)
def hpss(y, nfft=2048, hop=512, k=17):
    Z = stft(y, SRM, nperseg=nfft, noverlap=nfft - hop, window="hann")[2]
    mag = np.abs(Z)
    Hh = median_filter(mag, size=(1, k)); Pp = median_filter(mag, size=(k, 1))
    Hm = Hh ** 2 / (Hh ** 2 + Pp ** 2 + 1e-9)
    harm = istft(Z * Hm, SRM, nperseg=nfft, noverlap=nfft - hop, window="hann")[1].astype(float)
    perc = istft(Z * (1 - Hm), SRM, nperseg=nfft, noverlap=nfft - hop, window="hann")[1].astype(float)
    n = min(len(harm), len(perc), len(y)); return harm[:n], perc[:n]
harm, perc = hpss(music)
emph = present(1.15 * harm + 0.5 * perc)                            # harmonic-emphasised rebalance
MUSIC = [("orig", "Original", "full mix", "orig", music[:len(harm)]),
         ("harm", "Harmonic", "tonal / melody+harmony", "rx", present(harm)),
         ("perc", "Percussive", "rhythm / transients", "nal", present(perc)),
         ("emph", "Harmonic-emphasised", "tonal up, rhythm down", "cam", emph)]
AGm = {250: 30, 500: 30, 1000: 30, 2000: 35, 4000: 55, 8000: 60}   # Musician A's (poorer) left ear
_bar = buildkit.bar(len(MUSIC), "enh-music")
mu_conds = []
for cid, lab, sub, cl, y in MUSIC:
    m = buildkit.metrics_cached(metrics.all_metrics, y, music[:len(y)], SRM, AGm, full=True, music=True); _bar.update()
    mu_conds.append(dict(id=cid, label=lab, sub=sub, cls=cl,
                         file=write_aac(match(y, -22), f"enh_mus_{cid}", SRM), haaqi=m["haaqi"]))
_bar.close(); buildkit.save()

out = {"speech": {"png": png_b64(p), "snr": 5, "conditions": sp_conds},
       "music": {"placeholder": True, "conditions": mu_conds}}
json.dump(out, open(os.path.join(SC, "enhance_section.json"), "w"))
print("speech:", {c["id"]: (c["stoi"], c["haspi"], c["hasqi"]) for c in sp_conds})
print("music HAAQI:", {c["id"]: c["haaqi"] for c in mu_conds})
print("wrote enhance_section.json")
