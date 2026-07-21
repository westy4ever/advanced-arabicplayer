# -*- coding: utf-8 -*-
"""
Wecima extractor - wecima.click
Inherits from BaseExtractor.
"""

import re
import sys
import base64
import json
from .base import BaseExtractor, fetch, log, urljoin

if sys.version_info[0] == 3:
    from urllib.parse import quote_plus, urlparse, quote
    from html import unescape as html_unescape
else:
    from urllib import quote_plus
    from urlparse import urlparse
    from HTMLParser import HTMLParser
    html_unescape = HTMLParser().unescape


class WecimaExtractor(BaseExtractor):
    """Extractor for Wecima - wecima.click"""
    
    DOMAINS = [
        "https://wecima.click/",
        "https://wecima.cx/",
        "https://wecima.bid/",
        "https://www.wecima.site/",
    ]
    VALID_HOST_MARKERS = ("wecima.click", "wecima.cx", "wecima.bid", "wecima.site")
    BLOCKED_HOST_MARKERS = ("alliance4creativity.com",)
    
    CATEGORY_FALLBACKS = {
        "افلام اجنبي":    "/category/foreign-movies",
        "افلام عربي":     "/category/arabic-movies",
        "مسلسلات اجنبي":  "/category/foreign-series",
        "مسلسلات عربية":  "/category/arabic-series",
        "مسلسلات انمي":   "/category/anime-series",
        "تريندج":         "/trends",
    }
    
    def __init__(self):
        super(WecimaExtractor, self).__init__()
        self.main_url = self.DOMAINS[0]
        self._resolved_base = None
        self._home_html = None
    
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
        if "watch it legally" in text or "alliance for creativity" in text:
            return True
        if any(m in final for m in self.BLOCKED_HOST_MARKERS):
            return True
        return False
    
    def _looks_like_wecima_page(self, html):
        text = html or ""
        return (
            "Grid--WecimaPosts" in text
            or "NavigationMenu" in text
            or "Thumb--GridItem" in text
            or "GridItem" in text
            or "WatchServersList" in text
            or "WECIMA" in text
            or "وى سيما" in text
            or "wecima" in text.lower()
        )
    
    def _site_root(self, url):
        parts = urlparse(url)
        return "{}://{}/".format(parts.scheme or "https", parts.netloc)
    
    def _get_base(self):
        if self._resolved_base:
            return self._resolved_base
        for domain in self.DOMAINS:
            log("Wecima: probing {}".format(domain))
            html, final_url = fetch(domain, referer=domain)
            final_url = final_url or domain
            if self._is_blocked_page(html, final_url):
                log("Wecima: blocked {}".format(final_url))
                continue
            if html and self._looks_like_wecima_page(html):
                self._resolved_base = self._site_root(final_url)
                self.main_url = self._resolved_base
                self._home_html = html
                log("Wecima: selected base {}".format(self._resolved_base))
                return self._resolved_base
        self._resolved_base = self.DOMAINS[0]
        self.main_url = self._resolved_base
        log("Wecima: fallback base {}".format(self.main_url))
        return self.main_url
    
    def _search_url(self):
        return self._get_base().rstrip("/") + "/?s="
    
    def _normalize_url(self, url):
        if not url:
            return ""
        url = url.strip()
        try:
            url = url.encode("utf-8").decode("unicode_escape") if "\\u" in url else url
        except Exception:
            pass
        url = url.replace("\\u0026", "&").replace("&amp;", "&").replace("\\/", "/")
        url = html_unescape(url)
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return urljoin(self._get_base(), url)
        if any(m in self._host(url) for m in self.BLOCKED_HOST_MARKERS):
            return ""
        if self._is_valid_site_url(url):
            base_parts = urlparse(self._get_base())
            parts = urlparse(url)
            if parts.netloc != base_parts.netloc and any(m in parts.netloc for m in self.VALID_HOST_MARKERS):
                clean = "{}://{}{}".format(base_parts.scheme, base_parts.netloc, parts.path or "/")
                if parts.query:
                    clean += "?" + parts.query
                return clean
        return url
    
    def _candidate_urls(self, url):
        normalized = self._normalize_url(url)
        if not normalized:
            return []
        parts = urlparse(normalized)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        urls = []
        seen = set()
        seeds = []
        if self.main_url:
            seeds.append(self.main_url)
        seeds.extend(self.DOMAINS)
        if normalized.startswith("http"):
            seeds.insert(0, self._site_root(normalized))
        for domain in seeds:
            if not domain:
                continue
            base = domain if domain.endswith("/") else domain + "/"
            candidate = urljoin(base, path.lstrip("/"))
            if candidate in seen:
                continue
            seen.add(candidate)
            urls.append(candidate)
        if normalized not in seen:
            urls.insert(0, normalized)
        return urls
    
    def _fetch_live(self, url, referer=None):
        for candidate in self._candidate_urls(url):
            log("Wecima: fetching {}".format(candidate))
            html, final_url = fetch(candidate, referer=referer or self._get_base())
            final_url = final_url or candidate
            if self._is_blocked_page(html, final_url):
                log("Wecima: blocked {}".format(final_url))
                continue
            if html and self._looks_like_wecima_page(html):
                log("Wecima: success {}".format(final_url))
                return html, final_url
            if html:
                log("Wecima: page shape mismatch {}".format(final_url))
        log("Wecima: fetch failed for {}".format(url))
        return "", ""
    
    def _clean_html(self, text):
        text = html_unescape(text or "")
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()
    
    def _clean_title(self, title):
        title = self._clean_html(title)
        for token in (
            "مشاهدة فيلم", "مشاهدة مسلسل", "مشاهدة",
            "فيلم", "مسلسل", "اون لاين", "أون لاين",
            "مترجم", "مترجمة", "مدبلج", "مدبلجة",
        ):
            title = title.replace(token, "")
        return re.sub(r"\s+", " ", title).strip(" -|")
    
    def _home_html(self):
        if self._home_html:
            return self._home_html
        base = self._get_base()
        html, final_url = self._fetch_live(base, referer=base)
        self._home_html = html if not self._is_blocked_page(html, final_url) else ""
        return self._home_html
    
    def _guess_type(self, title, url):
        text = "{} {}".format(title or "", url or "").lower()
        if any(t in text for t in ("/episode/", "الحلقة", "حلقة", "/season/")):
            return "episode"
        if any(t in text for t in ("/series", "/seriestv", "مسلسل", "series-", "/season/")):
            return "series"
        return "movie"
    
    def _grid_blocks(self, html):
        blocks = []
        for block in re.split(r'(?=<div[^>]+class="GridItem")', html or "", flags=re.I):
            if 'class="GridItem"' not in block:
                continue
            end_match = re.search(
                r'<ul[^>]+class="PostItemStats"[^>]*>.*?</ul>\s*</div>',
                block, re.S | re.I,
            )
            if end_match:
                blocks.append(block[: end_match.end()])
            else:
                blocks.append(block[:3000])
        return blocks
    
    def _extract_cards(self, html):
        cards = []
        seen = set()
        
        for block in self._grid_blocks(html):
            href_match = re.search(r'<a[^>]+href="([^"]+)"', block, re.I)
            if not href_match:
                continue
            url = self._normalize_url(href_match.group(1))
            if not url or url in seen:
                continue
            
            lowered = url.lower()
            if any(t in lowered for t in ("/category/", "/tag/", "/page/", "/filtering", "/feed/", "/trends")):
                continue
            
            title_match = (
                re.search(r'<h2[^>]+class="hasyear"[^>]*itemprop="name"[^>]*>(.*?)</h2>', block, re.S | re.I) or
                re.search(r'<h2[^>]+class="hasyear"[^>]*>(.*?)</h2>', block, re.S | re.I) or
                re.search(r'title="([^"]+)"', block, re.I)
            )
            title = self._clean_title(title_match.group(1) if title_match else "")
            if not title:
                continue
            
            year = ""
            year_match = re.search(r'<span[^>]+class="year"[^>]*>\(?\s*(\d{4})\s*\)?</span>', block, re.I)
            if year_match:
                year = year_match.group(1)
            
            poster = ""
            poster_match = re.search(r'data-src="([^"]+)"', block, re.I)
            if poster_match:
                poster = poster_match.group(1)
            if not poster:
                poster_match = re.search(r'data-lazy-style="[^"]*url\(([^)]+)\)"', block, re.I)
                if poster_match:
                    poster = poster_match.group(1).strip("'\" ")
            if not poster:
                poster_match = re.search(r'style="[^"]*--image:url\(([^)]+)\)', block, re.I)
                if poster_match:
                    poster = poster_match.group(1).strip("'\" ")
            
            seen.add(url)
            cards.append({
                "title": title,
                "url": url,
                "poster": self._normalize_url(poster) if poster else "",
                "plot": year,
                "type": self._guess_type(title, url),
                "_action": "details",
            })
        
        log("Wecima: extracted {} cards".format(len(cards)))
        return cards
    
    def _extract_next_page(self, html):
        patterns = [
            r'<a[^>]+class="[^"]*next[^"]*page-numbers[^"]*"[^>]+href="([^"]+)"',
            r'<a[^>]+rel="next"[^>]+href="([^"]+)"',
            r'<a[^>]+href="([^"]+)"[^>]*>»</a>',
        ]
        for pat in patterns:
            m = re.search(pat, html or "", re.I)
            if m:
                return self._normalize_url(m.group(1))
        return ""
    
    def _category_from_home(self, label, fallback):
        html = self._home_html()
        for pattern in (
            r'<a[^>]+href="([^"]+)"[^>]*>\s*' + re.escape(label) + r'\s*</a>',
            r'<a[^>]+href="([^"]+)"[^>]*>\s*<span[^>]*>\s*' + re.escape(label) + r'\s*</span>',
        ):
            m = re.search(pattern, html or "", re.S | re.I)
            if m:
                url = self._normalize_url(m.group(1))
                if url:
                    return url
        return self._normalize_url(urljoin(self._get_base(), fallback))
    
    def _decode_wecima_url(self, encoded):
        if not encoded:
            return None
    
        log("Wecima: decoding: {}".format(repr(encoded[:80])))
    
        try:
            cleaned = encoded.strip().replace(' ', '+').replace('+', '')
            cleaned = re.sub(r'[^A-Za-z0-9/=]', '', cleaned)
            fixed = 'aHR0c' + cleaned
            missing_padding = len(fixed) % 4
            if missing_padding:
                fixed += '=' * (4 - missing_padding)
            decoded_bytes = base64.b64decode(fixed)
            decoded_url = decoded_bytes.decode('utf-8', errors='replace')
            decoded_url = decoded_url.replace('\\u0026', '&').replace('\\/', '/')
            if decoded_url.startswith('http://') or decoded_url.startswith('https://'):
                log("Wecima: decode success (prefix scheme): {}".format(decoded_url[:80]))
                return decoded_url
        except Exception as e:
            log("Wecima: prefix-scheme decode failed: {}".format(str(e)[:50]))
    
        try:
            cleaned = encoded.strip().replace(' ', '+')
            cleaned = re.sub(r'[^A-Za-z0-9+/=]', '', cleaned)
            missing_padding = len(cleaned) % 4
            if missing_padding:
                cleaned += '=' * (4 - missing_padding)
            decoded_bytes = base64.b64decode(cleaned)
    
            for encoding in ('ascii', 'utf-8', 'latin-1'):
                try:
                    decoded_url = decoded_bytes.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                decoded_url = decoded_bytes.decode('ascii', errors='replace')
    
            decoded_url = decoded_url.replace('\\u0026', '&').replace('\\/', '/')
            decoded_url = quote(decoded_url, safe=':/?&=#+')
    
            if decoded_url.startswith('//'):
                decoded_url = 'https:' + decoded_url
            elif decoded_url.startswith('https') and not decoded_url.startswith('https://'):
                decoded_url = 'https://' + decoded_url[5:]
            elif decoded_url.startswith('http') and not decoded_url.startswith('http://'):
                decoded_url = 'http://' + decoded_url[4:]
    
            if decoded_url and ('http://' in decoded_url or 'https://' in decoded_url):
                log("Wecima: decode success (plain b64 fallback): {}".format(decoded_url[:80]))
                return decoded_url
        except Exception as e:
            log("Wecima: plain-b64 decode failed: {}".format(str(e)[:50]))
    
        url_pattern = r'[a-zA-Z0-9\-]+\.(?:com|net|org|tv|cx|bid|site|click|show|video|rent|date|live|rip|top|xyz|ps)(?:/[a-zA-Z0-9\-_/]+)?'
        match = re.search(url_pattern, encoded)
        if match:
            url = "https://" + match.group(0)
            log("Wecima: extracted URL pattern: {}".format(url))
            return url
    
        log("Wecima: decode failed entirely for: {}".format(repr(encoded[:80])))
        return None
    
    def _extract_servers(self, html):
        servers = []
        seen = set()
        
        if not html:
            log("Wecima: empty HTML in _extract_servers")
            return []
    
        server_block_match = re.search(r'class="WatchServersList">(.*?)</ul>', html, re.S)
        
        if server_block_match:
            content = server_block_match.group(1)
            items = re.findall(r'data-url="([^"]+)"[^>]*>(.*?)<\/(?:btn|li|div)>', content, re.S)
            
            for encoded_url, inner_html in items:
                decoded_url = self._decode_wecima_url(encoded_url)
                if not decoded_url or not decoded_url.startswith('http'):
                    continue
                    
                if decoded_url not in seen:
                    name_match = re.search(r'<strong>(.*?)</strong>', inner_html)
                    server_name = name_match.group(1).strip() if name_match else "Wecima Server"
                    
                    seen.add(decoded_url)
                    servers.append({"name": server_name, "url": decoded_url, "type": "direct"})
                    log("Wecima: Found server '{}' -> {}".format(server_name, decoded_url[:60]))
    
        if not servers:
            log("Wecima: Targeted block not found, running deep scan fallback...")
            fallback_items = re.findall(r'data-url="([a-zA-Z0-9+/=]{20,})"', html)
            for encoded_url in fallback_items:
                decoded_url = self._decode_wecima_url(encoded_url)
                if decoded_url and decoded_url.startswith('http') and decoded_url not in seen:
                    seen.add(decoded_url)
                    servers.append({"name": "Server Fallback", "url": decoded_url, "type": "direct"})
    
        if not servers:
            log("Wecima: ERROR - No servers found. The site layout may have changed.")
        else:
            log("Wecima: Successfully extracted {} servers".format(len(servers)))
            
        return servers
    
    def _extract_episode_cards(self, html):
        episodes = []
        seen = set()
        for card in self._extract_cards(html):
            title = card.get("title") or ""
            url = card.get("url") or ""
            if "الحلقة" not in title and "حلقة" not in title and "/episode/" not in url.lower():
                continue
            if url in seen:
                continue
            seen.add(url)
            episodes.append({
                "title": title or "حلقة",
                "url": url,
                "type": "episode",
                "_action": "details",
            })
        return episodes
    
    def _parse_json_ld(self, html):
        json_ld_match = re.search(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html or "", re.S | re.I)
        if not json_ld_match:
            return None
        
        try:
            data = json.loads(json_ld_match.group(1))
            return data
        except Exception:
            return None
    
    def _detail_title(self, html):
        data = self._parse_json_ld(html)
        if data:
            if isinstance(data, dict):
                if data.get("name"):
                    return self._clean_title(data["name"])
                if "@graph" in data:
                    for item in data["@graph"]:
                        if item.get("name") and ("فيلم" in item.get("name", "") or "مسلسل" in item.get("name", "")):
                            return self._clean_title(item["name"])
        
        patterns = [
            r'<h1[^>]+itemprop="name"[^>]*>(.*?)</h1>',
            r'<h1[^>]+class="[^"]*title[^"]*"[^>]*>(.*?)</h1>',
            r'<h1[^>]*>(.*?)</h1>',
            r'property="og:title"[^>]+content="([^"]+)"',
        ]
        for pattern in patterns:
            m = re.search(pattern, html or "", re.S | re.I)
            if m:
                title = self._clean_title(m.group(1))
                if title:
                    return title
        return ""
    
    def _detail_plot(self, html):
        data = self._parse_json_ld(html)
        if data:
            if isinstance(data, dict):
                if data.get("description"):
                    desc = self._clean_html(data["description"])
                    if desc and len(desc) > 30:
                        return desc
                if "@graph" in data:
                    for item in data["@graph"]:
                        if item.get("description"):
                            desc = self._clean_html(item["description"])
                            if desc and len(desc) > 30:
                                return desc
        
        patterns = [
            r'<meta[^>]+itemprop="description"[^>]+content="([^"]+)"',
            r'property="og:description"[^>]+content="([^"]+)"',
            r'name="description"[^>]+content="([^"]+)"',
            r'<div[^>]+class="StoryMovieContent"[^>]*>(.*?)</div>',
        ]
        for pattern in patterns:
            m = re.search(pattern, html or "", re.S | re.I)
            if m:
                text = self._clean_html(m.group(1))
                if text and "موقع وي سيما" not in text.lower() and len(text) > 30:
                    return text
        return ""
    
    def _detail_poster(self, html):
        data = self._parse_json_ld(html)
        if data:
            if isinstance(data, dict):
                if data.get("image") and isinstance(data["image"], dict):
                    poster = data["image"].get("url", "")
                    if poster:
                        return self._normalize_url(poster)
                if "@graph" in data:
                    for item in data["@graph"]:
                        if item.get("image") and isinstance(item["image"], dict):
                            poster = item["image"].get("url", "")
                            if poster:
                                return self._normalize_url(poster)
                        if item.get("thumbnailUrl"):
                            return self._normalize_url(item["thumbnailUrl"])
        
        patterns = [
            r'property="og:image"[^>]+content="([^"]+)"',
            r'<meta[^>]+itemprop="thumbnailUrl"[^>]+content="([^"]+)"',
            r'data-lazy-style="[^"]*--img:url\(([^)]+)\)',
            r'data-src="([^"]+)"',
        ]
        for pattern in patterns:
            m = re.search(pattern, html or "", re.I)
            if m:
                poster = m.group(1).strip("'\" ")
                if poster:
                    return self._normalize_url(poster) or poster
        return ""
    
    def _detail_year(self, title, html):
        data = self._parse_json_ld(html)
        if data:
            if isinstance(data, dict):
                if data.get("datePublished"):
                    year_match = re.search(r'(\d{4})', data["datePublished"])
                    if year_match:
                        return year_match.group(1)
                if "@graph" in data:
                    for item in data["@graph"]:
                        if item.get("datePublished"):
                            year_match = re.search(r'(\d{4})', item["datePublished"])
                            if year_match:
                                return year_match.group(1)
        
        m = re.search(r'<span[^>]+class="year"[^>]*>\(?\s*(\d{4})\s*\)?</span>', html or "", re.I)
        if m:
            return m.group(1)
        m = re.search(r'\b(19\d{2}|20\d{2})\b', title or "")
        if m:
            return m.group(1)
        return ""
    
    def _detail_rating(self, html):
        data = self._parse_json_ld(html)
        if data:
            if isinstance(data, dict):
                if "aggregateRating" in data:
                    rating = data["aggregateRating"].get("ratingValue", "")
                    if rating:
                        return str(rating)
                if "@graph" in data:
                    for item in data["@graph"]:
                        if "aggregateRating" in item:
                            rating = item["aggregateRating"].get("ratingValue", "")
                            if rating:
                                return str(rating)
        
        m = re.search(r'"ratingValue"\s*:\s*"?(\\?\d+(?:\.\d+)?)', html or "", re.I)
        if m:
            return m.group(1).replace("\\", "")
        m = re.search(r'(\d+(?:\.\d+)?)\s*/\s*10', html or "", re.I)
        if m:
            return m.group(1)
        return ""
    
    def get_categories(self, mtype="movie"):
        return [
            {"title": "أفلام أجنبية",   "url": self._category_from_home("افلام اجنبي",   self.CATEGORY_FALLBACKS["افلام اجنبي"]),   "type": "category", "_action": "category"},
            {"title": "أفلام عربية",    "url": self._category_from_home("افلام عربي",    self.CATEGORY_FALLBACKS["افلام عربي"]),    "type": "category", "_action": "category"},
            {"title": "مسلسلات أجنبية", "url": self._category_from_home("مسلسلات اجنبي", self.CATEGORY_FALLBACKS["مسلسلات اجنبي"]), "type": "category", "_action": "category"},
            {"title": "مسلسلات عربية",  "url": self._category_from_home("مسلسلات عربية", self.CATEGORY_FALLBACKS["مسلسلات عربية"]), "type": "category", "_action": "category"},
            {"title": "كارتون وانمي",   "url": self._category_from_home("مسلسلات انمي",  self.CATEGORY_FALLBACKS["مسلسلات انمي"]),  "type": "category", "_action": "category"},
            {"title": "ترند",           "url": self._category_from_home("تريندج",        self.CATEGORY_FALLBACKS["تريندج"]),        "type": "category", "_action": "category"},
        ]
    
    def get_category_items(self, url, page=1):
        base = self._get_base()
        html, final_url = self._fetch_live(url, referer=base)
        if self._is_blocked_page(html, final_url):
            log("Wecima: category blocked {}".format(url))
            return []
        items = self._extract_cards(html)
        next_page = self._extract_next_page(html)
        if next_page:
            items.append({"title": "➡️ الصفحة التالية", "url": next_page, "type": "category", "_action": "category"})
        return items
    
    def search(self, query, page=1):
        base = self._get_base()
        items = []
        html = ""
        for search_url in [
            self._search_url() + quote_plus(query),
            urljoin(base, "search/") + quote_plus(query),
        ]:
            html, final_url = self._fetch_live(search_url, referer=base)
            if self._is_blocked_page(html, final_url):
                continue
            items = self._extract_cards(html)
            if items:
                break
        log("Wecima: search '{}' -> {} items".format(query, len(items)))
        if not items:
            return []
        next_page = self._extract_next_page(html)
        if next_page:
            items.append({"title": "➡️ الصفحة التالية", "url": next_page, "type": "category", "_action": "category"})
        return items
    
    def get_page(self, url, m_type=None):
        base = self._get_base()
        html, final_url = self._fetch_live(url, referer=base)
        if self._is_blocked_page(html, final_url) or not html:
            log("Wecima: detail failed {}".format(url))
            return {"title": "Error", "servers": [], "items": [], "type": m_type or "movie"}
    
        title = self._detail_title(html)
        poster = self._detail_poster(html)
        plot = self._detail_plot(html)
        year = self._detail_year(title, html)
        rating = self._detail_rating(html)
    
        servers = self._extract_servers(html)
        episodes = [] if servers else self._extract_episode_cards(html)
        log("Wecima: detail {} -> servers={}, episodes={}".format(url, len(servers), len(episodes)))
    
        item_type = m_type or self._guess_type(title, final_url or url)
        if episodes:
            item_type = "series"
        elif servers and any(t in (title or "") for t in ("الحلقة", "حلقة")):
            item_type = "episode"
    
        return {
            "url": final_url or url,
            "title": title,
            "plot": plot,
            "poster": poster,
            "rating": rating,
            "year": year,
            "servers": servers,
            "items": episodes,
            "type": item_type,
        }
    
    def extract_stream(self, url):
        """Delegate to base extractor."""
        from .base import extract_stream as base_extract_stream
        return base_extract_stream(url)