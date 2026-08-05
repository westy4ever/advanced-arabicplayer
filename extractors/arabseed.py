# -*- coding: utf-8 -*-
"""
Arabseed extractor - Multi-domain support
Inherits from BaseExtractor.
"""

import base64
import html as html_lib
import json
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from .base import BaseExtractor, fetch, log, urljoin, clear_cookies

QUALITY_ORDER = {"1080": 0, "720": 1, "480": 2}
BLOCKED_HOSTS = ("vidara.to", "bysezejataos.com")

# Known domains to try, ordered by preference
_KNOWN_DOMAINS = [
    "https://m.arsd.bid/",
    "https://arabseed.loan/",
    "https://arabseed.rocks/",
    "https://arabseed.in/",
]

# Class name fragments that identify movie/post blocks
_BLOCK_CLASS_FRAGMENTS = (
    "movie__block", "recent--block", "post--block",
    "movie-block", "post-block", "movie-item", "post-item",
    "film-item", "movieItem", "postItem", "filmItem",
    "Movies--Box", "SmallBox", "GridItem", "movie-card",
    "post-card", "card-item", "movie-box", "post-box",
    "Thumb--GridItem", "GridItem", "poster", "card",
)


class ArabseedExtractor(BaseExtractor):
    """Extractor for Arabseed - supports multiple domains"""

    MAIN_URL = _KNOWN_DOMAINS[0]

    def __init__(self):
        super(ArabseedExtractor, self).__init__()
        self.main_url = self.MAIN_URL
        self._resolved_base = None  # Will be set dynamically by _get_base()

    def _get_base(self):
        """Probe known domains and return the first working one."""
        if self._resolved_base:
            return self._resolved_base

        for domain in _KNOWN_DOMAINS:
            try:
                log("ArabSeed: Probing domain {}".format(domain))
                html, final_url = fetch(domain, referer=domain)
                if not html:
                    continue
                
                # Check for Cloudflare or dead redirects
                lower_html = html.lower()
                if "just a moment" in lower_html or "cf-chl" in lower_html:
                    log("ArabSeed: Domain {} blocked by Cloudflare".format(domain))
                    continue
                
                # Check if it redirected away to a non-arabseed domain
                final_host = re.search(r'https?://([^/]+)', final_url or "")
                if final_host and not any(d in final_host.group(1) for d in ("arabseed", "arsd")):
                    log("ArabSeed: Domain {} redirected to unknown host {}".format(domain, final_host.group(1)))
                    continue

                # If it passes all checks, use this domain
                self._resolved_base = domain
                self.main_url = domain
                log("ArabSeed: Selected working domain: {}".format(domain))
                return self._resolved_base
            except Exception as e:
                log("ArabSeed: Domain {} failed with error: {}".format(domain, e))
                continue

        # Fallback if all fail
        log("ArabSeed: All domains failed, falling back to {}".format(self.MAIN_URL))
        self._resolved_base = self.MAIN_URL
        return self._resolved_base

    def _full_url(self, path):
        if not path:
            return ""
        path = html_lib.unescape(path.strip()).replace("\\/", "/").replace("&amp;", "&")
        
        if path.startswith("http"):
            # If the URL points to a known Arabseed domain, rewrite it to the
            # currently active domain to avoid hitting a dead link again.
            current_base = self._get_base()
            for d in _KNOWN_DOMAINS:
                if path.startswith(d) and d != current_base:
                    path = current_base + path[len(d):]
                    break
            return path
            
        if path.startswith("//"):
            return "https:" + path
        return urljoin(self._get_base(), path)

    def _clean_title(self, title):
        title = html_lib.unescape(title or "")
        for word in ("مشاهدة", "فيلم", "مسلسل", "تحميل", "اون لاين", "أون لاين",
                     "مترجم", "مترجمة", "مدبلج", "مدبلجة", "بجودة", "عالية"):
            title = title.replace(word, "")
        title = re.sub(r'\s*[-|]\s*arabseed.*$', '', title, flags=re.I)
        title = re.sub(r'\s*[-|]\s*عرب\s*سيد.*$', '', title, flags=re.I)
        return re.sub(r'\s+', ' ', title).strip(" -|")

    def _extract_first(self, patterns, text):
        for pattern in patterns:
            match = re.search(pattern, text or "", re.S)
            if match:
                return match.group(1).strip()
        return ""

    def _decode_hidden_url(self, url):
        if not (url or "").strip():
            return ""
        url = (url or "").replace("\\/", "/").replace("&amp;", "&").strip()
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http"):
            url = urljoin(self._get_base(), url)
        for key in ("url", "id"):
            marker = key + "="
            if marker not in url:
                continue
            raw = url.split(marker, 1)[1].split("&", 1)[0]
            try:
                raw += "=" * ((4 - len(raw) % 4) % 4)
                decoded = base64.b64decode(raw).decode("utf-8")
                if decoded.startswith("http"):
                    return decoded
            except Exception:
                pass
        if url.rstrip("/") == self.MAIN_URL.rstrip("/"):
            return ""
        return url

    def _determine_item_type(self, link, title):
        link_lower = link.lower()
        if "-season-" in link_lower or "-episode-" in link_lower or "/episode/" in link_lower:
            return "episode"
        if "/series-" in link_lower or "/serie/" in link_lower or "/series/" in link_lower or "/selary/" in link_lower:
            return "series"
        if "مسلسل" in (title or "") or "الحلقة" in (title or "") or "حلقة" in (title or ""):
            return "series"
        return "movie"

    def _extract_item_from_block(self, block_html):
        """Extract a single item dict from an HTML block."""
        href_m = re.search(r'href=["\']([^"\']+)["\']', block_html, re.IGNORECASE)
        if not href_m:
            return None
        link = self._full_url(href_m.group(1))
        if not link or "/category/" in link or "/page/" in link or "/tag/" in link:
            return None
        if link.startswith("#") or link.startswith("javascript:"):
            return None

        title = ""
        title_m = (
            re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', block_html, re.IGNORECASE) or
            re.search(r'title=["\']([^"\']+)["\']', block_html, re.IGNORECASE) or
            re.search(r'<(?:h[1-4])[^>]*>([^<]+)</', block_html, re.IGNORECASE) or
            re.search(r'<(?:span|p|div)[^>]*class=["\'][^"\']*(?:title|name)[^"\']*["\'][^>]*>([^<]+)</', block_html, re.IGNORECASE)
        )
        if title_m:
            title = self._clean_title(title_m.group(1))
        if not title or len(title) < 2:
            return None

        img = ""
        img_m = re.search(
            r'<img[^>]+(?:data-src|data-lazy-src|data-original|src)=["\']([^"\']+)["\']',
            block_html, re.IGNORECASE
        )
        if img_m:
            img = self._full_url(img_m.group(1))
            if any(x in img.lower() for x in ("logo", "placeholder", "loading.gif", "lazy_load", "data:image")):
                img = ""

        return {
            "title": title,
            "url": link,
            "poster": img,
            "type": self._determine_item_type(link, title),
            "_action": "details",
        }

    def _extract_items_from_html(self, html):
        """Extract movie/series items using 4 strategies."""
        if not html:
            return []

        items = []
        seen = set()
        class_pattern = "|".join(re.escape(f) for f in _BLOCK_CLASS_FRAGMENTS)

        # === Strategy 1: <a> tags with movie-related classes ===
        a_block_re = re.compile(
            r'<a\s[^>]*class=["\'][^"\']*(?:' + class_pattern + r')[^"\']*["\'][^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL
        )
        for m in a_block_re.finditer(html):
            item = self._extract_item_from_block(m.group(0))
            if item and item["url"] not in seen:
                seen.add(item["url"])
                items.append(item)
        if items:
            log("ArabSeed: Strategy 1 found {} items".format(len(items)))
            return items

        # === Strategy 2: Container elements with movie-related classes ===
        container_re = re.compile(
            r'<(?:article|div|li)\s[^>]*class=["\'][^"\']*(?:' + class_pattern + r')[^"\']*["\'][^>]*>',
            re.IGNORECASE
        )
        for m in container_re.finditer(html):
            start = m.end()
            tag_name = re.match(r'<(\w+)', m.group(0)).group(1).lower()
            close_tag = '</{}>'.format(tag_name)
            depth = 1
            pos = start
            end = -1
            while depth > 0 and pos < len(html):
                no = html.find('<' + tag_name, pos)
                nc = html.find(close_tag, pos)
                if nc == -1:
                    break
                if no != -1 and no < nc:
                    depth += 1
                    pos = no + 1
                else:
                    depth -= 1
                    end = nc
                    pos = nc + len(close_tag)
            block = html[start:end] if end > start else html[start:start+2000]
            item = self._extract_item_from_block(m.group(0) + block)
            if item and item["url"] not in seen:
                seen.add(item["url"])
                items.append(item)
        if items:
            log("ArabSeed: Strategy 2 found {} items".format(len(items)))
            return items

        # === Strategy 3: Broad fallback - any <a> with href + title (img optional) ===
        log("ArabSeed: Using broad fallback extraction")
        for m in re.finditer(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
            link = self._full_url(m.group(1))
            inner = m.group(2)
            if not link or link in seen:
                continue
            if any(x in link.lower() for x in ("/category/", "/page/", "/tag/", "/author/",
                                                "/feed/", "#", "javascript:", "facebook.com",
                                                "twitter.com", "youtube.com", "google.com",
                                                "whatsapp.com", "telegram")):
                continue
            
            img = ""
            img_m = re.search(r'<img[^>]+(?:data-src|data-lazy-src|data-original|src)=["\']([^"\']+)["\']', inner, re.IGNORECASE)
            if img_m:
                img = self._full_url(img_m.group(1))
                if any(x in img.lower() for x in ("logo", "placeholder", "loading.gif", "lazy_load", "data:image", "sprite", "icon")):
                    img = ""
            
            if not img:
                bg_m = re.search(r'background(?:-image)?\s*:\s*url\(["\']?([^"\')]+)["\']?\)', inner, re.IGNORECASE)
                if bg_m:
                    img = self._full_url(bg_m.group(1))

            title_m = (
                re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', inner, re.IGNORECASE) or
                re.search(r'title=["\']([^"\']+)["\']', m.group(0), re.IGNORECASE) or
                re.search(r'<(?:h[1-4]|span|p)[^>]*>([^<]{2,})</', inner, re.IGNORECASE)
            )
            if not title_m:
                continue
            title = self._clean_title(title_m.group(1))
            if not title or len(title) < 2:
                continue
                
            seen.add(link)
            items.append({
                "title": title, "url": link, "poster": img,
                "type": self._determine_item_type(link, title), "_action": "details",
            })
        if items:
            log("ArabSeed: Strategy 3 found {} items".format(len(items)))
            return items

        # === Strategy 4: CSS Background Image Fallback ===
        log("ArabSeed: Using CSS background fallback extraction")
        for m in re.finditer(r'<(?:div|article|a)[^>]+style=["\'][^"\']*background-image:\s*url\(([^)]+)\)[^"\']*["\'][^>]*>(.*?)</(?:div|article|a)>', html, re.IGNORECASE | re.DOTALL):
            bg_url = m.group(1).strip("'\" ")
            block_html = m.group(2)
            
            href_m = re.search(r'href=["\']([^"\']+)["\']', m.group(0), re.IGNORECASE)
            if not href_m:
                continue
            link = self._full_url(href_m.group(1))
            if not link or link in seen:
                continue
                
            if any(x in link.lower() for x in ("/category/", "/page/", "/tag/", "/author/", "/feed/", "#", "javascript:")):
                continue
                
            title_m = (
                re.search(r'title=["\']([^"\']+)["\']', m.group(0), re.IGNORECASE) or
                re.search(r'<(?:h[1-4]|span|p)[^>]*>([^<]{2,})</', block_html, re.IGNORECASE)
            )
            if not title_m:
                continue
            title = self._clean_title(title_m.group(1))
            if not title or len(title) < 2:
                continue
                
            seen.add(link)
            items.append({
                "title": title, "url": link, "poster": self._full_url(bg_url),
                "type": self._determine_item_type(link, title), "_action": "details",
            })

        if items:
            log("ArabSeed: Strategy 4 found {} items".format(len(items)))
        else:
            log("ArabSeed: All strategies failed - no items found")
        return items

    def _server_priority(self, server_url):
        lowered = server_url.lower()
        if "reviewrate" in lowered or "reviewtech" in lowered:
            return 0
        if "vidmoly" in lowered:
            return 1
        if "downet.net" in lowered:
            return 2
        if "mxcontent.net" in lowered:
            return 3
        return 9

    def _server_name(self, server_url, label_hint=""):
        lowered = (server_url or "").lower()
        names = {
            "reviewrate": "عرب سيد", "reviewtech": "عرب سيد",
            "vidmoly": "VidMoly", "downet.net": "Downet (Direct)",
            "mxcontent.net": "MxContent", "streamwish": "StreamWish",
            "wishfast": "StreamWish", "filemoon": "FileMoon",
            "lulustream": "LuluStream", "mixdrop": "MixDrop",
            "dood": "DoodStream", "streamtape": "StreamTape",
            "vidguard": "VidGuard", "vgfplay": "VidGuard",
            "fastvid": "FastVid", "ok.ru": "OK.ru", "okru": "OK.ru",
            "uqload": "UqLoad", "streamruby": "StreamRuby",
            "hgcloud": "HGCloud", "filelions": "FileLions",
            "vidhide": "VidHide", "streamhide": "StreamHide",
            "govid": "GoVid", "savefiles": "SaveFiles",
        }
        for key, name in names.items():
            if key in lowered:
                return name
        if label_hint:
            return label_hint.strip()
        domain_match = re.search(r'https?://([^/]+)', server_url or "")
        return domain_match.group(1) if domain_match else "Server"

    def _collect_ajax_servers(self, watch_html, watch_url):
        base_domain = self._get_base()
        try:
            host = re.search(r'https?://([^/]+)', base_domain).group(1)
            clear_cookies(host)
        except Exception:
            pass

        token = self._extract_first([
            r"csrf__token['\"]?\s*[:=]\s*['\"]([^'\"]+)",
            r"csrf_token['\"]?\s*[:=]\s*['\"]([^'\"]+)",
            r"csrfToken['\"]?\s*[:=]\s*['\"]([^'\"]+)",
            r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)',
            r'value=["\']([^"\']+)["\'][^>]*name=["\']csrf_token',
            r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)',
            r'window\.\w*csrf\w*\s*=\s*["\']([^"\']+)',
            r'var\s+\w*csrf\w*\s*=\s*["\']([^"\']+)',
            r'csrf["\']\s*:\s*["\']([^"\']+)',
        ], watch_html)

        post_id = self._extract_first([
            r"psot_id['\"]?\s*[:=]\s*['\"]?(\d+)",
            r"post_id['\"]?\s*[:=]\s*['\"]?(\d+)",
            r"postID['\"]?\s*[:=]\s*['\"]?(\d+)",
            r"postId['\"]?\s*[:=]\s*['\"]?(\d+)",
            r'data-post-id=["\'](\d+)',
            r'data-post=["\'](\d+)',
            r'data-id=["\'](\d+)',
            r'name=["\']post_id["\'][^>]*value=["\'](\d+)',
            r'var\s+post_id\s*=\s*["\']?(\d+)',
            r'var\s+postId\s*=\s*["\']?(\d+)',
            r'"post_id"\s*:\s*"?(\d+)',
            r'"postId"\s*:\s*"?(\d+)',
            r'postid-(\d+)',
            r'\?p=(\d+)',
            r'post-(\d+)',
        ], watch_html)

        home_url = self._extract_first([
            r"main__obj\s*=\s*\{\s*'home__url':\s*'([^']+)'",
            r"home_url['\"]?\s*[:=]\s*['\"]([^'\"]+)",
            r"siteUrl['\"]?\s*[:=]\s*['\"]([^'\"]+)",
        ], watch_html) or base_domain

        if not token or not post_id:
            log("ArabSeed: Missing token={} post_id={}".format(bool(token), bool(post_id)))
            return []

        log("ArabSeed: AJAX token found, post_id={}".format(post_id))
        quality_url = urljoin(home_url, "get__quality__servers/")
        watch_server_url = urljoin(home_url, "get__watch__server/")
        results, seen, lock = [], set(), threading.Lock()

        def _cb(u):
            sep = "&" if "?" in u else "?"
            return "{}{}_cb={}{:04d}".format(u, sep, int(time.time() * 1000), random.randint(0, 9999))

        def fetch_row(rp, sid, rq, label):
            hdrs = {"X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Referer": watch_url}
            body, _ = fetch(_cb(watch_server_url),
                            post_data={"post_id": rp, "quality": rq, "server": sid, "csrf_token": token},
                            referer=watch_url, extra_headers=hdrs)
            if not body:
                return None
            try:
                d = json.loads(body)
            except Exception:
                return None
            if d.get("type") != "success" or not d.get("server"):
                return None
            u = self._decode_hidden_url(d.get("server", ""))
            if not u.startswith("http") or any(h in u for h in BLOCKED_HOSTS):
                return None
            return {"quality": rq, "url": u, "name": self._server_name(u, label)}

        def fetch_quality(q):
            local = []
            hdrs = {"X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Referer": watch_url}
            body, _ = fetch(_cb(quality_url),
                            post_data={"post_id": post_id, "quality": q, "csrf_token": token},
                            referer=watch_url, extra_headers=hdrs)
            if not body:
                return local
            try:
                d = json.loads(body)
            except Exception:
                return local
            if d.get("type") != "success":
                return local
            ds = self._decode_hidden_url(d.get("server", ""))
            if ds.startswith("http") and not any(h in ds for h in BLOCKED_HOSTS):
                local.append({"quality": q, "url": ds, "name": self._server_name(ds, "سيرفر عرب سيد")})
            rows = re.findall(
                r'<li[^>]+data-post="([^"]+)"[^>]+data-server="([^"]+)"[^>]+data-qu="([^"]+)"[^>]*>.*?<span>([^<]+)</span>',
                d.get("html", ""), re.S)
            if not rows:
                rows = re.findall(
                    r'<(?:li|div|a|button)[^>]+data-post="([^"]+)"[^>]+data-server="([^"]+)"[^>]+data-qu="([^"]+)"[^>]*>(.*?)</',
                    d.get("html", ""), re.S)
                rows = [(r[0], r[1], r[2], re.sub(r'<[^>]+>', '', r[3]).strip()) for r in rows]
            if rows:
                with ThreadPoolExecutor(max_workers=min(3, len(rows))) as ex:
                    for r in ex.map(lambda x: fetch_row(*x), rows):
                        if r:
                            local.append(r)
            return local

        with ThreadPoolExecutor(max_workers=3) as ex:
            for tier in ex.map(fetch_quality, ("1080", "720", "480")):
                for item in tier:
                    uk, nk = (item["quality"], item["url"]), (item["quality"], item["name"])
                    with lock:
                        if uk in seen or nk in seen:
                            continue
                        seen.add(uk); seen.add(nk)
                    results.append(item)

        if not results:
            log("ArabSeed: AJAX returned 0 servers")
        else:
            log("ArabSeed: AJAX returned {} servers".format(len(results)))
        results.sort(key=lambda i: (QUALITY_ORDER.get(i["quality"], 9), self._server_priority(i["url"]), i["name"]))
        return results

    def get_categories(self, mtype="movie"):
        base = self._get_base()
        return [
            {"title": "🎬 كل الأفلام",       "url": urljoin(base, "category/films/"),                 "type": "category", "_action": "category"},
            {"title": "🌍 أفلام أجنبي",      "url": urljoin(base, "category/films/foreign-movies/"),  "type": "category", "_action": "category"},
            {"title": "🌏 أفلام آسيوية",     "url": urljoin(base, "category/films/asian-movies/"),    "type": "category", "_action": "category"},
            {"title": "🇮🇳 أفلام هندي",      "url": urljoin(base, "category/films/indian-movies/"),   "type": "category", "_action": "category"},
            {"title": "🇹🇷 أفلام تركي",      "url": urljoin(base, "category/films/turkish-movies/"),  "type": "category", "_action": "category"},
            {"title": "📺 كل المسلسلات",     "url": urljoin(base, "category/tv/"),                    "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات أجنبي",    "url": urljoin(base, "category/tv/foreign-series/"),     "type": "category", "_action": "category"},
            {"title": "🇮🇳 مسلسلات هندي",    "url": urljoin(base, "category/tv/indian-tv-series/"),   "type": "category", "_action": "category"},
            {"title": "🇹🇷 مسلسلات تركي",    "url": urljoin(base, "category/tv/turkish-series/"),     "type": "category", "_action": "category"},
            {"title": "🎭 أفلام انمي",       "url": urljoin(base, "category/anime/anime-movies/"),    "type": "category", "_action": "category"},
            {"title": "🎭 مسلسلات انمي",     "url": urljoin(base, "category/anime/anime-series/"),    "type": "category", "_action": "category"},
        ]

    def get_category_items(self, url, page=1):
        # Ensure URL uses the active domain
        url = self._full_url(url)
        log("ArabSeed: get_category_items url={} page={}".format(url, page))
        html, _ = fetch(url, referer=self._get_base())
        if not html:
            log("ArabSeed: Failed to fetch: {}".format(url))
            return []
        if "just a moment" in html.lower() and ("cf-chl" in html.lower() or "challenge" in html.lower()):
            log("ArabSeed: Cloudflare challenge detected")
            return []
        items = self._extract_items_from_html(html)
        log("ArabSeed: Extracted {} items".format(len(items)))
        next_page = (
            re.search(r'<link[^>]+rel=["\']next["\'][^>]+href=["\']([^"\']+)["\']', html, re.I) or
            re.search(r'<a[^>]+class=["\'][^"\']*next[^"\']*["\'][^>]+href=["\']([^"\']+)["\']', html, re.I) or
            re.search(r'<a[^>]+rel=["\']next["\'][^>]+href=["\']([^"\']+)["\']', html, re.I) or
            re.search(r'href="([^"]+/page/\d+/)"', html, re.I)
        )
        if next_page:
            nu = self._full_url(next_page.group(1))
            if nu and nu != url:
                items.append({"title": "➡️ الصفحة التالية", "url": nu, "type": "category", "_action": "category"})
        return items

    def search(self, query, page=1):
        search_url = urljoin(self._get_base(), "?s=" + query.replace(" ", "+"))
        if page > 1:
            search_url = urljoin(self._get_base(), "page/{}/?s={}".format(page, query.replace(" ", "+")))
        log("ArabSeed: search url={}".format(search_url))
        html, _ = fetch(search_url, referer=self._get_base())
        if not html:
            return []
        return self._extract_items_from_html(html)

    def get_page(self, url, m_type=None):
        url = self._full_url(url)
        log("ArabSeed: get_page url={}".format(url))
        html, final_url = fetch(url, referer=self._get_base())
        if not html:
            return {"title": "Error", "servers": []}
        result = {"url": final_url or url, "title": "", "plot": "", "poster": "",
                  "rating": "", "year": "", "servers": [], "items": []}

        tm = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S) or re.search(r'og:title[^>]+content="([^"]+)"', html)
        if tm:
            result["title"] = self._clean_title(tm.group(1).split("-")[0])
        pm = re.search(r'og:image"[^>]+content="([^"]+)"', html)
        if pm:
            result["poster"] = self._full_url(pm.group(1))
        plm = re.search(r'name="description"[^>]+content="([^"]+)"', html)
        if plm:
            result["plot"] = html_lib.unescape(plm.group(1))
        ym = re.search(r'\(\s*(\d{4})\s*\)', result["title"])
        if ym:
            result["year"] = ym.group(1)

        is_series = (any(m in (final_url or url) for m in ("/series-", "-season-", "-episode-", "/selary/"))
                     or "مسلسل" in result["title"] or "الحلقة" in result["title"])

        base_url = (final_url or url).rstrip("/")
        watch_url = base_url + "/watch/"
        wm = re.search(r'href="([^"]+/watch/?)"', html)
        if wm:
            watch_url = self._full_url(wm.group(1))
        if not wm:
            wa = re.search(r'data-(?:watch|href|url)=["\']([^"\']+/watch[^"\']*)["\']', html, re.I)
            if wa:
                watch_url = self._full_url(wa.group(1))

        log("ArabSeed: watch_url={}".format(watch_url))
        watch_html, watch_final = fetch(watch_url, referer=final_url or url)
        if not watch_html:
            watch_html, watch_final = html, (final_url or url)

        for server in self._collect_ajax_servers(watch_html, watch_final or watch_url):
            result["servers"].append({
                "name": "[{}p] {}".format(server["quality"], server["name"]),
                "url": server["url"], "type": "direct"})

        if not result["servers"]:
            log("ArabSeed: AJAX failed, trying fallback")
            result["servers"] = self._extract_servers_fallback(watch_html, html, final_url or url)

        if is_series:
            seen_eps = set()
            cm = re.search(r'<ul[^>]+class=["\'][^"\']*episodes__list[^"\']*["\'][^>]*>(.*?)</ul>', html, re.S | re.I)
            if not cm:
                cm = re.search(r'<div[^>]+class=["\'][^"\']*(?:episodes|eps-list|all-eps)[^"\']*["\'][^>]*>(.*?)</div>', html, re.S | re.I)
            if cm:
                for em in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>.*?(?:الحلقة|Episode|EP|حلقة)\s*(\d+)', cm.group(1), re.S | re.I):
                    if em.group(1) in seen_eps:
                        continue
                    seen_eps.add(em.group(1))
                    result["items"].append({"title": "{} - الحلقة {}".format(result["title"], em.group(2)).strip(),
                                            "url": self._full_url(em.group(1)), "type": "episode", "_action": "details"})
            if not result["items"]:
                for ep_url, ep_title in re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]+title="([^"]+)"', html, re.S):
                    if ("الحلقة" not in ep_title and "حلقة" not in ep_title) or ep_url in seen_eps:
                        continue
                    if not any(x in ep_url for x in ("series-", "-season", "episode", "selary")):
                        continue
                    seen_eps.add(ep_url)
                    result["items"].append({"title": ep_title.strip(), "url": self._full_url(ep_url), "type": "episode", "_action": "details"})
        return result

    def _extract_servers_fallback(self, watch_html, main_html, page_url):
        """Fallback server extraction when AJAX fails."""
        servers, seen = [], set()
        source = watch_html or main_html or ""
        IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".ico")

        for attr in ("data-link", "data-url", "data-iframe", "data-src", "data-href", "data-server"):
            for m in re.finditer(attr + r'=["\']([^"\']+)["\']', source, re.I):
                u = self._decode_hidden_url(m.group(1))
                if not u.startswith("http") or u.lower().split("?", 1)[0].endswith(IMG_EXT):
                    continue
                if any(h in u for h in BLOCKED_HOSTS) or u in seen:
                    continue
                seen.add(u)
                servers.append({"name": self._server_name(u, "سيرفر {}".format(len(servers)+1)), "url": u, "type": "direct"})

        for m in re.finditer(r'<iframe[^>]+src=["\']([^"\']+)["\']', source, re.I):
            u = self._full_url(m.group(1))
            if not u or u in seen or any(x in u.lower() for x in ("facebook.com", "twitter.com", "google.com", "youtube.com/embed", "disqus.com")):
                continue
            if any(h in u for h in BLOCKED_HOSTS):
                continue
            seen.add(u)
            servers.append({"name": self._server_name(u, "سيرفر {}".format(len(servers)+1)), "url": u, "type": "embed"})

        for m in re.finditer(r'<(?:source|video)[^>]+src=["\']([^"\']+\.(?:mp4|m3u8|mkv)[^"\']*)["\']', source, re.I):
            u = self._full_url(m.group(1))
            if not u or u in seen:
                continue
            seen.add(u)
            q = "1080p" if "1080" in u.lower() else ("720p" if "720" in u.lower() else ("480p" if "480" in u.lower() else "HD"))
            servers.append({"name": "Direct - {}".format(q), "url": u, "type": "direct"})

        for pat in (r'file\s*:\s*["\']([^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
                    r'source\s*:\s*["\']([^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
                    r'"url"\s*:\s*"([^"]+\.(?:mp4|m3u8)[^"]*)"'):
            for m in re.finditer(pat, source, re.I):
                u = self._full_url(m.group(1).replace("\\/", "/"))
                if not u or u in seen or any(h in u for h in BLOCKED_HOSTS):
                    continue
                seen.add(u)
                q = "1080p" if "1080" in u.lower() else ("720p" if "720" in u.lower() else ("480p" if "480" in u.lower() else "HD"))
                servers.append({"name": "Direct - {}".format(q), "url": u, "type": "direct"})

        host_re = re.compile(
            r'(https?://(?:www\.)?(?:streamtape|doodstream|dood\.|mixdrop|uqload|voe\.|'
            r'streamwish|filemoon|lulustream|ok\.ru|vidguard|fastvid|'
            r'reviewrate|reviewtech|vidmoly|downet\.net|mxcontent\.net|'
            r'savefiles|delucloud|sprintcdn|filelions|vidhide|streamhide|'
            r'govid|hgcloud|vidbom|upstream|streamruby|abstream)[^"\'>\s]+)', re.IGNORECASE)
        for m in host_re.finditer(source):
            u = m.group(1).replace("\\/", "/").replace("&amp;", "&")
            if u in seen or any(h in u for h in BLOCKED_HOSTS):
                continue
            seen.add(u)
            servers.append({"name": self._server_name(u, "سيرفر {}".format(len(servers)+1)), "url": u, "type": "embed"})

        log("ArabSeed: Fallback found {} servers".format(len(servers)))
        return servers

    def extract_stream(self, url):
        from .base import extract_stream as base_extract_stream
        return base_extract_stream(url)