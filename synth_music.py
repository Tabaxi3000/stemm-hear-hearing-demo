"""Synthesize a ~20s public-domain placeholder instrumental (piano-like) for Musician A.
Clearly a stand-in; swap in the subject's real piece later."""
import numpy as np
from scipy.io import wavfile
SR=32000
def note(f, dur, sr=SR):
    t=np.arange(int(dur*sr))/sr
    y=sum((1.0/h**0.8)*np.sin(2*np.pi*f*h*t) for h in range(1,28))
    env=np.exp(-t/0.9)*(1-np.exp(-t/0.006))           # pluck: fast attack, slow decay
    return y*env
def chord(fs, dur): 
    m=max(len(note(f,dur)) for f in fs); out=np.zeros(m)
    for f in fs: out+=note(f,dur)
    return out
# I-V-vi-IV in C, twice; a simple melody on top
prog=[[261.63,329.63,392.00],[196.00,246.94,293.66],[220.00,261.63,329.63],[174.61,220.00,261.63]]
mel=[523.25,392.00,440.00,349.23, 523.25,587.33,523.25,392.00]  # one note per chord
beat=2.5
x=np.zeros(int(beat*8*SR))
for i in range(8):
    c=chord(prog[i%4], beat); s=int(i*beat*SR); x[s:s+len(c)]+=0.7*c
    mn=note(mel[i], beat); x[s:s+len(mn)]+=0.5*mn
x=x/(np.max(np.abs(x))+1e-9)*0.9
wavfile.write("placeholder_music.wav", SR, (x*32767).astype(np.int16))
print("placeholder_music.wav %.1fs"%(len(x)/SR))
