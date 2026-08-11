"""Build the self-contained demo website (index.html) from assets.json + subjects.json.

    (in scratchpad) python make_assets.py ; python make_subjects.py
    cp <scratchpad>/assets.json <scratchpad>/subjects.json .
    python build_site.py            # -> index.html   (single file; GitHub Pages / Artifact ready)

All audio + charts are embedded as base64 data URIs, so the page has no external requests.
"""
import os, json, html, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
# keep a copy of the real module next to the site so the in-browser tool (Pyodide) can fetch it
shutil.copy(os.path.join(HERE, "..", "colab", "speech_resynth.py"), os.path.join(HERE, "speech_resynth.py"))
A = json.load(open(os.path.join(HERE, "assets.json")))
S = json.load(open(os.path.join(HERE, "subjects.json")))

BLURB = {
    "sloping":  "Gentle high-frequency slope; near-normal lows.",
    "flat":     "Roughly equal loss across frequency — the 40 dB example.",
    "skislope": "Near-normal lows, severe highs — the hardest fit.",
}
COND = {"static": ("STATIC", "no dynamics", "static"), "wdrc_fast": ("60", "fast release", "fast"),
        "wdrc_med": ("150", "medium", "med"), "wdrc_slow": ("400", "slow release", "slow"),
        "prescriptive": ("Rx", "realistic fit", "rx")}
# per-subject copy + which part is a stand-in (audiogram vs music)
SUBJECT_META = {
    "speech_a": {"ph": "placeholder audiogram",
                 "blurb": "Strongly asymmetric loss — right ear moderate-severe, left near-normal, so the "
                          "ears get very different fits. Real audiogram to come; the shape here is a stand-in."},
    "musician_a": {"ph": "placeholder music",
                   "blurb": "Real audiogram — mild-to-mod-severe high-frequency loss, a little worse on the "
                            "left. A synthesised clip stands in for the chosen piece for now."},
}
SUBCOND = {"original": ("Original", "unaided", "orig"), "left": ("L fit", "left audiogram", "left"),
           "right": ("R fit", "right audiogram", "right"), "binaural": ("Binaural", "per-ear", "bin")}

PLAY = '<svg viewBox="0 0 24 24" class="i-play"><path d="M8 5v14l11-7z"/></svg>'
PAUSE = '<svg viewBox="0 0 24 24" class="i-pause"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>'


def transport(cur_label):
    return f"""<div class="transport">
        <button class="play" aria-label="Play">{PLAY}{PAUSE}</button>
        <div class="scrub"><div class="fill"></div><input class="seek" type="range"
          min="0" max="1000" value="0" aria-label="Seek"></div>
        <span class="time"><b>0:00</b> / <span>0:20</span></span>
      </div>
      <p class="cue"><span class="dot"></span><b class="cur">{cur_label}</b><span class="hint">{{hint}}</span></p>"""


def shape_section(n, s):
    sid = s["id"]
    audios = [f'<audio data-i="0" preload="auto" src="data:audio/mp4;base64,{A["original_aac"]}"></audio>']
    chips = ['<button class="chip c-orig" data-i="0" aria-pressed="true">Original<em>unaided</em></button>']
    for i, c in enumerate(s["conditions"], start=1):
        audios.append(f'<audio data-i="{i}" preload="auto" src="data:audio/mp4;base64,{c["aac"]}"></audio>')
        lab, sub, cls = COND[c["id"]]
        unit = '<span class="u">ms</span>' if c["id"].startswith("wdrc_") else ""
        chips.append(f'<button class="chip c-{cls}" data-i="{i}" aria-pressed="false">{lab}{unit}<em>{sub}</em></button>')
    hint = "&mdash; switch while it plays; position holds, so you A/B the same instant"
    return f"""
    <section class="specimen" id="st-{sid}" data-player>
      <div class="sp-head"><span class="sp-num">{n:02d}</span>
        <div class="sp-title"><h2>{html.escape(s['name'])}</h2>
        <p class="sp-blurb">{BLURB[sid]}</p></div></div>
      <div class="charts">
        <figure class="paper"><img alt="Audiogram, {html.escape(s['name'])}"
          src="data:image/png;base64,{s['png']}"><figcaption>Audiogram</figcaption></figure>
        <figure class="paper"><img alt="Input/output compression curve"
          src="data:image/png;base64,{s['comp']}"><figcaption>Prescribed&nbsp;in&nbsp;/&nbsp;out</figcaption></figure>
      </div>
      <div class="console"><div class="chips">{chips[0]}<span class="sep"></span>
        <span class="ramp">{''.join(chips[1:])}</span></div>
        {transport('Original').format(hint=hint)}</div>
      <div class="audio-pool" hidden>{''.join(audios)}</div>
    </section>"""


def subject_section(s):
    meta = SUBJECT_META.get(s["id"], {})
    badge = (f'<span class="badge">{meta["ph"]}</span>' if meta.get("ph") else "")
    blurb = meta.get("blurb", s.get("blurb", ""))
    ild_txt = ""
    if "ild_db" in s:
        ild = s["ild_db"]
        ild_txt = (f'Aided right&minus;left level difference <b>{ild:+.0f}&nbsp;dB</b>.'
                   if abs(ild) >= 1 else 'The two ears end up <b>nearly matched</b>.')
    audios, chips = [], []
    for i, c in enumerate(s["conditions"]):
        audios.append(f'<audio data-i="{i}" preload="auto" src="data:audio/mp4;base64,{c["aac"]}"></audio>')
        pressed = "true" if i == 0 else "false"
        chips.append(f'<button class="chip c-{c["cls"]}" data-i="{i}" aria-pressed="{pressed}">'
                     f'{html.escape(c["label"])}<em>{html.escape(c["sub"])}</em></button>')
    hint = "&mdash; headphones: the two ears differ"
    figcap = s.get("figcap", "Both ears &mdash; audiogram &amp; prescribed gain")
    return f"""
    <section class="specimen subject" id="st-{s['id']}" data-player>
      <div class="sp-head"><span class="sp-num sub">&#9670;</span>
        <div class="sp-title"><h2>{html.escape(s['name'])} <span class="kind">{html.escape(s['kind'])}</span>{badge}</h2>
        <p class="sp-blurb">{html.escape(blurb)} {ild_txt}</p></div></div>
      <figure class="paper wide"><img alt="{html.escape(s['name'])}"
        src="data:image/png;base64,{s['png']}"><figcaption>{figcap}</figcaption></figure>
      <div class="console"><div class="chips">{chips[0]}<span class="sep"></span>
        <span class="ramp">{''.join(chips[1:])}</span></div>
        {transport('Original').format(hint=hint)}</div>
      <div class="audio-pool" hidden>{''.join(audios)}</div>
    </section>"""


SUBJECTS = "\n".join(subject_section(s) for s in S["subjects"] if s["id"] != "ild")
ILD = "\n".join(subject_section(s) for s in S["subjects"] if s["id"] == "ild")
SHAPES = "\n".join(shape_section(i + 1, s) for i, s in enumerate(A["audiograms"]))
RAIL_SUB = "\n".join(f'<a href="#st-{s["id"]}" data-spy="st-{s["id"]}"><span>&#9670;</span>{html.escape(s["name"])}</a>'
                     for s in S["subjects"])
RAIL_SHAPE = "\n".join(f'<a href="#st-{s["id"]}" data-spy="st-{s["id"]}"><span>{i+1:02d}</span>{html.escape(s["name"])}</a>'
                       for i, s in enumerate(A["audiograms"]))

DSP_JS = open(os.path.join(HERE, "dsp.js")).read()
TOOL_JS = open(os.path.join(HERE, "tool.js")).read()

TOOL_CSS = """
.tool{padding:34px 0 40px;border-top:1px solid var(--line)}
.tool-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:22px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:var(--sh)}
.filebtn{display:inline-block;font-family:var(--mono);font-size:13px;font-weight:600;color:#fff;background:var(--teal);
  border-radius:9px;padding:8px 14px;cursor:pointer;transition:transform .06s}
.filebtn:hover{transform:translateY(-1px)} .filebtn input{display:none}
.fname{font-family:var(--mono);font-size:11px;color:var(--muted);margin-left:10px}
.presets{font-size:11px;color:var(--muted);margin:16px 0 8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-family:var(--mono)}
.presets button{font-family:var(--mono);font-size:11px;border:1px solid var(--line);background:transparent;color:var(--ink-2);
  border-radius:6px;padding:3px 8px;cursor:pointer}
.presets button:hover{border-color:var(--teal);color:var(--teal)}
.agwrap{display:flex;flex-direction:column;gap:12px;margin:6px 0 14px}
#agc{background:var(--paper);border:1px solid var(--line);border-radius:8px;width:100%;height:auto}
.sliders{display:flex;gap:2px;justify-content:space-between;padding:0 2px}
.sl{display:flex;flex-direction:column;align-items:center;gap:5px;font-family:var(--mono);font-size:9px;color:var(--muted)}
.sl input[type=range]{-webkit-appearance:slider-vertical;writing-mode:vertical-lr;direction:rtl;width:18px;height:110px;accent-color:var(--teal)}
.sl .slv{color:var(--ink-2);font-weight:600}
.rowctl{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--muted);margin:6px 0 16px;font-family:var(--mono)}
.rowctl input[type=range]{flex:1;accent-color:var(--teal)}
.runbtn{font-family:var(--mono);font-weight:600;font-size:14px;color:#fff;background:var(--teal);border:none;
  border-radius:10px;padding:10px 22px;cursor:pointer;transition:transform .06s}
.runbtn:hover{transform:translateY(-1px)} .runbtn:disabled{opacity:.45;cursor:default;transform:none}
.status{font-family:var(--mono);font-size:11px;color:var(--muted);margin-left:12px}
#tchips .chip:disabled{opacity:.45;cursor:default}
.dlrow{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-top:16px;font-family:var(--mono);font-size:11px;color:var(--muted)}
.dl{color:var(--teal);text-decoration:none;border-bottom:1px solid color-mix(in srgb,var(--teal) 40%,transparent);cursor:pointer}
.engine{font-family:var(--mono);font-size:10.5px;color:var(--muted);margin-top:12px;padding-top:9px;border-top:1px dashed var(--line)}
@media (max-width:560px){.tool-grid{grid-template-columns:1fr}.agwrap{flex-direction:column}}
"""

TOOL_HTML = f"""
    <p class="band-label">Interactive &mdash; run the pipeline on your own audio</p>
    <section class="tool" id="tool">
      <div class="sp-head"><span class="sp-num sub">&#9881;</span>
        <div class="sp-title"><h2>Try your own <span class="kind">upload · in-browser · exact</span></h2>
        <p class="sp-blurb">Upload a WAV or MP3, set an audiogram, and hear it re-synthesised &mdash; Original
        vs Static vs WDRC, at 32&nbsp;kHz with the bank running to 12&nbsp;kHz. It runs the <b>real Python
        module</b> in your browser via Pyodide (numpy/scipy in WebAssembly), so the output is notebook-identical;
        the first run downloads ~30&nbsp;MB and falls back to a JS approximation if that can't load. Nothing is
        uploaded &mdash; it all runs on your machine.</p></div></div>
      <div class="tool-grid">
        <div class="panel">
          <label class="filebtn">Choose audio<input type="file" id="tf" accept="audio/*"></label>
          <span id="fname" class="fname">no file chosen yet</span>
          <div class="presets">audiogram:
            <button data-preset="normal">normal</button><button data-preset="sloping">sloping</button>
            <button data-preset="flat">flat 40</button><button data-preset="ski">ski-slope</button></div>
          <div class="agwrap"><canvas id="agc" width="290" height="170"></canvas>
            <div class="sliders" id="sliders"></div></div>
          <div class="rowctl"><label for="rel">WDRC release</label>
            <input type="range" id="rel" min="20" max="600" step="10" value="150"><span id="relv">150 ms</span></div>
          <button id="run" class="runbtn" disabled>Process</button>
          <span id="tstatus" class="status">pick an audio file to start</span>
          <div id="engine" class="engine">engine: real Python module (Pyodide) &mdash; boots on first use</div>
        </div>
        <div class="panel">
          <div class="chips" id="tchips">
            <button class="chip c-orig" data-i="0" aria-pressed="true" disabled>Original<em>unaided</em></button>
            <span class="sep"></span>
            <span class="ramp">
              <button class="chip c-static" data-i="1" aria-pressed="false" disabled>Static<em>no dynamics</em></button>
              <button class="chip c-med" data-i="2" aria-pressed="false" disabled>WDRC<em>attack/release</em></button>
            </span>
          </div>
          <div class="transport">
            <button class="play" id="tplay" aria-label="Play" disabled>{PLAY}{PAUSE}</button>
            <div class="scrub"><div class="fill" id="tfill"></div><input class="seek" id="tseek" type="range"
              min="0" max="1000" value="0" aria-label="Seek"></div>
            <span class="time" id="ttime"><b>0:00</b> / 0:00</span>
          </div>
          <p class="cue"><span class="dot"></span><b class="cur" id="tcur">Original</b><span class="hint">&mdash;
            process a file, then switch to compare</span></p>
          <div class="dlrow" id="dlrow" style="display:none">download:
            <a id="dl_original" class="dl">original.wav</a><a id="dl_static" class="dl">static.wav</a>
            <a id="dl_wdrc" class="dl">wdrc.wav</a></div>
        </div>
      </div>
    </section>"""

DOC = f"""<title>Band-by-band compression &mdash; a WDRC listening catalogue</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{
  --bg:#ECF1F0; --paper:#FCFDFC; --panel:#FBFDFC;
  --ink:#101B1A; --ink-2:#3B4B49; --muted:#69807C; --line:#D5E0DD;
  --teal:#22706F; --teal-2:#0E3B3B; --teal-3:#8FBDBB; --amber:#9C6A1E;
  --red:#C0392B; --blue:#2C6FB0; --rx:#3F7D54;
  --c-static:#5F817F; --c-fast:#8FBDBB; --c-med:#22706F; --c-slow:#0E3B3B;
  --mono:ui-monospace,"SF Mono","Roboto Mono",Menlo,Consolas,monospace;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --sh:0 1px 1px rgba(16,27,26,.04),0 10px 26px -16px rgba(16,27,26,.26);
}}
@media (prefers-color-scheme:dark){{ :root{{
  --bg:#0B1413; --paper:#FCFDFC; --panel:#111E1C; --ink:#E6EEEC; --ink-2:#B3C4C1;
  --muted:#7E938F; --line:#213230; --teal:#4FA3A2; --teal-2:#78C4C3; --teal-3:#2E524F;
  --amber:#C89A54; --red:#E0685A; --blue:#5E9BD6; --rx:#5FA877;
  --c-static:#89A6A3; --c-fast:#2E524F; --c-med:#4FA3A2; --c-slow:#78C4C3;
  --sh:0 1px 1px rgba(0,0,0,.4),0 12px 30px -16px rgba(0,0,0,.7);
}} }}
:root[data-theme="light"]{{ --bg:#ECF1F0;--paper:#FCFDFC;--panel:#FBFDFC;--ink:#101B1A;--ink-2:#3B4B49;
  --muted:#69807C;--line:#D5E0DD;--teal:#22706F;--teal-2:#0E3B3B;--teal-3:#8FBDBB;--amber:#9C6A1E;
  --red:#C0392B;--blue:#2C6FB0;--rx:#3F7D54;--c-static:#5F817F;--c-fast:#8FBDBB;--c-med:#22706F;--c-slow:#0E3B3B; }}
:root[data-theme="dark"]{{ --bg:#0B1413;--paper:#FCFDFC;--panel:#111E1C;--ink:#E6EEEC;--ink-2:#B3C4C1;
  --muted:#7E938F;--line:#213230;--teal:#4FA3A2;--teal-2:#78C4C3;--teal-3:#2E524F;--amber:#C89A54;
  --red:#E0685A;--blue:#5E9BD6;--rx:#5FA877;--c-static:#89A6A3;--c-fast:#2E524F;--c-med:#4FA3A2;--c-slow:#78C4C3; }}

*{{box-sizing:border-box}} html{{scroll-behavior:smooth}}
@media (prefers-reduced-motion:reduce){{ html{{scroll-behavior:auto}} *{{transition:none!important}} }}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5;-webkit-font-smoothing:antialiased}}
h1,h2{{font-family:var(--serif);font-weight:600;letter-spacing:-.012em;text-wrap:balance;margin:0}}

.mast{{border-bottom:1px solid var(--line)}}
.mast .in{{max-width:1160px;margin:0 auto;padding:30px 28px 26px}}
.kick{{font-family:var(--mono);font-size:11px;letter-spacing:.24em;text-transform:uppercase;color:var(--teal);
  margin:0 0 14px;display:flex;align-items:center;gap:10px}}
.kick::after{{content:"";height:1px;flex:1;background:var(--line)}}
h1{{font-size:clamp(28px,4.2vw,44px);line-height:1.05;max-width:15ch}}
.dek{{font-size:clamp(14.5px,1.5vw,17px);color:var(--muted);max-width:58ch;margin:14px 0 0}}
.dek b{{color:var(--ink-2);font-weight:600}}

.shell{{max-width:1160px;margin:0 auto;padding:0 28px;display:grid;grid-template-columns:200px 1fr;gap:44px;align-items:start}}
.rail{{position:sticky;top:0;padding:36px 0 40px;font-family:var(--mono)}}
.rail h3{{font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);margin:0 0 12px;font-weight:600}}
.rail h3.mt{{margin-top:22px}}
.rail nav{{display:flex;flex-direction:column;gap:2px;margin-bottom:8px}}
.rail a{{display:flex;gap:10px;align-items:baseline;text-decoration:none;color:var(--ink-2);font-size:12.5px;
  padding:7px 10px;border-radius:7px;border-left:2px solid transparent;transition:color .15s,background .15s,border-color .15s}}
.rail a span{{color:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}}
.rail a:hover{{background:color-mix(in srgb,var(--teal) 9%,transparent);color:var(--ink)}}
.rail a.active{{color:var(--teal);border-left-color:var(--teal);background:color-mix(in srgb,var(--teal) 10%,transparent)}}
.rail a.active span{{color:var(--teal)}}
.key{{display:flex;flex-direction:column;gap:9px;padding-top:22px;margin-top:14px;border-top:1px solid var(--line)}}
.key .r{{display:flex;align-items:center;gap:9px;font-size:11px;color:var(--muted)}}
.key .sw{{width:11px;height:11px;border-radius:3px;flex:none}} .key b{{color:var(--ink-2);font-weight:600}}
.foot-note{{margin-top:20px;padding-top:18px;border-top:1px solid var(--line);font-size:10.5px;line-height:1.7;color:var(--muted);letter-spacing:.02em}}

main{{padding:14px 0 20px;min-width:0}}
.band-label{{font-family:var(--mono);font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--teal);
  margin:8px 0 -10px;padding-top:10px}}
.specimen{{padding:34px 0 40px;border-top:1px solid var(--line)}}
.specimen:first-of-type{{border-top:none}}
.sp-head{{display:flex;gap:18px;align-items:flex-start}}
.sp-num{{font-family:var(--mono);font-size:clamp(30px,4vw,44px);font-weight:600;line-height:.9;color:var(--teal-3);
  letter-spacing:-.02em;flex:none;padding-top:3px}}
.sp-num.sub{{font-size:26px;color:var(--teal)}}
.sp-title h2{{font-size:clamp(20px,2.4vw,27px)}}
.kind{{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
  border:1px solid var(--line);border-radius:6px;padding:2px 7px;margin-left:8px;vertical-align:middle;white-space:nowrap}}
.badge{{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--amber);
  border:1px solid color-mix(in srgb,var(--amber) 45%,var(--line));border-radius:6px;padding:2px 7px;margin-left:8px;vertical-align:middle}}
.sp-blurb{{color:var(--muted);font-size:14px;margin:6px 0 0}} .sp-blurb b{{color:var(--ink-2);font-weight:600}}

.charts{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:22px 0}}
figure.paper{{margin:0;background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:14px 14px 9px;box-shadow:var(--sh)}}
figure.paper.wide{{margin:22px 0}}
figure.paper img{{display:block;width:100%;height:auto}}
figure.paper figcaption{{font-family:var(--mono);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:#7C8E8B;margin-top:7px}}

.console{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px 15px;box-shadow:var(--sh)}}
.chips{{display:flex;flex-wrap:wrap;align-items:stretch;gap:8px}} .ramp{{display:flex;gap:8px;flex-wrap:wrap}}
.sep{{width:1px;background:var(--line);margin:3px 3px}}
.chip{{font-family:var(--mono);font-size:15px;font-weight:600;color:var(--ink);cursor:pointer;background:transparent;
  border:1.5px solid var(--line);border-radius:10px;padding:7px 12px 6px;display:flex;flex-direction:column;line-height:1.15;
  letter-spacing:.01em;transition:border-color .14s,background .14s,color .14s,transform .06s}}
.chip .u{{font-size:9.5px;font-weight:400;color:var(--muted);margin-left:1px}}
.chip em{{font-style:normal;font-family:var(--sans);font-size:9.5px;font-weight:400;letter-spacing:0;color:var(--muted);margin-top:1px}}
.chip:hover{{transform:translateY(-1px);border-color:var(--muted)}}
.chip:focus-visible{{outline:2px solid var(--teal);outline-offset:2px}}
.chip[aria-pressed="true"]{{color:#fff;border-color:transparent}}
.chip[aria-pressed="true"] em,.chip[aria-pressed="true"] .u{{color:rgba(255,255,255,.8)}}
.c-orig[aria-pressed="true"]{{background:var(--amber)}}
.c-static[aria-pressed="true"]{{background:var(--c-static)}}
.c-fast[aria-pressed="true"]{{background:var(--c-fast);color:var(--teal-2)}}
.c-fast[aria-pressed="true"] em,.c-fast[aria-pressed="true"] .u{{color:color-mix(in srgb,var(--teal-2) 70%,transparent)}}
.c-med[aria-pressed="true"]{{background:var(--c-med)}} .c-slow[aria-pressed="true"]{{background:var(--c-slow)}}
.c-left[aria-pressed="true"]{{background:var(--blue)}} .c-right[aria-pressed="true"]{{background:var(--red)}}
.c-bin[aria-pressed="true"]{{background:var(--teal)}} .c-rx[aria-pressed="true"]{{background:var(--rx)}}

.transport{{display:flex;align-items:center;gap:15px;margin:16px 0 0}}
.play{{flex:none;width:44px;height:44px;border-radius:50%;border:none;cursor:pointer;background:var(--teal);
  display:grid;place-items:center;box-shadow:0 4px 13px -5px color-mix(in srgb,var(--teal) 75%,transparent);transition:transform .06s}}
.play:hover{{transform:scale(1.05)}} .play:active{{transform:scale(.95)}}
.play:focus-visible{{outline:2px solid var(--teal);outline-offset:3px}}
.play svg{{width:19px;height:19px;fill:#fff}} .play .i-pause{{display:none}}
.play.on .i-play{{display:none}} .play.on .i-pause{{display:block}}
.scrub{{position:relative;flex:1;height:7px;border-radius:99px;background:var(--line)}}
.fill{{position:absolute;inset:0 auto 0 0;width:0;border-radius:99px;background:linear-gradient(90deg,var(--teal-3),var(--teal));pointer-events:none}}
.seek{{position:absolute;inset:-8px 0;width:100%;margin:0;opacity:0;cursor:pointer}}
.time{{font-family:var(--mono);font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}}
.time b{{color:var(--ink)}}
.cue{{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--muted);margin:13px 0 0}}
.cue .dot{{width:8px;height:8px;border-radius:50%;background:var(--amber);flex:none;transition:background .14s}}
.cue .cur{{font-family:var(--mono);font-weight:600;color:var(--ink);font-size:12px}} .cue .hint{{color:var(--muted)}}

footer{{border-top:1px solid var(--line);margin-top:8px;background:var(--panel)}}
footer .in{{max-width:1160px;margin:0 auto;padding:26px 28px 46px}}
footer .lbl{{font-family:var(--mono);font-size:10.5px;letter-spacing:.2em;text-transform:uppercase;color:var(--teal);margin:0 0 10px}}
footer p{{font-size:12.5px;color:var(--muted);max-width:92ch;margin:0 0 9px;line-height:1.6}} footer b{{color:var(--ink-2);font-weight:600}}
footer .warn{{border-left:2px solid var(--amber);padding-left:12px;margin-top:14px}}
#th{{position:fixed;right:15px;bottom:15px;width:38px;height:38px;border-radius:50%;border:1px solid var(--line);
  background:var(--panel);color:var(--ink);font-size:16px;cursor:pointer;box-shadow:var(--sh);z-index:20}}
#th:focus-visible{{outline:2px solid var(--teal);outline-offset:2px}}
{TOOL_CSS}
@media (max-width:840px){{
  .shell{{grid-template-columns:1fr;gap:0}}
  .rail{{position:static;padding:22px 0 6px;border-bottom:1px solid var(--line);margin-bottom:8px}}
  .rail nav{{flex-direction:row;flex-wrap:wrap;gap:6px}} .rail a{{border-left:none;border:1px solid var(--line)}}
  .rail a.active{{border-color:var(--teal)}} .key{{flex-flow:row wrap;gap:8px 16px}} .foot-note{{display:none}}
}}
@media (max-width:560px){{ .charts{{grid-template-columns:1fr}} .transport{{flex-wrap:wrap}} .scrub{{order:3;flex-basis:100%}} }}
</style>

<div class="mast"><div class="in">
  <p class="kick">STEMM-HEAR · filterbank resynthesis</p>
  <h1>Compression, band by band</h1>
  <p class="dek">Speech and music refit for real losses, at <b>65&nbsp;dB SPL</b>. Each fit lifts every
  band's soft floor to the listener's threshold and compresses above it; the buttons change only
  <b>how the gain moves in time</b> &mdash; and, for the subjects, <b>how each ear is fit</b>.</p>
</div></div>

<div class="shell">
  <aside class="rail">
    <h3>Interactive</h3>
    <nav><a href="#tool" data-spy="tool"><span>&#9881;</span>Try your own</a></nav>
    <h3 class="mt">Subjects</h3>
    <nav>{RAIL_SUB}</nav>
    <h3 class="mt">Textbook shapes</h3>
    <nav>{RAIL_SHAPE}</nav>
    <div class="key">
      <div class="r"><span class="sw" style="background:var(--amber)"></span><b>Original</b>&nbsp;unaided</div>
      <div class="r"><span class="sw" style="background:var(--red)"></span><b>Right</b>&nbsp;ear fit</div>
      <div class="r"><span class="sw" style="background:var(--blue)"></span><b>Left</b>&nbsp;ear fit</div>
      <div class="r"><span class="sw" style="background:var(--c-static)"></span><b>Static</b>&nbsp;/ WDRC ramp</div>
    </div>
    <p class="foot-note">Headphones recommended. Clips are loudness-matched &mdash; you're comparing
    spectral shaping and compression dynamics, not volume.</p>
  </aside>

  <main>
    <p class="band-label">Real subjects &mdash; two ears, fit independently</p>
{SUBJECTS}
    <p class="band-label">Binaural &mdash; keeping localization (ILD)</p>
{ILD}
    <p class="band-label">Textbook shapes &mdash; static vs WDRC, release swept</p>
{SHAPES}
{TOOL_HTML}
  </main>
</div>

<footer><div class="in">
  <p class="lbl">Method</p>
  <p><b>STFT filter bank</b>, 32 Greenwood bands to <b>12&nbsp;kHz</b> (32&nbsp;kHz sample rate), original
  fine-structure carrier at <b>65&nbsp;dB SPL</b>. The 64&nbsp;kbps audiobook speech is band-limited to
  ~8&nbsp;kHz, so the wider bank shows mainly on the music and on high-quality uploads.
  Per-band gain is a straight line mapping the input range onto <b>[threshold, UCL]</b> with a low-level
  expansion floor. <b>Static</b> applies it instantaneously; <b>WDRC</b> adds a 5&nbsp;ms attack and a
  <b>60&nbsp;/&nbsp;150&nbsp;/&nbsp;400&nbsp;ms</b> release. The <b>Prescriptive</b> tab swaps full
  lift-to-threshold for a realistic half-gain + high-frequency rolloff + output-limiting fit, so a steep
  loss no longer over-amplifies sibilants. Subjects are fit per ear and played in stereo.
  <b>Musician A</b> uses a real audiogram (the music is a synthesised placeholder for now);
  <b>Speech A</b> pairs a real speech clip with a <b>placeholder audiogram</b> until the subject's own
  is available.</p>
  <p class="warn"><b>Research prototype &mdash; not a medical device or a fitting.</b> Processing is offline
  and played to normal-hearing ears, so it shows the aid's output, not what an impaired listener perceives.
  On a steep loss, fully lifting the highs to threshold over-amplifies sibilants; a real fit would use
  partial gain, frequency lowering, and output limiting. UCL is estimated from the audiogram.</p>
</div></footer>

<button id="th" aria-label="Toggle light or dark theme" title="Toggle theme">◐</button>

<script>
(function(){{
  var fmt=function(t){{t=Math.max(0,t|0);return (t/60|0)+":"+("0"+(t%60)).slice(-2);}};
  document.querySelectorAll('[data-player]').forEach(function(root){{
    var pool=root.querySelectorAll('.audio-pool audio'), chips=root.querySelectorAll('.chip');
    var play=root.querySelector('.play'), seek=root.querySelector('.seek'), fill=root.querySelector('.fill'),
        tcur=root.querySelector('.time b'), ttot=root.querySelector('.time span'),
        cur=root.querySelector('.cur'), dot=root.querySelector('.cue .dot');
    var active=0,on=false,dur=20;
    var css=getComputedStyle(document.documentElement);
    function chipColor(i){{var c=chips[i].className.match(/c-(\\w+)/);var map={{orig:'--amber',static:'--c-static',
      fast:'--c-fast',med:'--c-med',slow:'--c-slow',left:'--blue',right:'--red',bin:'--teal'}};
      return css.getPropertyValue(map[c?c[1]:'orig']||'--amber');}}
    pool[0].addEventListener('loadedmetadata',function(){{dur=pool[0].duration||20;ttot.textContent=fmt(dur);}});
    function tick(){{var a=pool[active],p=dur?Math.min(1,a.currentTime/dur):0;fill.style.width=(p*100)+'%';
      seek.value=Math.round(p*1000);tcur.textContent=fmt(Math.min(a.currentTime,dur));if(on)requestAnimationFrame(tick);}}
    function setOn(v){{on=v;play.classList.toggle('on',v);play.setAttribute('aria-label',v?'Pause':'Play');if(v)requestAnimationFrame(tick);}}
    play.addEventListener('click',function(){{if(on){{pool[active].pause();setOn(false);}}else{{pool[active].play();setOn(true);}}}});
    pool.forEach(function(a){{a.addEventListener('ended',function(){{setOn(false);pool.forEach(function(x){{x.currentTime=0;}});
      fill.style.width='0%';seek.value=0;tcur.textContent='0:00';}});}});
    function to(i){{if(i===active)return;var f=pool[active],t=pool[i];f.pause();t.currentTime=f.currentTime;active=i;
      chips.forEach(function(c){{c.setAttribute('aria-pressed',c.dataset.i==i);}});
      cur.textContent=chips[i].textContent.replace(/\\s+/g,' ').trim().split(' ').slice(0,2).join(' ');
      dot.style.background=chipColor(i);if(on)t.play();}}
    chips.forEach(function(c){{c.addEventListener('click',function(){{to(+c.dataset.i);}});}});
    seek.addEventListener('input',function(){{var t=(seek.value/1000)*dur;pool.forEach(function(a){{a.currentTime=t;}});
      fill.style.width=(seek.value/10)+'%';tcur.textContent=fmt(t);}});
  }});
  var links={{}};document.querySelectorAll('.rail a').forEach(function(a){{links[a.dataset.spy]=a;}});
  if('IntersectionObserver' in window){{
    var io=new IntersectionObserver(function(es){{es.forEach(function(e){{if(e.isIntersecting){{
      Object.keys(links).forEach(function(k){{links[k].classList.remove('active');}});
      if(links[e.target.id])links[e.target.id].classList.add('active');}}}});}},{{rootMargin:'-45% 0px -50% 0px'}});
    document.querySelectorAll('.specimen, .tool').forEach(function(s){{io.observe(s);}});
  }}
  var root=document.documentElement;
  document.getElementById('th').addEventListener('click',function(){{
    root.setAttribute('data-theme',root.getAttribute('data-theme')==='dark'?'light':'dark');}});
}})();
</script>
<script>{DSP_JS}</script>
<script>{TOOL_JS}</script>
"""

open(os.path.join(HERE, "index.html"), "w").write(DOC)
print("wrote index.html  %.2f MB  (%d subjects, %d shapes)"
      % (len(DOC.encode()) / 1e6, len(S["subjects"]), len(A["audiograms"])))
