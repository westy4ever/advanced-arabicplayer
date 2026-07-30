# -*- coding: utf-8 -*-
"""
Shaheed4u extractor - Fixed for current site structure (shhahidd4u.net / shaheed4u.cash)
Supports: Movies, Series, TV Shows, Wrestling Shows
Uses base.fetch for all HTTP requests.
Inherits from BaseExtractor.
"""

import re
import sys
import json
import time
from .base import BaseExtractor, fetch, urljoin, log, resolve_iframe_chain, extract_stream_all

if sys.version_info[0] == 3:
    from urllib.parse import quote_plus, urlparse, quote
    from html import unescape as html_unescape
else:
    from urllib import quote_plus, quote
    from urlparse import urlparse
    from HTMLParser import HTMLParser
    html_unescape = HTMLParser().unescape


class ShaheedExtractor(BaseExtractor):
    """Extractor for Shaheed4u - shhahidd4u.net / shaheed4u.cash"""
    
    DOMAINS = [
        "https://shhahidd4u.net/",
        "https://shaheed4u.cash/",
        "https://shaied4u.co/",
    ]
    VALID_HOST_MARKERS = ("shhahidd4u.net", "shaheed4u.cash", "shaied4u.co", "shahid4u")
    BLOCKED_HOST_MARKERS = ("alliance4creativity.com",)
    
    def __init__(self):
        super(ShaheedExtractor, self).__init__()
        self.main_url = self.DOMAINS[0]
        self._resolved_base = None
        self._home_html = None
        self._home_last_fetch = 0
    
    def _get_base(self, force_refresh=False):
        if self._resolved_base and not force_refresh and (time.time() - self._home_last_fetch) < 21600:
            return self._resolved_base
    
        for domain in self.DOMAINS:
            html, final_url = fetch(domain, referer=domain)
            if not html:
                continue
            final_url = final_url or domain
            if self._is_blocked_page(html, final_url):
                continue
            if html and ("شاهد" in html or "shahid" in html.lower() or "film" in html.lower() or "مسلسل" in html):
                self._resolved_base = self._site_root(final_url)
                self.main_url = self._resolved_base
                self._home_html = html
                self._home_last_fetch = time.time()
                log("Shaheed: selected base: {}".format(self._resolved_base))
                return self._resolved_base
    
        self._resolved_base = self.DOMAINS[0]
        self.main_url = self._resolved_base
        log("Shaheed: falling back to: {}".format(self._resolved_base))
        return self._resolved_base
    
    def _site_root(self, url):
        parts = urlparse(url)
        return "{}://{}/".format(parts.scheme or "https", parts.netloc)
    
    def _is_blocked_page(self, html, final_url=""):
        text = (html or "").lower()
        final = (final_url or "").lower()
        if not text:
            return True
        challenge_patterns = [
            "just a moment", "cf-chl", "cf-turnstile",
            "challenge", "cloudflare", "browser check",
            "access denied", "blocked", "forbidden",
            "captcha", "verify you are human",
            "cf-browser-verification", "security check",
        ]
        if any(p in text for p in challenge_patterns):
            return True
        if any(m in final for m in self.BLOCKED_HOST_MARKERS):
            return True
        if len(text) < 500 and ("error" in text or "block" in text):
            return True
        return False
    
    def _is_valid_category_page(self, html):
        if not html:
            return False
        if re.search(r'class="[^"]*show-card[^"]*"', html, re.I):
            return True
        if re.search(r'href="[^"]*/(film|episode|series|watch)/[^"]*"', html, re.I):
            return True
        if '<title>' in html and ('افلام' in html or 'مسلسلات' in html):
            if not self._is_blocked_page(html) and len(html) > 5000:
                return True
        return False
    
    def _normalize_url(self, url):
        if not url:
            return ""
        url = html_unescape(url.strip())
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return urljoin(self._get_base(), url)
        return url
    
    def _fetch_live(self, url, referer=None):
        ref = referer or self._get_base()
        html, final_url = fetch(url, referer=ref)
        if self._is_blocked_page(html, final_url):
            self._get_base(force_refresh=True)
            html, final_url = fetch(url, referer=self._get_base())
            if self._is_blocked_page(html, final_url):
                return "", ""
        return html, final_url or url
    
    def _clean_title(self, title):
        if not title:
            return ""
        title = html_unescape(title)
        title = re.sub(r'\s*[-|]\s*شاهد\s*فور\s*يو.*$', '', title)
        title = re.sub(r'\s*[-|]\s*Shahid4u.*$', '', title, flags=re.I)
        return title.strip()
    
    def _extract_servers_from_watch(self, html, base_url):
        """Parse the watch page HTML to extract server information.
        Now uses extract_stream_all to get all quality variants.
        """
        servers = []
        match = re.search(r'let\s+securedServers\s*=\s*(\[.*?\]);', html, re.DOTALL | re.I)
        if not match:
            match = re.search(r'securedServers\s*=\s*(\[.*?\]);', html, re.DOTALL | re.I)
        if match:
            try:
                servers_data = json.loads(match.group(1))
                for idx, server in enumerate(servers_data):
                    name = server.get("name", "Server {}".format(idx+1))
                    hash_val = server.get("hash")
                    if hash_val:
                        embed_url = "{}/embed-stream/{}".format(base_url.rstrip('/'), quote(hash_val))
                        # Get all qualities
                        variants = extract_stream_all(embed_url)
                        if variants:
                            for stream_url, quality in variants:
                                servers.append({
                                    "name": f"{name} - {quality}",
                                    "url": stream_url,
                                    "type": "direct" if stream_url.endswith(('.m3u8', '.mp4')) else "embed"
                                })
                        else:
                            # fallback
                            servers.append({"name": name, "url": embed_url, "type": "embed"})
                return servers
            except Exception as e:
                log("Shaheed: failed to parse securedServers: {}".format(e))

        # Fallback: iframes
        iframe_matches = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
        for src in iframe_matches:
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = urljoin(base_url, src)
            skip_domains = ['youtube', 'facebook', 'twitter', 'google', 'doubleclick',
                            'analytics', 'googletagmanager', 'cloudflareinsights',
                            'adsco.re', 'intelligenceadx']
            if any(x in src.lower() for x in skip_domains):
                continue
            variants = extract_stream_all(src)
            if variants:
                for stream_url, quality in variants:
                    servers.append({
                        "name": f"Embed Player - {quality}",
                        "url": stream_url,
                        "type": "direct" if stream_url.endswith(('.m3u8', '.mp4')) else "embed"
                    })
            else:
                servers.append({"name": "Embed Player", "url": src, "type": "iframe"})
        return servers
    
    def get_categories(self, mtype="movie"):
        base = self._get_base().rstrip("/")
        return [
            {"title": "🎬 افلام اجنبي", "url": base + "/category/افلام-اجنبي", "type": "category", "_action": "category"},
            {"title": "🎬 افلام عربي", "url": base + "/category/افلام-عربي", "type": "category", "_action": "category"},
            {"title": "🎬 افلام هندي", "url": base + "/category/افلام-هندي", "type": "category", "_action": "category"},
            {"title": "🎬 افلام انمي", "url": base + "/category/افلام-انمي", "type": "category", "_action": "category"},
            {"title": "🎬 افلام تركية", "url": base + "/category/افلام-تركية", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات اجنبي", "url": base + "/category/مسلسلات-اجنبي", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات تركية", "url": base + "/category/مسلسلات-تركية", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات انمي", "url": base + "/category/مسلسلات-انمي", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات مدبلجة", "url": base + "/category/مسلسلات-مدبلجة", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات عربي", "url": base + "/category/مسلسلات-عربي", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات هندية", "url": base + "/category/مسلسلات-هندية", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات اسيوية", "url": base + "/category/مسلسلات-اسيوية", "type": "category", "_action": "category"},
            {"title": "🤼 عروض مصارعة", "url": base + "/category/عروض-مصارعة", "type": "category", "_action": "category"},
            {"title": "📺 برامج تلفزيونية", "url": base + "/category/برامج-تلفزيونية", "type": "category", "_action": "category"},
            {"title": "🌙 مسلسلات رمضان 2026", "url": base + "/category/مسلسلات-رمضان-2026", "type": "category", "_action": "category"},
        ]
    
    def get_category_items(self, url, page=1):
        html, _ = self._fetch_live(url)
        if not html:
            return []

        if not self._is_valid_category_page(html):
            self._get_base(force_refresh=True)
            html, _ = self._fetch_live(url)
            if not html or not self._is_valid_category_page(html):
                return []

        items = []
        seen_urls = set()

        for match in re.finditer(r'<a\s[^>]*class="[^"]*show-card[^"]*"[^>]*>(.*?)</a>', html, re.DOTALL | re.I):
            tag_open = html[match.start():match.start() + 300]
            card_content = match.group(1)

            href_m = re.search(r'href="([^"]+)"', tag_open, re.I)
            if not href_m:
                continue
            full_url = self._normalize_url(href_m.group(1))
            if not full_url or full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            poster_url = ""
            poster_m = re.search(r'background-image:\s*url\(([^)]+)\)', tag_open + card_content, re.I)
            if poster_m:
                poster_url = self._normalize_url(poster_m.group(1).strip("'\" "))

            title_m = re.search(r'<p[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</p>', card_content, re.I)
            if not title_m:
                title_m = re.search(r'<[^>]+class="[^"]*title[^"]*"[^>]*>([^<]+)</', card_content, re.I)
            if not title_m:
                title_m = re.search(r'>([^<]{3,})<', card_content)
            title = html_unescape(title_m.group(1).strip()) if title_m else ""
            if not title:
                continue

            quality_m = re.search(r'<span[^>]*class="[^"]*sticker[^"]*"[^>]*>([^<]+)</span>', card_content, re.I)
            quality = quality_m.group(1).strip() if quality_m else ""

            categ_m = re.search(r'<span[^>]*class="[^"]*categ[^"]*"[^>]*>([^<]+)</span>', card_content, re.I)
            category = categ_m.group(1).strip() if categ_m else ""

            item_type = "series" if ("مسلسلات" in category or "عروض" in category or
                                      "/category/مسلسلات" in url or "/category/عروض" in url) else "movie"

            display_title = "{} [{}]".format(title, quality) if quality else title
            items.append({
                "title": display_title,
                "url": full_url,
                "poster": poster_url,
                "plot": category,
                "type": item_type,
                "_action": "details",
            })

        if not items:
            for match in re.finditer(
                r'<(?:article|div)[^>]+class="[^"]*(?:card|item|post|movie)[^"]*"[^>]*>(.*?)</(?:article|div)>',
                html, re.S | re.I
            ):
                block = match.group(1)
                href_m = re.search(r'href="([^"]+)"', block, re.I)
                if not href_m:
                    continue
                full_url = self._normalize_url(href_m.group(1))
                if not full_url or full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                title_m = (re.search(r'<h[1-4][^>]*>([^<]+)</h[1-4]>', block, re.I) or
                           re.search(r'alt="([^"]+)"', block, re.I) or
                           re.search(r'title="([^"]+)"', block, re.I))
                title = html_unescape(title_m.group(1).strip()) if title_m else ""
                if not title:
                    continue

                img_m = (re.search(r'src="([^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', block, re.I) or
                         re.search(r'data-src="([^"]+)"', block, re.I))
                poster_url = self._normalize_url(img_m.group(1)) if img_m else ""

                items.append({
                    "title": title,
                    "url": full_url,
                    "poster": poster_url,
                    "type": "movie",
                    "_action": "details",
                })

        current_page = None
        max_page = None

        curr_match = re.search(
            r'<button[^>]+class="[^"]*page-link[^"]*cursor-normal[^"]*"[^>]*>(\d+)</button>',
            html, re.I
        )
        if curr_match:
            current_page = int(curr_match.group(1))

        page_nums = set()
        for match in re.finditer(r"updateQuery\('page',\s*(\d+)\)", html):
            page_nums.add(int(match.group(1)))
        if page_nums:
            max_page = max(page_nums)

        if current_page is not None and max_page is not None and max_page > current_page:
            sep = "&" if "?" in url else "?"
            items.append({
                "title": "➡️ Next Page",
                "url": url + sep + "page=" + str(current_page + 1),
                "type": "category",
                "_action": "category",
            })

        return items
    
    def search(self, query, page=1):
        base = self._get_base()
        url = base + "/search?s=" + quote_plus(query)
        if page > 1:
            url += "&page=" + str(page)
        html, _ = self._fetch_live(url)
        if not html:
            return []
        return self.get_category_items(url)
    
    def get_page(self, url, m_type=None):
        html, final_url = self._fetch_live(url)

        result = {
            "url": final_url or url,
            "title": "",
            "plot": "",
            "poster": "",
            "servers": [],
            "items": [],
            "type": "movie",
        }

        if not html:
            return result

        title_match = re.search(r'<title>(.*?)</title>', html)
        if title_match:
            title = html_unescape(title_match.group(1))
            title = self._clean_title(title)
            result["title"] = title

        desc_match = re.search(r'<meta\s+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if desc_match:
            result["plot"] = html_unescape(desc_match.group(1))

        poster_match = re.search(r'<meta\s+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if poster_match:
            result["poster"] = self._normalize_url(poster_match.group(1))

        watch_url = None
        if "/watch/" in url:
            watch_url = url
        else:
            watch_link_match = re.search(r'<a[^>]+href=["\']([^"\']+/watch/[^"\']*)["\'][^>]*>.*?مشاهدة', html, re.I | re.S)
            if watch_link_match:
                watch_url = self._normalize_url(watch_link_match.group(1))
            else:
                watch_link_match = re.search(r'<a[^>]+class=["\'][^"\']*watch[^"\']*["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
                if watch_link_match:
                    watch_url = self._normalize_url(watch_link_match.group(1))

        watch_html = None
        if watch_url:
            watch_html, _ = self._fetch_live(watch_url)
        else:
            if "/watch/" in url:
                watch_html = html
                watch_url = url

        if watch_html:
            base_for_embed = self._get_base().rstrip('/')
            servers = self._extract_servers_from_watch(watch_html, base_for_embed)
            if servers:
                result["servers"] = servers
            else:
                log("Shaheed: no servers found on watch page")

            eps_container_match = re.search(r'<div[^>]*id=["\']eps["\'][^>]*>(.*?)</div>', watch_html, re.S | re.I)
            if not eps_container_match:
                eps_container_match = re.search(r'<div[^>]*class=["\'][^"\']*eps[^"\']*["\'][^>]*>(.*?)</div>', watch_html, re.S | re.I)
            if eps_container_match:
                eps_html = eps_container_match.group(1)
                for ep_match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', eps_html, re.S | re.I):
                    ep_url = self._normalize_url(ep_match.group(1))
                    if not ep_url or ep_url == watch_url:
                        continue
                    ep_inner = ep_match.group(2)
                    ep_text = re.sub(r'<[^>]+>', '', ep_inner).strip()
                    ep_num_match = re.search(r'الحلقة\s*(\d+)', ep_text)
                    if ep_num_match:
                        ep_title = "حلقة {}".format(ep_num_match.group(1))
                    else:
                        ep_title = ep_text or "حلقة"
                    if ep_url != watch_url and ep_url not in [item.get("url") for item in result["items"]]:
                        result["items"].append({
                            "title": ep_title,
                            "url": ep_url,
                            "type": "episode",
                            "_action": "details",
                        })
            else:
                log("Shaheed: no episode list found on watch page")

        if result["items"]:
            result["type"] = "series"
        elif "مسلسلات" in url or "series" in url.lower() or "/عروض" in url or "/post/" in url:
            result["type"] = "series"
        elif "/episode/" in url:
            result["type"] = "episode"
        else:
            result["type"] = "movie"

        return result
    
    def extract_stream(self, url):
        log("Shaheed extract_stream: {}".format(url))
        referer = self._get_base()
        if "|" in url:
            parts = url.split("|", 1)
            url = parts[0]
            if "Referer=" in parts[1]:
                referer = parts[1].split("Referer=")[1].strip()

        if url.startswith("/"):
            url = urljoin(self._get_base(), url)

        stream, _ = resolve_iframe_chain(url, referer=referer, max_depth=10)
        if stream:
            return stream, None, referer

        html, _ = fetch(url, referer=referer)
        if html:
            video_src = re.search(r'(?:src|data-src)=["\']([^"\']+\.(?:mp4|m3u8|webm)[^"\']*)["\']', html, re.I)
            if video_src:
                return video_src.group(1), None, referer
            iframe_src = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
            if iframe_src:
                return self.extract_stream(iframe_src.group(1))

        from .base import extract_stream as base_extract_stream
        return base_extract_stream(url)