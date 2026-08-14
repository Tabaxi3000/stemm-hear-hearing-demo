"""Build-time helpers for the gallery make_*.py scripts (NOT shipped to the browser).

The slow part of a gallery rebuild is the hearing-aid metrics (HASPI/HASQI/HAAQI run an auditory
model, ~8 s each), so re-running after a small tweak used to recompute all ~50 of them (~13 min).

`metrics_cached` / `poorer_cached` memoise the metric dict keyed by the *exact rendered waveform*
(+ audiogram + flags), so a re-run whose audio is unchanged loads the numbers instantly. Keying on
the waveform bytes means the cache can never go stale relative to the audio it scores, and the whole
cache is namespaced by a hash of the metric code (metrics.py + the HASPI package) so any change to
the metric implementation busts it automatically.

Also provides a tiny `bar()` progress meter (tqdm if available, else a stderr fallback).
"""
import os
import sys
import json
import time
import hashlib
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_HERE, ".build_cache")
_CACHE_PATH = os.path.join(_CACHE_DIR, "metrics.json")


def _code_version():
    """Hash the metric code so any change to how metrics are computed invalidates the cache."""
    h = hashlib.sha1()
    for rel in ("metrics.py", "haspi_vendor/eb.py", "haspi_vendor/ebm.py", "haspi_vendor/ip.py",
                "haspi_vendor/haspi.py", "haspi_vendor/hasqi.py", "haspi_vendor/haaqi.py",
                "sii.py", "stoi_vendor.py"):
        p = os.path.join(_HERE, rel)
        if os.path.exists(p):
            h.update(open(p, "rb").read())
    return h.hexdigest()[:12]


_VER = _code_version()
_cache = {}
try:
    _cache = json.load(open(_CACHE_PATH)).get(_VER, {})   # namespaced by metric-code version
except Exception:
    _cache = {}
_stats = {"hit": 0, "miss": 0}


def _key(*parts):
    h = hashlib.sha1()
    for p in parts:
        if isinstance(p, np.ndarray):
            h.update(np.ascontiguousarray(p, dtype=np.float32).tobytes())
        else:
            h.update(repr(p).encode())
    return h.hexdigest()


def metrics_cached(fn, aided, clean, sr, audiogram, full=False, music=False):
    """Cached metrics.all_metrics: keyed by the aided + clean waveforms, audiogram and flags."""
    k = _key(aided, clean, sr, sorted(audiogram.items()), full, music)
    if k in _cache:
        _stats["hit"] += 1
        return dict(_cache[k])
    _stats["miss"] += 1
    m = fn(aided, clean, sr, audiogram, full=full, music=music)
    _cache[k] = m
    return m


def poorer_cached(fn, stereo, clean, sr, ag_l, ag_r, full=False, music=False):
    """Cached metrics.poorer_ear_metrics (binaural), keyed by the stereo + clean waveforms + audiograms."""
    k = _key(stereo, clean, sr, sorted(ag_l.items()), sorted(ag_r.items()), full, music)
    if k in _cache:
        _stats["hit"] += 1
        return dict(_cache[k])
    _stats["miss"] += 1
    m = fn(stereo, clean, sr, ag_l, ag_r, full=full, music=music)
    _cache[k] = m
    return m


def save():
    """Persist the cache (merging with other code versions already on disk) + print a summary."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    disk = {}
    try:
        disk = json.load(open(_CACHE_PATH))
    except Exception:
        disk = {}
    disk[_VER] = _cache
    json.dump(disk, open(_CACHE_PATH, "w"))
    print("  [buildkit] metrics cache: %d loaded, %d computed" % (_stats["hit"], _stats["miss"]))


# ---- progress bar -------------------------------------------------------------------------------
def bar(total, desc=""):
    try:
        from tqdm import tqdm
        return tqdm(total=total, desc=desc, ncols=72, file=sys.stderr)
    except Exception:
        return _Bar(total, desc)


class _Bar:
    def __init__(self, total, desc):
        self.total, self.n, self.desc, self.t0 = total, 0, desc, time.time()

    def update(self, k=1):
        self.n += k
        sys.stderr.write("\r  %s %d/%d  (%.0fs)" % (self.desc, self.n, self.total, time.time() - self.t0))
        sys.stderr.flush()

    def close(self):
        sys.stderr.write("\n")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
