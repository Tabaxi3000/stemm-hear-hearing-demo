"""Build the 'Ours vs OpenMHA' gallery section -> openmha_section.json.
Per shape audiogram: Original / Ours (Rx) / OpenMHA NAL-NL2 / DSL / CAMFIT, at 65 dB SPL (16 kHz,
matching OpenMHA), loudness-matched. Also validates our Python NAL/DSL (the tool's engine) against
the real OpenMHA output and reports the mean spectral difference."""
import os, sys, json, base64, subprocess, tempfile
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

SC = "/private/tmp/claude-502/-Users-tabaxitft-Desktop-STEMM-HEAR/02cdbe4e-d460-4375-a16a-683a6e731aea/scratchpad"
PROJ = "/Users/tabaxitft/Desktop/STEMM-HEAR/FILTER BANKS/speech_resynthesis"
OMHA = os.path.join(PROJ, "openmha", "out")
sys.path.insert(0, os.path.join(PROJ, "colab")); sys.path.insert(0, os.path.join(PROJ, "openmha"))
import speech_resynth as sp, fitting
SR = 16000
FC = sp.band_centres(sp.band_edges(100.0, 7200.0, 28, "greenwood"))
COMMON = dict(backend="stft", n_bands=28, flo=100.0, fhi=7200.0, carrier="original",
              loud_ref=sp.dbfs_ref_for_spl(100.0), match_rms=False, gate_db=-45.0, gate_knee_db=18.0)
AUDIOGRAMS = {
    "sloping":  {250:20, 500:25, 1000:30, 2000:40, 4000:55, 8000:65},
    "flat":     {250:40, 500:42, 1000:45, 2000:45, 4000:48, 8000:50},
    "skislope": {250:15, 500:20, 1000:30, 2000:50, 4000:70, 8000:80},
}
NAME = {"sloping": "Sloping loss", "flat": "Flat loss (~40 dB)", "skislope": "Ski-slope loss"}

sr0, full = wavfile.read(os.path.join(SC, "frank_full.wav")); full = full.astype(float) / 32768.0
clip = full[int(40.15*sr0):int(60.15*sr0)]
x65 = clip / (np.sqrt(np.mean(clip**2)) + 1e-12) * 10**((65-100)/20)

def _rms(w): return float(np.sqrt(np.mean(w**2)) + 1e-12)
def _softknee(y, thr=0.92):
    a = np.abs(y); o = y.copy(); m = a > thr
    o[m] = np.sign(y[m]) * (thr + (1.0-thr)*np.tanh((a[m]-thr)/(1.0-thr))); return o
def match(y, db): return _softknee(y / _rms(y) * 10**(db/20))
def loadwav(p): sr, x = wavfile.read(p); return x.astype(float)/32768.0

def ours_rx(ag): return sp.run(x65, SR, gain=sp.PrescriptiveGain(FC, ag), attack_ms=5, release_ms=150, **COMMON)["waveform"]
def ours_rule(ag, rule): return sp.run(x65, SR, gain=fitting.GainTableWDRC(FC, ag, rule), attack_ms=5, release_ms=150, **COMMON)["waveform"]

def spec_db(y):                                   # coarse long-term 1/3-oct-ish band levels (dB)
    P = np.abs(np.fft.rfft(y*np.hanning(len(y))))**2; f = np.fft.rfftfreq(len(y), 1/SR)
    edges = np.geomspace(150, 7000, 16); out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (f >= lo) & (f < hi); out.append(10*np.log10(P[m].mean()+1e-12) if m.any() else -120)
    return np.array(out)

def aud_png(ag, path):
    fr = sorted(ag); xs = range(len(fr))
    fig, ax = plt.subplots(figsize=(3.7, 3.0), dpi=150)
    ax.plot(xs, [ag[f] for f in fr], "-x", color="#2C7A7B", ms=7, mew=2, lw=1.8)
    ax.set_xticks(list(xs)); ax.set_xticklabels([f"{f//1000}k" if f>=1000 else str(f) for f in fr], fontsize=8)
    ax.set_ylim(120,-10); ax.set_yticks(range(0,121,20)); ax.axhspan(-10,20,color="#EAF3F3",zorder=0)
    ax.set_ylabel("dB HL", fontsize=8.5); ax.set_xlabel("Frequency (Hz)", fontsize=8.5)
    ax.tick_params(labelsize=8); ax.grid(alpha=.25)
    for s in ("top","right"): ax.spines[s].set_visible(False)
    fig.tight_layout(pad=0.4); fig.savefig(path, transparent=True); plt.close(fig)

def to_aac_b64(y16):
    y32 = resample_poly(np.clip(y16, -0.985, 0.985), 2, 1)              # 16k -> 32k for AAC
    with tempfile.TemporaryDirectory() as d:
        wavfile.write(f"{d}/a.wav", 32000, (np.clip(y32,-1,1)*32767).astype(np.int16))
        subprocess.run(["afconvert","-f","m4af","-d","aac","-b","96000",f"{d}/a.wav",f"{d}/a.m4a"],
                       check=True, capture_output=True)
        return base64.b64encode(open(f"{d}/a.m4a","rb").read()).decode()
def png_b64(p): return base64.b64encode(open(p,"rb").read()).decode()

COND = [("original","Original","unaided","orig"), ("ours","Ours (Rx)","our prescriptive fit","rx"),
        ("nal_nl2","NAL-NL2","OpenMHA","nal"), ("dsl_mio","DSL m[i/o]","OpenMHA","dsl"),
        ("camfit","CAMFIT","OpenMHA","cam")]

out = {"audiograms": []}; valdiffs = []
for aid, ag in AUDIOGRAMS.items():
    raw = {"original": x65.copy(), "ours": ours_rx(ag)}
    for rule in ("nal_nl2","dsl_mio","camfit"):
        raw[rule] = loadwav(os.path.join(OMHA, f"openmha_{aid}_{rule}.wav"))
    # validate the tool's Python NAL/DSL vs real OpenMHA (mean abs band-level diff, dB)
    for rule in ("nal_nl2","dsl_mio"):
        d = np.abs(spec_db(ours_rule(ag, rule)) - spec_db(raw[rule]))
        valdiffs.append(d.mean())
    clips = {"original": match(raw["original"], -24)}
    for k in ("ours","nal_nl2","dsl_mio","camfit"): clips[k] = match(raw[k], -20)
    p = os.path.join(SC, f"omha_{aid}.png"); aud_png(ag, p)
    out["audiograms"].append(dict(id=aid, name=NAME[aid], png=png_b64(p),
        conditions=[dict(id=c, label=l, sub=s, cls=cl, aac=to_aac_b64(clips[c])) for c,l,s,cl in COND]))
    print(f"{aid}: rendered 5 conditions")

out["validation_db"] = round(float(np.mean(valdiffs)), 1)
json.dump(out, open(os.path.join(SC, "openmha_section.json"), "w"))
print(f"wrote openmha_section.json  ({os.path.getsize(os.path.join(SC,'openmha_section.json'))/1e6:.2f} MB) | "
      f"Python-vs-OpenMHA mean band diff {out['validation_db']} dB")
