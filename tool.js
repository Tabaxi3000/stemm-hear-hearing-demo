/* "Try your own": upload audio + set an audiogram -> Original / Static / WDRC, in-browser.
   Uses DSP.process (dsp.js). All client-side; no uploads leave the page. */
(function () {
  "use strict";
  var FREQS = [250, 500, 1000, 2000, 4000, 8000];
  var ag = [20, 25, 30, 40, 55, 65];               // default: mild sloping
  var SR = 16000, CAP = 25;                          // process at 16 kHz, cap 25 s
  var input16 = null, fileName = "", clips = {}, urls = {};
  var $ = function (id) { return document.getElementById(id); };

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
  function toWav(f32, sr) {                           // 16-bit PCM WAV Blob
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
    var c = $("agc"), x = c.getContext("2d"), W = c.width, H = c.height, pl = 34, pr = 8, pt = 10, pb = 20;
    var cs = getComputedStyle(document.documentElement);
    var line = cs.getPropertyValue("--line") || "#ccc", teal = cs.getPropertyValue("--teal") || "#227";
    var ink = cs.getPropertyValue("--muted") || "#678";
    x.clearRect(0, 0, W, H);
    var xx = function (i) { return pl + (W - pl - pr) * i / (FREQS.length - 1); };
    var yy = function (db) { return pt + (H - pt - pb) * (db + 10) / 130; };   // -10..120
    x.strokeStyle = line; x.fillStyle = ink; x.lineWidth = 1; x.font = "9px ui-monospace,monospace";
    for (var d = 0; d <= 120; d += 20) { x.globalAlpha = .5; x.beginPath(); x.moveTo(pl, yy(d)); x.lineTo(W - pr, yy(d)); x.stroke();
      x.globalAlpha = 1; x.textAlign = "right"; x.fillText(d, pl - 4, yy(d) + 3); }
    x.textAlign = "center";
    for (var i = 0; i < FREQS.length; i++) x.fillText(FREQS[i] >= 1000 ? FREQS[i] / 1000 + "k" : FREQS[i], xx(i), H - 6);
    x.strokeStyle = teal.trim(); x.fillStyle = teal.trim(); x.lineWidth = 2; x.beginPath();
    for (i = 0; i < FREQS.length; i++) { var px = xx(i), py = yy(ag[i]); i ? x.lineTo(px, py) : x.moveTo(px, py); }
    x.stroke();
    for (i = 0; i < FREQS.length; i++) { x.beginPath(); x.arc(xx(i), yy(ag[i]), 3.5, 0, 6.29); x.fill(); }
  }
  function buildSliders() {
    var host = $("sliders"); host.innerHTML = "";
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

  // ---- file load: decode -> mono 16 kHz ----------------------------------------------
  function loadFile(file) {
    var status = $("tstatus"); status.textContent = "decoding…";
    var reader = new FileReader();
    reader.onload = function () {
      var AC = window.AudioContext || window.webkitAudioContext, ac = new AC();
      ac.decodeAudioData(reader.result, function (buf) {
        var len = Math.min(Math.ceil(buf.duration * SR), SR * CAP);
        var OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
        var off = new OAC(1, len, SR), src = off.createBufferSource();
        src.buffer = buf; src.connect(off.destination); src.start();
        off.startRendering().then(function (r) {
          input16 = r.getChannelData(0).slice(0, len); ac.close();
          fileName = file.name; $("fname").textContent = file.name + "  (" + (len / SR).toFixed(1) + " s)";
          status.textContent = "ready — press Process"; $("run").disabled = false;
        });
      }, function () { status.textContent = "couldn't decode that file — try a WAV or MP3"; ac.close(); });
    };
    reader.readAsArrayBuffer(file);
  }

  // ---- process + wire the player -----------------------------------------------------
  var pool = [], active = 0, on = false, dur = 0, raf = 0;
  function fmt(t) { t = Math.max(0, t | 0); return (t / 60 | 0) + ":" + ("0" + (t % 60)).slice(-2); }
  function tick() { var a = pool[active]; if (!a) return; var p = dur ? a.currentTime / dur : 0;
    $("tfill").style.width = (p * 100) + "%"; $("tseek").value = Math.round(p * 1000);
    $("ttime").innerHTML = "<b>" + fmt(a.currentTime) + "</b> / " + fmt(dur); if (on) raf = requestAnimationFrame(tick); }
  function setOn(v) { on = v; $("tplay").classList.toggle("on", v); if (v) raf = requestAnimationFrame(tick); }
  function switchTo(i) {
    if (i === active || !pool[i]) return; var f = pool[active], t = pool[i];
    if (f) { f.pause(); t.currentTime = f.currentTime; } active = i;
    document.querySelectorAll("#tchips .chip").forEach(function (c) { c.setAttribute("aria-pressed", c.dataset.i == i); });
    $("tcur").textContent = ["Original", "Static", "WDRC"][i]; if (on) t.play();
  }
  function process() {
    if (!input16) { $("tstatus").textContent = "pick a file first"; return; }
    $("tstatus").textContent = "processing…"; $("run").disabled = true;
    setTimeout(function () {                          // let the UI paint "processing…"
      var rel = +$("rel").value, opt = { agFreqs: FREQS, agVals: ag, presentSPL: 65 };
      clips.original = normalize(input16.slice(), -24);
      clips.static = normalize(DSP.process(input16, SR, Object.assign({ mode: "static" }, opt)), -20);
      clips.wdrc = normalize(DSP.process(input16, SR, Object.assign({ mode: "wdrc", attackMs: 5, releaseMs: rel }, opt)), -20);
      ["original", "static", "wdrc"].forEach(function (k, i) {
        if (urls[k]) URL.revokeObjectURL(urls[k]);
        urls[k] = URL.createObjectURL(toWav(clips[k], SR));
        pool[i].src = urls[k];
        var dl = $("dl_" + k); dl.href = urls[k]; dl.download = (fileName.replace(/\.[^.]+$/, "") || "clip") + "_" + k + ".wav";
      });
      pool[0].addEventListener("loadedmetadata", function () { dur = pool[0].duration || input16.length / SR; }, { once: true });
      dur = input16.length / SR;
      document.querySelectorAll("#tchips .chip").forEach(function (c) { c.disabled = false; });
      $("dlrow").style.display = "flex"; $("tplay").disabled = false;
      active = 0; switchTo(0); $("tstatus").textContent = "done — A/B the three below"; $("run").disabled = false;
    }, 30);
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
    // redraw audiogram on theme change
    new MutationObserver(drawAg).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  });
})();
