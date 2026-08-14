"""Build the 'fits in noise' gallery section -> noise_section.json.
The same clinical fits, but on speech in +5 dB SNR babble (one steep loss). This is where the
metrics spread out: in quiet they saturate, in noise HASPI/HASQI/STOI clearly separate the fits.
Uses our Python engine (fitting.GainTableWDRC / PrescriptiveGain) on the noisy input; every clip is
scored against the CLEAN reference with the full metric set (SII / STOI / HASPI / HASQI)."""
import os, sys, json, base64, subprocess, tempfile
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

SC = "/private/tmp/claude-502/-Users-tabaxitft-Desktop-STEMM-HEAR/02cdbe4e-d460-4375-a16a-683a6e731aea/scratchpad"
PROJ = "/Users/tabaxitft/Desktop/STEMM-HEAR/FILTER BANKS/speech_resynthesis"
sys.path.insert(0, os.path.join(PROJ, "colab")); sys.path.insert(0, os.path.join(PROJ, "openmha"))
sys.path.append(os.path.join(PROJ, "web"))
import speech_resynth as sp, fitting, metrics
SR = 16000
FC = sp.band_centres(sp.band_edges(100.0, 7200.0, 28, "greenwood"))
COMMON = dict(backend="stft", n_bands=28, flo=100.0, fhi=7200.0, carrier="original",
              loud_ref=sp.dbfs_ref_for_spl(100.0), match_rms=False, gate_db=-45.0, gate_knee_db=18.0)
AG = {250: 15, 500: 20, 1000: 30, 2000: 50, 4000: 70, 8000: 80}       # steep ski-slope loss
SNR, NOISE = 5.0, "babble"

sr0, full = wavfile.read(os.path.join(SC, "frank_full.wav")); full = full.astype(float) / 32768.0
clip = full[int(40.15*sr0):int(60.15*sr0)]
def present(y): return y / (np.sqrt(np.mean(y**2)) + 1e-12) * 10**((65-100)/20)
xclean = present(clip)                                                 # clean reference @65 dB SPL
xnoisy = present(sp.add_noise(xclean, SNR, NOISE))                     # unaided, noisy input @65 dB SPL

def fit(gain, x): return sp.run(x, SR, gain=gain, attack_ms=5, release_ms=150, **COMMON)["waveform"]
RAW = {"original": xnoisy,
       "nal": fit(fitting.GainTableWDRC(FC, AG, "nal_nl2"), xnoisy),
       "dsl": fit(fitting.GainTableWDRC(FC, AG, "dsl_mio"), xnoisy),
       "cam": fit(fitting.GainTableWDRC(FC, AG, "camfit"), xnoisy),
       "rx": fit(sp.PrescriptiveGain(FC, AG), xnoisy)}
COND = [("original", "Original", "unaided, +5 dB babble", "orig"),
        ("nal", "NAL-NL2", "in noise", "nal"), ("dsl", "DSL m[i/o]", "in noise", "dsl"),
        ("cam", "CAM2", "in noise", "cam"), ("rx", "Ours (Rx)", "in noise", "rx")]

def _rms(w): return float(np.sqrt(np.mean(w**2)) + 1e-12)
def _softknee(y, thr=0.92):
    a = np.abs(y); o = y.copy(); m = a > thr
    o[m] = np.sign(y[m]) * (thr + (1.0-thr)*np.tanh((a[m]-thr)/(1.0-thr))); return o
def match(y, db): return _softknee(y / _rms(y) * 10**(db/20))

WEB = os.path.join(PROJ, "web"); AUD = os.path.join(WEB, "audio"); os.makedirs(AUD, exist_ok=True)
def write_aac(y16, name):                                             # 16k -> 32k -> lazy .m4a
    y32 = resample_poly(np.clip(y16, -0.985, 0.985), 2, 1)
    with tempfile.TemporaryDirectory() as d:
        wavfile.write(f"{d}/a.wav", 32000, (np.clip(y32,-1,1)*32767).astype(np.int16))
        subprocess.run(["afconvert","-f","m4af","-d","aac","-b","96000",f"{d}/a.wav",os.path.join(AUD,name+".m4a")],
                       check=True, capture_output=True)
    return f"audio/{name}.m4a"

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

p = os.path.join(SC, "noise_ag.png"); aud_png(AG, p)
db = {"original": -24}
conds = []
for cid, lab, sub, cl in COND:
    conds.append(dict(id=cid, label=lab, sub=sub, cls=cl,
                      file=write_aac(match(RAW[cid], db.get(cid, -20)), f"noise_{cid}"),
                      **metrics.all_metrics(RAW[cid], xclean, SR, AG, full=True)))
out = {"name": "Ski-slope loss", "snr": SNR, "png": base64.b64encode(open(p,"rb").read()).decode(),
       "conditions": conds}
json.dump(out, open(os.path.join(SC, "noise_section.json"), "w"))
print("noise section:", {c["id"]: (c["sii"], c["stoi"], c.get("haspi"), c.get("hasqi")) for c in conds})
print("wrote noise_section.json")
