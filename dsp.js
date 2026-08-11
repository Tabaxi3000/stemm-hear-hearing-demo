/* Client-side hearing-aid resynthesis — a JS port of the core of colab/speech_resynth.py
   (STFT filter bank + per-band straight-line gain [threshold->UCL] + WDRC attack/release).
   Faithful in concept, not bit-identical to the Python. Works in the browser and under node. */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.DSP = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var GW_A = 0.06, GW_K = 165.4, EPS = 1e-12, LOUD_REF = 1e-5; // full-scale amplitude 1.0 -> 100 dB SPL
  var log10 = Math.log10 || function (x) { return Math.log(x) / Math.LN10; };

  function frq2mm(f) { return (1 / GW_A) * log10(f / GW_K + 1); }
  function mm2frq(mm) { return GW_K * (Math.pow(10, GW_A * mm) - 1); }
  function bandEdges(flo, fhi, n) {
    var a = frq2mm(flo), b = frq2mm(fhi), e = new Array(n + 1);
    for (var i = 0; i <= n; i++) e[i] = mm2frq(a + (b - a) * i / n);
    return e;
  }
  // audiogram {freq:threshold} interpolated in log-frequency, clamped at the ends
  function threshAt(fc, agF, agV) {
    var lf = log10(fc), n = agF.length;
    if (lf <= log10(agF[0])) return agV[0];
    if (lf >= log10(agF[n - 1])) return agV[n - 1];
    for (var i = 1; i < n; i++) {
      if (lf <= log10(agF[i])) {
        var l0 = log10(agF[i - 1]), l1 = log10(agF[i]);
        return agV[i - 1] + (agV[i] - agV[i - 1]) * (lf - l0) / (l1 - l0);
      }
    }
    return agV[n - 1];
  }

  // in-place iterative radix-2 FFT; inv=true => inverse (no 1/N scaling here)
  function fft(re, im, inv) {
    var n = re.length, i, j = 0, k, m, hn = n >> 1;
    for (i = 1; i < n; i++) {                 // bit reversal
      var bit = hn;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) { var tr = re[i]; re[i] = re[j]; re[j] = tr; var ti = im[i]; im[i] = im[j]; im[j] = ti; }
    }
    for (m = 2; m <= n; m <<= 1) {
      var ang = (inv ? 2 : -2) * Math.PI / m, wr = Math.cos(ang), wi = Math.sin(ang), h = m >> 1;
      for (k = 0; k < n; k += m) {
        var cr = 1, ci = 0;
        for (j = 0; j < h; j++) {
          var a = k + j, b = a + h;
          var xr = re[b] * cr - im[b] * ci, xi = re[b] * ci + im[b] * cr;
          re[b] = re[a] - xr; im[b] = im[a] - xi; re[a] += xr; im[a] += xi;
          var ncr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = ncr;
        }
      }
    }
  }

  function hann(N) { var w = new Float64Array(N); for (var i = 0; i < N; i++) w[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / N); return w; }

  /* x: Float32/Float64 mono samples; opt: {agFreqs, agVals, mode:'static'|'wdrc',
     attackMs, releaseMs, presentSPL, nBands, headroom, uclFloor, W, H} -> Float32Array */
  function process(x, sr, opt) {
    opt = opt || {};
    var n = opt.nBands || 28, W = opt.W || 1024, H = opt.H || 256;
    var mode = opt.mode || "wdrc", presentSPL = opt.presentSPL == null ? 65 : opt.presentSPL;
    var headroom = opt.headroom == null ? 5 : opt.headroom, uclFloor = opt.uclFloor == null ? 95 : opt.uclFloor;
    var agF = opt.agFreqs, agV = opt.agVals;

    x = Float64Array.from(x);
    var rms = 0, i; for (i = 0; i < x.length; i++) rms += x[i] * x[i];
    rms = Math.sqrt(rms / x.length) + EPS;
    var g0 = Math.pow(10, (presentSPL - 100) / 20) / rms;    // present at target SPL
    for (i = 0; i < x.length; i++) x[i] *= g0;

    var flo = 100, fhi = 0.45 * sr, edges = bandEdges(flo, fhi, n);
    var fc = new Float64Array(n), thr = new Float64Array(n), slope = new Float64Array(n), off = new Float64Array(n);
    for (var b = 0; b < n; b++) {
      fc[b] = Math.sqrt(edges[b] * edges[b + 1]);
      thr[b] = threshAt(fc[b], agF, agV);
      var ucl = Math.max(uclFloor, 100 + 0.25 * thr[b]) - headroom;
      slope[b] = (ucl - thr[b]) / 100; off[b] = thr[b];       // in_lo=0 -> input 0 maps to threshold
    }
    var rx = !!opt.prescriptive, g0 = new Float64Array(n), uclA = new Float64Array(n);   // Rx: half-gain + rolloff
    var RX_CR = 2.2, RX_KNEE = 45.0;
    if (rx) for (b = 0; b < n; b++) {
      var roll = Math.max(0, Math.log2(Math.max(fc[b], 1) / 2000)) * 6.0;
      g0[b] = Math.min(42, Math.max(0, 0.5 * thr[b] - roll));
      uclA[b] = Math.max(100, 100 + 0.25 * thr[b]) - 5;
    }
    var half = W >> 1, binBand = new Int16Array(half + 1);
    for (var k = 0; k <= half; k++) {
      var f = k * sr / W, bb = -1;
      if (f >= flo && f < fhi) for (b = 0; b < n; b++) if (f >= edges[b] && f < edges[b + 1]) { bb = b; break; }
      binBand[k] = bb;
    }
    var win = hann(W), winRms = Math.sqrt(3 / 8);            // RMS of a Hann window
    var aAtk = Math.exp(-H / ((opt.attackMs == null ? 5 : opt.attackMs) * 1e-3 * sr + EPS));
    var aRel = Math.exp(-H / ((opt.releaseMs == null ? 150 : opt.releaseMs) * 1e-3 * sr + EPS));

    var out = new Float64Array(x.length + W), wsum = new Float64Array(x.length + W);
    var re = new Float64Array(W), im = new Float64Array(W);
    var gPrev = new Float64Array(n); for (b = 0; b < n; b++) gPrev[b] = 1;
    var gBand = new Float64Array(n);
    var nFrames = x.length > W ? Math.floor((x.length - W) / H) + 1 : 0;
    var dbg = opt._debug ? { sumL: new Float64Array(n), sumG: new Float64Array(n), fc: fc, thr: thr } : null;

    for (var fr = 0; fr < nFrames; fr++) {
      var s0 = fr * H;
      for (i = 0; i < W; i++) { re[i] = x[s0 + i] * win[i]; im[i] = 0; }
      fft(re, im, false);
      for (b = 0; b < n; b++) {
        var sq = 0;
        // gathered below in the bin loop instead (cheaper): placeholder
        gBand[b] = 0;
      }
      // band energy
      var sums = new Float64Array(n);
      for (k = 0; k <= half; k++) {
        var band = binBand[k]; if (band < 0) continue;
        var p = re[k] * re[k] + im[k] * im[k];
        sums[band] += (k === 0 || k === half) ? p : 2 * p;   // account for negative-frequency twin
      }
      for (b = 0; b < n; b++) {
        var env = Math.sqrt(sums[b]) / W / winRms;             // ~ time-domain RMS of the band
        var L = 20 * log10(env / LOUD_REF + EPS);
        var Lout = rx ? Math.min(L + Math.max(0, g0[b] - Math.max(0, L - RX_KNEE) * (1 - 1 / RX_CR)), uclA[b])
                      : slope[b] * L + off[b];
        var g = Math.pow(10, (Lout - L) / 20);
        if (mode === "wdrc") { var a = g < gPrev[b] ? aAtk : aRel; g = a * gPrev[b] + (1 - a) * g; }
        gPrev[b] = g; gBand[b] = g;
        if (dbg) { dbg.sumL[b] += L; dbg.sumG[b] += 20 * log10(g + EPS); }
      }
      // apply per-band gain, rebuild conjugate-symmetric spectrum
      for (k = 0; k <= half; k++) {
        var bd = binBand[k], gg = bd < 0 ? 1 : gBand[bd];
        re[k] *= gg; im[k] *= gg;
        if (k > 0 && k < half) { re[W - k] = re[k]; im[W - k] = -im[k]; }
      }
      fft(re, im, true);
      for (i = 0; i < W; i++) { var wv = win[i]; out[s0 + i] += (re[i] / W) * wv; wsum[s0 + i] += wv * wv; }
    }
    var y = new Float32Array(x.length);
    for (i = 0; i < x.length; i++) y[i] = wsum[i] > EPS ? out[i] / wsum[i] : 0;
    if (dbg) {
      dbg.meanL = []; dbg.meanG = [];
      for (b = 0; b < n; b++) { dbg.meanL.push(dbg.sumL[b] / (nFrames || 1)); dbg.meanG.push(dbg.sumG[b] / (nFrames || 1)); }
      dbg.y = y; return dbg;
    }
    return y;
  }

  return { frq2mm: frq2mm, mm2frq: mm2frq, bandEdges: bandEdges, threshAt: threshAt, fft: fft, process: process };
});
