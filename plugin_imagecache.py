# -*- coding: utf-8 -*-
"""
Advanced Arabic Player - async poster/artwork cache
=======================================================
Ported from westy4ever's XtreamNew plugin (imagecache.py), renamed to fit
this project. No business-logic dependency - pure disk cache + a bounded
background-download worker pool.

Design (unchanged from the source): GUI code calls getCachedImage(url) to
check the local cache instantly (no network call from the Enigma2 UI
thread), and requestImageAsync()/requestImageAsyncPriority() to queue a
background download if it's not cached yet. There is no completion
callback - callers are expected to poll getCachedImage() again on a
short timer (see AdvancedArabicPlayerHome._posterPollTimer in plugin.py),
which is the same pattern the source plugin's carousel screens use.
"""

from __future__ import absolute_import, print_function

import os
import time
import hashlib
import threading

try:
    import urllib2 as urllib_request
except Exception:
    import urllib.request as urllib_request

try:
    from urlparse import urlparse
except Exception:
    from urllib.parse import urlparse


CACHE_BASE_HDD = "/media/hdd/AdvancedArabicPlayer/cache"
CACHE_BASE_TMP = "/tmp/AdvancedArabicPlayer/cache"
CACHE_IMAGES_DIRNAME = "images"
CACHE_MAX_AGE = 60 * 60 * 24 * 365 * 100   # effectively no expiry


def ensureDir(path):
    try:
        if path and not os.path.exists(path):
            os.makedirs(path)
    except Exception:
        pass


def getCacheBase():
    base = CACHE_BASE_HDD
    if not os.path.exists("/media/hdd"):
        base = CACHE_BASE_TMP
    ensureDir(base)
    return base


def getImagesDir():
    p = os.path.join(getCacheBase(), CACHE_IMAGES_DIRNAME)
    ensureDir(p)
    return p


def guessExtFromUrl(url):
    try:
        low = (urlparse(url).path or "").lower()
        if low.endswith(".png"):
            return ".png"
        if low.endswith(".webp"):
            return ".webp"
        if low.endswith(".jpeg"):
            return ".jpg"
        if low.endswith(".jpg"):
            return ".jpg"
    except Exception:
        pass
    return ".jpg"


def buildCachePath(url, target_size=None):
    key = url if not target_size else "%s|%dx%d" % (url, target_size[0], target_size[1])
    try:
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    except Exception:
        digest = hashlib.md5(str(key).encode("utf-8")).hexdigest()
    return os.path.join(getImagesDir(), digest + guessExtFromUrl(url))


def touch(path):
    try:
        now = time.time()
        os.utime(path, (now, now))
    except Exception:
        pass


def isFresh(path):
    try:
        if not os.path.exists(path):
            return False
        age = time.time() - os.path.getmtime(path)
        return age < CACHE_MAX_AGE
    except Exception:
        return False


def writeFileAtomic(path, data):
    tmp = path + ".tmp"
    try:
        f = open(tmp, "wb")
        f.write(data)
        f.close()
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        os.rename(tmp, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


def downloadUrl(url, timeout=8):
    try:
        req = urllib_request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        response = urllib_request.urlopen(req, timeout=timeout)
        data = response.read()
        if data:
            return data
    except Exception:
        return None
    return None


def resizeCover(data, target_size):
    """Resize+crop image bytes to exactly fill target_size (cover fit,
    aspect-preserving, center-cropped) so the cached file already matches
    the display widget's box pixel-for-pixel. Enigma2's Pixmap widgets
    don't reliably aspect-scale a mismatched-size image into a fixed box
    on their own - without this, posters can end up stretched or
    effectively "zoomed in" depending on the receiver's image/skin
    engine. Falls back to the original bytes if PIL isn't available or
    the image can't be decoded.
    """
    if not target_size:
        return data
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        try:
            from PIL import ImageOps
            fitted = ImageOps.fit(img, target_size, Image.LANCZOS)
        except Exception:
            fitted = img.resize(target_size, Image.LANCZOS)
        out = io.BytesIO()
        fitted.save(out, format="JPEG", quality=88)
        return out.getvalue()
    except Exception:
        return data


# ─── Non-blocking image cache ────────────────────────────────────────────────
# GUI code checks the local cache instantly and requests downloads in a
# background thread. No network call is made from the Enigma2 UI thread.

_ASYNC_LOCK = threading.Lock()
_ASYNC_IN_PROGRESS = {}
_ASYNC_STATS_TOTAL = 0
_ASYNC_STATS_DONE = 0
_ASYNC_QUEUE = []
_ASYNC_WORKERS = 0
_ASYNC_MAX_WORKERS = 5
_ASYNC_CANCEL_TOKEN = 0


def getCachedImage(url, target_size=None):
    """Return the local cached path only if it already exists/fresh."""
    if not url:
        return ""
    try:
        if not isinstance(url, str):
            try:
                url = url.decode("utf-8", "ignore")
            except Exception:
                url = str(url)
    except Exception:
        pass
    try:
        cache_path = buildCachePath(url, target_size)
        if isFresh(cache_path):
            touch(cache_path)
            return cache_path
    except Exception:
        pass
    return ""


def _mark_async_done(cache_path):
    global _ASYNC_STATS_DONE
    try:
        with _ASYNC_LOCK:
            existed = bool(_ASYNC_IN_PROGRESS.pop(cache_path, None))
            if existed:
                _ASYNC_STATS_DONE += 1
    except Exception:
        pass


def _async_worker_loop():
    global _ASYNC_WORKERS
    try:
        worker_token = int(_ASYNC_CANCEL_TOKEN)
    except Exception:
        worker_token = 0
    try:
        while True:
            item = None
            try:
                with _ASYNC_LOCK:
                    if _ASYNC_QUEUE:
                        item = _ASYNC_QUEUE.pop(0)
                    else:
                        _ASYNC_WORKERS = max(0, int(_ASYNC_WORKERS) - 1)
                        return
            except Exception:
                item = None
            if not item:
                return
            try:
                if int(_ASYNC_CANCEL_TOKEN) != int(worker_token):
                    _mark_async_done(item[1])
                    continue
            except Exception:
                pass
            url, cache_path, target_size = item
            try:
                data = downloadUrl(url, timeout=8)
                try:
                    if int(_ASYNC_CANCEL_TOKEN) != int(worker_token):
                        _mark_async_done(cache_path)
                        continue
                except Exception:
                    pass
                if data:
                    if target_size:
                        data = resizeCover(data, target_size)
                    writeFileAtomic(cache_path, data)
            except Exception:
                pass
            _mark_async_done(cache_path)
    except Exception:
        try:
            with _ASYNC_LOCK:
                _ASYNC_WORKERS = max(0, int(_ASYNC_WORKERS) - 1)
        except Exception:
            pass


def _ensure_async_workers():
    global _ASYNC_WORKERS
    need = False
    try:
        with _ASYNC_LOCK:
            need = bool(_ASYNC_QUEUE) and int(_ASYNC_WORKERS) < int(_ASYNC_MAX_WORKERS)
            if need:
                _ASYNC_WORKERS += 1
    except Exception:
        need = False
    if not need:
        return
    try:
        t = threading.Thread(target=_async_worker_loop)
        t.daemon = True
        t.start()
    except Exception:
        try:
            with _ASYNC_LOCK:
                _ASYNC_WORKERS = max(0, int(_ASYNC_WORKERS) - 1)
        except Exception:
            pass


def cancelAsyncImages():
    """Stop pending artwork downloads for the screen that is closing.

    Running urllib calls cannot be interrupted safely, but this clears the
    queue immediately and makes workers ignore their current result if it
    belongs to a stale token.
    """
    global _ASYNC_STATS_TOTAL, _ASYNC_STATS_DONE, _ASYNC_CANCEL_TOKEN
    try:
        with _ASYNC_LOCK:
            _ASYNC_CANCEL_TOKEN += 1
            _ASYNC_QUEUE[:] = []
            _ASYNC_IN_PROGRESS.clear()
            _ASYNC_STATS_TOTAL = 0
            _ASYNC_STATS_DONE = 0
    except Exception:
        pass


def requestImageAsync(url, target_size=None):
    """Queue a background download if needed; return cached path if ready."""
    global _ASYNC_STATS_TOTAL
    if not url:
        return ""
    ready = getCachedImage(url, target_size)
    if ready:
        return ready
    try:
        if not isinstance(url, str):
            try:
                url = url.decode("utf-8", "ignore")
            except Exception:
                url = str(url)
        cache_path = buildCachePath(url, target_size)
    except Exception:
        return ""

    queued = False
    try:
        with _ASYNC_LOCK:
            if not _ASYNC_IN_PROGRESS.get(cache_path):
                _ASYNC_IN_PROGRESS[cache_path] = 1
                _ASYNC_QUEUE.append((url, cache_path, target_size))
                queued = True
                _ASYNC_STATS_TOTAL += 1
    except Exception:
        queued = False
    if queued:
        _ensure_async_workers()
    return ""


def requestImageAsyncPriority(url, target_size=None):
    """Queue a background download at the front for currently visible artwork.

    Keeps full-page warmup running in the background, but gives the
    selected/visible poster priority so navigation doesn't wait behind
    everything else already queued.
    """
    global _ASYNC_STATS_TOTAL
    if not url:
        return ""
    ready = getCachedImage(url, target_size)
    if ready:
        return ready
    try:
        if not isinstance(url, str):
            try:
                url = url.decode("utf-8", "ignore")
            except Exception:
                url = str(url)
        cache_path = buildCachePath(url, target_size)
    except Exception:
        return ""
    queued = False
    try:
        with _ASYNC_LOCK:
            if not _ASYNC_IN_PROGRESS.get(cache_path):
                _ASYNC_IN_PROGRESS[cache_path] = 1
                _ASYNC_QUEUE.insert(0, (url, cache_path, target_size))
                queued = True
                _ASYNC_STATS_TOTAL += 1
    except Exception:
        queued = False
    if queued:
        _ensure_async_workers()
    return ""


def hasPendingAsyncImages():
    try:
        return bool(_ASYNC_IN_PROGRESS)
    except Exception:
        return False


def getAsyncImageStats():
    try:
        pending = len(_ASYNC_IN_PROGRESS)
    except Exception:
        pending = 0
    try:
        total = int(_ASYNC_STATS_TOTAL)
        done = int(_ASYNC_STATS_DONE)
    except Exception:
        total = done = 0
    return {"done": done, "total": total, "pending": pending}
