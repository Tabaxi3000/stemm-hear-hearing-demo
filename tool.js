/* "Try your own": upload audio + set an audiogram -> Original / Static / WDRC, in-browser.
   Primary engine: the REAL colab/speech_resynth.py run under Pyodide (numpy/scipy in WASM), so
   output is notebook-identical. Falls back to the JS port (dsp.js) if Pyodide can't load.
   Everything is client-side; nothing is uploaded. Processing at 32 kHz, bank to 12 kHz. */
(function () {
  "use strict";
  var FREQS = [250, 500, 1000, 2000, 4000, 8000];
  var ag = [20, 25, 30, 40, 55, 65];                   // left ear (also the mono audiogram)
  var agR = ag.slice();                                // right ear (used only in binaural mode)
  var binauralOn = false, binaEverOn = false;
  var SR = 32000, CAP = 10;                            // process up to 10 s (each fit is a full DSP pass)
  var input = null, fileName = "", urls = {}, clips = {};
  var KEYS = ["original", "static", "wdrc", "rx", "nal", "dsl", "cam", "per"], specCache = {};
  var LABELS = ["Original", "Static", "WDRC", "Rx", "NAL-NL2", "DSL", "CAM2", "Personalized"];
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
  function showMetrics(si, st, er) {                   // SII (audibility) + STOI (intelligibility) + dB-to-target
    var el = $("siirow"); if (!el) return;
    if (!si) { el.style.display = "none"; return; }
    var L = ["Original", "Static", "WDRC", "Rx", "NAL", "DSL", "CAM2", "Pers"];
    function row(lab, arr, fmt) {
      return '<div><b>' + lab + '</b> ' + L.map(function (n, i) { return n + " " + (arr && arr[i] != null ? fmt(arr[i]) : "–"); }).join("  ·  ") + '</div>';
    }
    var ear = binauralOn ? ", poorer ear" : "";
    var h = row("ANSI SII (0–1" + ear + "):", si, function (v) { return v.toFixed(2); });
    if (st) h += row("STOI (0–1" + ear + "):", st, function (v) { return v.toFixed(2); });
    if (er) h += row("dB RMS to NAL target" + ear + ":", er, function (v) { return v.toFixed(0); });
    h += '<div class="metleg">SII &amp; STOI: higher = better (more audible / intelligible) &middot; dB&#8209;to&#8209;target: closer to 0 = closer to the NAL&#8209;NL2 prescription</div>';
    el.innerHTML = h; el.style.display = "";
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
    if (clips.original) plot(specCache.original || (specCache.original = ltas(chanL(clips.original))), mut, true);
    var ak = KEYS[active]; if (clips[ak]) plot(specCache[ak] || (specCache[ak] = ltas(chanL(clips[ak]))), teal, false);
  }
  function chanL(c) { return c && c.l ? c.l : c; }        // mono Float32Array, or the left channel of a stereo clip
  function toWav(clip, sr) {
    var stereo = !!(clip && clip.l), l = chanL(clip), r = stereo ? clip.r : null;
    var ch = stereo ? 2 : 1, n = l.length, bytes = n * ch * 2;
    var buf = new ArrayBuffer(44 + bytes), dv = new DataView(buf), i;
    function s(o, str) { for (var j = 0; j < str.length; j++) dv.setUint8(o + j, str.charCodeAt(j)); }
    function w16(o, v) { dv.setInt16(o, Math.max(-1, Math.min(1, v)) * 32767, true); }
    s(0, "RIFF"); dv.setUint32(4, 36 + bytes, true); s(8, "WAVE"); s(12, "fmt ");
    dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, ch, true);
    dv.setUint32(24, sr, true); dv.setUint32(28, sr * ch * 2, true); dv.setUint16(32, ch * 2, true);
    dv.setUint16(34, 16, true); s(36, "data"); dv.setUint32(40, bytes, true);
    for (i = 0; i < n; i++) { var o = 44 + i * ch * 2; w16(o, l[i]); if (stereo) w16(o + 2, r[i]); }
    return new Blob([buf], { type: "audio/wav" });
  }
  function normalizeStereo(c, targetDb) {                 // match by JOINT rms so the interaural difference survives
    var l = c.l, r = c.r, n = l.length, s = 0, i;
    for (i = 0; i < n; i++) s += l[i] * l[i] + r[i] * r[i];
    var g = Math.pow(10, targetDb / 20) / (Math.sqrt(s / (2 * n)) + 1e-12);
    var ol = new Float32Array(n), or = new Float32Array(n);
    for (i = 0; i < n; i++) { ol[i] = l[i] * g; or[i] = r[i] * g; }
    return { l: softknee(ol), r: softknee(or) };
  }

  // ---- audiogram canvas + sliders ----------------------------------------------------
  function drawAgOn(cid, vals, col) {
    var c = $(cid); if (!c) return;
    var x = c.getContext("2d"), W = c.width, H = c.height, pl = 34, pr = 8, pt = 10, pb = 20;
    var cs = getComputedStyle(document.documentElement);
    var line = cs.getPropertyValue("--line") || "#ccc",
        teal = (cs.getPropertyValue(col || "--teal") || "#227").trim(), ink = cs.getPropertyValue("--muted") || "#678";
    x.clearRect(0, 0, W, H);
    var xx = function (i) { return pl + (W - pl - pr) * i / (FREQS.length - 1); };
    var yy = function (db) { return pt + (H - pt - pb) * (db + 10) / 130; };
    x.strokeStyle = line; x.fillStyle = ink; x.lineWidth = 1; x.font = "9px ui-monospace,monospace";
    for (var d = 0; d <= 120; d += 20) { x.globalAlpha = .5; x.beginPath(); x.moveTo(pl, yy(d)); x.lineTo(W - pr, yy(d)); x.stroke();
      x.globalAlpha = 1; x.textAlign = "right"; x.fillText(d, pl - 4, yy(d) + 3); }
    x.textAlign = "center";
    for (var i = 0; i < FREQS.length; i++) x.fillText(FREQS[i] >= 1000 ? FREQS[i] / 1000 + "k" : FREQS[i], xx(i), H - 6);
    x.strokeStyle = teal; x.fillStyle = teal; x.lineWidth = 2; x.beginPath();
    for (i = 0; i < FREQS.length; i++) { var px = xx(i), py = yy(vals[i]); i ? x.lineTo(px, py) : x.moveTo(px, py); }
    x.stroke();
    for (i = 0; i < FREQS.length; i++) { x.beginPath(); x.arc(xx(i), yy(vals[i]), 3.5, 0, 6.29); x.fill(); }
  }
  function drawAg() { drawAgOn("agc", ag, "--teal"); if ($("agc2")) drawAgOn("agc2", agR, "--blue"); }
  function buildSlidersOn(hostId, vals, col) {
    var host = $(hostId); if (!host) return; host.innerHTML = "";
    FREQS.forEach(function (f, i) {
      var wrap = document.createElement("label"); wrap.className = "sl";
      wrap.innerHTML = '<span class="slf">' + (f >= 1000 ? f / 1000 + "k" : f) + '</span>' +
        '<input type="range" min="0" max="120" step="5" value="' + vals[i] + '" orient="vertical">' +
        '<span class="slv">' + vals[i] + '</span>';
      var inp = wrap.querySelector("input"), out = wrap.querySelector(".slv");
      inp.addEventListener("input", function () { vals[i] = +inp.value; out.textContent = inp.value; drawAg(); });
      host.appendChild(wrap);
    });
  }
  function buildSliders() { buildSlidersOn("sliders", ag, "--teal"); buildSlidersOn("sliders2", agR, "--blue"); }
  function preset(name) {
    var P = { normal:[5,5,5,5,10,10], sloping:[20,25,30,40,55,65], flat:[40,42,45,45,48,50], ski:[15,20,30,50,70,80], cookie:[15,35,55,55,35,20], reverse:[60,55,45,30,25,25], notch:[10,15,25,55,30,20] };
    ag = P[name].slice();
    if (binauralOn) agR = P[name].slice();                   // two-ear mode: a preset seeds both ears symmetrically
    buildSliders(); drawAg();
  }
  function setEarMode(two) {
    binauralOn = two;
    if (two && !binaEverOn) { agR = ag.slice(); binaEverOn = true; }   // start the right ear matched to the left
    var w = $("agwrap2"); if (w) w.hidden = !two;
    if ($("earlblL")) $("earlblL").textContent = two ? "left ear" : "audiogram";
    if ($("earlblL")) $("earlblL").classList.toggle("earR", false);
    if ($("earOne")) $("earOne").classList.toggle("on", !two);
    if ($("earTwo")) $("earTwo").classList.toggle("on", two);
    buildSliders(); drawAg();
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
      .then(function () { return Promise.all(["./speech_resynth.py", "./fitting.py", "./sii.py", "./stoi_vendor.py", "./metrics.py", "./toolrun.py"].map(function (u) { return fetch(u); })); })
      .then(function (rs) { if (rs.some(function (r) { return !r.ok; })) throw new Error("module fetch failed"); return Promise.all(rs.map(function (r) { return r.text(); })); })
      .then(function (srcs) {
        pyodide.FS.writeFile("speech_resynth.py", srcs[0]);
        pyodide.FS.writeFile("fitting.py", srcs[1]);
        pyodide.FS.writeFile("sii.py", srcs[2]);                        // vendored ANSI SII (Malcolm Slaney)
        pyodide.FS.writeFile("stoi_vendor.py", srcs[3]);               // vendored STOI (Taal et al.)
        pyodide.FS.writeFile("metrics.py", srcs[4]);                   // shared SII/STOI/dB-to-target (same as gallery)
        pyodide.FS.writeFile("toolrun.py", srcs[5]);                   // incremental engine (one fit at a time)
        pyodide.runPython("import numpy as np\nimport speech_resynth as sp\nimport fitting\nimport sii\nimport stoi_vendor\nimport metrics\nimport toolrun");
        pyReady = true; pyBooting = false; engine("engine: exact — Python (numpy / scipy) + OpenMHA-style fittings");
      })
      .catch(function (e) { pyFailed = true; pyBooting = false;
        engine("engine: approximate — JS fallback (Python unavailable)"); console.warn("Pyodide failed:", e); });
  }
  function opts() {
    return { rel: +$("rel").value, spl: $("level") ? +$("level").value : 65,
             flow: $("flow") ? +$("flow").value : 1, loss: $("losssim") ? $("losssim").checked : false,
             gap: $("gap") ? +$("gap").value : 0, ohc: $("ohc") ? +$("ohc").value / 100 : 0,
             levels: !!($("levels") && $("levels").value === "real"),
             noise: $("noise") ? +$("noise").value : -1, nr: !!($("nr") && $("nr").checked),
             prog: $("prog") ? $("prog").value : "speech",
             ntype: $("ntype") ? $("ntype").value : "ssn", rev: $("rev") ? +$("rev").value : 0,
             binaural: binauralOn };
  }
  function yieldUI() { return new Promise(function (r) { setTimeout(r, 0); }); }   // let the browser repaint

  // Run ONE ear on the real engine, one fit at a time, yielding to the UI between fits (onFit()
  // fires after each) so the main thread never locks up -> no "page unresponsive" popups.
  function runEngineAsync(agVals, onFit) {
    var o = opts(); agVals = agVals || ag;
    if (!pyReady) {                                       // JS fallback (sync, fast; no NAL/DSL/CAM2/Pers/loss-sim)
      var jo = { agFreqs: FREQS, agVals: agVals, presentSPL: o.spl, nBands: 32 };
      return Promise.resolve({
        static: DSP.process(input, SR, Object.assign({ mode: "static" }, jo)),
        wdrc: DSP.process(input, SR, Object.assign({ mode: "wdrc", attackMs: 5, releaseMs: o.rel }, jo)),
        rx: DSP.process(input, SR, Object.assign({ mode: "wdrc", attackMs: 5, releaseMs: o.rel, prescriptive: true }, jo)),
        loss: false, levels: o.levels
      });
    }
    pyodide.globals.set("xin", input);
    pyodide.globals.set("agf", pyodide.toPy(FREQS));
    pyodide.globals.set("agv", pyodide.toPy(agVals));
    pyodide.globals.set("sr", SR);
    pyodide.globals.set("t_spl", o.spl); pyodide.globals.set("t_flow", o.flow);
    pyodide.globals.set("t_noise", o.noise); pyodide.globals.set("t_ntype", o.ntype);
    pyodide.globals.set("t_rev", o.rev); pyodide.globals.set("t_nr", o.nr);
    pyodide.globals.set("t_gap", o.gap); pyodide.globals.set("t_ohc", o.ohc);
    pyodide.globals.set("t_prog", o.prog); pyodide.globals.set("t_rel", o.rel);
    var order = pyodide.runPython(
      "toolrun.tool_setup(xin, agf, agv, sr, t_spl, t_flow, t_noise, t_ntype, t_rev, t_nr, t_gap, t_ohc, t_prog, t_rel)").toJs();
    var fitKeys = order.slice(1);                         // 'original' is already computed in setup
    return fitKeys.reduce(function (chain, k) {
      return chain.then(yieldUI).then(function () {
        pyodide.globals.set("t_k", k); pyodide.runPython("toolrun.tool_fit(t_k)");
        if (onFit) onFit();
      });
    }, Promise.resolve())
      .then(function () { if (o.loss) return yieldUI().then(function () { pyodide.runPython("toolrun.tool_losssim()"); }); })
      .then(yieldUI)
      .then(function () {
        var res = { loss: o.loss, levels: o.levels };
        order.forEach(function (k) { pyodide.globals.set("t_k", k);
          res[k] = Float32Array.from(pyodide.runPython("toolrun.tool_get(t_k)").toJs()); });
        var mt = pyodide.runPython("toolrun.tool_metrics()").toJs();
        res.sii = mt[0]; res.stoi = mt[1]; res.err = mt[2];
        return res;
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
    $("tcur").textContent = LABELS[i]; if (on) t.play();
    drawSpec();
  }

  function applyClips() {                                 // wire the (mono or stereo) clips{} to chips / player / downloads
    KEYS.forEach(function (k, i) {
      var chip = document.querySelector('#tchips .chip[data-i="' + i + '"]'), dl = $("dl_" + k);
      if (!clips[k]) { if (chip) chip.disabled = true; if (dl) dl.style.display = "none"; return; }
      if (urls[k]) URL.revokeObjectURL(urls[k]);
      urls[k] = URL.createObjectURL(toWav(clips[k], SR)); pool[i].src = urls[k]; if (chip) chip.disabled = false;
      if (dl) { dl.href = urls[k]; dl.download = (fileName.replace(/\.[^.]+$/, "") || "clip") + "_" + k + ".wav"; dl.style.display = ""; }
    });
  }
  function finishUp(si, st, er, msg) {
    progHide();
    specCache = {}; showMetrics(si, st, er);
    dur = input.length / SR;
    $("dlrow").style.display = "flex"; $("tplay").disabled = false;
    if ($("blindbtn")) $("blindbtn").disabled = false;
    active = 0; switchTo(0); drawSpec(); status(msg); $("run").disabled = false;
  }
  function progShow(total) {
    var p = $("tprog"); if (!p) return;
    if (!total) { p.hidden = true; return; }               // fallback engine: no per-fit progress
    p.hidden = false; if ($("tprogfill")) $("tprogfill").style.width = "0%";
    if ($("tprogtxt")) $("tprogtxt").textContent = "fit 0 / " + total;
  }
  function progStep(done, total) {
    if ($("tprogfill")) $("tprogfill").style.width = Math.round(done / total * 100) + "%";
    if ($("tprogtxt")) $("tprogtxt").textContent = "fit " + done + " / " + total;
  }
  function progHide() { var p = $("tprog"); if (p) p.hidden = true; }
  function peakOf(arrs) { var pk = 0, j, i; for (j = 0; j < arrs.length; j++) { var a = arrs[j]; for (i = 0; i < a.length; i++) { var v = Math.abs(a[i]); if (v > pk) pk = v; } } return pk; }
  function scaleTo(a, g) { var o = new Float32Array(a.length), i; for (i = 0; i < a.length; i++) o[i] = a[i] * g; return softknee(o); }

  function process() {
    if (!input) { status("pick a file first"); return; }
    $("run").disabled = true; status("processing…");
    var o = opts(), bin, done = 0, total;
    bootPyodide().then(function () {
      bin = o.binaural && pyReady;                         // binaural needs the Python engine (per-ear fits)
      total = pyReady ? (bin ? 14 : 7) : 0;                // 7 fits per ear
      progShow(total);
      function step() { progStep(++done, total); }
      if (bin) return runEngineAsync(ag, step).then(function (L) { return runEngineAsync(agR, step).then(function (R) { return { L: L, R: R }; }); });
      return runEngineAsync(ag, step).then(function (L) { return { L: L }; });
    }).then(function (res) {
      var L = res.L, R = res.R, common = L.loss || L.levels;
      if (bin) {                                           // ---- binaural: combine per-ear results into stereo ----
        var raw = {};
        KEYS.forEach(function (k) { raw[k] = (L[k] && R[k]) ? { l: L[k], r: R[k] } : null; });
        if (common) {
          var chans = []; KEYS.forEach(function (k) { if (raw[k]) { chans.push(raw[k].l); chans.push(raw[k].r); } });
          var g = 0.92 / (peakOf(chans) + 1e-9);
          KEYS.forEach(function (k) { clips[k] = raw[k] ? { l: scaleTo(raw[k].l, g), r: scaleTo(raw[k].r, g) } : null; });
        } else {
          KEYS.forEach(function (k) { clips[k] = raw[k] ? normalizeStereo(raw[k], k === "original" ? -24 : -20) : null; });
        }
        var mn = function (a, b) { return a && b ? a.map(function (v, i) { return Math.min(v, b[i]); }) : null; };
        var mx = function (a, b) { return a && b ? a.map(function (v, i) { return Math.max(v, b[i]); }) : null; };
        applyClips();
        finishUp(mn(L.sii, R.sii), mn(L.stoi, R.stoi), mx(L.err, R.err),   // poorer ear (worse SII/STOI, larger dB error)
                 "done — binaural, each ear fit on its own audiogram (headphones); SII is the poorer ear");
        return;
      }
      var r = L;                                           // ---- mono ----
      if (common) {
        var arrs = []; KEYS.forEach(function (k) { if (r[k]) arrs.push(r[k]); });
        var g = 0.92 / (peakOf(arrs) + 1e-9);
        KEYS.forEach(function (k) { clips[k] = r[k] ? scaleTo(r[k], g) : null; });
      } else {
        clips.original = normalize(r.original || input.slice(), -24);
        KEYS.slice(1).forEach(function (k) { clips[k] = r[k] ? normalize(r[k], -20) : null; });
      }
      applyClips();
      finishUp(r.sii, r.stoi, r.err,
               r.loss ? "done — heard through the loss (unaided degraded; aided restores it)" : r.levels ? "done — real levels (the aid makes it louder)"
                      : (r.nal ? "done — A/B all seven" : "done — NAL/DSL/CAM2 need the Python engine"));
    }).catch(function (e) { progHide(); status("processing failed: " + e.message); console.error(e); $("run").disabled = false; });
  }

  // ---- blind A/B preference test -----------------------------------------------------
  var blind = { A: null, B: null, trials: [], ba: null, bb: null, n: 0, cur: null };
  var LAB = {}; KEYS.forEach(function (k, i) { LAB[k] = LABELS[i]; });
  function blindPrefBtns(disabled) {
    ["bprefA", "bprefB", "bskip"].forEach(function (id) { if ($(id)) $(id).disabled = disabled; });
  }
  function blindNext() {
    var ks = KEYS.filter(function (k) { return clips[k]; }); if (ks.length < 2) return;
    var i = Math.floor(Math.random() * ks.length), j; do { j = Math.floor(Math.random() * ks.length); } while (j === i);
    blind.A = ks[i]; blind.B = ks[j]; blind.cur = null;
    if (blind.ba.src) URL.revokeObjectURL(blind.ba.src); if (blind.bb.src) URL.revokeObjectURL(blind.bb.src);
    blind.ba.src = URL.createObjectURL(toWav(clips[blind.A], SR)); blind.bb.src = URL.createObjectURL(toWav(clips[blind.B], SR));
    blind.n++; $("btrial").textContent = blind.n; $("breveal").textContent = "";
    if ($("bcomment")) $("bcomment").style.display = "none";
    if ($("bcommentA")) $("bcommentA").value = ""; if ($("bcommentB")) $("bcommentB").value = "";
    blindPrefBtns(false);                                 // re-enable choosing for the new pair
  }
  function blindPlay(which) {
    var a = which === "A" ? blind.ba : blind.bb, o = which === "A" ? blind.bb : blind.ba;
    o.pause(); a.currentTime = o.currentTime || 0; a.play();
  }
  function blindPrefer(which) {
    if (blind.cur) return;                                // already chose this trial; use "save & next"
    var win = which === "A" ? blind.A : blind.B, lose = which === "A" ? blind.B : blind.A, o = opts();
    blind.cur = { trial: blind.n, clipA: blind.A, clipB: blind.B, prefer: win, over: lose,
      commentA: "", commentB: "", audiogram: ag.join("/"), level: o.spl, noise: o.noise,
      ntype: o.ntype, reverb: o.rev, nr: o.nr, prog: o.prog, binaural: binauralOn };
    blind.trials.push(blind.cur); blindSave();
    // stay fully blind on screen: never name the fits to the listener (identities live in the CSV only)
    $("breveal").innerHTML = "You chose <b>" + which + "</b>. Trial " + blind.n + " logged (" +
      blind.trials.length + " total) &mdash; add notes below, then continue.";
    blind.ba.pause(); blind.bb.pause();
    if ($("bcomment")) $("bcomment").style.display = "flex";
    blindPrefBtns(true);                                  // lock the choice; play buttons stay live for re-listening
    if ($("bcommentA")) $("bcommentA").focus();
  }
  function blindSave() { try { localStorage.setItem("blind_ab", JSON.stringify(blind.trials)); } catch (e) {} }
  function csvCell(v) { v = (v == null ? "" : String(v)); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
  function blindCSV() {
    var cols = ["trial", "clipA", "clipB", "preferred", "over", "comment_A", "comment_B",
      "audiogram", "level_dB", "noise_SNR", "noise_type", "reverb", "NR", "program", "binaural"];
    var rows = [cols];
    blind.trials.forEach(function (t) {
      rows.push([t.trial, LAB[t.clipA] || t.clipA, LAB[t.clipB] || t.clipB, LAB[t.prefer] || t.prefer,
        LAB[t.over] || t.over, t.commentA, t.commentB, t.audiogram, t.level, t.noise, t.ntype,
        t.reverb, t.nr, t.prog, t.binaural]);
    });
    var body = rows.map(function (r) { return r.map(csvCell).join(","); }).join("\r\n");
    var url = URL.createObjectURL(new Blob([body], { type: "text/csv" }));
    var a = document.createElement("a"); a.href = url; a.download = "blind_ab_" + Date.now() + ".csv"; a.click();
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
    if ($("earOne")) $("earOne").addEventListener("click", function () { setEarMode(false); });
    if ($("earTwo")) $("earTwo").addEventListener("click", function () { setEarMode(true); });
    if ($("copyLR")) $("copyLR").addEventListener("click", function () { agR = ag.slice(); buildSliders(); drawAg(); });
    if ($("copyRL")) $("copyRL").addEventListener("click", function () { ag = agR.slice(); buildSliders(); drawAg(); });
    $("run").addEventListener("click", process);
    for (var i = 0; i < KEYS.length; i++) { pool[i] = new Audio(); pool[i].preload = "auto"; }
    blind.ba = new Audio(); blind.bb = new Audio();
    try { var _sv = JSON.parse(localStorage.getItem("blind_ab") || "[]"); if (_sv.length) blind.trials = _sv; } catch (e) {}
    if ($("blindbtn")) $("blindbtn").addEventListener("click", function () {
      $("blindpanel").style.display = "block"; $("blindbtn").style.display = "none"; blindNext(); });
    if ($("bA")) $("bA").addEventListener("click", function () { blindPlay("A"); });
    if ($("bB")) $("bB").addEventListener("click", function () { blindPlay("B"); });
    if ($("bprefA")) $("bprefA").addEventListener("click", function () { blindPrefer("A"); });
    if ($("bprefB")) $("bprefB").addEventListener("click", function () { blindPrefer("B"); });
    if ($("bskip")) $("bskip").addEventListener("click", blindNext);
    if ($("bnext")) $("bnext").addEventListener("click", blindNext);
    if ($("bcommentA")) $("bcommentA").addEventListener("input", function () { if (blind.cur) { blind.cur.commentA = $("bcommentA").value; blindSave(); } });
    if ($("bcommentB")) $("bcommentB").addEventListener("input", function () { if (blind.cur) { blind.cur.commentB = $("bcommentB").value; blindSave(); } });
    if ($("bdone")) $("bdone").addEventListener("click", blindCSV);
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
