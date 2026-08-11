"""Render the two named binaural subjects (Speech A, Musician A) -> subjects.json.
Four A/B tracks each: Original (diotic), Left-ear fit, Right-ear fit, Binaural (each ear its
own fit). Per-ear straight-line gain [thr->UCL] + WDRC (5 ms attack / 150 ms release), gate."""
import os, sys, json, base64, subprocess, tempfile
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

SC = "/private/tmp/claude-502/-Users-tabaxitft-Desktop-STEMM-HEAR/02cdbe4e-d460-4375-a16a-683a6e731aea/scratchpad"
sys.path.insert(0, "/Users/tabaxitft/Desktop/STEMM-HEAR/FILTER BANKS/speech_resynthesis/colab")
import speech_resynth as sp
SR = 32000                                     # 32 kHz -> 12 kHz filter bank
FLO, FHI, NB = 100.0, 12000.0, 32
FC = sp.band_centres(sp.band_edges(FLO, FHI, NB, "greenwood"))
LOUD = sp.dbfs_ref_for_spl(100.0)
COMMON = dict(backend="stft", n_bands=NB, flo=FLO, fhi=FHI, carrier="original", loud_ref=LOUD,
              match_rms=False, gate_db=-45.0, gate_knee_db=18.0)

SUBJECTS = [
    dict(id="speech_a", name="Speech A", kind="Speech · asymmetric loss",
         blurb="Right ear moderate-severe, left near-normal — the ears get very different fits.",
         src="speech", aR={250:35,500:55,1000:65,2000:60,4000:70,8000:35},
         aL={250:15,500:15,1000:15,2000:20,4000:10,8000:20}),
    dict(id="musician_a", name="Musician A", kind="Music · near-symmetric loss",
         blurb="Mild-to-mod-severe high-frequency loss, slightly worse on the left. Placeholder music.",
         src="music", aR={250:30,500:30,1000:30,2000:35,4000:45,8000:50},
         aL={250:30,500:30,1000:30,2000:35,4000:55,8000:60}),
]

# ---- sources presented at 65 dB SPL --------------------------------------------------
def present65(x): return x / (np.sqrt(np.mean(x ** 2)) + 1e-12) * 10 ** ((65 - 100) / 20)
# speech: cached 16 kHz decode (source ~8 kHz-limited) -> slice -> 32 kHz
sr0, f0 = wavfile.read(os.path.join(SC, "frank_full.wav")); f0 = f0.astype(float) / 32768.0
speech = resample_poly(f0[int(40.15 * sr0):int(60.15 * sr0)], SR // sr0, 1)
nf = int(0.012 * SR); w = np.sin(np.linspace(0, np.pi/2, nf))**2
speech[:nf] *= w; speech[-nf:] *= w[::-1]
SPEECH = present65(speech)
srm, m = wavfile.read(os.path.join(SC, "placeholder_music.wav")); assert srm == SR
MUSIC = present65(m.astype(float) / 32768.0)

def render_ear(x65, ag):
    pm = sp.PersonalizedGainMap(FC, audiogram=ag)
    return sp.run(x65, SR, gain=pm, attack_ms=5, release_ms=150, **COMMON)["waveform"]

def _rms(w): return float(np.sqrt(np.mean(w**2)) + 1e-12)
def _softknee(y, thr=0.92):
    a = np.abs(y); out = y.copy(); m = a > thr
    out[m] = np.sign(y[m]) * (thr + (1.0-thr)*np.tanh((a[m]-thr)/(1.0-thr)))
    return out
T20 = 10 ** (-20/20)

# ---- two-ear audiogram + per-ear insertion-gain figures ------------------------------
RED, BLUE = "#C0392B", "#2C6FB0"
def subject_png(sub, path):
    fig, ax = plt.subplots(1, 2, figsize=(7.4, 3.0), dpi=150)
    fr = sorted(sub["aR"]); xs = range(len(fr))
    ax[0].plot(xs, [sub["aR"][f] for f in fr], "-o", color=RED, ms=5, lw=1.8, label="Right")
    ax[0].plot(xs, [sub["aL"][f] for f in fr], "-x", color=BLUE, ms=7, mew=2, lw=1.8, label="Left")
    ax[0].set_xticks(list(xs)); ax[0].set_xticklabels([f"{f//1000}k" if f>=1000 else str(f) for f in fr], fontsize=8)
    ax[0].set_ylim(120,-10); ax[0].set_yticks(range(0,121,20)); ax[0].axhspan(-10,20,color="#EAF3F3",zorder=0)
    ax[0].set_ylabel("dB HL", fontsize=8.5); ax[0].set_title("Audiogram (both ears)", fontsize=9.5)
    ax[0].tick_params(labelsize=8); ax[0].grid(alpha=.25); ax[0].legend(fontsize=8, loc="lower left")
    for s in ("top","right"): ax[0].spines[s].set_visible(False)
    fcb = FC
    for ag, col, lab, mk in [(sub["aR"],RED,"Right","-"),(sub["aL"],BLUE,"Left","--")]:
        pm = sp.PersonalizedGainMap(fcb, audiogram=ag)
        gain = pm.slope*50.0 + pm.offset - 50.0                # insertion gain at 50 dB SPL input
        ax[1].semilogx(fcb, gain, mk, color=col, lw=2, label=lab)
    ax[1].set_xlabel("Hz", fontsize=8.5); ax[1].set_ylabel("insertion gain (dB)", fontsize=8.5)
    ax[1].set_title("Prescribed gain per ear", fontsize=9.5)
    ax[1].tick_params(labelsize=8); ax[1].grid(alpha=.25, which="both"); ax[1].legend(fontsize=8)
    for s in ("top","right"): ax[1].spines[s].set_visible(False)
    fig.tight_layout(pad=0.5); fig.savefig(path, transparent=True); plt.close(fig)

# ---- stereo AAC encode ---------------------------------------------------------------
def to_aac_b64(st):                                   # st: (N,2) float
    st = np.clip(st, -0.985, 0.985)
    st44 = np.stack([resample_poly(st[:,0],441,160), resample_poly(st[:,1],441,160)], 1)
    with tempfile.TemporaryDirectory() as d:
        wavfile.write(f"{d}/a.wav", 44100, (np.clip(st44,-1,1)*32767).astype(np.int16))
        subprocess.run(["afconvert","-f","m4af","-d","aac","-b","96000",f"{d}/a.wav",f"{d}/a.m4a"],
                       check=True, capture_output=True)
        return base64.b64encode(open(f"{d}/a.m4a","rb").read()).decode()
def png_b64(p): return base64.b64encode(open(p,"rb").read()).decode()
def diotic(mono): return np.stack([mono, mono], 1)

out = {"subjects": []}
for sub in SUBJECTS:
    x65 = SPEECH if sub["src"] == "speech" else MUSIC
    lraw, rraw = render_ear(x65, sub["aL"]), render_ear(x65, sub["aR"])
    original = diotic(x65 / _rms(x65) * 10 ** (-24/20))
    left_iso = diotic(_softknee(lraw / _rms(lraw) * T20))
    right_iso = diotic(_softknee(rraw / _rms(rraw) * T20))
    binaural = np.stack([lraw, rraw], 1)
    binaural = _softknee(binaural * (T20 / _rms(binaural)))          # keep L/R ratio, overall ~-20 dBFS
    ild = 20*np.log10(_rms(rraw)/(_rms(lraw)+1e-12))
    conds = [("original","Original","unaided",original),
             ("left","Left-ear fit","left audiogram",left_iso),
             ("right","Right-ear fit","right audiogram",right_iso),
             ("binaural","Binaural","each ear its own fit",binaural)]
    pth = os.path.join(SC, f"subj_{sub['id']}.png"); subject_png(sub, pth)
    out["subjects"].append(dict(
        id=sub["id"], name=sub["name"], kind=sub["kind"], blurb=sub["blurb"],
        placeholder=(sub["src"]=="music"), ild_db=round(float(ild),1), png=png_b64(pth),
        conditions=[dict(id=c, label=l, sub=s, aac=to_aac_b64(a)) for c,l,s,a in conds]))
    print(f"{sub['name']:12s} rendered | aided R-L level diff {ild:+.1f} dB")

json.dump(out, open(os.path.join(SC, "subjects.json"), "w"))
print("wrote subjects.json  %.2f MB" % (os.path.getsize(os.path.join(SC,"subjects.json"))/1e6))
