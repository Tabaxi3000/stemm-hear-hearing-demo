# STEMM-HEAR — band-by-band compression: a WDRC listening catalogue

An interactive demo of hearing-aid-style speech/music resynthesis. A filter bank splits the signal
into 28 Greenwood bands; each band's soft floor is lifted to the listener's threshold and compressed
above it. You can A/B:

- **Real subjects** (two ears fit independently, in stereo): *Speech A* (asymmetric loss) and
  *Musician A* (near-symmetric high-frequency loss; a **synthesised placeholder** stands in for the
  chosen piece).
- **Textbook shapes** (single ear): static vs WDRC compression, with the release time swept
  60 → 150 → 400 ms.

**Research prototype — not a medical device or a clinical fitting.** Processing is offline and played
to normal-hearing ears, so it shows the aid's *output*, not what an impaired listener perceives.
Audiograms are de-identified. UCL is estimated from the audiogram.

## Build
`index.html` is self-contained (audio + charts embedded as base64). To regenerate:
```
python make_assets.py      # textbook shapes  -> assets.json      (needs the source audio)
python make_subjects.py    # Speech A / Musician A -> subjects.json
python build_site.py       # assets.json + subjects.json -> index.html
```
Core DSP lives in `../colab/speech_resynth.py`.
