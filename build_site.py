"""Build the self-contained demo website (index.html) from assets.json + subjects.json.

    (in scratchpad) python make_assets.py ; python make_subjects.py
    cp <scratchpad>/assets.json <scratchpad>/subjects.json .
    python build_site.py            # -> index.html   (single file; GitHub Pages / Artifact ready)

Charts are embedded (base64); audio is written to web/audio/*.m4a and lazy-loaded per section
(IntersectionObserver) so the page ships tiny and fetches clips on demand.
"""
import os, json, html, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
# keep copies of the real modules next to the site so the in-browser tool (Pyodide) can fetch them
shutil.copy(os.path.join(HERE, "..", "colab", "speech_resynth.py"), os.path.join(HERE, "speech_resynth.py"))
shutil.copy(os.path.join(HERE, "..", "openmha", "fitting.py"), os.path.join(HERE, "fitting.py"))
A = json.load(open(os.path.join(HERE, "assets.json")))
S = json.load(open(os.path.join(HERE, "subjects.json")))
O = json.load(open(os.path.join(HERE, "openmha_section.json")))
SO = json.load(open(os.path.join(HERE, "subjects_openmha.json")))

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


def metric_rows(items, sii_label="ANSI SII (0–1)"):     # items: [(name, {sii, stoi, err}), ...]
    def row(lab, key, fmt):
        cells = "  &middot;  ".join(
            (f"{html.escape(n)} {fmt(m[key])}" if m.get(key) is not None else f"{html.escape(n)} –")
            for n, m in items)
        return f"<div><b>{lab}:</b> {cells}</div>"
    return ('<div class="siirow">'
            + row(sii_label, "sii", lambda v: f"{v:.2f}")
            + row("STOI (0–1)", "stoi", lambda v: f"{v:.2f}")
            + row("dB RMS to NAL-NL2 ref", "err", lambda v: f"{v:.0f}")
            + '<div class="metleg">SII &amp; STOI: higher = better &middot; dB&#8209;to&#8209;ref measures each fit\'s shaping '
              'against one common yardstick (the NAL&#8209;NL2 prescription), so NAL&#8209;NL2 sits near 0 by design '
              'and the others show how far they differ (not worse).</div>'
            + '</div>')


def shape_section(n, s):
    sid = s["id"]
    audios = [f'<audio data-i="0" preload="none" src="{A["original_file"]}"></audio>']
    chips = ['<button class="chip c-orig" data-i="0" aria-pressed="true">Original<em>unaided</em></button>']
    for i, c in enumerate(s["conditions"], start=1):
        audios.append(f'<audio data-i="{i}" preload="none" src="{c["file"]}"></audio>')
        lab, sub, cls = COND[c["id"]]
        unit = '<span class="u">ms</span>' if c["id"].startswith("wdrc_") else ""
        chips.append(f'<button class="chip c-{cls}" data-i="{i}" aria-pressed="false">{lab}{unit}<em>{sub}</em></button>')
    hint = "&mdash; switch while it plays; position holds, so you A/B the same instant"
    srow = metric_rows([("Original", s["orig"])] + [(COND[c["id"]][0], c) for c in s["conditions"]])
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
        {transport('Original').format(hint=hint)}
        {srow}</div>
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
        audios.append(f'<audio data-i="{i}" preload="none" src="{c["file"]}"></audio>')
        pressed = "true" if i == 0 else "false"
        chips.append(f'<button class="chip c-{c["cls"]}" data-i="{i}" aria-pressed="{pressed}">'
                     f'{html.escape(c["label"])}<em>{html.escape(c["sub"])}</em></button>')
    hint = "&mdash; headphones: the two ears differ"
    if s.get("io"):                                       # audiogram + input/output, like the shapes
        charts = (f'<div class="charts">'
                  f'<figure class="paper"><img alt="Audiogram, {html.escape(s["name"])}" '
                  f'src="data:image/png;base64,{s["png"]}"><figcaption>Audiogram (both ears)</figcaption></figure>'
                  f'<figure class="paper"><img alt="Input/output, {html.escape(s["name"])}" '
                  f'src="data:image/png;base64,{s["io"]}"><figcaption>Input&nbsp;&rarr;&nbsp;output (compression)</figcaption></figure>'
                  f'</div>')
    else:                                                 # single wide figure (e.g. the ILD bar chart)
        charts = (f'<figure class="paper wide"><img alt="{html.escape(s["name"])}" '
                  f'src="data:image/png;base64,{s["png"]}"><figcaption>{s.get("figcap","")}</figcaption></figure>')
    srow = ""
    if s["conditions"] and "sii" in s["conditions"][0]:   # binaural subjects carry poorer-ear metrics
        srow = metric_rows([(c["label"], c) for c in s["conditions"]], "ANSI SII, poorer ear (0–1)")
    return f"""
    <section class="specimen subject" id="st-{s['id']}" data-player>
      <div class="sp-head"><span class="sp-num sub">&#9670;</span>
        <div class="sp-title"><h2>{html.escape(s['name'])} <span class="kind">{html.escape(s['kind'])}</span>{badge}</h2>
        <p class="sp-blurb">{html.escape(blurb)} {ild_txt}</p></div></div>
      {charts}
      <div class="console"><div class="chips">{chips[0]}<span class="sep"></span>
        <span class="ramp">{''.join(chips[1:])}</span></div>
        {transport('Original').format(hint=hint)}
        {srow}</div>
      <div class="audio-pool" hidden>{''.join(audios)}</div>
    </section>"""


def openmha_section(a):                                  # ours (Rx) vs OpenMHA rules on one loss
    audios, chips = [], []
    for i, c in enumerate(a["conditions"]):
        audios.append(f'<audio data-i="{i}" preload="none" src="{c["file"]}"></audio>')
        pressed = "true" if i == 0 else "false"
        chips.append(f'<button class="chip c-{c["cls"]}" data-i="{i}" aria-pressed="{pressed}">'
                     f'{html.escape(c["label"])}<em>{html.escape(c["sub"])}</em></button>')
    hint = "&mdash; loudness-matched; compare our fit to the clinical prescriptions"
    srow = metric_rows([(c["label"], c) for c in a["conditions"]])
    return f"""
    <section class="specimen" id="st-omha-{a['id']}" data-player>
      <div class="sp-head"><span class="sp-num sub">&#9670;</span>
        <div class="sp-title"><h2>{html.escape(a['name'])} <span class="kind">ours vs OpenMHA</span></h2>
        <p class="sp-blurb">Our Rx fit against real <b>OpenMHA</b> running NAL-NL2, DSL m[i/o] and CAMFIT,
        on the same clip at 65&nbsp;dB SPL.</p></div></div>
      <figure class="paper omfig"><img alt="Audiogram, {html.escape(a['name'])}"
        src="data:image/png;base64,{a['png']}"><figcaption>Audiogram</figcaption></figure>
      <div class="console"><div class="chips">{chips[0]}<span class="sep"></span>
        <span class="ramp">{''.join(chips[1:])}</span></div>
        {transport('Original').format(hint=hint)}
        {srow}</div>
      <div class="audio-pool" hidden>{''.join(audios)}</div>
    </section>"""


def subj_omha_section(a):                               # binaural subject: ours vs OpenMHA, per ear
    audios, chips = [], []
    for i, c in enumerate(a["conditions"]):
        audios.append(f'<audio data-i="{i}" preload="none" src="{c["file"]}"></audio>')
        pressed = "true" if i == 0 else "false"
        chips.append(f'<button class="chip c-{c["cls"]}" data-i="{i}" aria-pressed="{pressed}">'
                     f'{html.escape(c["label"])}<em>{html.escape(c["sub"])}</em></button>')
    ph = ' <span class="badge">placeholder music</span>' if a.get("placeholder") else ""
    hint = "&mdash; headphones: each ear is fit on its own audiogram; loudness-matched"
    srow = metric_rows([(c["label"], c) for c in a["conditions"]], "ANSI SII, poorer ear (0–1)")
    return f"""
    <section class="specimen subject" id="st-somha-{a['id']}" data-player>
      <div class="sp-head"><span class="sp-num sub">&#9670;</span>
        <div class="sp-title"><h2>{html.escape(a['name'])} <span class="kind">binaural &mdash; ours vs OpenMHA</span>{ph}</h2>
        <p class="sp-blurb">Each ear fit on its own audiogram: our Rx against real <b>OpenMHA</b>
        (NAL-NL2, DSL m[i/o], CAMFIT/CAM2), played in stereo at 65&nbsp;dB SPL.</p></div></div>
      <figure class="paper omfig"><img alt="Audiogram, {html.escape(a['name'])}"
        src="data:image/png;base64,{a['png']}"><figcaption>Audiogram (both ears)</figcaption></figure>
      <div class="console"><div class="chips">{chips[0]}<span class="sep"></span>
        <span class="ramp">{''.join(chips[1:])}</span></div>
        {transport('Original').format(hint=hint)}
        {srow}</div>
      <div class="audio-pool" hidden>{''.join(audios)}</div>
    </section>"""


SUBJ_OMHA = "\n".join(subj_omha_section(x) for x in SO["subjects"])
SUBJECTS = "\n".join(subject_section(s) for s in S["subjects"] if s["id"] != "ild")
ILD = "\n".join(subject_section(s) for s in S["subjects"] if s["id"] == "ild")
SHAPES = "\n".join(shape_section(i + 1, s) for i, s in enumerate(A["audiograms"]))
OMHA = "\n".join(openmha_section(x) for x in O["audiograms"])
RAIL_OMHA = "\n".join(f'<a href="#st-omha-{x["id"]}" data-spy="st-omha-{x["id"]}"><span>&#9670;</span>{html.escape(x["name"])}</a>'
                      for x in O["audiograms"])
RAIL_SUBJ_OMHA = "\n".join(f'<a href="#st-somha-{x["id"]}" data-spy="st-somha-{x["id"]}"><span>&#9670;</span>{html.escape(x["name"])} &middot; binaural</a>'
                           for x in SO["subjects"])
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
.rowctl{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--muted);margin:6px 0 12px;font-family:var(--mono)}
.rowctl label{min-width:112px}
.rowctl input[type=range]{flex:1;accent-color:var(--teal)}
.rowctl select{font-family:var(--mono);font-size:12px;background:var(--surface);color:var(--ink);
  border:1px solid var(--line);border-radius:6px;padding:3px 6px}
.chk{display:flex;align-items:flex-start;gap:8px;font-size:12.5px;color:var(--ink-2);margin:4px 0 16px;cursor:pointer;line-height:1.4}
.chk input{margin-top:2px;accent-color:var(--teal)} .chknote{color:var(--muted);font-size:11.5px}
.siirow{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin-top:12px;padding-top:10px;
  border-top:1px dashed var(--line);line-height:1.7} .siirow b{color:var(--ink)}
.metleg{font-size:10.5px;color:var(--muted);opacity:.85;margin-top:7px;line-height:1.5;border-top:none;padding-top:0}
.verdict{font-family:var(--mono);font-size:12px;color:var(--ink);background:color-mix(in srgb,var(--teal) 8%,transparent);
  border:1px solid var(--line);border-left:3px solid var(--teal);border-radius:8px;padding:8px 11px;margin-top:12px;line-height:1.5}
.verdict b{color:var(--teal)}
.tprog{display:flex;align-items:center;gap:9px;margin-top:9px}
.tprog-bar{flex:1;height:7px;border-radius:6px;background:var(--line);overflow:hidden}
.tprog-bar>i{display:block;height:100%;width:0;background:var(--teal);transition:width .18s ease}
.tprog-txt{font-family:var(--mono);font-size:10.5px;color:var(--muted);white-space:nowrap}
.runbtn{font-family:var(--mono);font-weight:600;font-size:14px;color:#fff;background:var(--teal);border:none;
  border-radius:10px;padding:10px 22px;cursor:pointer;transition:transform .06s}
.runbtn:hover{transform:translateY(-1px)} .runbtn:disabled{opacity:.45;cursor:default;transform:none}
.status{font-family:var(--mono);font-size:11px;color:var(--muted);margin-left:12px}
#tchips .chip:disabled{opacity:.45;cursor:default}
.dlrow{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-top:16px;font-family:var(--mono);font-size:11px;color:var(--muted)}
.dl{color:var(--teal);text-decoration:none;border-bottom:1px solid color-mix(in srgb,var(--teal) 40%,transparent);cursor:pointer}
.engine{font-family:var(--mono);font-size:10.5px;color:var(--muted);margin-top:12px;padding-top:9px;border-top:1px dashed var(--line)}
.ctlnote{font-size:11px;color:var(--muted);margin:0 0 12px;line-height:1.45}
.quickstart{font-size:12.5px;color:var(--ink-2);background:color-mix(in srgb,var(--teal) 7%,transparent);
  border:1px solid var(--line);border-radius:10px;padding:11px 14px;margin:0 0 18px;line-height:1.5}
.quickstart b{color:var(--ink)}
.advanced{margin:8px 0 14px;border:1px solid var(--line);border-radius:10px;padding:0 12px;background:color-mix(in srgb,var(--teal) 3%,transparent)}
.advanced>summary{cursor:pointer;font-size:11.5px;color:var(--ink-2);font-family:var(--mono);padding:11px 0;list-style:none;line-height:1.4}
.advanced>summary::-webkit-details-marker{display:none}
.advanced>summary:before{content:"\25B8  ";color:var(--teal)} .advanced[open]>summary:before{content:"\25BE  "}
.advanced[open]{padding-bottom:8px}
.advgrp{font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--teal);margin:14px 0 6px}
.advgrp:first-of-type{margin-top:4px}
.earmode{display:flex;align-items:center;gap:8px;margin:10px 0 6px;flex-wrap:wrap}
.earmode-lbl{font-family:var(--mono);font-size:11px;color:var(--muted)}
.segbtn{font-family:var(--mono);font-size:11px;padding:5px 11px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink-2);cursor:pointer}
.segbtn:hover{border-color:var(--teal-3)}
.segbtn.on{background:var(--teal);border-color:var(--teal);color:#fff}
.ears{display:flex;flex-wrap:wrap;gap:16px}
.agcol{display:flex;flex-direction:column}
.earlbl{font-family:var(--mono);font-size:10px;letter-spacing:.13em;text-transform:uppercase;color:var(--teal);margin-bottom:4px}
.earlbl.earR{color:var(--blue)}
.minirow{display:flex;gap:6px;margin-top:6px}
.minibtn{font-family:var(--mono);font-size:10.5px;padding:4px 9px;border:1px solid var(--line);border-radius:7px;background:var(--panel);color:var(--ink-2);cursor:pointer}
.minibtn:hover{border-color:var(--teal);color:var(--teal)}
.spec{display:block;width:100%;height:auto;margin-top:12px;background:var(--paper);border:1px solid var(--line);border-radius:8px}
.blindstart{font-family:var(--mono);font-size:12px;font-weight:600;color:var(--ink);background:transparent;border:1.5px solid var(--line);border-radius:9px;padding:8px 14px;cursor:pointer;margin-top:14px}
.blindstart:hover:not(:disabled){border-color:var(--teal);color:var(--teal)} .blindstart:disabled{opacity:.45;cursor:default}
.blind{margin-top:14px;padding:14px;border:1px solid var(--line);border-radius:12px;background:var(--panel)}
.blindhdr{font-size:12.5px;color:var(--ink-2);margin-bottom:12px} .blindhdr b{color:var(--ink)}
.blindctl{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.bbtn{font-family:var(--mono);font-size:13px;font-weight:600;color:var(--ink);background:var(--surface);border:1.5px solid var(--line);border-radius:9px;padding:7px 13px;cursor:pointer}
.bbtn:hover{border-color:var(--teal)} .bbtn.pref{color:#fff;background:var(--teal);border-color:transparent}
.bbtn.done{margin-top:12px;background:transparent;color:var(--muted);font-size:11px}
.bsep{width:1px;align-self:stretch;background:var(--line);margin:2px 4px}
.breveal{font-size:12.5px;color:var(--teal);min-height:18px;margin-top:10px}
.bcomment{display:flex;flex-direction:column;gap:9px;margin:10px 0}
.bnote{display:flex;flex-direction:column;gap:4px}
.bnl{font-family:var(--mono);font-size:11px;color:var(--ink-2)} .bnl b{color:var(--teal)}
.bcomment textarea{font-family:var(--sans);font-size:12.5px;color:var(--ink);background:var(--surface);
  border:1.5px solid var(--line);border-radius:9px;padding:7px 9px;resize:vertical;min-height:38px;width:100%}
.bcomment textarea:focus{outline:none;border-color:var(--teal)}
.bcomment #bnext{align-self:flex-start}
@media (max-width:560px){.tool-grid{grid-template-columns:1fr}.agwrap{flex-direction:column}}
"""

TOOL_HTML = f"""
    <p class="band-label">Interactive &mdash; run the pipeline on your own audio</p>
    <section class="tool" id="tool">
      <div class="sp-head"><span class="sp-num sub">&#9881;</span>
        <div class="sp-title"><h2>Try your own <span class="kind">upload · in-browser · exact</span></h2>
        <p class="sp-blurb">Upload a WAV or MP3, set an audiogram, and hear it re-synthesised &mdash; Original
        vs Static vs WDRC vs a realistic <b>Rx</b> fit vs <b>NAL-NL2</b> / <b>DSL</b> / <b>CAM2</b> (the exact
        Cambridge/CAMFIT rule, bit-identical to OpenMHA), at 32&nbsp;kHz with the bank running to 12&nbsp;kHz.
        Tick <b>Two ears</b> to fit each ear on its own audiogram in stereo. It runs the <b>real Python
        module</b> in your browser via Pyodide (numpy/scipy in WebAssembly), so the output is notebook-identical;
        the first run downloads ~30&nbsp;MB and falls back to a JS approximation if that can't load. Nothing is
        uploaded &mdash; it all runs on your machine.</p></div></div>
      <p class="quickstart"><b>Quick start:</b> pick an audiogram preset (or drag the sliders) &rarr;
        <b>Choose audio</b> &rarr; <b>Process</b>, then click the tabs to A/B. Set your volume so <b>Original</b>
        is comfortable &mdash; it's presented at ~65&nbsp;dB&nbsp;SPL (normal conversation), and the fits lift it
        from there. SII numbers are the <b>official ANSI S3.5</b> index.</p>
      <div class="tool-grid">
        <div class="panel">
          <label class="filebtn">Choose audio<input type="file" id="tf" accept="audio/*"></label>
          <span id="fname" class="fname">no file chosen yet</span>
          <div class="presets">audiogram preset:
            <button data-preset="normal">normal</button><button data-preset="sloping">sloping</button>
            <button data-preset="flat">flat 40</button><button data-preset="ski">ski-slope</button>
            <button data-preset="cookie">cookie-bite</button><button data-preset="reverse">reverse</button>
            <button data-preset="notch">noise-notch</button></div>
          <div class="earmode"><span class="earmode-lbl">ears:</span>
            <button type="button" id="earOne" class="segbtn on">one &mdash; same both sides</button>
            <button type="button" id="earTwo" class="segbtn">two &mdash; left / right</button></div>
          <div class="ears">
            <div class="agwrap" id="agwrapL">
              <div class="agcol"><span class="earlbl" id="earlblL">audiogram</span>
                <canvas id="agc" width="290" height="170"></canvas></div>
              <div class="sliders" id="sliders"></div></div>
            <div class="agwrap ear2" id="agwrap2" hidden>
              <div class="agcol"><span class="earlbl earR">right ear</span>
                <canvas id="agc2" width="290" height="170"></canvas>
                <div class="minirow"><button id="copyLR" type="button" class="minibtn">copy L &rarr; R</button>
                  <button id="copyRL" type="button" class="minibtn">copy R &rarr; L</button></div></div>
              <div class="sliders" id="sliders2"></div></div>
          </div>
          <div class="rowctl"><label for="level">Input level</label>
            <select id="level"><option value="50">soft &middot; 50</option><option value="65" selected>normal &middot; 65</option>
            <option value="80">loud &middot; 80</option></select><span>dB SPL</span></div>
          <details class="advanced">
            <summary>More options &mdash; program, noise &amp; reverb, bone/OHC, frequency lowering, "hear as the patient"</summary>
            <p class="advgrp">Fitting</p>
            <div class="rowctl"><label for="prog">Program</label>
              <select id="prog"><option value="speech" selected>speech</option>
              <option value="music">music (slow release)</option></select><span>music = wide dynamics</span></div>
            <div class="rowctl"><label for="rel">WDRC release</label>
              <input type="range" id="rel" min="20" max="600" step="10" value="150"><span id="relv">150 ms</span></div>
            <div class="rowctl"><label for="flow">Frequency lowering</label>
              <select id="flow"><option value="1" selected>off</option><option value="1.5">1.5&times;</option>
              <option value="2">2&times;</option></select><span>for dead highs</span></div>
            <div class="rowctl"><label for="gap">Air&ndash;bone gap</label>
              <input type="range" id="gap" min="0" max="40" step="5" value="0"><span id="gapv">0 dB</span></div>
            <div class="rowctl"><label for="ohc">OHC health</label>
              <input type="range" id="ohc" min="0" max="100" step="10" value="0"><span id="ohcv">0%</span></div>
            <p class="ctlnote">Air&ndash;bone gap (conductive) and healthy outer hair cells both mean less
              recruitment &rarr; the <b>Personalized</b> fit compresses less (more linear).</p>
            <p class="advgrp">Listening signal</p>
            <div class="rowctl"><label for="noise">Add noise</label>
              <select id="noise"><option value="-1" selected>off</option><option value="10">+10 dB SNR</option>
              <option value="5">+5 dB SNR</option><option value="0">0 dB SNR</option></select>
              <select id="ntype"><option value="ssn" selected>speech-shaped</option><option value="babble">babble</option></select></div>
            <div class="rowctl"><label for="rev">Reverberation</label>
              <select id="rev"><option value="0" selected>off</option><option value="0.3">small room</option>
              <option value="0.6">hall</option></select></div>
            <label class="chk"><input type="checkbox" id="nr"> Noise reduction (aid-side denoiser)
              <span class="chknote">&mdash; suppresses steady noise between words</span></label>
            <p class="advgrp">Play it as</p>
            <div class="rowctl"><label for="levels">Levels</label>
              <select id="levels"><option value="matched" selected>matched (fair A/B)</option>
              <option value="real">real (aid is louder)</option></select></div>
            <label class="chk"><input type="checkbox" id="losssim"> Hear it as the patient does
              <span class="chknote">&mdash; through a simulation of the loss, so aided vs unaided shows the benefit</span></label>
          </details>
          <button id="run" class="runbtn" disabled>Process</button>
          <div id="tprog" class="tprog" hidden><div class="tprog-bar"><i id="tprogfill"></i></div><span id="tprogtxt" class="tprog-txt"></span></div>
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
              <button class="chip c-rx" data-i="3" aria-pressed="false" disabled>Rx<em>realistic fit</em></button>
              <button class="chip c-nal" data-i="4" aria-pressed="false" disabled>NAL-NL2<em>OpenMHA-style</em></button>
              <button class="chip c-dsl" data-i="5" aria-pressed="false" disabled>DSL<em>OpenMHA-style</em></button>
              <button class="chip c-cam" data-i="6" aria-pressed="false" disabled>CAM2<em>exact CAMFIT</em></button>
              <button class="chip c-per" data-i="7" aria-pressed="false" disabled>Pers<em>bone/OHC-aware</em></button>
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
          <div id="tverdict" class="verdict" style="display:none"></div>
          <div id="siirow" class="siirow" style="display:none"></div>
          <canvas id="spec" width="460" height="150" class="spec" title="Long-term spectrum: dashed = original, solid = selected"></canvas>
          <div class="dlrow" id="dlrow" style="display:none">download:
            <a id="dl_original" class="dl">original.wav</a><a id="dl_static" class="dl">static.wav</a>
            <a id="dl_wdrc" class="dl">wdrc.wav</a><a id="dl_rx" class="dl">rx.wav</a>
            <a id="dl_nal" class="dl">nal.wav</a><a id="dl_dsl" class="dl">dsl.wav</a>
            <a id="dl_cam" class="dl">cam2.wav</a><a id="dl_per" class="dl">personalized.wav</a></div>
          <button id="blindbtn" class="blindstart" disabled>Blind A/B preference test</button>
          <div class="blind" id="blindpanel" style="display:none">
            <div class="blindhdr">Blind A/B &mdash; two unlabeled fits, pick the one you prefer &middot; trial <b id="btrial">1</b> <span id="btally"></span></div>
            <div class="blindctl">
              <button id="bA" class="bbtn">&#9654;&nbsp;A</button><button id="bB" class="bbtn">&#9654;&nbsp;B</button>
              <span class="bsep"></span>
              <button id="bprefA" class="bbtn pref">prefer&nbsp;A</button><button id="bprefB" class="bbtn pref">prefer&nbsp;B</button>
              <button id="bskip" class="bbtn">skip</button></div>
            <div id="breveal" class="breveal"></div>
            <div id="bcomment" class="bcomment" style="display:none">
              <label class="bnote"><span class="bnl" id="bnlA">Notes on A</span>
                <textarea id="bcommentA" rows="2" placeholder="what stood out on A &mdash; good or bad?"></textarea></label>
              <label class="bnote"><span class="bnl" id="bnlB">Notes on B</span>
                <textarea id="bcommentB" rows="2" placeholder="what stood out on B, and what decided it?"></textarea></label>
              <button id="bnext" class="bbtn pref">save &amp; next trial &rarr;</button>
            </div>
            <button id="bdone" class="bbtn done">done &mdash; download CSV</button>
          </div>
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
  --red:#C0392B; --blue:#2C6FB0; --rx:#3F7D54; --nal:#6A5ACD; --dsl:#B5651D; --cam:#3F6E8C;
  --c-static:#5F817F; --c-fast:#8FBDBB; --c-med:#22706F; --c-slow:#0E3B3B;
  --mono:ui-monospace,"SF Mono","Roboto Mono",Menlo,Consolas,monospace;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --sh:0 1px 1px rgba(16,27,26,.04),0 10px 26px -16px rgba(16,27,26,.26);
}}
@media (prefers-color-scheme:dark){{ :root{{
  --bg:#0B1413; --paper:#FCFDFC; --panel:#111E1C; --ink:#E6EEEC; --ink-2:#B3C4C1;
  --muted:#7E938F; --line:#213230; --teal:#4FA3A2; --teal-2:#78C4C3; --teal-3:#2E524F;
  --amber:#C89A54; --red:#E0685A; --blue:#5E9BD6; --rx:#5FA877; --nal:#9A8CE0; --dsl:#D08A4A; --cam:#6F9BB8;
  --c-static:#89A6A3; --c-fast:#2E524F; --c-med:#4FA3A2; --c-slow:#78C4C3;
  --sh:0 1px 1px rgba(0,0,0,.4),0 12px 30px -16px rgba(0,0,0,.7);
}} }}
:root[data-theme="light"]{{ --bg:#ECF1F0;--paper:#FCFDFC;--panel:#FBFDFC;--ink:#101B1A;--ink-2:#3B4B49;
  --muted:#69807C;--line:#D5E0DD;--teal:#22706F;--teal-2:#0E3B3B;--teal-3:#8FBDBB;--amber:#9C6A1E;
  --red:#C0392B;--blue:#2C6FB0;--rx:#3F7D54;--nal:#6A5ACD;--dsl:#B5651D;--cam:#3F6E8C;--c-static:#5F817F;--c-fast:#8FBDBB;--c-med:#22706F;--c-slow:#0E3B3B; }}
:root[data-theme="dark"]{{ --bg:#0B1413;--paper:#FCFDFC;--panel:#111E1C;--ink:#E6EEEC;--ink-2:#B3C4C1;
  --muted:#7E938F;--line:#213230;--teal:#4FA3A2;--teal-2:#78C4C3;--teal-3:#2E524F;--amber:#C89A54;
  --red:#E0685A;--blue:#5E9BD6;--rx:#5FA877;--nal:#9A8CE0;--dsl:#D08A4A;--cam:#6F9BB8;--c-static:#89A6A3;--c-fast:#2E524F;--c-med:#4FA3A2;--c-slow:#78C4C3; }}

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
.c-nal[aria-pressed="true"]{{background:var(--nal)}} .c-dsl[aria-pressed="true"]{{background:var(--dsl)}} .c-cam[aria-pressed="true"]{{background:var(--cam)}}
.c-per[aria-pressed="true"]{{background:var(--cam)}}
.omfig{{max-width:400px;margin:22px 0}}

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
    <h3 class="mt">Ours vs OpenMHA</h3>
    <nav>{RAIL_OMHA}</nav>
    <nav>{RAIL_SUBJ_OMHA}</nav>
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
    <p class="band-label">Ours vs OpenMHA &mdash; real clinical prescriptions</p>
{OMHA}
    <p class="band-label">Subjects vs OpenMHA &mdash; binaural, each ear fit on its own audiogram</p>
{SUBJ_OMHA}
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
  <p><b>Ours vs OpenMHA:</b> the gallery section runs <b>real OpenMHA</b> (its dc_simple compressor).
  <b>CAMFIT</b> is OpenMHA's own authoritative rule (computed by its <span style="font-family:var(--mono)">gainrule_camfit_compr</span>);
  <b>NAL-NL2</b> and <b>DSL</b> use published approximations, since the exact vendor rules aren't public.
  The "Try your own" tool reproduces NAL-NL2 / DSL in Python (approximations, our compressor) and adds
  <b>CAM2</b> &mdash; a faithful port of OpenMHA's own <span style="font-family:var(--mono)">gainrule_camfit_compr</span>
  that matches the Octave CAMFIT gains to <b>0.00&nbsp;dB</b>, so any uploaded audiogram gets the exact
  Cambridge rule with no Docker. Tick <b>Two ears</b> to fit each ear on its own audiogram and hear the
  result in stereo.</p>
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
  // lazy-load: fetch a section's audio only as it nears the viewport (page ships no inlined audio)
  if('IntersectionObserver' in window){{
    var lazyIO=new IntersectionObserver(function(es){{es.forEach(function(e){{
      if(e.isIntersecting){{e.target.querySelectorAll('.audio-pool audio').forEach(function(a){{a.preload='auto';a.load();}});lazyIO.unobserve(e.target);}}}});}},{{rootMargin:'500px 0px'}});
    document.querySelectorAll('[data-player]').forEach(function(s){{if(s.querySelector('.audio-pool'))lazyIO.observe(s);}});
  }}
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
