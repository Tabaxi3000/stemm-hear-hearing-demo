"""Build the binaural 'subjects vs OpenMHA' section -> subjects_openmha.json.
Per subject (Speech A -> speech, Musician A -> music), per EAR, we already rendered real OpenMHA
NAL-NL2 / DSL m[i/o] / CAMFIT (render_openmha_subjects.py). Here we combine L+R into stereo, add
Original (diotic) and Ours (Rx, per ear), loudness-match, and report the BETTER-EAR ANSI SII."""
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
sys.path.append(os.path.join(PROJ, "web"))
import speech_resynth as sp, fitting, metrics
SR = 16000
FC = sp.band_centres(sp.band_edges(100.0, 7200.0, 28, "greenwood"))
COMMON = dict(backend="stft", n_bands=28, flo=100.0, fhi=7200.0, carrier="original",
              loud_ref=sp.dbfs_ref_for_spl(100.0), match_rms=False, gate_db=-45.0, gate_knee_db=18.0)
RED, BLUE = "#C1443C", "#2C5AA0"

SUBJECTS = [
    dict(id="speech_a", name="Speech A", kind="Speech · asymmetric loss", src="speech",
         aR={250:35,500:55,1000:65,2000:60,4000:70,8000:35}, aL={250:15,500:15,1000:15,2000:20,4000:10,8000:20}),
    dict(id="musician_a", name="Musician A", kind="Music · near-symmetric loss", src="music",
         aR={250:30,500:30,1000:30,2000:35,4000:45,8000:50}, aL={250:30,500:30,1000:30,2000:35,4000:55,8000:60}),
]

def present65(x): return x / (np.sqrt(np.mean(x**2)) + 1e-12) * 10**((65-100)/20)
sr0, f0 = wavfile.read(os.path.join(SC, "frank_full.wav")); f0 = f0.astype(float)/32768.0
speech = f0[int(40.15*sr0):int(60.15*sr0)]
srm, m = wavfile.read(os.path.join(SC, "placeholder_music.wav")); m = m.astype(float)/32768.0
music = resample_poly(m, SR, srm) if srm != SR else m
SRC = {"speech": present65(speech), "music": present65(music)}

def _rms(w): return float(np.sqrt(np.mean(w**2)) + 1e-12)
def _softknee(y, thr=0.92):
    a = np.abs(y); o = y.copy(); m = a > thr
    o[m] = np.sign(y[m]) * (thr + (1.0-thr)*np.tanh((a[m]-thr)/(1.0-thr))); return o
def match_st(st, db):                                   # loudness-match a stereo clip by its joint RMS
    return _softknee(st / (np.sqrt(np.mean(st**2)) + 1e-12) * 10**(db/20))
def loadwav(p): sr, x = wavfile.read(p); return x.astype(float)/32768.0
def ours_ear(x65, ag): return sp.run(x65, SR, gain=sp.PrescriptiveGain(FC, ag),
                                     attack_ms=5, release_ms=150, **COMMON)["waveform"]

def twoear_png(sub, path):
    fr = sorted(sub["aR"]); xs = range(len(fr))
    fig, ax = plt.subplots(figsize=(3.7, 3.0), dpi=150)
    ax.plot(xs, [sub["aR"][f] for f in fr], "-o", color=RED, ms=5, lw=1.8, label="Right")
    ax.plot(xs, [sub["aL"][f] for f in fr], "-x", color=BLUE, ms=7, mew=2, lw=1.8, label="Left")
    ax.set_xticks(list(xs)); ax.set_xticklabels([f"{f//1000}k" if f>=1000 else str(f) for f in fr], fontsize=8)
    ax.set_ylim(120,-10); ax.set_yticks(range(0,121,20)); ax.axhspan(-10,20,color="#EAF3F3",zorder=0)
    ax.set_ylabel("dB HL", fontsize=8.5); ax.set_xlabel("Frequency (Hz)", fontsize=8.5)
    ax.tick_params(labelsize=8); ax.grid(alpha=.25); ax.legend(fontsize=8, loc="lower left")
    for s in ("top","right"): ax.spines[s].set_visible(False)
    fig.tight_layout(pad=0.4); fig.savefig(path, transparent=True); plt.close(fig)

WEB = os.path.join(PROJ, "web"); AUD = os.path.join(WEB, "audio"); os.makedirs(AUD, exist_ok=True)
def write_aac(st, name):                                # (N,2) float @16k -> lazy stereo .m4a
    st = np.clip(st, -0.985, 0.985)
    with tempfile.TemporaryDirectory() as d:
        wavfile.write(f"{d}/a.wav", SR, (np.clip(st,-1,1)*32767).astype(np.int16))
        subprocess.run(["afconvert","-f","m4af","-d","aac","-b","96000",f"{d}/a.wav",
                        os.path.join(AUD,name+".m4a")], check=True, capture_output=True)
    return f"audio/{name}.m4a"
def png_b64(p): return base64.b64encode(open(p,"rb").read()).decode()

def poorer_ear_sii(stereo, src, sub):                   # min of the two monaural ANSI SII: the ear
    sL = sp.official_sii(stereo[:,0], src, SR, sub["aL"])   # the fit actually has to work on (the
    sR = sp.official_sii(stereo[:,1], src, SR, sub["aR"])   # better ear can sit near ceiling)
    return round(float(min(sL, sR)), 2)

COND = [("original","Original","unaided","orig"), ("ours","Ours (Rx)","our prescriptive fit","rx"),
        ("nal_nl2","NAL-NL2","OpenMHA","nal"), ("dsl_mio","DSL m[i/o]","OpenMHA","dsl"),
        ("camfit","CAMFIT / CAM2","OpenMHA","cam")]

out = {"subjects": []}
for sub in SUBJECTS:
    x65 = SRC[sub["src"]]
    stereo = {"original": np.stack([x65, x65], 1),
              "ours": np.stack([ours_ear(x65, sub["aL"]), ours_ear(x65, sub["aR"])], 1)}
    for rule in ("nal_nl2","dsl_mio","camfit"):
        L = loadwav(os.path.join(OMHA, f"omhasub_{sub['id']}_L_{rule}.wav"))
        R = loadwav(os.path.join(OMHA, f"omhasub_{sub['id']}_R_{rule}.wav"))
        n = min(len(L), len(R), len(x65)); stereo[rule] = np.stack([L[:n], R[:n]], 1)
    clips = {"original": match_st(stereo["original"], -24)}
    for k in ("ours","nal_nl2","dsl_mio","camfit"): clips[k] = match_st(stereo[k], -20)
    p = os.path.join(SC, f"subomha_{sub['id']}.png"); twoear_png(sub, p)
    conds = []
    for cid, lab, s, cl in COND:
        pm = metrics.poorer_ear_metrics(stereo[cid], x65, SR, sub["aL"], sub["aR"])
        conds.append(dict(id=cid, label=lab, sub=s, cls=cl,
                          sii=pm["sii"], stoi=pm["stoi"], err=pm["err"],
                          file=write_aac(clips[cid], f"subomha_{sub['id']}_{cid}")))
    out["subjects"].append(dict(id=sub["id"], name=sub["name"], kind=sub["kind"],
                                placeholder=(sub["src"]=="music"), png=png_b64(p), conditions=conds))
    print(f"{sub['name']:12s} SII better-ear:", {c['id']: c['sii'] for c in conds})

json.dump(out, open(os.path.join(SC, "subjects_openmha.json"), "w"))
print("wrote subjects_openmha.json  %.3f MB" % (os.path.getsize(os.path.join(SC,"subjects_openmha.json"))/1e6))
