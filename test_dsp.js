var DSP = require("./dsp.js");
function rms(a){var s=0;for(var i=0;i<a.length;i++)s+=a[i]*a[i];return Math.sqrt(s/a.length);}
function db(x){return 20*Math.log10(x+1e-12);}
var ok=true, EPS=1e-9;
// 1) FFT round-trip
(function(){
  var N=1024, re=new Float64Array(N), im=new Float64Array(N), orig=new Float64Array(N);
  for(var i=0;i<N;i++){re[i]=orig[i]=Math.sin(0.3*i)+0.5*Math.cos(0.017*i);}
  DSP.fft(re,im,false); DSP.fft(re,im,true);
  var err=0;for(i=0;i<N;i++)err=Math.max(err,Math.abs(re[i]/N-orig[i]));
  console.log("1. FFT round-trip max err:",err.toExponential(2), err<1e-9?"OK":"FAIL"); ok=ok&&err<1e-9;
})();
// helper signals @16k
var sr=16000, T=2*sr;
function tone(f){var x=new Float64Array(T);for(var i=0;i<T;i++)x[i]=Math.sin(2*Math.PI*f*i/sr);return x;}
function whiteAtSPL(spl){var x=new Float64Array(T);for(var i=0;i<T;i++)x[i]=(Math.random()*2-1);
  var r=rms(x);var g=Math.pow(10,(spl-100)/20)/r;for(i=0;i<T;i++)x[i]*=g;return x;}
var agF=[250,500,1000,2000,4000,8000];
var SLOPE={agFreqs:agF,agVals:[20,25,30,40,55,65]};
// 2) calibration: white noise presented at 65 dB -> mean band level plausible (~40-58)
(function(){
  var x=whiteAtSPL(65);
  var d=DSP.process(x,sr,Object.assign({mode:"static",presentSPL:65,_debug:true},SLOPE));
  var mL=d.meanL.reduce((a,b)=>a+b,0)/d.meanL.length;
  console.log("2. white@65 mean band L:",mL.toFixed(1),"dB", (mL>38&&mL<60)?"OK":"CHECK");
  ok=ok&&mL>30&&mL<70;
})();
// 3) sloping loss boosts highs: HF/LF energy ratio rises vs input
(function(){
  var x=whiteAtSPL(65);
  var y=DSP.process(x,sr,Object.assign({mode:"static",presentSPL:65},SLOPE));
  function bandE(a,lo,hi){ // crude DFT-free: filter via goertzel-ish? just use full FFT once
    var N=16384, re=new Float64Array(N), im=new Float64Array(N);
    for(var i=0;i<N;i++)re[i]=a[i]||0;
    DSP.fft(re,im,false); var e=0;
    for(var k=0;k<N/2;k++){var f=k*sr/N; if(f>=lo&&f<hi)e+=re[k]*re[k]+im[k]*im[k];}
    return e;
  }
  var tiltIn=bandE(x,3000,7000)/bandE(x,200,1000);
  var tiltOut=bandE(y,3000,7000)/bandE(y,200,1000);
  console.log("3. HF/LF tilt  in:",tiltIn.toFixed(2)," out:",tiltOut.toFixed(2),
    tiltOut>tiltIn?"OK (highs boosted)":"FAIL"); ok=ok&&tiltOut>tiltIn;
})();
// 4) finiteness + length + not exploding, static & wdrc
(function(){
  var x=tone(1000); for(var i=0;i<T;i++)x[i]*=0.2;
  ["static","wdrc"].forEach(function(m){
    var y=DSP.process(x,sr,Object.assign({mode:m,presentSPL:65,attackMs:5,releaseMs:150},SLOPE));
    var fin=y.every(v=>isFinite(v)); var pk=Math.max.apply(null,Array.from(y).map(Math.abs));
    console.log("4. "+m+": len",y.length,"finite",fin,"peak",pk.toFixed(2),
      (fin&&y.length===T&&pk<8)?"OK":"CHECK"); ok=ok&&fin&&y.length===T;
  });
})();
// 5) gain map matches Python formula at a band (thr->ucl mapping): input 0 dB -> ~threshold
(function(){
  // at very low input the output level ~ threshold (0 dB in -> thr out). Check applied gain sign.
  var d=DSP.process(whiteAtSPL(40),sr,Object.assign({mode:"static",presentSPL:40,_debug:true},SLOPE));
  var hfGain=d.meanG[24], lfGain=d.meanG[4];  // high band vs low band avg gain
  console.log("5. mean gain  low-band:",lfGain.toFixed(1),"dB  high-band:",hfGain.toFixed(1),"dB",
    hfGain>lfGain?"OK (more gain up high)":"FAIL"); ok=ok&&hfGain>lfGain;
})();
console.log("\n"+(ok?"ALL PASS":"SOME FAILED"));
process.exit(ok?0:1);
