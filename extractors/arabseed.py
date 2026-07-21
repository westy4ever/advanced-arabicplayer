# -*- coding: utf-8 -*-
"""
Arabseed extractor - arabseeds.cam
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


class ArabseedExtractor(BaseExtractor):
    """Extractor for Arabseed - arabseeds.cam"""
    
    MAIN_URL = "https://arabseeds.cam/"
    
    def __init__(self):
        super(ArabseedExtractor, self).__init__()
        self.main_url = self.MAIN_URL
        self._resolved_base = self.MAIN_URL
    
    def _get_base(self):
        return self._resolved_base or self.MAIN_URL
    
    def _clean_title(self, title):
        return (
            html_lib.unescape(title or "")
            .replace("مشاهدة", "")
            .replace("فيلم", "")
            .strip()
        )
    
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
        if "reviewrate" in lowered or "reviewtech" in lowered:
            return "عرب سيد"
        if "vidmoly" in lowered:
            return "VidMoly"
        if "downet.net" in lowered:
            return "Downet (Direct)"
        if "mxcontent.net" in lowered:
            return "MxContent"
        if label_hint:
            return label_hint.strip()
        domain_match = re.search(r'https?://([^/]+)', server_url or "")
        return domain_match.group(1) if domain_match else "Server"
    
    def _collect_ajax_servers(self, watch_html, watch_url):
        try:
            clear_cookies("arabseeds.cam")
        except Exception:
            pass
    
        token = self._extract_first(
            [
                r"csrf__token['\"]?\s*[:=]\s*['\"]([^'\"]+)",
                r"csrf_token['\"]?\s*[:=]\s*['\"]([^'\"]+)",
            ],
            watch_html,
        )
        post_id = self._extract_first(
            [
                r"psot_id['\"]?\s*[:=]\s*['\"](\d+)",
                r"post_id['\"]?\s*[:=]\s*['\"](\d+)",
            ],
            watch_html,
        )
        home_url = self._extract_first([r"main__obj\s*=\s*\{\s*'home__url':\s*'([^']+)'"], watch_html) or self._get_base()
        if not token or not post_id:
            log("ArabSeed: Missing AJAX token/post_id")
            return []
    
        quality_url     = urljoin(home_url, "get__quality__servers/")
        watch_server_url = urljoin(home_url, "get__watch__server/")
        results = []
        seen    = set()
        lock    = threading.Lock()
    
        def _cache_bust(u):
            sep = "&" if "?" in u else "?"
            return "{}{}_cb={}{:04d}".format(u, sep, int(time.time() * 1000), random.randint(0, 9999))
    
        def fetch_row(row_post_id, server_id, row_quality, label):
            extra_headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": watch_url,
            }
            watch_body, _ = fetch(
                _cache_bust(watch_server_url),
                post_data={
                    "post_id":   row_post_id,
                    "quality":   row_quality,
                    "server":    server_id,
                    "csrf_token": token,
                },
                referer=watch_url,
                extra_headers=extra_headers,
            )
            if not watch_body:
                return None
            try:
                watch_data = json.loads(watch_body)
            except Exception:
                return None
            if watch_data.get("type") != "success" or not watch_data.get("server"):
                return None
    
            server_url_decoded = self._decode_hidden_url(watch_data.get("server", ""))
            if not server_url_decoded.startswith("http"):
                return None
            if any(h in server_url_decoded for h in BLOCKED_HOSTS):
                return None
            return {
                "quality": row_quality,
                "url":     server_url_decoded,
                "name":    self._server_name(server_url_decoded, label),
            }
    
        def fetch_quality(quality):
            local_results = []
            extra_headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": watch_url,
            }
            body, _ = fetch(
                _cache_bust(quality_url),
                post_data={"post_id": post_id, "quality": quality, "csrf_token": token},
                referer=watch_url,
                extra_headers=extra_headers,
            )
            if not body:
                return local_results
            try:
                data = json.loads(body)
            except Exception:
                log("ArabSeed: Failed to decode quality JSON for {}p".format(quality))
                return local_results
            if data.get("type") != "success":
                return local_results
    
            direct_server = self._decode_hidden_url(data.get("server", ""))
            if direct_server.startswith("http") and not any(h in direct_server for h in BLOCKED_HOSTS):
                local_results.append({
                    "quality": quality,
                    "url":     direct_server,
                    "name":    self._server_name(direct_server, "سيرفر عرب سيد"),
                })
    
            server_rows = re.findall(
                r'<li[^>]+data-post="([^"]+)"[^>]+data-server="([^"]+)"[^>]+data-qu="([^"]+)"[^>]*>.*?<span>([^<]+)</span>',
                data.get("html", ""),
                re.S,
            )
            if server_rows:
                with ThreadPoolExecutor(max_workers=min(3, len(server_rows))) as ex:
                    for row_result in ex.map(lambda r: fetch_row(*r), server_rows):
                        if row_result:
                            local_results.append(row_result)
            return local_results
    
        with ThreadPoolExecutor(max_workers=3) as ex:
            for tier_results in ex.map(fetch_quality, ("1080", "720", "480")):
                for item in tier_results:
                    key = (item["quality"], item["url"])
                    with lock:
                        if key in seen:
                            continue
                        seen.add(key)
                    results.append(item)
    
        if not results:
            log("ArabSeed: AJAX returned 0 servers for watch_url={}".format(watch_url))
    
        results.sort(key=lambda item: (
            QUALITY_ORDER.get(item["quality"], 9),
            self._server_priority(item["url"]),
            item["name"],
        ))
        return results
    
    def get_categories(self, mtype="movie"):
        return [
            {"title": "🎬 كل الأفلام",       "url": urljoin(self._get_base(), "category/films/"),                 "type": "category", "_action": "category"},
            {"title": "🌍 أفلام أجنبي",      "url": urljoin(self._get_base(), "category/films/foreign-movies/"),  "type": "category", "_action": "category"},
            {"title": "🌏 أفلام آسيوية",     "url": urljoin(self._get_base(), "category/films/asian-movies/"),    "type": "category", "_action": "category"},
            {"title": "🇮🇳 أفلام هندي",      "url": urljoin(self._get_base(), "category/films/indian-movies/"),   "type": "category", "_action": "category"},
            {"title": "🇹🇷 أفلام تركي",      "url": urljoin(self._get_base(), "category/films/turkish-movies/"),  "type": "category", "_action": "category"},
            {"title": "📺 كل المسلسلات",     "url": urljoin(self._get_base(), "category/tv/"),                    "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات أجنبي",    "url": urljoin(self._get_base(), "category/tv/foreign-series/"),     "type": "category", "_action": "category"},
            {"title": "🇮🇳 مسلسلات هندي",    "url": urljoin(self._get_base(), "category/tv/indian-tv-series/"),   "type": "category", "_action": "category"},
            {"title": "🇹🇷 مسلسلات تركي",    "url": urljoin(self._get_base(), "category/tv/turkish-series/"),     "type": "category", "_action": "category"},
            {"title": "🎭 أفلام انمي",       "url": urljoin(self._get_base(), "category/anime/anime-movies/"),    "type": "category", "_action": "category"},
            {"title": "🎭 مسلسلات انمي",     "url": urljoin(self._get_base(), "category/anime/anime-series/"),    "type": "category", "_action": "category"},
        ]
    
    def get_category_items(self, url, page=1):
        html, _ = fetch(url, referer=self._get_base())
        if not html:
            return []
    
        items = []
        seen  = set()
    
        blocks = re.findall(
            r'<a[^>]+class=["\']([^"\']*(?:movie__block|recent--block|post--block)[^"\']*)["\'][^>]*>(.*?)</a>',
            html, re.S | re.IGNORECASE
        )
        if not blocks:
            blocks = [("", b) for b in re.findall(
                r'(<a[^>]+href=["\'][^>]*>.*?<img[^>]+(?:data-src|src)=["\'][^>]*>.*?</a>)',
                html, re.S | re.IGNORECASE
            )]
    
        for class_attr, block in blocks:
            m = (
                re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]+title=["\']([^"\']+)["\'][^>]*>', block, re.S) or
                re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>.*?<img[^>]+alt=["\']([^"\']+)["\']', block, re.S)
            )
            if m:
                link, title = m.groups()
                img_m = re.search(r'<img[^>]+(?:data-src|src)=["\']([^"\']+)["\']', block)
                img   = img_m.group(1) if img_m else ""
                if link in seen or "/category/" in link:
                    continue
                seen.add(link)
                title     = self._clean_title(title)
                if "-season-" in link or "-episode-" in link:
                    item_type = "episode"
                elif "is__episode" in class_attr or "/series-" in link or "مسلسل" in title or "الحلقة" in title:
                    item_type = "series"
                else:
                    item_type = "movie"
                items.append({"title": title, "url": link, "poster": img, "type": item_type, "_action": "details"})
    
        if not items:
            regex = r'<a[^>]+href=["\']([^"\']+)["\'][^>]+title=["\']([^"\']+)["\'][^>]*>.*?<img[^>]+(?:data-src|src)=["\']([^"\']+)["\']'
            for link, title, img in re.findall(regex, html, re.S | re.IGNORECASE):
                if link in seen or "/category/" in link:
                    continue
                seen.add(link)
                if "-season-" in link or "-episode-" in link:
                    item_type = "episode"
                elif "/series-" in link or "مسلسل" in title or "الحلقة" in title:
                    item_type = "series"
                else:
                    item_type = "movie"
                items.append({"title": title.strip(), "url": link, "poster": img, "type": item_type, "_action": "details"})
    
        next_page = (
            re.search(r'<link[^>]+rel=["\']next["\'][^>]+href=["\']([^"\']+/page/\d+/)["\']', html) or
            re.search(r'href="([^"]+/page/\d+/)"', html)
        )
        if next_page:
            items.append({"title": "➡️ الصفحة التالية", "url": next_page.group(1), "type": "category", "_action": "category"})
        return items
    
    def search(self, query, page=1):
        search_url = urljoin(self._get_base(), "?s=" + query.replace(" ", "+"))
        if page > 1:
            search_url = urljoin(self._get_base(), "page/{}/?s={}".format(page, query.replace(" ", "+")))
        
        html, _ = fetch(search_url, referer=self._get_base())
        if not html:
            return []
        
        items = []
        blocks = re.findall(
            r'<a[^>]+class=["\']([^"\']*(?:movie__block|recent--block|post--block)[^"\']*)["\'][^>]*>(.*?)</a>',
            html, re.S | re.IGNORECASE
        )
        if not blocks:
            blocks = [("", b) for b in re.findall(
                r'(<a[^>]+href=["\'][^>]*>.*?<img[^>]+(?:data-src|src)=["\'][^>]*>.*?</a>)',
                html, re.S | re.IGNORECASE
            )]
        
        for class_attr, block in blocks:
            m = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>.*?<img[^>]+alt=["\']([^"\']+)["\']', block, re.S)
            if m:
                link, title = m.groups()
                img_m = re.search(r'<img[^>]+(?:data-src|src)=["\']([^"\']+)["\']', block)
                img = img_m.group(1) if img_m else ""
                if not link or "/category/" in link:
                    continue
                items.append({"title": self._clean_title(title), "url": link, "poster": img, "type": "movie", "_action": "details"})
        
        return items
    
    def get_page(self, url, m_type=None):
        html, final_url = fetch(url, referer=self._get_base())
        if not html:
            return {"title": "Error", "servers": []}
    
        result = {
            "url":     final_url or url,
            "title":   "",
            "plot":    "",
            "poster":  "",
            "rating":  "",
            "year":    "",
            "servers": [],
            "items":   [],
        }
    
        title_match = (
            re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S) or
            re.search(r'og:title[^>]+content="([^"]+)"', html)
        )
        if title_match:
            result["title"] = self._clean_title(title_match.group(1).split("-")[0])
    
        poster_match = re.search(r'og:image"[^>]+content="([^"]+)"', html)
        if poster_match:
            result["poster"] = poster_match.group(1)
    
        plot_match = re.search(r'name="description"[^>]+content="([^"]+)"', html)
        if plot_match:
            result["plot"] = plot_match.group(1)
    
        rating_match = re.search(r'class="post__ratings">\s*([\d.]+)\s*</div>', html)
        if rating_match:
            result["rating"] = rating_match.group(1)
    
        year_match = re.search(r'\(\s*(\d{4})\s*\)', result["title"])
        if year_match:
            result["year"] = year_match.group(1)
    
        is_series = (
            any(m in (final_url or url) for m in ("/series-", "-season-", "-episode-"))
            or "مسلسل" in result["title"]
            or "الحلقة" in result["title"]
        )
    
        watch_url   = (final_url or url).rstrip("/") + "/watch/"
        watch_match = re.search(r'href="([^"]+/watch/)"', html)
        if watch_match:
            watch_url = watch_match.group(1)
    
        watch_html, watch_final = fetch(watch_url, referer=final_url or url)
        if not watch_html:
            watch_html, watch_final = html, (final_url or url)
    
        for server in self._collect_ajax_servers(watch_html, watch_final or watch_url):
            result["servers"].append({
                "name": "[{}p] {}".format(server["quality"], server["name"]),
                "url":  server["url"],
                "type": "direct",
            })
    
        if is_series:
            seen_eps = set()
            container_match = re.search(
                r'<ul[^>]+class=["\'][^"\']*episodes__list[^"\']*["\'][^>]*>(.*?)</ul>',
                html, re.S | re.I
            )
            if container_match:
                container = container_match.group(1)
                for ep_url, ep_num in re.findall(
                    r'<a[^>]+href="(https?://[^/]+/[^"]+)"[^>]*>.*?<div[^>]+class="epi__num">[^<]*<b>(\d+)</b></div>',
                    container, re.S
                ):
                    if ep_url in seen_eps:
                        continue
                    seen_eps.add(ep_url)
                    ep_title, n_subs = re.subn(r'(الحلقة\s*)\d+', r'\g<1>' + ep_num, result["title"])
                    if n_subs == 0 and ep_title:
                        ep_title = "{} - الحلقة {}".format(result["title"], ep_num)
                    result["items"].append({
                        "title":   ep_title.strip(),
                        "url":     ep_url,
                        "type":    "episode",
                        "_action": "details",
                    })
            else:
                for ep_url, ep_title in re.findall(
                    r'<a[^>]+href="(https?://[^/]+/[^"]+)"[^>]+title="([^"]+)"',
                    html, re.S
                ):
                    if ("الحلقة" not in ep_title and "حلقة" not in ep_title) or ep_url in seen_eps:
                        continue
                    if not any(x in ep_url for x in ("series-", "-season", "episode")):
                        continue
                    seen_eps.add(ep_url)
                    result["items"].append({
                        "title":   ep_title.strip(),
                        "url":     ep_url,
                        "type":    "episode",
                        "_action": "details",
                    })
    
        if not result["servers"]:
            IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg")
            for fallback in re.findall(r'data-(?:link|url|iframe|src|href)="([^"]+)"', watch_html or "", re.S):
                fallback = self._decode_hidden_url(fallback)
                if not fallback.startswith("http"):
                    continue
                if fallback.lower().split("?", 1)[0].endswith(IMAGE_EXT):
                    continue
                if any(h in fallback for h in BLOCKED_HOSTS):
                    continue
                if fallback not in [s["url"] for s in result["servers"]]:
                    result["servers"].append({"name": "Fallback", "url": fallback, "type": "direct"})
    
        return result
    
    def extract_stream(self, url):
        """Delegate to base extractor."""
        from .base import extract_stream as base_extract_stream
        return base_extract_stream(url)