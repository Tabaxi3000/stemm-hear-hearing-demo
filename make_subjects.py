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
sys.path.append("/Users/tabaxitft/Desktop/STEMM-HEAR/FILTER BANKS/speech_resynthesis/web")   # metrics
import speech_resynth as sp
import metrics
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
def subject_ag_png(sub, path):                                  # two-ear audiogram (matches the shapes)
    fig, ax = plt.subplots(figsize=(3.7, 3.0), dpi=150)
    fr = sorted(sub["aR"]); xs = range(len(fr))
    ax.plot(xs, [sub["aR"][f] for f in fr], "-o", color=RED, ms=5, lw=1.8, label="Right")
    ax.plot(xs, [sub["aL"][f] for f in fr], "-x", color=BLUE, ms=7, mew=2, lw=1.8, label="Left")
    ax.set_xticks(list(xs)); ax.set_xticklabels([f"{f//1000}k" if f>=1000 else str(f) for f in fr], fontsize=8)
    ax.set_ylim(120,-10); ax.set_yticks(range(0,121,20)); ax.axhspan(-10,20,color="#EAF3F3",zorder=0)
    ax.set_ylabel("dB HL", fontsize=8.5); ax.set_xlabel("Frequency (Hz)", fontsize=8.5)
    ax.tick_params(labelsize=8); ax.grid(alpha=.25); ax.legend(fontsize=8, loc="lower left")
    for s in ("top","right"): ax.spines[s].set_visible(False)
    fig.tight_layout(pad=0.4); fig.savefig(path, transparent=True); plt.close(fig)

def subject_io_png(sub, path):                                  # input/output curve => shows COMPRESSION
    fig, ax = plt.subplots(figsize=(3.7, 3.0), dpi=150)
    xin = np.linspace(0, 100, 200)
    ax.plot(xin, xin, "--", color="#9AA7A6", lw=1.2, label="unaided (y = x)")
    b = int(np.argmin(np.abs(FC - 2000.0)))                     # a representative band
    for ag, col, lab in [(sub["aR"], RED, "Right"), (sub["aL"], BLUE, "Left")]:
        pm = sp.PersonalizedGainMap(FC, audiogram=ag)           # slope < 1 => compression
        ax.plot(xin, pm.slope[b]*xin + pm.offset[b], "-", color=col, lw=2, label=f"{lab} @2 kHz")
    ax.set_xlim(0, 100); ax.set_ylim(0, 125)
    ax.set_xlabel("input level (dB SPL)", fontsize=8.5); ax.set_ylabel("output (dB SPL)", fontsize=8.5)
    ax.set_title("Input → output (compression)", fontsize=9.5)
    ax.tick_params(labelsize=8); ax.grid(alpha=.25); ax.legend(fontsize=7.5, loc="lower right")
    for s in ("top","right"): ax.spines[s].set_visible(False)
    fig.tight_layout(pad=0.4); fig.savefig(path, transparent=True); plt.close(fig)

# ---- stereo AAC encode ---------------------------------------------------------------
WEB = "/Users/tabaxitft/Desktop/STEMM-HEAR/FILTER BANKS/speech_resynthesis/web"
AUD = os.path.join(WEB, "audio"); os.makedirs(AUD, exist_ok=True)
def write_aac(st, name):                              # st: (N,2) float -> lazy-loaded .m4a file (URL)
    st = np.clip(st, -0.985, 0.985)
    with tempfile.TemporaryDirectory() as d:
        wavfile.write(f"{d}/a.wav", SR, (np.clip(st,-1,1)*32767).astype(np.int16))
        subprocess.run(["afconvert","-f","m4af","-d","aac","-b","96000",f"{d}/a.wav",os.path.join(AUD,name+".m4a")],
                       check=True, capture_output=True)
    return f"audio/{name}.m4a"
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
    conds = [("original","Original","unaided","orig",original),
             ("left","Left-ear fit","left audiogram","left",left_iso),
             ("right","Right-ear fit","right audiogram","right",right_iso),
             ("binaural","Binaural","each ear its own fit","bin",binaural)]
    agp = os.path.join(SC, f"subj_{sub['id']}_ag.png"); subject_ag_png(sub, agp)
    iop = os.path.join(SC, f"subj_{sub['id']}_io.png"); subject_io_png(sub, iop)
    out["subjects"].append(dict(
        id=sub["id"], name=sub["name"], kind=sub["kind"], blurb=sub["blurb"],
        placeholder=(sub["src"]=="music"), ild_db=round(float(ild),1),
        png=png_b64(agp), io=png_b64(iop),
        conditions=[dict(id=c, label=l, sub=s, cls=cl, file=write_aac(a, f"subj_{sub['id']}_{c}"),
                         **{k: metrics.poorer_ear_metrics(a, x65, SR, sub["aL"], sub["aR"])[k] for k in ("sii","stoi","err")})
                    for c,l,s,cl,a in conds]))
    print(f"{sub['name']:12s} rendered | aided R-L level diff {ild:+.1f} dB")

# ---- ILD / localization demo: a panned talker, independent vs linked compression -----
agSym = {250:30,500:35,1000:45,2000:55,4000:60,8000:60}         # symmetric, so only the ILD moves
x80 = speech / (np.sqrt(np.mean(speech**2)) + 1e-12) * 10**((80-100)/20)   # loud -> compression
ILD0 = 8.0
xLp, xRp = x80 * 10**(-ILD0/40), x80 * 10**(ILD0/40)           # +8 dB in the right ear
src = np.stack([xLp, xRp], 1)
indep = sp.binaural(xLp, xRp, SR, agSym, agSym, link=False)
linked = sp.binaural(xLp, xRp, SR, agSym, agSym, link=True)
scl = 0.94 / (max(np.max(np.abs(z)) for z in (src, indep, linked)) + 1e-9)   # common scale keeps ILD
out_ild = lambda st: 20*np.log10(_rms(st[:,1]) / _rms(st[:,0]))
oi = {"source": out_ild(src), "indep": out_ild(indep), "linked": out_ild(linked)}
print("ILD demo | source %.1f  independent %.1f  linked %.1f dB" % (oi["source"], oi["indep"], oi["linked"]))

ildp = os.path.join(SC, "subj_ild.png")
fig, axi = plt.subplots(figsize=(4.2, 3.0), dpi=150)
bars = ["source", "indep", "linked"]; cols = ["#A9762C", RED, "#2C7A7B"]
axi.bar(range(3), [oi[b] for b in bars], color=cols, width=.62)
axi.axhline(ILD0, ls="--", color="#7C8E8B", lw=1.3); axi.text(2.4, ILD0+.15, f"source ILD {ILD0:.0f} dB", fontsize=8, ha="right", color="#5C6E6B")
axi.set_xticks(range(3)); axi.set_xticklabels(["source", "independent", "linked"], fontsize=8.5)
axi.set_ylabel("output ILD (dB)", fontsize=9); axi.set_ylim(0, ILD0+2.5)
axi.set_title("Interaural level difference kept vs lost", fontsize=9.5)
for s_ in ("top", "right"): axi.spines[s_].set_visible(False)
fig.tight_layout(pad=.5); fig.savefig(ildp, transparent=True); plt.close(fig)

condsI = [("source", "Source", "unaided, panned right", "orig", src*scl),
          ("indep", "Independent", "two separate compressors", "right", indep*scl),
          ("linked", "Linked", "shared drive level", "bin", linked*scl)]
out["subjects"].append(dict(
    id="ild", name="Localization (ILD)", kind="Binaural · ILD preservation",
    blurb="A talker panned to the right (8 dB louder in the right ear). Independent per-ear compressors "
          "pull the loud ear down and shrink that cue &mdash; the talker drifts toward centre; linking the "
          "compression to a shared level preserves it.",
    figcap="Output interaural level difference", png=png_b64(ildp),
    conditions=[dict(id=c, label=l, sub=s, cls=cl, file=write_aac(a, f"ild_{c}")) for c,l,s,cl,a in condsI]))

json.dump(out, open(os.path.join(SC, "subjects.json"), "w"))
print("wrote subjects.json  %.2f MB" % (os.path.getsize(os.path.join(SC,"subjects.json"))/1e6))
