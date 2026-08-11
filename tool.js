/* "Try your own": upload audio + set an audiogram -> Original / Static / WDRC, in-browser.
   Primary engine: the REAL colab/speech_resynth.py run under Pyodide (numpy/scipy in WASM), so
   output is notebook-identical. Falls back to the JS port (dsp.js) if Pyodide can't load.
   Everything is client-side; nothing is uploaded. Processing at 32 kHz, bank to 12 kHz. */
(function () {
  "use strict";
  var FREQS = [250, 500, 1000, 2000, 4000, 8000];
  var ag = [20, 25, 30, 40, 55, 65];
  var SR = 32000, CAP = 22;
  var input = null, fileName = "", urls = {}, clips = {};
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
      .then(function () { return fetch("./speech_resynth.py"); })
      .then(function (r) { if (!r.ok) throw new Error("module fetch " + r.status); return r.text(); })
      .then(function (src) {
        pyodide.FS.writeFile("speech_resynth.py", src);
        pyodide.runPython("import numpy as np\nimport speech_resynth as sp");
        pyReady = true; pyBooting = false; engine("engine: exact — Python (numpy / scipy)");
      })
      .catch(function (e) { pyFailed = true; pyBooting = false;
        engine("engine: approximate — JS fallback (Python unavailable)"); console.warn("Pyodide failed:", e); });
  }
  var PYCODE = [
    "x = np.asarray(xin.to_py(), dtype=float)",
    "ag = {int(k): float(v) for k, v in agjs.to_py().items()}",
    "fc = sp.band_centres(sp.band_edges(100.0, 12000.0, 32, 'greenwood'))",
    "pm = sp.PersonalizedGainMap(fc, audiogram=ag)",
    "cm = dict(backend='stft', n_bands=32, flo=100.0, fhi=12000.0, carrier='original',",
    "          loud_ref=sp.dbfs_ref_for_spl(100.0), match_rms=False, gate_db=-45.0, gate_knee_db=18.0)",
    "x65 = x / (np.sqrt(np.mean(x**2)) + 1e-12) * 10**((65 - 100) / 20)",
    "ys = sp.run(x65, sr, gain=pm, **cm)['waveform'].astype('float32')",
    "yw = sp.run(x65, sr, gain=pm, attack_ms=5, release_ms=rel, **cm)['waveform'].astype('float32')"
  ].join("\n");

  function runEngine() {                               // -> Promise<{static,wdrc}>
    var relMs = +$("rel").value;
    if (pyReady) {
      pyodide.globals.set("xin", input);
      pyodide.globals.set("agjs", pyodide.toPy(FREQS.reduce(function (o, f, i) { o[f] = ag[i]; return o; }, {})));
      pyodide.globals.set("sr", SR); pyodide.globals.set("rel", relMs);
      pyodide.runPython(PYCODE);
      var ys = pyodide.globals.get("ys").toJs(), yw = pyodide.globals.get("yw").toJs();
      return Promise.resolve({ static: Float32Array.from(ys), wdrc: Float32Array.from(yw) });
    }
    var opt = { agFreqs: FREQS, agVals: ag, presentSPL: 65, nBands: 32 };     // JS fallback
    return Promise.resolve({
      static: DSP.process(input, SR, Object.assign({ mode: "static" }, opt)),
      wdrc: DSP.process(input, SR, Object.assign({ mode: "wdrc", attackMs: 5, releaseMs: relMs }, opt))
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
    $("tcur").textContent = ["Original", "Static", "WDRC"][i]; if (on) t.play();
  }

  function process() {
    if (!input) { status("pick a file first"); return; }
    $("run").disabled = true; status("processing…");
    bootPyodide().then(function () {
      return runEngine();
    }).then(function (r) {
      clips.original = normalize(input.slice(), -24);
      clips.static = normalize(r.static, -20);
      clips.wdrc = normalize(r.wdrc, -20);
      ["original", "static", "wdrc"].forEach(function (k, i) {
        if (urls[k]) URL.revokeObjectURL(urls[k]);
        urls[k] = URL.createObjectURL(toWav(clips[k], SR));
        pool[i].src = urls[k];
        var dl = $("dl_" + k); dl.href = urls[k]; dl.download = (fileName.replace(/\.[^.]+$/, "") || "clip") + "_" + k + ".wav";
      });
      dur = input.length / SR;
      document.querySelectorAll("#tchips .chip").forEach(function (c) { c.disabled = false; });
      $("dlrow").style.display = "flex"; $("tplay").disabled = false;
      active = 0; switchTo(0); status("done — A/B the three below"); $("run").disabled = false;
    }).catch(function (e) { status("processing failed: " + e.message); console.error(e); $("run").disabled = false; });
  }

  // ---- init --------------------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", function () {
    if (!$("agc")) return;
    buildSliders(); drawAg();
    $("tf").addEventListener("change", function (e) { if (e.target.files[0]) loadFile(e.target.files[0]); });
    $("rel").addEventListener("input", function () { $("relv").textContent = $("rel").value + " ms"; });
    document.querySelectorAll("[data-preset]").forEach(function (b) {
      b.addEventListener("click", function () { preset(b.dataset.preset); }); });
    $("run").addEventListener("click", process);
    for (var i = 0; i < 3; i++) { pool[i] = new Audio(); pool[i].preload = "auto"; }
    pool.forEach(function (a) { a.addEventListener("ended", function () { setOn(false);
      pool.forEach(function (x) { x.currentTime = 0; }); $("tfill").style.width = "0%"; $("tseek").value = 0; }); });
    $("tplay").addEventListener("click", function () { if (!pool[active].src) return;
      if (on) { pool[active].pause(); setOn(false); } else { pool[active].play(); setOn(true); } });
    document.querySelectorAll("#tchips .chip").forEach(function (c) {
      c.addEventListener("click", function () { switchTo(+c.dataset.i); }); });
    $("tseek").addEventListener("input", function () { var t = ($("tseek").value / 1000) * dur;
      pool.forEach(function (a) { if (a.src) a.currentTime = t; }); $("tfill").style.width = ($("tseek").value / 10) + "%"; });
    new MutationObserver(drawAg).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  });
})();
