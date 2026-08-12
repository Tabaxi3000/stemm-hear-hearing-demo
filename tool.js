/* "Try your own": upload audio + set an audiogram -> Original / Static / WDRC, in-browser.
   Primary engine: the REAL colab/speech_resynth.py run under Pyodide (numpy/scipy in WASM), so
   output is notebook-identical. Falls back to the JS port (dsp.js) if Pyodide can't load.
   Everything is client-side; nothing is uploaded. Processing at 32 kHz, bank to 12 kHz. */
(function () {
  "use strict";
  var FREQS = [250, 500, 1000, 2000, 4000, 8000];
  var ag = [20, 25, 30, 40, 55, 65];
  var SR = 32000, CAP = 10;                            // process up to 10 s (each fit is a full DSP pass)
  var input = null, fileName = "", urls = {}, clips = {};
  var KEYS = ["original", "static", "wdrc", "rx", "nal", "dsl", "per"], specCache = {};
  var pyodide = null, pyReady = false, pyBooting = false, pyFailed = false;
  var $ = function (id) { return document.getElementById(id); };
  function status(t) { var e = $("tstatus"); if (e) e.textContent = t; }
  function engine(t) { var e = $("engine"); if (e) e.textContent = t; }

  function rms(a) { var s = 0; for (var i = 0; i < a.length; i++) s += a[i] * a[i]; return Math.sqrt(s / a.length) + 1e-12; }
  function softknee(a, thr) {
    thr = thr || 0.92; var o = new Float32Array(a.length);
    for (var i = 0; i < a.length; i++) { var v = a[i], m = Math.abs(v);
      o[i] = m > thr ? Math.sign(v) * (thr + (1 - thr) * Math.tanh((m - thr) / (1 - thr))) : v; }
    return o;
  }
  function normalize(a, targetDb) {
    var g = Math.pow(10, targetDb / 20) / rms(a), o = new Float32Array(a.length);
    for (var i = 0; i < a.length; i++) o[i] = a[i] * g;
    return softknee(o);
  }
  function showSII(si) {                               // audibility (SII proxy) per condition
    var el = $("siirow"); if (!el) return;
    if (!si) { el.style.display = "none"; return; }
    var L = ["Original","Static","WDRC","Rx","NAL","DSL","Pers"];
    el.innerHTML = '<b>Audibility (SII proxy, 0–1):</b> ' +
      L.map(function (n, i) { return n + " " + (si[i] != null ? si[i].toFixed(2) : "–"); }).join("  ·  ");
    el.style.display = "";
  }
  function ltas(a) {                                   // Welch long-term magnitude spectrum (dB) via DSP.fft
    if (typeof DSP === "undefined" || !a || a.length < 4096) return null;
    var W = 4096, Hh = 2048, re = new Float64Array(W), im = new Float64Array(W), acc = new Float64Array(W / 2 + 1), nf = 0, i, k, s;
    for (s = 0; s + W <= a.length; s += Hh) {
      for (i = 0; i < W; i++) { re[i] = a[s + i] * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / W)); im[i] = 0; }
      DSP.fft(re, im, false);
      for (k = 0; k <= W / 2; k++) acc[k] += re[k] * re[k] + im[k] * im[k];
      nf++;
    }
    var out = new Float64Array(W / 2 + 1); for (k = 0; k <= W / 2; k++) out[k] = 10 * Math.log10(acc[k] / (nf || 1) + 1e-12);
    return out;
  }
  function drawSpec() {                                 // dashed = original, solid = selected condition
    var c = $("spec"); if (!c) return; var g = c.getContext("2d"), W = c.width, H = c.height;
    g.clearRect(0, 0, W, H);
    var cs = getComputedStyle(document.documentElement);
    var mut = (cs.getPropertyValue("--muted") || "#889").trim(), teal = (cs.getPropertyValue("--teal") || "#227").trim(),
        line = (cs.getPropertyValue("--line") || "#ddd").trim();
    var fmin = 100, fmax = SR / 2, NB = 4096, pad = 26;
    var xf = function (f) { return pad + (Math.log10(f) - Math.log10(fmin)) / (Math.log10(fmax) - Math.log10(fmin)) * (W - pad - 6); };
    g.fillStyle = mut; g.font = "9px ui-monospace,monospace"; g.textAlign = "center";
    [100, 1000, 10000].forEach(function (f) { if (f <= fmax) { var xx = xf(f); g.strokeStyle = line; g.globalAlpha = .4; g.beginPath(); g.moveTo(xx, 4); g.lineTo(xx, H - 12); g.stroke(); g.globalAlpha = 1; g.fillText(f >= 1000 ? f / 1000 + "k" : f, xx, H - 2); } });
    function plot(spec, color, dashed) {
      if (!spec) return; g.strokeStyle = color; g.lineWidth = dashed ? 1 : 1.8; g.setLineDash(dashed ? [3, 3] : []); g.beginPath(); var first = true;
      for (var k = 1; k <= NB / 2; k++) { var f = k * SR / NB; if (f < fmin || f > fmax) continue;
        var y = H - 14 - ((spec[k] + 100) / 75) * (H - 22); y = Math.max(3, Math.min(H - 13, y)); var xx = xf(f);
        if (first) { g.moveTo(xx, y); first = false; } else g.lineTo(xx, y); }
      g.stroke(); g.setLineDash([]);
    }
    if (clips.original) plot(specCache.original || (specCache.original = ltas(clips.original)), mut, true);
    var ak = KEYS[active]; if (clips[ak]) plot(specCache[ak] || (specCache[ak] = ltas(clips[ak])), teal, false);
  }
  function toWav(f32, sr) {
    var n = f32.length, buf = new ArrayBuffer(44 + n * 2), dv = new DataView(buf), i;
    function s(o, str) { for (var j = 0; j < str.length; j++) dv.setUint8(o + j, str.charCodeAt(j)); }
    s(0, "RIFF"); dv.setUint32(4, 36 + n * 2, true); s(8, "WAVE"); s(12, "fmt ");
    dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
    dv.setUint32(24, sr, true); dv.setUint32(28, sr * 2, true); dv.setUint16(32, 2, true);
    dv.setUint16(34, 16, true); s(36, "data"); dv.setUint32(40, n * 2, true);
    for (i = 0; i < n; i++) { var v = Math.max(-1, Math.min(1, f32[i])); dv.setInt16(44 + i * 2, v * 32767, true); }
    return new Blob([buf], { type: "audio/wav" });
  }

  // ---- audiogram canvas + sliders ----------------------------------------------------
  function drawAg() {
    var c = $("agc"); if (!c) return;
    var x = c.getContext("2d"), W = c.width, H = c.height, pl = 34, pr = 8, pt = 10, pb = 20;
    var cs = getComputedStyle(document.documentElement);
    var line = cs.getPropertyValue("--line") || "#ccc", teal = (cs.getPropertyValue("--teal") || "#227").trim(),
        ink = cs.getPropertyValue("--muted") || "#678";
    x.clearRect(0, 0, W, H);
    var xx = function (i) { return pl + (W - pl - pr) * i / (FREQS.length - 1); };
    var yy = function (db) { return pt + (H - pt - pb) * (db + 10) / 130; };
    x.strokeStyle = line; x.fillStyle = ink; x.lineWidth = 1; x.font = "9px ui-monospace,monospace";
    for (var d = 0; d <= 120; d += 20) { x.globalAlpha = .5; x.beginPath(); x.moveTo(pl, yy(d)); x.lineTo(W - pr, yy(d)); x.stroke();
      x.globalAlpha = 1; x.textAlign = "right"; x.fillText(d, pl - 4, yy(d) + 3); }
    x.textAlign = "center";
    for (var i = 0; i < FREQS.length; i++) x.fillText(FREQS[i] >= 1000 ? FREQS[i] / 1000 + "k" : FREQS[i], xx(i), H - 6);
    x.strokeStyle = teal; x.fillStyle = teal; x.lineWidth = 2; x.beginPath();
    for (i = 0; i < FREQS.length; i++) { var px = xx(i), py = yy(ag[i]); i ? x.lineTo(px, py) : x.moveTo(px, py); }
    x.stroke();
    for (i = 0; i < FREQS.length; i++) { x.beginPath(); x.arc(xx(i), yy(ag[i]), 3.5, 0, 6.29); x.fill(); }
  }
  function buildSliders() {
    var host = $("sliders"); if (!host) return; host.innerHTML = "";
    FREQS.forEach(function (f, i) {
      var wrap = document.createElement("label"); wrap.className = "sl";
      wrap.innerHTML = '<span class="slf">' + (f >= 1000 ? f / 1000 + "k" : f) + '</span>' +
        '<input type="range" min="0" max="120" step="5" value="' + ag[i] + '" orient="vertical">' +
        '<span class="slv">' + ag[i] + '</span>';
      var inp = wrap.querySelector("input"), out = wrap.querySelector(".slv");
      inp.addEventListener("input", function () { ag[i] = +inp.value; out.textContent = inp.value; drawAg(); });
      host.appendChild(wrap);
    });
  }
  function preset(name) {
    var P = { sloping: [20, 25, 30, 40, 55, 65], flat: [40, 42, 45, 45, 48, 50], ski: [15, 20, 30, 50, 70, 80], normal: [5, 5, 5, 5, 10, 10] };
    ag = P[name].slice(); buildSliders(); drawAg();
  }

  // ---- Pyodide (real module) ---------------------------------------------------------
  function loadScript(src) { return new Promise(function (res, rej) {
    var s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s); }); }
  function bootPyodide() {
    if (pyBooting || pyReady || pyFailed) return Promise.resolve();
    pyBooting = true; engine("engine: booting Python… (~30 MB, first time only)");
    var V = "0.26.4", U = "https://cdn.jsdelivr.net/pyodide/v" + V + "/full/";
    return loadScript(U + "pyodide.js")
      .then(function () { return loadPyodide({ indexURL: U }); })
      .then(function (py) { pyodide = py; engine("engine: loading numpy / scipy…"); return py.loadPackage(["numpy", "scipy"]); })
      .then(function () { return Promise.all([fetch("./speech_resynth.py"), fetch("./fitting.py")]); })
      .then(function (rs) { if (!rs[0].ok || !rs[1].ok) throw new Error("module fetch failed"); return Promise.all([rs[0].text(), rs[1].text()]); })
      .then(function (srcs) {
        pyodide.FS.writeFile("speech_resynth.py", srcs[0]);
        pyodide.FS.writeFile("fitting.py", srcs[1]);
        pyodide.runPython("import numpy as np\nimport speech_resynth as sp\nimport fitting");
        pyReady = true; pyBooting = false; engine("engine: exact — Python (numpy / scipy) + OpenMHA-style fittings");
      })
      .catch(function (e) { pyFailed = true; pyBooting = false;
        engine("engine: approximate — JS fallback (Python unavailable)"); console.warn("Pyodide failed:", e); });
  }
  var PYCODE = [
    "ag = {int(f): float(v) for f, v in zip(list(agf), list(agv))}",
    "fc = sp.band_centres(sp.band_edges(100.0, 12000.0, 32, 'greenwood'))",
    "thr = sp.audiogram_thresholds(fc, ag)",
    "imp = np.exp(-0.5*((np.log10(fc)-np.log10(1800.0))/0.42)**2)",
    "cm = dict(backend='stft', n_bands=32, flo=100.0, fhi=12000.0, carrier='original',",
    "          loud_ref=sp.dbfs_ref_for_spl(100.0), match_rms=False, gate_db=-45.0, gate_knee_db=18.0)",
    "x = np.asarray(xin.to_py(), dtype=float)",
    "x = sp.frequency_compress(x, sr, f_start=1500.0, ratio=flow) if flow > 1.01 else x",
    "if noise >= 0: x = sp.add_noise(x, float(noise), 'ssn')",                    // speech-in-noise
    "xin2 = x / (np.sqrt(np.mean(x**2)) + 1e-12) * 10**((spl - 100) / 20)",       // noisy, at chosen SPL
    "xfit = xin2",                                                                // aid input
    "if nr:",                                                                     // noise reduction (aid-side)
    "    xfit = sp.denoise(xin2, sr); xfit = xfit / (np.sqrt(np.mean(xfit**2)) + 1e-12) * 10**((spl - 100) / 20)",
    "pm = sp.PersonalizedGainMap(fc, audiogram=ag)",
    "GAINS = {'static': (pm, False), 'wdrc': (pm, True), 'rx': (sp.PrescriptiveGain(fc, ag), True),",
    "         'nal': (fitting.GainTableWDRC(fc, ag, 'nal_nl2'), True), 'dsl': (fitting.GainTableWDRC(fc, ag, 'dsl_mio'), True),",
    "         'per': (sp.PersonalizedWDRC(fc, audiogram=ag, airbone_gap=gap, ohc_health=ohc), True)}",   // bone/OHC-aware
    "def _sii(Lo):",                                                              // audibility from the run matrix (cheap)
    "    bl = 10*np.log10(np.mean(10**(Lo/10), axis=1) + 1e-12)",
    "    return round(float((imp*np.clip((bl-thr)/30.0, 0, 1)).sum()/imp.sum()), 2)",
    "OUT = {'original': xin2.astype('float32')}; SII = {'original': round(sp.audibility(xin2, sr, ag), 2)}",
    "for _k,(_g,_dyn) in GAINS.items():",
    "    _r = sp.run(xfit, sr, gain=_g, attack_ms=(5 if _dyn else None), release_ms=(rel if _dyn else None), **cm)",
    "    OUT[_k] = _r['waveform'].astype('float32'); SII[_k] = _sii(_r['matrix']['level_out'])",
    "if losssim:",                                                               // 'hear it as the patient does'
    "    LS = sp.HearingLossSim(fc, ag)",
    "    for _k in list(OUT): OUT[_k] = sp.run(np.asarray(OUT[_k], dtype=float), sr, gain=LS, **cm)['waveform'].astype('float32')",
    "yo=OUT['original']; ys=OUT['static']; yw=OUT['wdrc']; yr=OUT['rx']; yn=OUT['nal']; yd=OUT['dsl']; yp=OUT['per']",
    "si=[SII['original'],SII['static'],SII['wdrc'],SII['rx'],SII['nal'],SII['dsl'],SII['per']]"
  ].join("\n");

  function opts() {
    return { rel: +$("rel").value, spl: $("level") ? +$("level").value : 65,
             flow: $("flow") ? +$("flow").value : 1, loss: $("losssim") ? $("losssim").checked : false,
             gap: $("gap") ? +$("gap").value : 0, ohc: $("ohc") ? +$("ohc").value / 100 : 0,
             levels: !!($("levels") && $("levels").value === "real"),
             noise: $("noise") ? +$("noise").value : -1, nr: !!($("nr") && $("nr").checked) };
  }
  function runEngine() {
    var o = opts();
    if (pyReady) {
      pyodide.globals.set("xin", input);
      pyodide.globals.set("agf", pyodide.toPy(FREQS));
      pyodide.globals.set("agv", pyodide.toPy(ag));
      pyodide.globals.set("sr", SR); pyodide.globals.set("rel", o.rel);
      pyodide.globals.set("spl", o.spl); pyodide.globals.set("flow", o.flow); pyodide.globals.set("losssim", o.loss);
      pyodide.globals.set("gap", o.gap); pyodide.globals.set("ohc", o.ohc);
      pyodide.globals.set("noise", o.noise); pyodide.globals.set("nr", o.nr);
      pyodide.runPython(PYCODE);
      var G = function (n) { return Float32Array.from(pyodide.globals.get(n).toJs()); };
      return Promise.resolve({ original: G("yo"), static: G("ys"), wdrc: G("yw"), rx: G("yr"), nal: G("yn"), dsl: G("yd"), per: G("yp"),
        sii: pyodide.globals.get("si").toJs(), loss: o.loss, levels: o.levels });
    }
    var jo = { agFreqs: FREQS, agVals: ag, presentSPL: o.spl, nBands: 32 };   // JS fallback (no NAL/DSL/Personalized/loss-sim)
    return Promise.resolve({
      static: DSP.process(input, SR, Object.assign({ mode: "static" }, jo)),
      wdrc: DSP.process(input, SR, Object.assign({ mode: "wdrc", attackMs: 5, releaseMs: o.rel }, jo)),
      rx: DSP.process(input, SR, Object.assign({ mode: "wdrc", attackMs: 5, releaseMs: o.rel, prescriptive: true }, jo)),
      loss: false, levels: o.levels
    });
  }

  // ---- file load: decode -> mono 32 kHz ----------------------------------------------
  function loadFile(file) {
    status("decoding…");
    var reader = new FileReader();
    reader.onload = function () {
      var AC = window.AudioContext || window.webkitAudioContext, ac = new AC();
      ac.decodeAudioData(reader.result, function (buf) {
        var len = Math.min(Math.ceil(buf.duration * SR), SR * CAP);
        var OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
        var off = new OAC(1, len, SR), src = off.createBufferSource();
        src.buffer = buf; src.connect(off.destination); src.start();
        off.startRendering().then(function (r) {
          input = r.getChannelData(0).slice(0, len); ac.close();
          fileName = file.name; $("fname").textContent = file.name + "  (" + (len / SR).toFixed(1) + " s)";
          status("ready — press Process"); $("run").disabled = false;
        });
      }, function () { status("couldn't decode that file — try a WAV or MP3"); ac.close(); });
    };
    reader.readAsArrayBuffer(file);
    bootPyodide();                                     // start the download while they set the audiogram
  }

  // ---- player ------------------------------------------------------------------------
  var pool = [], active = 0, on = false, dur = 0;
  function fmt(t) { t = Math.max(0, t | 0); return (t / 60 | 0) + ":" + ("0" + (t % 60)).slice(-2); }
  function tick() { var a = pool[active]; if (!a) return; var p = dur ? Math.min(1, a.currentTime / dur) : 0;
    $("tfill").style.width = (p * 100) + "%"; $("tseek").value = Math.round(p * 1000);
    $("ttime").innerHTML = "<b>" + fmt(Math.min(a.currentTime, dur)) + "</b> / " + fmt(dur); if (on) requestAnimationFrame(tick); }
  function setOn(v) { on = v; $("tplay").classList.toggle("on", v); if (v) requestAnimationFrame(tick); }
  function switchTo(i) {
    if (i === active || !pool[i]) return; var f = pool[active], t = pool[i];
    if (f) { f.pause(); t.currentTime = f.currentTime; } active = i;
    document.querySelectorAll("#tchips .chip").forEach(function (c) { c.setAttribute("aria-pressed", c.dataset.i == i); });
    $("tcur").textContent = ["Original","Static","WDRC","Rx","NAL-NL2","DSL","Personalized"][i]; if (on) t.play();
    drawSpec();
  }

  function process() {
    if (!input) { status("pick a file first"); return; }
    $("run").disabled = true; status("processing…");
    bootPyodide().then(function () {
      return runEngine();
    }).then(function (r) {
      var keys = ["original", "static", "wdrc", "rx", "nal", "dsl", "per"];
      if (r.loss || r.levels) {              // loss-sim OR 'real levels': one common scale keeps the natural differences
        var pk = 0; keys.forEach(function (k) { if (r[k]) for (var i = 0; i < r[k].length; i++) { var a = Math.abs(r[k][i]); if (a > pk) pk = a; } });
        var g = 0.92 / (pk + 1e-9);
        keys.forEach(function (k) { if (!r[k]) { clips[k] = null; return; } var o = new Float32Array(r[k].length); for (var i = 0; i < r[k].length; i++) o[i] = r[k][i] * g; clips[k] = softknee(o); });
      } else {                               // loudness-matched A/B
        clips.original = normalize(r.original || input.slice(), -24);
        ["static", "wdrc", "rx", "nal", "dsl", "per"].forEach(function (k) { clips[k] = r[k] ? normalize(r[k], -20) : null; });
      }
      keys.forEach(function (k, i) {
        var chip = document.querySelector('#tchips .chip[data-i="' + i + '"]'), dl = $("dl_" + k);
        if (!clips[k]) { if (chip) chip.disabled = true; if (dl) dl.style.display = "none"; return; }
        if (urls[k]) URL.revokeObjectURL(urls[k]);
        urls[k] = URL.createObjectURL(toWav(clips[k], SR)); pool[i].src = urls[k]; if (chip) chip.disabled = false;
        if (dl) { dl.href = urls[k]; dl.download = (fileName.replace(/\.[^.]+$/, "") || "clip") + "_" + k + ".wav"; dl.style.display = ""; }
      });
      specCache = {}; showSII(r.sii);
      dur = input.length / SR;
      $("dlrow").style.display = "flex"; $("tplay").disabled = false;
      active = 0; switchTo(0); drawSpec();
      status(r.loss ? "done — heard through the loss (unaided degraded; aided restores it)" : r.levels ? "done — real levels (the aid makes it louder)"
                    : (r.nal ? "done — A/B all six" : "done — NAL/DSL need the Python engine"));
      $("run").disabled = false;
    }).catch(function (e) { status("processing failed: " + e.message); console.error(e); $("run").disabled = false; });
  }

  // ---- init --------------------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", function () {
    if (!$("agc")) return;
    buildSliders(); drawAg();
    $("tf").addEventListener("change", function (e) { if (e.target.files[0]) loadFile(e.target.files[0]); });
    $("rel").addEventListener("input", function () { $("relv").textContent = $("rel").value + " ms"; });
    if ($("gap")) $("gap").addEventListener("input", function () { $("gapv").textContent = $("gap").value + " dB"; });
    if ($("ohc")) $("ohc").addEventListener("input", function () { $("ohcv").textContent = $("ohc").value + "%"; });
    document.querySelectorAll("[data-preset]").forEach(function (b) {
      b.addEventListener("click", function () { preset(b.dataset.preset); }); });
    $("run").addEventListener("click", process);
    for (var i = 0; i < 7; i++) { pool[i] = new Audio(); pool[i].preload = "auto"; }
    pool.forEach(function (a) { a.addEventListener("ended", function () { setOn(false);
      pool.forEach(function (x) { x.currentTime = 0; }); $("tfill").style.width = "0%"; $("tseek").value = 0; }); });
    $("tplay").addEventListener("click", function () { if (!pool[active].src) return;
      if (on) { pool[active].pause(); setOn(false); } else { pool[active].play(); setOn(true); } });
    document.querySelectorAll("#tchips .chip").forEach(function (c) {
      c.addEventListener("click", function () { switchTo(+c.dataset.i); }); });
    $("tseek").addEventListener("input", function () { var t = ($("tseek").value / 1000) * dur;
      pool.forEach(function (a) { if (a.src) a.currentTime = t; }); $("tfill").style.width = ($("tseek").value / 10) + "%"; });
    new MutationObserver(function(){drawAg();drawSpec();}).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  });
})();
