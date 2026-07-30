# -*- coding: utf-8 -*-
"""
Extractor for faselhdx.bid (FaselHD CDN variant)
Domains: web51212x / web5106x / web51118x / web5120x.faselhdx.bid
Inherits from BaseExtractor.
"""

import re
import sys
from .base import BaseExtractor, fetch, urljoin, log

if sys.version_info[0] == 3:
    from urllib.parse import quote_plus, urlparse
else:
    from urllib import quote_plus
    from urlparse import urlparse


class FaselhdHdxExtractor(BaseExtractor):
    """Extractor for faselhdx.bid"""
    
    BASE_URL = "https://www.fasel-hd.cam"
    KNOWN_DOMAIN_SUFFIXES = ("faselhdx.bid", "faselhd.bid", "fasel-hd.cam", "faselhd.pro", "faselhd.life")
    FAKE_M3U8_HOSTS = {"img.scdns.io"}
    
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0.0.0 Safari/537.36")
    
    HEADERS = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ar,en-US;q=0.7,en;q=0.3",
        "DNT": "1",
    }
    
    SCRIPT_NOISE = {
        "jwpcdn.com", "jwplatform.com",
        "unpkg.com", "cdn.jsdelivr.net", "cdnjs.cloudflare.com",
        "ajax.googleapis.com", "code.jquery.com", "stackpath.bootstrapcdn.com",
        "google-analytics.com", "googletagmanager.com",
        "aclib.net", "acscdn.com", "madurird.com", "browsecoherentunrefined.com",
        "crumpetprankerstench.com",
    }
    
    def __init__(self):
        super(FaselhdHdxExtractor, self).__init__()
        self.main_url = self.BASE_URL
        self._resolved_base = self.BASE_URL
    
    def _get_base(self):
        if self._resolved_base:
            return self._resolved_base
        return self.BASE_URL
    
    def _update_base(self, url):
        p = urlparse(url)
        if p.netloc and any(p.netloc.lower().endswith(suf) for suf in self.KNOWN_DOMAIN_SUFFIXES):
            self._resolved_base = "{}://{}".format(p.scheme or "https", p.netloc)
            self.main_url = self._resolved_base
    
    def _norm(self, url):
        if not url:
            return ""
        url = str(url).strip().replace("&amp;", "&")
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return self._get_base().rstrip("/") + "/" + url.lstrip("/")
        return url
    
    def _clean_title(self, text):
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace("&amp;", "&")
        text = text.replace("فاصل إعلاني", "").replace("FaselHD", "")
        text = re.sub(r'\s*[-|]\s*(فاصل\s*إعلاني|FaselHD).*$', '', text, flags=re.I)
        return text.strip()
    
    def _is_real_m3u8(self, url):
        host = urlparse(url).netloc.lower()
        if host in self.FAKE_M3U8_HOSTS:
            return False
        if re.search(r'\.(jpg|jpeg|png|gif|webp|avif)\.m3u8', urlparse(url).path.lower()):
            return False
        return True
    
    def _get(self, url, referer=None, extra=None):
        hdrs = dict(self.HEADERS)
        hdrs["Referer"] = referer or self._get_base()
        if extra:
            hdrs.update(extra)
        
        from .base import _BROWSER_PROXY_URL, _fetch_via_browser_proxy
        if _BROWSER_PROXY_URL and ("video_player" in url or "player_token" in url):
            log("faselhd_hdx: using external proxy for video_player page: {}".format(url[:80]))
            proxy_html, proxy_final = _fetch_via_browser_proxy(url, referer=referer or self._get_base())
            if proxy_html:
                log("faselhd_hdx: proxy fetch successful ({} bytes)".format(len(proxy_html)))
                return proxy_html, proxy_final or url
    
        return fetch(url, referer=referer or self._get_base(), extra_headers=hdrs)
    
    def _classify_type(self, item_url, title):
        if re.search(r'/(?:[a-z-]*-)?episodes/', item_url, re.I):
            return "episode"
        if "/series" in item_url or "مسلسل" in title:
            return "series"
        if "/anime" in item_url and "/anime-movies" not in item_url:
            return "series"
        return "movie"
    
    def _extract_m3u8_from_player_page(self, html):
        if not html:
            return None
    
        for m in re.finditer(
            r'(https?://(?:r\d+--[a-zA-Z0-9]+\.c\.scdns\.io|master\.[a-zA-Z0-9]+\.c\.scdns\.io)/stream/v1/hls/[^"\'<>`\\\s]+\.m3u8)',
            html, re.I
        ):
            url = m.group(1).replace("\\/", "/").replace("&amp;", "&")
            if self._is_real_m3u8(url):
                return url
    
        js_blocks = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.I)
        for js in js_blocks:
            for m in re.finditer(
                r'(?:sources|files|streams)\s*[:=]\s*\[([^\]]+)\]',
                js, re.I
            ):
                block = m.group(1)
                for url_m in re.finditer(
                    r'(?:file|src|url)\s*[:=]\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                    block, re.I
                ):
                    url = url_m.group(1).replace("\\/", "/").replace("&amp;", "&")
                    if self._is_real_m3u8(url):
                        return url
    
            for m in re.finditer(
                r'(?:hlsManifestUrl|manifestUrl|playlistUrl)\s*[:=]\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                js, re.I
            ):
                url = m.group(1).replace("\\/", "/").replace("&amp;", "&")
                if self._is_real_m3u8(url):
                    return url
    
            for m in re.finditer(
                r'setup\s*\(\s*\{[^}]*file\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
                js, re.I
            ):
                url = m.group(1).replace("\\/", "/").replace("&amp;", "&")
                if self._is_real_m3u8(url):
                    return url
    
        for m in re.finditer(
            r'(https?://[^\s"\'<>`\\]+\.m3u8(?:\?[^\s"\'<>`\\]*)?)', html, re.I
        ):
            u = m.group(1).replace("\\/", "/").replace("&amp;", "&")
            if self._is_real_m3u8(u):
                return u
    
        return None
    
    def get_categories(self, mtype="movie"):
        base = self._get_base()
        return [
            {"title": "🆕 المضاف حديثا",            "url": base + "/most_recent",         "type": "category", "_action": "category"},
            {"title": "🎬 جميع الافلام",             "url": base + "/all-movies",           "type": "category", "_action": "category"},
            {"title": "🎬 افلام اجنبي",              "url": base + "/movies",               "type": "category", "_action": "category"},
            {"title": "🎬 افلام مدبلجة",             "url": base + "/dubbed-movies",        "type": "category", "_action": "category"},
            {"title": "🎬 افلام هندي",               "url": base + "/hindi",                "type": "category", "_action": "category"},
            {"title": "🎬 افلام اسيوي",              "url": base + "/asian-movies",         "type": "category", "_action": "category"},
            {"title": "🎬 افلام انمي",               "url": base + "/anime-movies",         "type": "category", "_action": "category"},
            {"title": "⭐ الاعلي تصويتا",            "url": base + "/movies_top_votes",     "type": "category", "_action": "category"},
            {"title": "👁️ الاعلي مشاهدة",            "url": base + "/movies_top_views",     "type": "category", "_action": "category"},
            {"title": "🏆 الاعلي IMDB",              "url": base + "/movies_top_imdb",      "type": "category", "_action": "category"},
            {"title": "🏆 جوائز الاوسكار",           "url": base + "/oscars-winners",       "type": "category", "_action": "category"},
            {"title": "🎬 سلاسل الافلام",            "url": base + "/movies_collections",   "type": "category", "_action": "category"},
            {"title": "📺 جميع المسلسلات",           "url": base + "/series",               "type": "category", "_action": "category"},
            {"title": "📺 المضاف حديثا (مسلسلات)",  "url": base + "/recent_series",        "type": "category", "_action": "category"},
            {"title": "📺 احدث الحلقات",             "url": base + "/episodes",             "type": "category", "_action": "category"},
            {"title": "📺 الاعلي مشاهدة (مسلسلات)", "url": base + "/series_top_views",    "type": "category", "_action": "category"},
            {"title": "📺 الاعلي IMDB (مسلسلات)",   "url": base + "/series_top_imdb",     "type": "category", "_action": "category"},
            {"title": "📺 المسلسلات القصيرة",        "url": base + "/short_series",         "type": "category", "_action": "category"},
            {"title": "📡 جميع البرامج",             "url": base + "/tvshows",              "type": "category", "_action": "category"},
            {"title": "📡 المضاف حديثا (برامج)",    "url": base + "/recent_tvshows",       "type": "category", "_action": "category"},
            {"title": "📡 احدث الحلقات (برامج)",    "url": base + "/tvepisodes",           "type": "category", "_action": "category"},
            {"title": "📡 الاعلي مشاهدة (برامج)",   "url": base + "/tvshows_top_views",   "type": "category", "_action": "category"},
            {"title": "🌏 مسلسلات اسيوي",            "url": base + "/asian-series",         "type": "category", "_action": "category"},
            {"title": "🌏 المضاف حديثا (اسيوي)",    "url": base + "/recent_asian",         "type": "category", "_action": "category"},
            {"title": "🌏 احدث الحلقات (اسيوي)",    "url": base + "/asian-episodes",       "type": "category", "_action": "category"},
            {"title": "🌏 الاعلي مشاهدة (اسيوي)",   "url": base + "/asian_top_views",     "type": "category", "_action": "category"},
            {"title": "🎌 جميع الانمي",              "url": base + "/anime",                "type": "category", "_action": "category"},
            {"title": "🎌 المضاف حديثا (انمي)",     "url": base + "/recent_anime",         "type": "category", "_action": "category"},
            {"title": "🎌 احدث الحلقات (انمي)",     "url": base + "/anime-episodes",       "type": "category", "_action": "category"},
            {"title": "🎌 الاعلي مشاهدة (انمي)",    "url": base + "/anime_top_views",     "type": "category", "_action": "category"},
        ]
    
    def _extract_cards(self, html, max_items=50):
        post_list_m = re.search(r'<div[^>]+id=["\']postList["\'][^>]*>(.*?)(?=<div[^>]+class="[^"]*subHead|<div[^>]+id="[^"]*footer|</div>\s*</div>\s*</div>\s*</div>\s*<div[^>]+id)', html, re.DOTALL | re.I)
        if post_list_m:
            scope = post_list_m.group(1)
            log("faselhd_hdx: scoped to postList ({} chars)".format(len(scope)))
        else:
            scope = html
            log("faselhd_hdx: postList not found, using full HTML")
    
        items = []
        seen = set()
        pattern = r'<div[^>]*class="postDiv[^"]*"[^>]*>\s*<a\s+href="([^"]+)"[^>]*>(?:(?!<div[^>]*class="postDiv).)*?data-src="([^"]+)"(?:(?!<div[^>]*class="postDiv).)*?<div[^>]*class="h1"[^>]*>([^<]+)</div>'
    
        for m in re.finditer(pattern, scope, re.DOTALL | re.I):
            item_url = self._norm(m.group(1))
            poster = self._norm(m.group(2).split("?")[0])
            title = self._clean_title(m.group(3))
            card_html = m.group(0)
    
            if not item_url or item_url in seen:
                continue
            if "/page/" in item_url:
                continue
    
            qm = re.search(r'<span[^>]*class="[^"]*quality[^"]*"[^>]*>([^<]+)</span>', card_html, re.I)
            im = re.search(r'<span[^>]*class="[^"]*pImdb[^"]*"[^>]*>.*?([\d.]+)', card_html, re.I | re.DOTALL)
    
            item_type = self._classify_type(item_url, title)
    
            seen.add(item_url)
            items.append({
                "title": title,
                "url": item_url,
                "poster": poster,
                "thumb": poster,
                "rating": im.group(1).strip() if im else "",
                "quality": qm.group(1).strip() if qm else "",
                "year": "",
                "type": item_type,
                "_action": "details",
            })
            if len(items) >= max_items:
                break
    
        return items
    
    def get_category_items(self, url, page=1):
        self._update_base(url)
    
        pm = re.search(r'/page/(\d+)/?$', url.rstrip('/'))
        if pm and page == 1:
            page = int(pm.group(1))
    
        log("faselhd_hdx: get_category_items page={} url={}".format(page, url))
    
        clean = re.sub(r'/page/\d+/?$', '', url.rstrip('/'))
        current_url = "{}/page/{}".format(clean, page) if page > 1 else clean + "/"
    
        html, final_url = self._get(current_url, referer=self._get_base())
        if not html:
            log("faselhd_hdx: fetch failed: {}".format(current_url))
            return []
    
        if final_url:
            self._update_base(final_url)
    
        items = self._extract_cards(html)
        log("faselhd_hdx: extracted {} items (page {})".format(len(items), page))
    
        next_n = page + 1
        nm = re.search(r'<a[^>]+class="[^"]*page-link[^"]*"[^>]+href="([^"]+/page/{}(?:[/"?][^"]*)?)"'.format(next_n), html, re.I)
        if nm:
            items.append({
                "title": "➡️ Next Page - Page {}".format(next_n),
                "url": self._norm(nm.group(1).rstrip('/')),
                "type": "category", "_action": "category",
            })
        else:
            arrow = re.search(r'<a[^>]+class="[^"]*page-link[^"]*"[^>]+href="([^"]+)"[^>]*>\s*[›»]\s*</a>', html, re.I)
            if arrow:
                items.append({
                    "title": "➡️ Next Page",
                    "url": self._norm(arrow.group(1).rstrip('/')),
                    "type": "category", "_action": "category",
                })
            else:
                rel = re.search(r'<link[^>]+rel=["\']next["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
                if rel:
                    items.append({
                        "title": "➡️ Next Page",
                        "url": self._norm(rel.group(1).rstrip('/')),
                        "type": "category", "_action": "category",
                    })
    
        return items
    
    def search(self, query, page=1):
        self._update_base(self.BASE_URL)
        url = self.BASE_URL + "/?s=" + quote_plus(query)
        if page > 1:
            url += "&paged=" + str(page)
    
        html, final_url = self._get(url, referer=self.BASE_URL)
        if not html:
            return []
        if final_url:
            self._update_base(final_url)
    
        return self._extract_cards(html)
    
    def get_page(self, url, m_type=None):
        self._update_base(url)
        log("faselhd_hdx: get_page {}".format(url))
    
        html, final_url = self._get(url, referer=self.BASE_URL)
        if not html:
            return {"title": "Error", "servers": [], "items": [], "type": "movie"}
        if final_url:
            self._update_base(final_url)
    
        pid_m = re.search(r'\bpostid-(\d+)\b', html)
        post_id = pid_m.group(1) if pid_m else None
        if post_id:
            log("faselhd_hdx: post_id={}".format(post_id))
    
        title_m = (
            re.search(r'<div[^>]*class="[^"]*h1 title[^"]*"[^>]*>(.*?)(?:<span|</div>)', html, re.I | re.DOTALL) or
            re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html)
        )
        title = self._clean_title(title_m.group(1)) if title_m else ""
    
        poster = ""
        for pat in [
            r'itemprop=["\']image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<div[^>]*class="[^"]*posterImg[^"]*"[^>]*>.*?<img[^>]+src="(https://[^"]+)"',
            r'itemprop=["\']thumbnailUrl["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        ]:
            m = re.search(pat, html, re.I | re.DOTALL)
            if m:
                poster = self._norm(m.group(1).split("?")[0])
                break
    
        plotm = re.search(r'class="singleDesc"[^>]*>(.*?)</div>', html, re.I | re.DOTALL)
        plot = self._clean_title(plotm.group(1)) if plotm else ""
    
        ym = (
            re.search(r'(?:سنة\s*الإنتاج|موعد الصدور)\s*:.*?(\d{4})', html, re.I | re.DOTALL) or
            re.search(r'\b(20\d{2})\b', title)
        )
        year = ym.group(1) if ym else ""
    
        rm = (
            re.search(r'class="singleStar"[^>]*>.*?<strong>([\d.]+)</strong>', html, re.I | re.DOTALL) or
            re.search(r'class="pImdb"[^>]*>.*?([\d.]+)', html, re.I | re.DOTALL)
        )
        rating = rm.group(1) if rm else ""
    
        is_tv_content = (
            "/series" in url or "/episodes" in url or
            "مسلسل" in title or "/anime" in url
        )
        item_type = self._classify_type(url, title)
    
        servers, seen_embed = [], set()
    
        def _add(embed_url, name=None):
            embed_url = str(embed_url).replace("&amp;", "&").replace("&#39;", "").strip()
            if not embed_url or embed_url in seen_embed:
                return
            seen_embed.add(embed_url)
            label = name or "🎬 Server {}".format(len(servers) + 1)
            servers.append({"name": label, "url": embed_url, "type": "embed"})
            log("faselhd_hdx: server {}: {}".format(len(servers), embed_url[:80]))
    
        tabs_m = re.search(r'<ul[^>]*class="[^"]*tabs-ul[^"]*"[^>]*>(.*?)</ul>', html, re.I | re.DOTALL)
        if tabs_m:
            tabs_html = tabs_m.group(1)
            for li_m in re.finditer(
                r'onclick=["\'][^"\']*player_iframe\.location\.href\s*=\s*(?:&#39;|["\'])([^"\'&]+(?:&amp;[^"\'&]+)*)(?:&#39;|["\'])',
                tabs_html, re.I
            ):
                raw_url = self._norm(li_m.group(1).replace("&amp;", "&"))
                snippet = tabs_html[li_m.start():li_m.start() + 300]
                a_m = re.search(r'<a[^>]*>(.*?)</a>', snippet, re.DOTALL | re.I)
                label = "🎬 Server {}".format(len(servers) + 1)
                if a_m:
                    raw_label = re.sub(r'<[^>]+>', '', a_m.group(1)).strip()
                    if raw_label:
                        label = raw_label
                _add(raw_url, label)
    
        ifm = re.search(r'<iframe[^>]+name=["\']player_iframe["\'][^>]+data-src=["\']([^"\']+)["\']', html, re.I)
        if ifm and not servers:
            _add(self._norm(ifm.group(1)))
    
        log("faselhd_hdx: {} servers found".format(len(servers)))
    
        episodes = []
        if is_tv_content:
            for ep_m in re.finditer(
                r'<a[^>]+href="([^"]+(?:faselhdx|faselhd)[^"]+)"[^>]*>[^<]*(?:الحلقة|Episode)\s*(\d+)',
                html, re.I
            ):
                episodes.append({
                    "title": "الحلقة {}".format(ep_m.group(2)),
                    "url": self._norm(ep_m.group(1)),
                    "type": "episode",
                    "_action": "details",
                })
    
        return {
            "url": final_url or url,
            "title": title,
            "plot": plot,
            "poster": poster,
            "thumb": poster,
            "year": year,
            "rating": rating,
            "servers": servers,
            "items": episodes,
            "type": item_type,
        }
    
    def extract_stream(self, url):
        log("faselhd_hdx extract_stream: {}".format(url[:100]))
        url = url.replace("&amp;", "&").strip()
        self._update_base(url)
    
        if ".m3u8" in url:
            if not self._is_real_m3u8(url):
                log("faselhd_hdx: rejected false-positive m3u8: {}".format(url[:80]))
                return None, "", self._get_base()
            quality = "1080p" if "1080" in url else ("720p" if "720" in url else "HD")
            return url, quality, self._get_base()
    
        if "video_player" in url or "player_token" in url:
            log("faselhd_hdx: fetching video_player page")
            html, final_url = self._get(url, referer=self._get_base())
            if html:
                stream = self._extract_m3u8_from_player_page(html)
                if stream:
                    log("faselhd_hdx: extracted m3u8: {}".format(stream[:80]))
                    quality = "1080p" if "1080" in stream else ("720p" if "720" in stream else "HD")
                    return stream, quality, url
    
            player_url = (final_url or url).replace("&amp;", "&")
            log("faselhd_hdx: no m3u8 found, returning player page: {}".format(player_url[:80]))
            return player_url, "HD", self._get_base()
    
        if any(d in url for d in ["t7meel.site", "thmeel", "srvdown", "t7hd"]):
            log("faselhd_hdx: following download link: {}".format(url[:80]))
            try:
                html, final = self._get(url, referer=self._get_base())
                if html:
                    stream = self._extract_m3u8_from_player_page(html)
                    if stream:
                        log("faselhd_hdx: found stream via download link: {}".format(stream[:80]))
                        return stream, "HD", url
                resolved = (final or url).replace("&amp;", "&")
                return resolved, "HD", self._get_base()
            except Exception as e:
                log("faselhd_hdx: download link error: {}".format(e))
                return url, "HD", self._get_base()
    
        from .base import extract_stream as base_extract_stream
        stream_url, quality, ref = base_extract_stream(url)
        if stream_url:
            return stream_url, quality, ref
    
        html, _ = self._get(url, referer=self._get_base())
        if html:
            stream = self._extract_m3u8_from_player_page(html)
            if stream:
                return stream, "HD", self._get_base()
    
        return url, "HD", self._get_base()