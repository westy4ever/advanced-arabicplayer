# -*- coding: utf-8 -*-
"""
Shahid4u Solar extractor - for shahid4u.cash (formerly shahid4u.solar)
Supports: Movies, Series, TV Shows
Inherits from BaseExtractor.
"""

import re
import sys
import json
import time
import requests
from .base import BaseExtractor, fetch, log, urljoin

if sys.version_info[0] == 3:
    from urllib.parse import quote_plus, urlparse, quote
    from html import unescape as html_unescape
else:
    from urllib import quote_plus, quote
    from urlparse import urlparse
    from HTMLParser import HTMLParser
    html_unescape = HTMLParser().unescape


class Shahid4uSolarExtractor(BaseExtractor):
    """Extractor for Shahid4u - shahid4u.cash / shahid4u.solar"""
    
    DOMAINS = [
        "https://shahid4u.cash/",
        "https://shahid4u.solar/",
    ]
    VALID_HOST_MARKERS = ("shahid4u.cash", "shahid4u.solar")
    BLOCKED_HOST_MARKERS = ("alliance4creativity.com",)
    
    def __init__(self):
        super(Shahid4uSolarExtractor, self).__init__()
        self.main_url = self.DOMAINS[0]
        self._resolved_base = None
        self._home_html = None
        self._home_last_fetch = 0
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "ar,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
    
    def _host(self, url):
        try:
            return (urlparse(url).netloc or "").lower()
        except Exception:
            return ""
    
    def _is_blocked_page(self, html, final_url=""):
        text = (html or "").lower()
        final = (final_url or "").lower()
        if not text:
            return True
        if "just a moment" in text and "cf-chl" in text:
            return True
        if "cf-turnstile" in text:
            return True
        if "challenge" in text and "cloudflare" in text:
            return True
        if "access denied" in text or "blocked" in text:
            return True
        if "alliance for creativity" in text:
            return True
        if any(m in final for m in self.BLOCKED_HOST_MARKERS):
            return True
        return False
    
    def _is_valid_category_page(self, html):
        if not html:
            return False
        if 'class="Small--Box"' in html or 'class="recent--block"' in html:
            return True
        if '<div class="BlocksHolder"' in html:
            return True
        if '<title>' in html and ('افلام' in html or 'مسلسلات' in html):
            if not self._is_blocked_page(html):
                return True
        return False
    
    def _site_root(self, url):
        parts = urlparse(url)
        return "{}://{}/".format(parts.scheme or "https", parts.netloc)
    
    def _get_base(self, force_refresh=False):
        if self._resolved_base and not force_refresh and (time.time() - self._home_last_fetch) < 21600:
            return self._resolved_base
    
        for domain in self.DOMAINS:
            html, final_url = self._fetch_with_retry(domain, referer=domain)
            final_url = final_url or domain
            if self._is_blocked_page(html, final_url):
                continue
            if html and ("شاهد" in html or "shahid" in html.lower() or "film" in html.lower()):
                self._resolved_base = self._site_root(final_url)
                self.main_url = self._resolved_base
                self._home_html = html
                self._home_last_fetch = time.time()
                log("Shahid4u: selected base: {}".format(self._resolved_base))
                return self._resolved_base
    
        self._resolved_base = self.DOMAINS[0]
        self.main_url = self._resolved_base
        log("Shahid4u: falling back to: {}".format(self._resolved_base))
        return self._resolved_base
    
    def _fetch_with_retry(self, url, referer=None, max_retries=3):
        for attempt in range(max_retries):
            try:
                headers = {}
                if referer:
                    headers["Referer"] = referer
                resp = self._session.get(url, headers=headers, timeout=15, allow_redirects=True)
                final_url = resp.url
                html = resp.text
                if self._is_blocked_page(html, final_url):
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    else:
                        return "", final_url
                return html, final_url
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return "", url
        return "", url
    
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
        h, final_url = self._fetch_with_retry(url, referer=ref)
        if self._is_blocked_page(h, final_url):
            self._get_base(force_refresh=True)
            h, final_url = self._fetch_with_retry(url, referer=self._get_base())
            if self._is_blocked_page(h, final_url):
                return "", ""
        return h, final_url or url
    
    def _clean_title(self, title):
        if not title:
            return ""
        title = html_unescape(title)
        title = re.sub(r'\s*[-|]\s*شاهد\s*فور\s*يو.*$', '', title)
        title = re.sub(r'\s*[-|]\s*shahid4u.*$', '', title, flags=re.I)
        return title.strip()
    
    def get_categories(self, mtype="movie"):
        base = self._get_base().rstrip("/")
        return [
            {"title": "🎬 افلام اجنبي", "url": base + "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d8%ac%d9%86%d8%a8%d9%8a/", "type": "category", "_action": "category"},
            {"title": "🎬 افلام اسيوية", "url": base + "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d8%b3%d9%8a%d9%88%d9%8a%d8%a9/", "type": "category", "_action": "category"},
            {"title": "🎬 افلام انمي", "url": base + "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d9%86%d9%85%d9%8a/", "type": "category", "_action": "category"},
            {"title": "🎬 افلام تركية", "url": base + "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9/", "type": "category", "_action": "category"},
            {"title": "🎬 افلام عربي", "url": base + "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%b9%d8%b1%d8%a8%d9%8a/", "type": "category", "_action": "category"},
            {"title": "🎬 افلام هندي", "url": base + "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d9%87%d9%86%d8%af%d9%8a/", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات اجنبي", "url": base + "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%a7%d8%ac%d9%86%d8%a8%d9%8a/", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات اسيوية", "url": base + "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%a7%d8%b3%d9%8a%d9%88%d9%8a%d8%a9/", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات انمي", "url": base + "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%a7%d9%86%d9%85%d9%8a/", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات تركية", "url": base + "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9/", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات عربي", "url": base + "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b9%d8%b1%d8%a8%d9%8a/", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات مدبلجة", "url": base + "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d9%85%d8%af%d8%a8%d9%84%d8%ac%d8%a9/", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات هندية", "url": base + "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d9%87%d9%86%d8%af%d9%8a%d8%a9/", "type": "category", "_action": "category"},
            {"title": "📺 برامج تلفزيونية", "url": base + "/category/%d8%a8%d8%b1%d8%a7%d9%85%d8%ac-%d8%aa%d9%84%d9%81%d8%b2%d9%8a%d9%88%d9%86%d9%8a%d8%a9/", "type": "category", "_action": "category"},
            {"title": "🤼 عروض مصارعة", "url": base + "/category/%d8%b9%d8%b1%d9%88%d8%b6-%d9%85%d8%b5%d8%a7%d8%b1%d8%b9%d8%a9/", "type": "category", "_action": "category"},
            {"title": "🌙 مسلسلات رمضان 2026", "url": base + "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2026/", "type": "category", "_action": "category"},
            {"title": "🌙 مسلسلات رمضان 2025", "url": base + "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2025/", "type": "category", "_action": "category"},
            {"title": "🌙 مسلسلات رمضان 2024", "url": base + "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2024/", "type": "category", "_action": "category"},
            {"title": "🌙 مسلسلات رمضان 2023", "url": base + "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2023/", "type": "category", "_action": "category"},
            {"title": "🌙 رمضان 2022", "url": base + "/category/%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2022/", "type": "category", "_action": "category"},
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
    
        # Pattern for the new shahid4u.cash theme
        box_matches = re.finditer(
            r'<div[^>]*class="[^"]*Small--Box[^"]*"[^>]*>(.*?)</div>\s*(?=<div|$)',
            html, re.S | re.I
        )
        for box_match in box_matches:
            box_html = box_match.group(1)
            a_match = re.search(
                r'<a[^>]*class="[^"]*recent--block[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                box_html, re.S | re.I
            )
            if not a_match:
                continue
            link = self._normalize_url(a_match.group(1))
            if not link or link in seen_urls:
                continue
            seen_urls.add(link)
            inner = a_match.group(2)
    
            poster = ""
            poster_match = re.search(r'<div[^>]*class="[^"]*Poster[^"]*"[^>]*>.*?<img[^>]+data-src="([^"]+)"', box_html, re.S | re.I)
            if poster_match:
                poster = self._normalize_url(poster_match.group(1))
    
            title_match = re.search(r'<inner--title>.*?<h2>(.*?)</h2>', box_html, re.S | re.I)
            if not title_match:
                title_match = re.search(r'<a[^>]*title="([^"]+)"', a_match.group(0), re.I)
            if not title_match:
                continue
            title = html_unescape(title_match.group(1).strip())
            if not title:
                continue
    
            episode_number = ""
            ep_match = re.search(r'<div[^>]*class="[^"]*number[^"]*"[^>]*>.*?<span>الحلقة</span>\s*<em>(\d+)</em>', box_html, re.S | re.I)
            if ep_match:
                episode_number = ep_match.group(1)
                item_type = "episode"
            elif "مسلسلات" in link or "series" in link.lower():
                item_type = "series"
            else:
                item_type = "movie"
    
            display_title = title
            if episode_number:
                display_title = "{} - حلقة {}".format(title, episode_number)
    
            items.append({
                "title": display_title,
                "url": link,
                "poster": poster,
                "plot": "",
                "type": item_type,
                "_action": "details",
            })
    
        # Fallback pattern for older theme
        if not items:
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
    
                item_type = "series" if ("مسلسلات" in full_url or "series" in full_url.lower()) else "movie"
                items.append({
                    "title": title,
                    "url": full_url,
                    "poster": poster_url,
                    "type": item_type,
                    "_action": "details",
                })
    
        # Pagination
        current_page = 1
        page_match = re.search(r'[?&]page=(\d+)|/page/(\d+)/', url)
        if page_match:
            current_page = int(page_match.group(1) or page_match.group(2))
    
        next_match = re.search(r'<a[^>]*class="[^"]*next[^"]*page-numbers[^"]*"[^>]*href="([^"]+)"', html, re.I)
        if next_match:
            next_url = self._normalize_url(next_match.group(1))
            if next_url and next_url != url:
                items.append({
                    "title": "➡️ Next Page",
                    "url": next_url,
                    "type": "category",
                    "_action": "category",
                })
    
        log("Shahid4u: category {} -> {} items (page {})".format(url, len(items), current_page))
        return items
    
    def search(self, query, page=1):
        base = self._get_base()
        url = base + "/?s=" + quote_plus(query)
        if page > 1:
            url += "&page=" + str(page)
        html, _ = self._fetch_live(url)
        if not html:
            return []
        return self.get_category_items(url, page)
    
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
            result["title"] = self._clean_title(title_match.group(1))
    
        og_title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if og_title:
            title = html_unescape(og_title.group(1))
            if title:
                result["title"] = self._clean_title(title)
    
        desc_match = re.search(r'<meta\s+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if desc_match:
            result["plot"] = html_unescape(desc_match.group(1))
    
        poster_match = re.search(r'<meta\s+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if poster_match:
            result["poster"] = self._normalize_url(poster_match.group(1))
    
        # Find watch URL
        watch_url = None
        if '/watch/' in url or "watch=1" in url:
            watch_url = url
        else:
            watch_link_match = re.search(r'<a[^>]+class="[^"]*watch[^"]*"[^>]+href="([^"]+)"', html, re.I)
            if watch_link_match:
                watch_url = self._normalize_url(watch_link_match.group(1))
            else:
                # Check for the watch button
                watch_link_match = re.search(r'<a[^>]+href=["\']([^"\']+/watch/[^"\']*)["\'][^>]*>.*?مشاهدة', html, re.I | re.S)
                if watch_link_match:
                    watch_url = self._normalize_url(watch_link_match.group(1))
    
        watch_html = None
        if watch_url:
            watch_html, _ = self._fetch_live(watch_url)
            if watch_html:
                log("Shahid4u: fetched watch page: {}".format(watch_url[:80]))
        else:
            if '/watch/' in final_url or "watch=1" in final_url:
                watch_html = html
                watch_url = final_url
    
        if watch_html:
            # Extract servers from watch page
            servers = []
            
            # Look for data-watch attributes
            watch_items = re.findall(r'<li[^>]*data-watch="([^"]+)"[^>]*>(.*?)</li>', watch_html, re.S | re.I)
            
            if watch_items:
                for server_url, inner_html in watch_items:
                    server_url = server_url.strip()
                    if not server_url:
                        continue
                    
                    # Extract server name
                    name_match = re.search(r'<i[^>]*></i>\s*(.*?)(?:</li>|$)', inner_html, re.S)
                    if name_match:
                        name = name_match.group(1).strip()
                    else:
                        name = "سيرفر"
                    
                    from .base import extract_stream_all
                    variants = extract_stream_all(server_url)
                    if variants:
                        for stream_url, quality in variants:
                            servers.append({
                                "name": f"{name} - {quality}",
                                "url": stream_url,
                                "type": "direct" if stream_url.endswith(('.m3u8', '.mp4')) else "embed"
                            })
                    else:
                        servers.append({
                            "name": name,
                            "url": server_url,
                            "type": "embed"
                        })
                
                result["servers"] = servers
            
            # Fallback: look for iframes
            if not servers:
                iframe_matches = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', watch_html, re.I)
                for src in iframe_matches:
                    if src.startswith("//"):
                        src = "https:" + src
                    elif src.startswith("/"):
                        src = urljoin(self._get_base(), src)
                    skip_domains = ['youtube', 'facebook', 'twitter', 'google', 'doubleclick',
                                    'analytics', 'googletagmanager', 'cloudflareinsights']
                    if any(x in src.lower() for x in skip_domains):
                        continue
                    
                    from .base import extract_stream_all
                    variants = extract_stream_all(src)
                    if variants:
                        for stream_url, quality in variants:
                            servers.append({
                                "name": f"Embed Player - {quality}",
                                "url": stream_url,
                                "type": "direct" if stream_url.endswith(('.m3u8', '.mp4')) else "embed"
                            })
                    else:
                        servers.append({
                            "name": "Embed Player",
                            "url": src,
                            "type": "iframe"
                        })
                
                result["servers"] = servers
    
        # Extract episodes for series
        episodes = []
        eps_container = re.search(
            r'<div[^>]*class="[^"]*w-100 bg-main rounded my-4[^"]*"[^>]*>.*?جميع الحلقات.*?</div>.*?<div[^>]*class="[^"]*items[^"]*"[^>]*>(.*?)</div>',
            html, re.S | re.I
        )
        if not eps_container:
            eps_container = re.search(r'<div[^>]*id="eps"[^>]*>(.*?)</div>', html, re.S | re.I)
    
        if eps_container:
            eps_html = eps_container.group(1)
            for ep_match in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', eps_html, re.S | re.I):
                ep_url = self._normalize_url(ep_match.group(1))
                if not ep_url or ep_url == url or ep_url == final_url:
                    continue
                ep_inner = ep_match.group(2)
                ep_text = re.sub(r'<[^>]+>', '', ep_inner).strip()
                ep_num_match = re.search(r'الحلقة\s*(\d+)', ep_text)
                if ep_num_match:
                    ep_title = "حلقة {}".format(ep_num_match.group(1))
                else:
                    num_match = re.search(r'\b(\d+)\b', ep_text)
                    if num_match:
                        ep_title = "حلقة {}".format(num_match.group(1))
                    else:
                        ep_title = ep_text or "حلقة"
                if ep_url not in [e.get("url") for e in episodes]:
                    episodes.append({
                        "title": ep_title,
                        "url": ep_url,
                        "type": "episode",
                        "_action": "details",
                    })
            if episodes:
                result["items"] = episodes
                result["type"] = "series"
    
        if '/episode/' in url and not result["items"]:
            result["type"] = "episode"
        elif 'مسلسلات' in url or 'series' in url.lower():
            result["type"] = "series"
        elif result["servers"] and not result["items"]:
            result["type"] = "movie"
    
        return result
    
    def extract_stream(self, url):
        log("Shahid4u extract_stream: {}".format(url))
        referer = self._get_base()
        if "|" in url:
            parts = url.split("|", 1)
            url = parts[0]
            if "Referer=" in parts[1]:
                referer = parts[1].split("Referer=")[1].strip()
    
        from .base import resolve_iframe_chain
        stream, _ = resolve_iframe_chain(url, referer=referer, max_depth=10)
        if stream:
            return stream, None, referer
    
        try:
            resp = self._session.get(url, headers={"Referer": referer}, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                video_src = re.search(r'(?:src|data-src)=["\']([^"\']+\.(?:mp4|m3u8|webm)[^"\']*)["\']', resp.text, re.I)
                if video_src:
                    return video_src.group(1), None, referer
                iframe_src = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', resp.text, re.I)
                if iframe_src:
                    return self.extract_stream(iframe_src.group(1))
        except Exception as e:
            log("Shahid4u: extract_stream fallback error: {}".format(e))
    
        from .base import extract_stream as base_extract_stream
        return base_extract_stream(url)