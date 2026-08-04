# -*- coding: utf-8 -*-
"""
Advanced Arabic Player - Utility helpers
=========================================
Pure text/formatting/ranking helpers plus poster-cache download helpers.

Deliberately excluded from this module: anything that is mutated via a
bare `global` statement from inside plugin.py's Screen classes (the live
playback position tracker and the local proxy hit/byte counters). Those
stay in plugin.py itself so the `global NAME` idiom used throughout
AdvancedArabicPlayerSimplePlayer / LocalProxyHandler keeps working exactly
as before without having to rewrite every read/write site to go through
a module attribute. See plugin.py's module docstring note for details.
"""

import os
import re
import hashlib
import urllib.request as urllib2

from extractors import get_site_metadata

SAFE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

_POSTER_CACHE_DIR = "/tmp/ap_cache"


# ─── Site label helpers ──────────────────────────────────────────────────────

def _site_label(site):
    meta = get_site_metadata(site)
    return meta.get("title", str(site or "").capitalize())


def _site_tagline(site):
    meta = get_site_metadata(site)
    return meta.get("tagline", "")


def _site_search_item(site):
    return {
        "title": "بحث داخل {}".format(_site_label(site)),
        "_action": "search_site",
        "_site": site,
        "type": "tool",
        "plot": "ابحث داخل {} فقط بدون خلط النتائج مع باقي المصادر.".format(_site_label(site)),
    }


# ─── Query / title normalization ─────────────────────────────────────────────

def _normalize_query(text):
    text = (text or "").strip().lower()
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي")
    # Keep word boundaries: map anything that isn't alnum/space to a space
    # rather than deleting it, so multi-word matching and substring checks
    # work on actual words instead of accidentally-glued tokens.
    text = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_arabic_from_english_title(title):
    if not title:
        return title
    stripped = title.replace(" ", "")
    if not stripped:
        return title
    ar_count = sum(1 for c in stripped if "\u0600" <= c <= "\u06ff")
    if ar_count / len(stripped) >= 0.30:
        return title
    cleaned = re.sub(r"[\u0600-\u06ff]+", " ", title)
    cleaned = re.sub(r"[\s|\-–_]+$", "", cleaned)
    cleaned = re.sub(r"^[\s|\-–_]+", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -|_")
    return cleaned if cleaned.strip() else title


def _clean_title_for_tmdb(title):
    if not title: return ""
    junk = [
        u"مترجم", u"اون لاين", u"بجودة", u"عالية", u"كامل", u"تحميل", u"مشاهدة", u"فيلم", u"مسلسل",
        u"انمي", u"كرتون", u"حصري", u"شاشه", u"كامله", u"نسخة", u"اصلية", u"bluray", u"web-dl", u"hdtv", u"720p", u"1080p", u"4k",
        u"توب سينما", u"عرب سيد", u"فاصل اعلاني", u"faselhd",
    ]
    title = title.lower()
    for word in junk:
        title = title.replace(word, "")
    title = re.sub(r'\s+\d{4}\s*$', '', title)
    return re.sub(r'\s+', ' ', title).strip()


# ─── Display text wrapping ────────────────────────────────────────────────────

def _wrap_ui_text(text, width=40, max_lines=2, fallback=""):
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return fallback
    words = text.split(" ")
    lines = []
    current = ""

    for word in words:
        candidate = word if not current else "{} {}".format(current, word)
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            if len(lines) >= max_lines:
                break
        current = word

    if len(lines) < max_lines and current:
        lines.append(current)
    if not lines:
        lines = [text[:width]]

    consumed = " ".join(lines)
    if len(consumed) < len(text):
        lines[-1] = lines[-1].rstrip(" .،") + "..."
    return "\n".join(lines[:max_lines])


def _single_line_text(text, width=54, fallback=""):
    return _wrap_ui_text(text, width=width, max_lines=1, fallback=fallback)


def _search_scope_label(scope):
    if scope == "all":
        return "كل المصادر: EgyDead / Akoam / Arabseed / Wecima / TopCinemaa"
    return "المصدر الحالي: {}".format(_site_label(scope))


# ─── Search result / list ranking ────────────────────────────────────────────

def _dedupe_items(items):
    unique = []
    seen = set()
    for item in items or []:
        key = item.get("url") or item.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _rank_search_items(items, query):
    q = _normalize_query(query)
    q_words = [w for w in q.split() if len(w) >= 2] if q else []

    strong   = []
    weak     = []
    no_match = []

    for item in _dedupe_items(items):
        title  = item.get("title", "")
        ntitle = _normalize_query(title)
        rank   = 9

        if not q:
            rank = 5
        elif ntitle == q:
            rank = 0
        elif ntitle.startswith(q):
            rank = 1
        elif q in ntitle:
            rank = 2
        elif q_words:
            matched_words = sum(1 for w in q_words if w in ntitle)
            if matched_words == len(q_words):
                rank = 3
            elif matched_words >= max(1, len(q_words) * 2 // 3):
                rank = 4
            elif matched_words > 0:
                rank = 5

        entry = (rank, title.lower(), item)
        if rank <= 3:
            strong.append(entry)
        elif rank <= 5:
            weak.append(entry)
        else:
            no_match.append(item)

    strong.sort(key=lambda r: (r[0], r[1]))
    weak.sort(key=lambda r: (r[0], r[1]))

    result = [r[2] for r in strong]

    if len(result) < 3:
        result += [r[2] for r in weak[:max(0, 5 - len(result))]]

    if not result and weak:
        result = [r[2] for r in weak]

    return result


def _quality_rank(server_name):
    text = (server_name or "").lower()
    if "2160" in text or "4k" in text:
        return 0
    if "1080" in text:
        return 1
    if "720" in text or "hd" in text:
        return 2
    if "480" in text:
        return 3
    if "360" in text:
        return 4
    return 9


def _sort_servers(servers):
    return sorted(servers or [], key=lambda s: (_quality_rank(s.get("name", "")), s.get("name", "").lower()))


def _decorate_item_title(item, site=None):
    action = item.get("_action", "")

    if action == "separator" or item.get("type") == "separator":
        return "─── {} ───".format(item.get("title", ""))

    title = _strip_arabic_from_english_title((item.get("title") or "---").strip())
    item_type = item.get("type", action)

    if action.startswith("site_"):
        return title

    if item_type == "category" and item.get("url") and "release-year" in item.get("url", ""):
        return title

    if item_type == "movie":
        prefix = "[فيلم]"
    elif item_type == "series":
        prefix = "[مسلسل]"
    elif item_type == "season":
        prefix = "[موسم]"
    elif item_type == "episode":
        prefix = "[حلقة]"
    elif item_type == "category":
        return title
    else:
        prefix = "•"

    item_site = item.get("_site") or site

    if item_type in ("movie", "series", "episode", "season"):
        return title

    if item_site and item_type == "tool":
        return "{} [{}] {}".format(prefix, _site_label(item_site), title)

    return "{} {}".format(prefix, title)


# ─── Plot text selection ─────────────────────────────────────────────────────

def _display_plot_text(value):
    text = re.sub(r"\s+", " ", value or "").strip()
    return text or "القصة غير متوفرة حالياً لهذا العنصر."


def _pick_plot_text_with_source(*sources):
    best = ""
    best_source = ""
    for source in sources:
        if isinstance(source, dict):
            candidates = [
                ("plot", source.get("plot")),
                ("overview", source.get("overview")),
                ("desc", source.get("desc")),
                ("tmdb.plot", (source.get("_tmdb") or {}).get("plot")),
            ]
        else:
            candidates = [("value", source)]
        for label, candidate in candidates:
            text = _display_plot_text(candidate)
            if text == "القصة غير متوفرة حالياً لهذا العنصر.":
                continue
            if len(text) > len(best):
                best = text
                best_source = label
    return best or "القصة غير متوفرة حالياً لهذا العنصر.", best_source or "none"


def _pick_plot_text(*sources):
    return _pick_plot_text_with_source(*sources)[0]


# ─── Poster cache helpers ─────────────────────────────────────────────────────

def _poster_cache_path(url):
    if not url: return None
    try:
        if not os.path.isdir(_POSTER_CACHE_DIR):
            os.makedirs(_POSTER_CACHE_DIR)
    except Exception: pass
    url_hash = hashlib.md5(url.encode("utf-8", "ignore")).hexdigest()
    return os.path.join(_POSTER_CACHE_DIR, "{}.jpg".format(url_hash))


def _normalize_poster_url(url):
    if not url:
        return url
    if url.startswith("//"):
        url = "https:" + url
    try:
        from urllib.parse import urlparse, quote, unquote, urlunparse
        p = list(urlparse(url))
        p[2] = quote(unquote(p[2]))
        p[4] = quote(unquote(p[4]))
        return urlunparse(p)
    except Exception:
        return url


def _is_poster_cached(url):
    path = _poster_cache_path(url)
    return path and os.path.exists(path)


def _get_cached_poster(url):
    path = _poster_cache_path(url)
    if path and os.path.exists(path):
        return path
    return None


def _fetch_poster_bytes(url, referer, timeout=7):
    req = urllib2.Request(url, headers={"User-Agent": SAFE_UA, "Referer": referer})
    data = urllib2.urlopen(req, timeout=timeout).read()
    looks_like_webp = url.lower().split("?", 1)[0].endswith(".webp") or data[:4] == b"RIFF"
    if not looks_like_webp:
        return data
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data)).convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG")
        return out.getvalue()
    except Exception:
        pass
    try:
        alt_url = re.sub(r'\.webp(\?.*)?$', lambda m: ".jpg" + (m.group(1) or ""), url, flags=re.I)
        if alt_url != url:
            alt_req = urllib2.Request(alt_url, headers={"User-Agent": SAFE_UA, "Referer": referer})
            alt_data = urllib2.urlopen(alt_req, timeout=timeout).read()
            if alt_data:
                return alt_data
    except Exception:
        pass
    return data
