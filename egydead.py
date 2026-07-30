# -*- coding: utf-8 -*-
"""
EgyDead extractor — WordPress site
Domains: tv10.egydead.live, egydead.com, egydead.fyi, etc.

Inherits from BaseExtractor for common functionality.
"""

import re
import sys
import time
import threading
from .base import BaseExtractor, fetch, log, _correct_stream_url, _extract_quality_from_streamruby_url
from urllib.parse import urljoin, urlparse, quote_plus, quote, unquote
from html import unescape as html_unescape

if sys.version_info[0] == 3:
    from urllib.parse import quote_plus, urljoin, urlparse, quote, unquote
    from html import unescape as html_unescape
else:
    from urllib import quote_plus
    from urlparse import urljoin, urlparse
    from HTMLParser import HTMLParser
    html_unescape = HTMLParser().unescape

# ─── Process-wide base-domain cache ──────────────────────────────────────────
_BASE_CACHE_TTL   = 300   # 5 minutes (reduced from 30 for faster token refresh)
_PROBE_COOLDOWN   = 30    # 30 seconds
_base_cache = {"url": None, "resolved_at": 0, "probed_at": 0}
_base_cache_lock = threading.Lock()


class EgyDeadExtractor(BaseExtractor):
    """Extractor for EgyDead main domain (tv10.egydead.live)."""
    
    MAIN_URL = "https://tv10.egydead.live/"
    
    DOMAINS = [
        "https://tv10.egydead.live/",
        "https://tv9.egydead.live/",
        "https://tv8.egydead.live/",
        "https://tv7.egydead.live/",
        "https://tv.egydead.live/",
        "https://a46.egydead.live/",
        "https://www.egydead.live/",
        "https://egydead.live/",
        "https://egydead.com/",
        "https://egydead.media/",
        "https://egydead.space/",
        "https://egydead.video/",
        "https://egydead.watch/",
        "https://egydead.center/",
        "https://egydead.pics/",
        "https://egydead.org/",
        "https://x7k9f.sbs/",
        "https://egydead.fyi/",
        "https://egydead.lat/",
    ]
    
    VALID_HOST_MARKERS = ("egydead", "x7k9f.sbs")
    BLOCKED_HOST_MARKERS = ("alliance4creativity.com",)
    
    CLEAN_WORDS = [
        "مشاهدة فيلم", "مشاهدة", "فيلم", "مسلسل",
        "مترجمة اون لاين", "مترجم اون لاين",
        "مترجمة", "مترجم", "اون لاين", "أون لاين",
        "مدبلجة", "مدبلج", "كرتون", "انمي",
        "بالمصري", "سلسلة افلام", "عرض", "برنامج", "جميع مواسم",
    ]
    
    def __init__(self):
        super(EgyDeadExtractor, self).__init__()
        self.main_url = self.MAIN_URL
        self._resolved_base = None
    
    def _host(self, url):
        try:
            return (urlparse(url).netloc or "").lower()
        except Exception:
            return ""
    
    def _is_valid_site_url(self, url):
        host = self._host(url)
        if not host:
            return False
        if any(m in host for m in self.BLOCKED_HOST_MARKERS):
            return False
        return any(m in host for m in self.VALID_HOST_MARKERS)
    
    def _is_blocked_page(self, html, final_url=""):
        text = (html or "").lower()
        final = (final_url or "").lower()
        if not text:
            return True
        if "just a moment" in text and ("cf-chl" in text or "challenge" in text):
            return True
        if "enable javascript and cookies to continue" in text:
            return True
        if any(m in final for m in self.BLOCKED_HOST_MARKERS):
            return True
        return False
    
    def _looks_like_egydead_page(self, html):
        text = html or ""
        return (
            "movieItem" in text
            or "BottomTitle" in text
            or "egydead" in text.lower()
            or "serversList" in text
            or "EpsList" in text
            or "seasons-list" in text
        )
    
    def _site_root(self, url):
        parts = urlparse(url)
        return "{}://{}/".format(parts.scheme or "https", parts.netloc)
    
    def _get_base(self):
        """Get the base URL with improved caching and fallback."""
        if self._resolved_base:
            return self._resolved_base

        now = time.time()
        with _base_cache_lock:
            cached_url  = _base_cache["url"]
            resolved_at = _base_cache["resolved_at"]
            probed_at   = _base_cache["probed_at"]

        if cached_url and (now - resolved_at) < _BASE_CACHE_TTL:
            log("EgyDead: reusing cached base {} (resolved {}s ago)".format(cached_url, int(now - resolved_at)))
            self._resolved_base = cached_url
            self.main_url = cached_url
            return cached_url

        if cached_url and (now - probed_at) < _PROBE_COOLDOWN:
            log("EgyDead: skipping full re-probe (cooldown), reusing {} for now".format(cached_url))
            self._resolved_base = cached_url
            self.main_url = cached_url
            return cached_url

        # Try each domain with improved headers
        for domain in self.DOMAINS:
            log("EgyDead: probing {}".format(domain))
            
            # Add proper headers for probing
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            }
            
            html, final_url = fetch(domain, referer=domain, extra_headers=headers)
            final_url = final_url or domain
            
            if not self._is_valid_site_url(final_url):
                log("EgyDead: unexpected host after redirect {}".format(final_url))
                continue
                
            if self._is_blocked_page(html, final_url):
                log("EgyDead: blocked {}".format(final_url))
                continue
                
            if html and self._looks_like_egydead_page(html):
                self._resolved_base = self._site_root(final_url)
                self.main_url = self._resolved_base
                with _base_cache_lock:
                    _base_cache["url"] = self._resolved_base
                    _base_cache["resolved_at"] = now
                    _base_cache["probed_at"] = now
                log("EgyDead: selected base {}".format(self._resolved_base))
                return self._resolved_base
                
        # Fallback to first domain
        self._resolved_base = self.DOMAINS[0]
        self.main_url = self._resolved_base
        with _base_cache_lock:
            _base_cache["url"] = self._resolved_base
            _base_cache["probed_at"] = now
        log("EgyDead: all probes failed, falling back to {}".format(self._resolved_base))
        return self._resolved_base
    
    def _clean_title(self, title):
        title = self._strip_tags(title)
        for word in self.CLEAN_WORDS:
            title = title.replace(word, "")
        title = re.sub(r"\s*\|\s*$", "", title)
        title = re.sub(r"\s*\-\s*$", "", title)
        return re.sub(r"\s+", " ", title).strip(" -|")
    
    def _full_url(self, path):
        if not path:
            return ""
        path = html_unescape(path.strip())
        if path.startswith("//"):
            path = "https:" + path
        elif not path.startswith("http"):
            path = urljoin(self._get_base(), path)
        try:
            path = quote(unquote(path), safe=':/?&=#+')
        except Exception:
            pass
        return path
    
    def _pick_real_image(self, html_chunk):
        best = None
        for img_tag in re.findall(r'<img[^>]+>', html_chunk, re.I):
            tag_candidates = []
            for attr in ('data-src', 'data-lazy-src', 'data-original', 'data-lazy', 'src'):
                m = re.search(attr + r'=["\']([^"\']+)["\']', img_tag, re.I)
                if m:
                    tag_candidates.append(m.group(1))
            for c in tag_candidates:
                if '/wp-content/uploads/' in c:
                    return c
            if best is None and tag_candidates:
                best = tag_candidates[0]
        return best
    
    def _encode_arabic_url(self, url):
        try:
            parsed = urlparse(url)
            path_segments = []
            for segment in parsed.path.split('/'):
                if segment:
                    if any(ord(c) > 127 for c in segment):
                        path_segments.append(quote_plus(segment.encode('utf-8')))
                    else:
                        path_segments.append(segment)
                else:
                    path_segments.append('')
            encoded_path = '/'.join(path_segments)
            if not encoded_path.startswith('/'):
                encoded_path = '/' + encoded_path
            encoded_query = ''
            if parsed.query:
                try:
                    query_parts = []
                    for part in parsed.query.split('&'):
                        if '=' in part:
                            key, val = part.split('=', 1)
                            if any(ord(c) > 127 for c in val):
                                query_parts.append(key + '=' + quote_plus(val.encode('utf-8')))
                            else:
                                query_parts.append(part)
                        else:
                            query_parts.append(part)
                    encoded_query = '&'.join(query_parts)
                except Exception:
                    encoded_query = parsed.query
            encoded_url = parsed._replace(path=encoded_path, query=encoded_query).geturl()
            return encoded_url
        except Exception:
            return url
    
    def _fetch(self, url, referer=None, post_data=None):
        extra = {}
        if post_data:
            extra["Content-Type"] = "application/x-www-form-urlencoded"
            extra["X-Requested-With"] = "XMLHttpRequest"
        extra["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        extra["Accept-Language"] = "ar-EG,ar;q=0.9,en;q=0.8"
        extra["Cache-Control"] = "no-cache"
        extra["Pragma"] = "no-cache"
        extra["Sec-Fetch-Dest"] = "document"
        extra["Sec-Fetch-Mode"] = "navigate"
        extra["Sec-Fetch-Site"] = "none"
        extra["Sec-Fetch-User"] = "?1"
        extra["Upgrade-Insecure-Requests"] = "1"
        encoded_url = self._encode_arabic_url(url)
        return fetch(
            encoded_url,
            referer=referer or self._get_base(),
            extra_headers=extra if extra else None,
            post_data=post_data,
        )
    
    def _extract_quality_from_url(self, url):
        if not url:
            return ""
        # Correct the URL first
        url = _correct_stream_url(url)
        lower = url.lower()
        
        # Check for streamruby quality patterns
        if "_o" in lower or "1080" in lower or "fhd" in lower or "hd1080" in lower or "-f3-" in lower or "_o" in lower or "_x" in lower:
            return "1080p"
        elif "_h" in lower or "720" in lower or "hd" in lower or "hd720" in lower or "-f2-" in lower or "_h" in lower:
            return "720p"
        elif "_n" in lower or "480" in lower or "-f1-" in lower or "_n" in lower:
            return "480p"
        elif "_l" in lower or "360" in lower or "_l" in lower:
            return "360p"
        elif "master.m3u8" in lower or "playlist" in lower:
            return "HD"
        return ""
    
    def _parse_movie_items(self, html, current_url=None):
        items = []
        seen = set()

        for li in re.findall(r'<li[^>]*class=["\'][^"\']*(?:movieItem)[^"\']*["\'][^>]*>(.*?)</li>', html, re.S | re.I):
            url_match = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', li)
            if not url_match:
                continue
            url = self._full_url(url_match.group(1))
            if not url or url in seen:
                continue
            seen.add(url)

            if any(x in url for x in ("/page/", "page=")):
                continue

            title = ""
            title_match = (
                re.search(r'<h1[^>]*class=["\'][^"\']*BottomTitle[^"\']*["\'][^>]*>(.*?)</h1>', li, re.S | re.I) or
                re.search(r'<h[1-3][^>]*>(.*?)</h[1-3]>', li, re.S | re.I) or
                re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', li) or
                re.search(r'<a[^>]+title=["\']([^"\']+)["\']', li)
            )
            if title_match:
                title = self._clean_title(title_match.group(1))

            poster = self._pick_real_image(li)
            if poster:
                poster = self._full_url(poster)
                poster = re.sub(r'-\d+x\d+(?=\.\w+$)', '', poster)
            else:
                poster = ""

            cat_match = re.search(r'<span[^>]*class=["\'][^"\']*cat_name[^"\']*["\'][^>]*>(.*?)</span>', li, re.S | re.I)
            quality = self._strip_tags(cat_match.group(1)) if cat_match else ""

            ep_num = ""
            ep_match = re.search(r'<span[^>]*class=["\'][^"\']*number_episode[^"\']*["\'][^>]*>.*?<em>(\d+)</em>', li, re.S | re.I)
            if ep_match:
                ep_num = ep_match.group(1)

            url_low = url.lower()
            raw_title_text = title_match.group(1) if title_match else ""

            if "/episode/" in url_low or "حلقه" in raw_title_text or ep_num:
                item_type = "episode"
            elif "/season/" in url_low or "موسم" in raw_title_text:
                item_type = "season"
            elif "/serie/" in url_low or "/series/" in url_low or "مسلسل" in raw_title_text:
                item_type = "series"
            else:
                item_type = "movie"

            display_title = title
            if ep_num and item_type == "episode":
                display_title = "{} - حلقة {}".format(title, ep_num)

            if display_title:
                items.append({
                    "title": display_title,
                    "url": url,
                    "poster": poster,
                    "plot": quality,
                    "type": item_type,
                    "_action": "details",
                })

        return items
    
    def _episode_number(self, item):
        url = item.get("url", "") or ""
        m = re.search(r'-e(\d{1,4})(?:[-/]|$)', url, re.I)
        if m:
            return int(m.group(1))
        title = item.get("title", "") or ""
        nums = re.findall(r'\d+', title)
        if nums:
            return int(nums[-1])
        return 999999
    
    def _parse_episode_list(self, html):
        items = []
        seen = set()

        eps_match = re.search(r'<div[^>]*class=["\'][^"\']*EpsList[^"\']*["\'][^>]*>(.*?)</div>', html, re.S | re.I)
        if not eps_match:
            return items

        eps_html = eps_match.group(1)
        for ep in re.finditer(r'<li>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>\s*</li>', eps_html, re.S | re.I):
            url = self._full_url(ep.group(1))
            if url in seen or not url:
                continue
            seen.add(url)
            title = self._strip_tags(ep.group(2)).strip()
            items.append({
                "title": "{}".format(title),
                "url": url,
                "type": "episode",
                "_action": "details",
            })

        items.sort(key=self._episode_number)
        return items
    
    def _arabic_season_ordinals(self):
        return {
            "الاول": 1, "الأول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4,
            "الخامس": 5, "السادس": 6, "السابع": 7, "الثامن": 8, "التاسع": 9,
            "العاشر": 10,
        }
    
    def _season_number(self, item):
        url = (item.get("url", "") or "").lower()
        m = re.search(r'[-_]s(\d{1,3})(?:[-/]|$)', url)
        if m:
            return int(m.group(1))
        m2 = re.search(r'season[-_](\d{1,3})', url)
        if m2:
            return int(m2.group(1))
        title = item.get("title", "") or ""
        ordinals = self._arabic_season_ordinals()
        for word, num in ordinals.items():
            if word in title:
                return num
        nums = re.findall(r'\d+', title)
        if nums:
            return int(nums[-1])
        return 999999
    
    def _parse_season_list(self, html):
        items = []
        seen = set()

        season_match = re.search(r'<div[^>]*class=["\'][^"\']*seasons-list[^"\']*["\'][^>]*>(.*?)</div>', html, re.S | re.I)
        if not season_match:
            return items

        season_html = season_match.group(1)
        for item in self._parse_movie_items(season_html):
            if item.get("url") and item.get("url") not in seen:
                seen.add(item.get("url"))
                item["type"] = "season"
                items.append(item)

        numbers = [self._season_number(it) for it in items]
        if items and all(n == 999999 for n in numbers):
            items.reverse()
        else:
            items.sort(key=self._season_number)

        return items
    
    def _parse_pagination(self, html, current_url):
        next_match = re.search(
            r'<a[^>]+class=["\'][^"\']*next[^"\']*(?:page-numbers)?["\'][^>]+href=["\']([^"\']+)["\']',
            html, re.I
        )
        if next_match:
            raw_href = html_unescape(next_match.group(1).strip())
            if raw_href.startswith("http"):
                next_url = raw_href
            elif raw_href.startswith("//"):
                next_url = "https:" + raw_href
            else:
                next_url = urljoin(current_url, raw_href)

            # Rewrite to currently resolved base
            try:
                parsed_next = urlparse(next_url)
                parsed_base = urlparse(self._get_base())
                if parsed_next.netloc and parsed_base.netloc and parsed_next.netloc != parsed_base.netloc:
                    next_url = parsed_next._replace(scheme=parsed_base.scheme, netloc=parsed_base.netloc).geturl()
            except Exception:
                pass

            if next_url and next_url != current_url:
                return {
                    "title": "➡️ Next Page",
                    "url": next_url,
                    "type": "category",
                    "_action": "category",
                }
        return None
    
    def _extract_detail_meta(self, html):
        title = ""
        title_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if title_match:
            title = self._clean_title(title_match.group(1))

        if not title:
            title_match = re.search(r'<title>(.*?)</title>', html, re.I)
            if title_match:
                title = self._clean_title(title_match.group(1).split('|')[0])

        poster = ""
        poster_match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if poster_match and '/wp-content/uploads/' in poster_match.group(1):
            poster = self._full_url(poster_match.group(1))
            poster = re.sub(r'-\d+x\d+(?=\.\w+$)', '', poster)

        if not poster:
            poster_area_match = re.search(r'<div[^>]+class=["\'][^"\']*[Pp]oster[^"\']*["\'][^>]*>(.*?)</div>', html, re.S | re.I)
            found = self._pick_real_image(poster_area_match.group(1)) if poster_area_match else None
            if not found:
                found = self._pick_real_image(html)
            if found:
                poster = self._full_url(found)
                poster = re.sub(r'-\d+x\d+(?=\.\w+$)', '', poster)

        plot = ""
        desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if desc_match:
            plot = self._strip_tags(desc_match.group(1))

        if not plot:
            story_match = re.search(r'<div[^>]*class=["\'][^"\']*singleStory[^"\']*["\'][^>]*>(.*?)</div>', html, re.S | re.I)
            if story_match:
                plot = self._strip_tags(story_match.group(1))

        year = ""
        year_match = re.search(r'\b(19\d{2}|20\d{2})\b', title + " " + plot)
        if year_match:
            year = year_match.group(1)

        return title, poster, plot, year
    
    def _extract_watch_servers(self, html, page_url):
        servers = []
        seen = set()

        servers_html = self._find_servers_html(html)

        if servers_html:
            for li_match in re.finditer(r'<li[^>]*data-link=["\']([^"\']+)["\'][^>]*>(.*?)</li>', servers_html, re.S | re.I):
                video_url = html_unescape(li_match.group(1).strip())
                li_content = li_match.group(2)

                if not video_url or video_url in seen:
                    continue

                if video_url.startswith("//"):
                    video_url = "https:" + video_url
                seen.add(video_url)

                name_match = re.search(r'<span[^>]*><p[^>]*>(.*?)</p></span>', li_content, re.I) or \
                            re.search(r'<p[^>]*>(.*?)</p>', li_content, re.I) or \
                            re.search(r'<span[^>]*>(.*?)</span>', li_content, re.I)

                name = self._strip_tags(name_match.group(1)) if name_match else "Watch Server {}".format(len(servers) + 1)

                quality = self._extract_quality_from_url(video_url)
                servers.append({
                    "name": name.strip(),
                    "url": video_url,
                    "type": "embed",
                    "quality": quality
                })

        if not servers:
            iframe_match = re.search(r'<iframe[^>]+id=["\']videoIframe["\'][^>]+src=["\']([^"\']+)["\']', html, re.I)
            if iframe_match:
                video_url = iframe_match.group(1)
                if video_url and video_url not in seen:
                    seen.add(video_url)
                    quality = self._extract_quality_from_url(video_url)
                    servers.append({
                        "name": "Video Player",
                        "url": video_url,
                        "type": "embed",
                        "quality": quality
                    })

        log("EgyDead: Found {} watch servers for {}".format(len(servers), page_url))
        return servers
    
    def _find_servers_html(self, html):
        m = re.search(
            r'<ul[^>]+class=["\'][^"\']*serversList[^"\']*["\'][^>]*>(.*?)</ul>',
            html, re.S | re.I
        )
        return m.group(1) if m else ""
    
    # ── Public API ───────────────────────────────────────────────────────────

    def get_categories(self, mtype="movie"):
        base = self._get_base()

        if mtype == "movie":
            return [
                {"title": "🎬 English Movies",        "url": self._full_url("/category/english-movies/"),      "type": "category", "_action": "category"},
                {"title": "🇪🇬 Arabic Movies",          "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%b9%d8%b1%d8%a8%d9%8a/"),       "type": "category", "_action": "category"},
                {"title": "🌏 Asian Movies",           "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d8%b3%d9%8a%d9%88%d9%8a%d8%a9/"),     "type": "category", "_action": "category"},
                {"title": "🇹🇷 Turkish Movies",         "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9/"),      "type": "category", "_action": "category"},
                {"title": "🇮🇳 Indian Movies",          "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d9%87%d9%86%d8%af%d9%8a%d8%a9/"),       "type": "category", "_action": "category"},
                {"title": "🎭 Cartoon Movies",         "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d9%83%d8%b1%d8%aa%d9%88%d9%86/"),      "type": "category", "_action": "category"},
                {"title": "🎌 Anime Movies",           "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d9%86%d9%85%d9%8a/"),       "type": "category", "_action": "category"},
                {"title": "📽️ Documentary Movies",    "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d9%88%d8%ab%d8%a7%d8%a6%d9%82%d9%8a%d8%a9/"),    "type": "category", "_action": "category"},
                {"title": "🎬 All Movies",             "url": self._full_url("/category/movies/"),             "type": "category", "_action": "category"},
            ]

        return [
            {"title": "📺 Complete Series",      "url": self._full_url("/serie/"),              "type": "category", "_action": "category"},
            {"title": "📺 Complete Seasons",     "url": self._full_url("/season/"),             "type": "category", "_action": "category"},
            {"title": "📺 Episodes",             "url": self._full_url("/episode/"),            "type": "category", "_action": "category"},
            {"title": "📺 English Series",        "url": self._full_url("/series-category/english-series/"),    "type": "category", "_action": "category"},
            {"title": "🇪🇬 Arabic Series",         "url": self._full_url("/series-category/arabic-series/"),     "type": "category", "_action": "category"},
            {"title": "🇹🇷 Turkish Series",       "url": self._full_url("/series-category/turkish-series/"),    "type": "category", "_action": "category"},
            {"title": "🌏 Asian Series",          "url": self._full_url("/series-category/asian-series/"),      "type": "category", "_action": "category"},
            {"title": "🎌 Anime Series",          "url": self._full_url("/series-category/anime-series/"),      "type": "category", "_action": "category"},
            {"title": "🎠 Cartoon Series",        "url": self._full_url("/series-category/cartoon-series/"),    "type": "category", "_action": "category"},
            {"title": "🇮🇳 Indian Series",         "url": self._full_url("/series-category/indian-series/"),     "type": "category", "_action": "category"},
            {"title": "📽️ Documentary Series",    "url": self._full_url("/series-category/documentary-series/"), "type": "category", "_action": "category"},
            {"title": "📡 TV Shows",              "url": self._full_url("/series-category/tv-shows/"),          "type": "category", "_action": "category"},
        ]

    def get_category_items(self, url, page=None):
        fetch_url = url
        if page and page > 1:
            if '/page/' in fetch_url:
                fetch_url = re.sub(r'/page/\d+', f'/page/{page}', fetch_url)
            elif re.search(r'[?&]page=\d+', fetch_url):
                fetch_url = re.sub(r'([?&]page=)\d+', r'\g<1>' + str(page), fetch_url)
            elif fetch_url.endswith('/'):
                fetch_url = f"{fetch_url}page/{page}/"
            else:
                fetch_url = f"{fetch_url}/page/{page}/"

        log("EgyDead: Fetching category page: {}".format(fetch_url))
        html, final_url = self._fetch(fetch_url)
        if not html:
            log("EgyDead: get_category_items failed: {}".format(fetch_url))
            return []

        items = self._parse_movie_items(html)

        if not page or page == 1:
            nxt = self._parse_pagination(html, fetch_url)
            if nxt:
                items.append(nxt)

        log("EgyDead: category {} page {} → {} items".format(url, page or 1, len(items)))
        return items

    def search(self, query, page=1):
        search_url = self._get_base().rstrip("/") + "/?s=" + quote_plus(query)
        if page > 1:
            search_url += "&paged={}".format(page)

        html, final_url = self._fetch(search_url)
        if not html:
            log("EgyDead: search failed for '{}'".format(query))
            return []

        items = self._parse_movie_items(html)

        if page == 1:
            nxt = self._parse_pagination(html, search_url)
            if nxt:
                items.append(nxt)

        log("EgyDead: search '{}' → {} items".format(query, len(items)))
        return items

    def get_page(self, url, m_type=None):
        html, final_url = self._fetch(url)
        result = {
            "url": url,
            "title": "",
            "poster": "",
            "plot": "",
            "year": "",
            "rating": "",
            "servers": [],
            "items": [],
            "type": m_type or "movie",
        }

        if not html:
            log("EgyDead: get_page failed: {}".format(url))
            return result

        url_low = url.lower()

        if "/episode/" in url_low:
            log("EgyDead: parsing episode page")
            title, poster, plot, year = self._extract_detail_meta(html)
            result["title"] = title
            result["poster"] = poster
            result["plot"] = plot
            result["year"] = year
            result["type"] = "episode"

            servers = self._extract_watch_servers(html, final_url or url)
            if not servers:
                log("EgyDead: no servers on initial load, retrying with View=1 POST")
                post_html, post_final_url = self._fetch(url, post_data={"View": "1"})
                if post_html:
                    servers = self._extract_watch_servers(post_html, post_final_url or url)

            result["servers"] = servers
            log("EgyDead: episode {} → {} servers".format(title, len(servers)))
            return result

        if "/season/" in url_low:
            log("EgyDead: parsing season page")
            title, poster, plot, year = self._extract_detail_meta(html)
            result["title"] = title
            result["poster"] = poster
            result["plot"] = plot
            result["year"] = year
            result["type"] = "season"

            episodes = self._parse_episode_list(html)
            result["items"] = episodes
            log("EgyDead: season {} → {} episodes".format(title, len(episodes)))
            return result

        if "/serie/" in url_low or "/series/" in url_low:
            log("EgyDead: parsing series page")
            title, poster, plot, year = self._extract_detail_meta(html)
            result["title"] = title
            result["poster"] = poster
            result["plot"] = plot
            result["year"] = year
            result["type"] = "series"

            seasons = self._parse_season_list(html)
            result["items"] = seasons
            log("EgyDead: series {} → {} seasons".format(title, len(seasons)))
            return result

        log("EgyDead: parsing movie page (fallback)")
        title, poster, plot, year = self._extract_detail_meta(html)
        result["title"] = title
        result["poster"] = poster
        result["plot"] = plot
        result["year"] = year
        result["type"] = "movie"

        servers = self._extract_watch_servers(html, final_url or url)
        if not servers:
            log("EgyDead: no servers on initial load, retrying with View=1 POST")
            post_html, post_final_url = self._fetch(url, post_data={"View": "1"})
            if post_html:
                servers = self._extract_watch_servers(post_html, post_final_url or url)

        result["servers"] = servers
        log("EgyDead: movie {} → {} servers".format(title, len(servers)))
        return result

    def extract_stream(self, url):
        """
        Resolve a server URL to a playable stream.
        Enhanced to handle all EgyDead CDN patterns including .txt and .woff2 manifests.
        """
        from .base import resolve_streamruby, resolve_host, resolve_mixdrop, resolve_doodstream, get_last_quality_variants, get_synthesized_variants, extract_stream as base_extract_stream, _correct_stream_url, _extract_quality_from_streamruby_url

        def _variants_for(stream):
            v = [(lbl, u) for lbl, u in get_last_quality_variants() if u != stream]
            if not v:
                v = [(lbl, u) for lbl, u in get_synthesized_variants(stream) if u != stream]
            return v

        # Correct the URL first
        url = _correct_stream_url(url)
        low = (url or "").lower()

        # ─── STREAMRUBY ──────────────────────────────────────────────────────
        if "stmruby" in low or "streamruby" in low:
            stream = resolve_streamruby(url)
            if stream:
                stream = _correct_stream_url(stream)
                quality = _extract_quality_from_streamruby_url(stream)
                variants = _variants_for(stream)
                return (
                    stream + "|Referer=https://stmruby.com/&Origin=https://stmruby.com",
                    quality,
                    "https://stmruby.com/",
                    variants,
                )

        # ─── MIXDROP ────────────────────────────────────────────────────────
        if "mixdrop" in low or "mxcontent" in low:
            stream = resolve_mixdrop(url)
            if stream:
                stream = _correct_stream_url(stream)
                variants = _variants_for(stream)
                return stream, None, None, variants

        # ─── DOODSTREAM ─────────────────────────────────────────────────────
        if "dood" in low or "doodstream" in low or "cloudatacdn" in low:
            stream = resolve_doodstream(url)
            if stream:
                stream = _correct_stream_url(stream)
                variants = _variants_for(stream)
                return stream, None, None, variants

        # ─── GOVID ──────────────────────────────────────────────────────────
        if "govid.live" in low:
            try:
                from .base import resolve_govid
                stream = resolve_govid(url)
                if stream:
                    stream = _correct_stream_url(stream)
                    variants = _variants_for(stream)
                    return stream, None, None, variants
            except ImportError:
                pass

        # ─── .TXT MANIFESTS (Maplecrest, etc.) ─────────────────────────────
        if ".txt" in low and ("systemorchestration" in low or "highqualityprints" in low or "dramiyos" in low or "maplecrest" in low or "lakesideproductionstudio" in low):
            log("EgyDead: .txt HLS manifest detected: {}".format(url[:80]))
            html, _ = fetch(url, referer=self._get_base())
            if html and "#EXTM3U" in html:
                variants = self._detect_quality_variants(url)
                if variants:
                    for label, variant_url in variants:
                        variant_url = _correct_stream_url(variant_url)
                        if "f3" in variant_url or "1080" in variant_url:
                            return variant_url, "1080p", self._get_base(), variants
                        elif "f2" in variant_url or "720" in variant_url:
                            return variant_url, "720p", self._get_base(), variants
                    return variants[0][1], variants[0][0], self._get_base(), variants[1:] if len(variants) > 1 else []
                return url, "HD", self._get_base(), []

        # ─── .M3U8 DIRECT ──────────────────────────────────────────────────
        if ".m3u8" in low:
            variants = self._detect_quality_variants(url)
            if variants:
                quality = "HD"
                for label, variant_url in variants:
                    variant_url = _correct_stream_url(variant_url)
                    if "f3" in variant_url or "1080" in variant_url or "_o" in variant_url or "_x" in variant_url:
                        quality = "1080p"
                    elif "f2" in variant_url or "720" in variant_url or "_h" in variant_url:
                        quality = "720p"
                    elif "f1" in variant_url or "480" in variant_url or "_n" in variant_url:
                        quality = "480p"
                    elif "_l" in variant_url or "360" in variant_url:
                        quality = "360p"
                return url, quality, self._get_base(), variants

            quality = "HD"
            if "1080" in low or "fhd" in low:
                quality = "1080p"
            elif "720" in low or "hd" in low:
                quality = "720p"
            elif "480" in low:
                quality = "480p"
            elif "360" in low:
                quality = "360p"
            return url, quality, self._get_base(), []

        # ─── .MP4 DIRECT ────────────────────────────────────────────────────
        if ".mp4" in low:
            quality = "HD"
            if "1080" in low:
                quality = "1080p"
            elif "720" in low:
                quality = "720p"
            elif "480" in low:
                quality = "480p"
            return url, quality, self._get_base(), []

        # ─── VIBUXER ────────────────────────────────────────────────────────
        if "vibuxer" in low:
            log("EgyDead: vibuxer embed detected: {}".format(url[:80]))
            html, _ = fetch(url, referer=self._get_base())
            if html:
                iframe = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
                if iframe:
                    return self.extract_stream(iframe.group(1))
                stream = re.search(r'(https?://[^\s"\'<>]+\.(?:m3u8|txt|woff2)[^\s"\'<>]*)', html, re.I)
                if stream:
                    return self.extract_stream(_correct_stream_url(stream.group(1)))
            return None, "", self._get_base(), []

        # ─── FALLBACK ──────────────────────────────────────────────────────
        return base_extract_stream(url)
    
    def _detect_quality_variants(self, stream_url):
        if not stream_url:
            return []
        
        # Correct the URL first
        stream_url = _correct_stream_url(stream_url)
        
        variants = []
        seen = set()
        
        # ─── STREAMRUBY QUALITY PATTERN: _,l,n,h,o,.urlset/ ──────────────
        # Example: psbm7b7diwj7_,l,n,h,o,.urlset/master.m3u8
        quality_pattern = re.search(r'([^/]+)_(?:,l|,n|,h|,o|,l,n,h,o|,l,n,h|,l,n,o|,l,h,o|,n,h,o|,l,n|,l,h|,l,o|,n,h|,n,o|,h,o|,l,n,h,o|,l,n,h|,l,n,o|,l,h,o|,n,h,o)\.urlset/', stream_url)
        if quality_pattern:
            base_part = stream_url[:quality_pattern.start(1)]
            rest = stream_url[quality_pattern.end():]
            
            # Define quality mappings for streamruby
            quality_map = {
                '_l': '360p',
                '_n': '480p', 
                '_h': '720p',
                '_o': 'Original',
                '_x': 'Original'
            }
            
            # Try to find all quality variants
            for suffix, label in quality_map.items():
                # Construct variant URL
                variant_url = base_part + suffix + rest
                
                # For streamruby, the variant might be in the folder name
                # Alternative: the variant is in the filename pattern
                if '/_l/' in variant_url or '/_n/' in variant_url or '/_h/' in variant_url or '/_o/' in variant_url:
                    # Already has variant in path
                    pass
                else:
                    # Try to insert variant before .urlset
                    variant_url = re.sub(r'(_[lnho])\.urlset', r'\1.urlset', variant_url)
                    variant_url = variant_url.replace('_.urlset', '_' + suffix + '.urlset')
                
                if variant_url not in seen:
                    seen.add(variant_url)
                    variants.append((label, variant_url))
            
            # Also check if the base URL itself has a quality indicator
            if '_o' in stream_url:
                variants.insert(0, ('Original', stream_url))
            elif '_h' in stream_url:
                variants.insert(0, ('720p', stream_url))
            elif '_n' in stream_url:
                variants.insert(0, ('480p', stream_url))
            elif '_l' in stream_url:
                variants.insert(0, ('360p', stream_url))
            
            return variants
        
        # ─── F1/F2/F3 PATTERN ──────────────────────────────────────────────
        f_match = re.search(r'(index-?f?)(\d+)([-_v][^\s"\'<>]+\.(?:m3u8|txt))', stream_url, re.I)
        if f_match:
            prefix = f_match.group(1)
            suffix = f_match.group(3)
            base_part = stream_url[:f_match.start(1)] + prefix
            
            for quality, label in [('f1', '480p'), ('f2', '720p'), ('f3', '1080p'), ('f4', 'Original')]:
                variant_url = _correct_stream_url(base_part + quality + suffix)
                if variant_url not in seen:
                    seen.add(variant_url)
                    variants.append((label, variant_url))
            return variants
        
        # ─── _LNHO PATTERN ──────────────────────────────────────────────────
        l_match = re.search(r'(_[lnho])(?=/)', stream_url)
        if l_match:
            suffix_map = {'_l': '360p', '_n': '480p', '_h': '720p', '_o': 'Original', '_x': 'Original'}
            base_part = stream_url[:l_match.start()]
            rest = stream_url[l_match.end():]
            
            for s, label in suffix_map.items():
                variant_url = _correct_stream_url(base_part + s + rest)
                if variant_url not in seen:
                    seen.add(variant_url)
                    variants.append((label, variant_url))
            return variants
        
        # ─── HLS PATTERN ────────────────────────────────────────────────────
        q_match = re.search(r'/hls[23]/', stream_url)
        if q_match:
            variants.append(('HD', stream_url))
        
        return variants