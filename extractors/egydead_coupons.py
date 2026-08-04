# -*- coding: utf-8 -*-
"""
EgyDead Coupons extractor — WordPress site
Domain: egydead.coupons

Inherits from BaseExtractor for common functionality.
Uses Arabic URL structure for categories.
"""

import re
import sys
from .base import BaseExtractor, fetch, log
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


class EgyDeadCouponsExtractor(BaseExtractor):
    """Extractor for EgyDead Coupons domain (egydead.coupons)."""
    
    MAIN_URL = "https://egydead.coupons/"
    
    DOMAINS = [
        "https://egydead.coupons/",
        "https://www.egydead.coupons/",
    ]
    
    VALID_HOST_MARKERS = ("egydead.coupons",)
    BLOCKED_HOST_MARKERS = ("alliance4creativity.com",)
    
    CLEAN_WORDS = [
        "مشاهدة فيلم", "مشاهدة", "فيلم", "مسلسل",
        "مترجمة اون لاين", "مترجم اون لاين",
        "مترجمة", "مترجم", "اون لاين", "أون لاين",
        "مدبلجة", "مدبلج", "كرتون", "انمي",
        "بالمصري", "سلسلة افلام", "عرض", "برنامج", "جميع مواسم",
    ]
    
    # Category URL mappings for Arabic slugs
    CATEGORY_URLS = {
        # Movies
        "افلام اجنبي": "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d8%ac%d9%86%d8%a8%d9%8a/",
        "افلام اسيوية": "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d8%b3%d9%8a%d9%88%d9%8a%d8%a9/",
        "افلام تركية": "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9/",
        "افلام عربي": "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%b9%d8%b1%d8%a8%d9%8a/",
        "افلام هندي": "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d9%87%d9%86%d8%af%d9%8a/",
        "افلام انمي": "/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d9%86%d9%85%d9%8a/",
        # Series
        "مسلسلات اجنبي": "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%a7%d8%ac%d9%86%d8%a8%d9%8a/",
        "مسلسلات اسيوية": "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%a7%d8%b3%d9%8a%d9%88%d9%8a%d8%a9/",
        "مسلسلات تركية": "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9/",
        "مسلسلات عربي": "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b9%d8%b1%d8%a8%d9%8a/",
        "مسلسلات مدبلجة": "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d9%85%d8%af%d8%a8%d9%84%d8%ac%d8%a9/",
        "مسلسلات هندية": "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d9%87%d9%86%d8%af%d9%8a%d8%a9/",
        "مسلسلات انمي": "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%a7%d9%86%d9%85%d9%8a/",
        # Ramadan Series
        "مسلسلات رمضان 2022": "/category/%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2022/",
        "مسلسلات رمضان 2023": "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2023/",
        "مسلسلات رمضان 2024": "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2024/",
        "مسلسلات رمضان 2025": "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2025/",
        "مسلسلات رمضان 2026": "/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2026/",
        # Other
        "برامج تلفزيونية": "/category/%d8%a8%d8%b1%d8%a7%d9%85%d8%ac-%d8%aa%d9%84%d9%81%d8%b2%d9%8a%d9%88%d9%86%d9%8a%d8%a9/",
        "عروض مصارعة": "/category/%d8%b9%d8%b1%d9%88%d8%b6-%d9%85%d8%b5%d8%a7%d8%b1%d8%b9%d8%a9/",
    }
    
    def __init__(self):
        super(EgyDeadCouponsExtractor, self).__init__()
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
            or "single-header" in text
        )
    
    def _site_root(self, url):
        parts = urlparse(url)
        return "{}://{}/".format(parts.scheme or "https", parts.netloc)
    
    def _get_base(self):
        if self._resolved_base:
            return self._resolved_base
        for domain in self.DOMAINS:
            log("EgyDeadCoupons: probing {}".format(domain))
            html, final_url = fetch(domain, referer=domain)
            final_url = final_url or domain
            if not self._is_valid_site_url(final_url):
                log("EgyDeadCoupons: unexpected host after redirect {}".format(final_url))
                continue
            if self._is_blocked_page(html, final_url):
                log("EgyDeadCoupons: blocked {}".format(final_url))
                continue
            if html and self._looks_like_egydead_page(html):
                self._resolved_base = self._site_root(final_url)
                self.main_url = self._resolved_base
                log("EgyDeadCoupons: selected base {}".format(self._resolved_base))
                return self._resolved_base
        self._resolved_base = self.DOMAINS[0]
        self.main_url = self._resolved_base
        log("EgyDeadCoupons: all probes failed, falling back to {}".format(self._resolved_base))
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
        lower = url.lower()
        if "1080" in lower or "fhd" in lower or "hd1080" in lower or "-f3-" in lower or "_o" in lower or "_x" in lower:
            return "1080p"
        elif "720" in lower or "hd" in lower or "hd720" in lower or "-f2-" in lower or "_h" in lower:
            return "720p"
        elif "480" in lower or "-f1-" in lower or "_n" in lower:
            return "480p"
        elif "360" in lower or "_l" in lower:
            return "360p"
        elif "master.m3u8" in lower or "playlist" in lower:
            return "HD"
        return ""
    
    def _parse_movie_items(self, html, current_url=None):
        """Parse movie items with enhanced pattern matching."""
        items = []
        seen = set()

        # Try multiple patterns for movie items
        item_patterns = [
            r'<li[^>]*class=["\'][^"\']*(?:movieItem|post-item|film-item|m-item)[^"\']*["\'][^>]*>(.*?)</li>',
            r'<div[^>]*class=["\'][^"\']*(?:movieItem|post-item|film-item)[^"\']*["\'][^>]*>(.*?)</div>',
        ]
        
        for pattern in item_patterns:
            matches = re.findall(pattern, html, re.S | re.I)
            if matches:
                for match in matches:
                    self._parse_single_item(match, current_url, items, seen)
                break
        else:
            # Fallback: find any link with image
            for a in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
                url = self._full_url(a.group(1))
                if not url or url in seen:
                    continue
                if any(x in url for x in ("/page/", "page=", "#", "javascript:")):
                    continue
                content = a.group(2)
                if '<img' in content:
                    seen.add(url)
                    title = self._clean_title(re.sub(r'<[^>]+>', ' ', content).strip())
                    poster = self._pick_real_image(content)
                    if poster:
                        poster = self._full_url(poster)
                        poster = re.sub(r'-\d+x\d+(?=\.\w+$)', '', poster)
                    items.append({
                        "title": title or "Untitled",
                        "url": url,
                        "poster": poster or "",
                        "type": "movie",
                        "_action": "details",
                    })
        
        return items
    
    def _parse_single_item(self, html_chunk, current_url, items, seen):
        """Parse a single movie item from HTML."""
        url_match = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', html_chunk)
        if not url_match:
            return
        
        url = self._full_url(url_match.group(1))
        if not url or url in seen:
            return
        if any(x in url for x in ("/page/", "page=", "#", "javascript:")):
            return
        seen.add(url)

        # Extract title
        title = ""
        title_match = (
            re.search(r'<h[1-3][^>]*class=["\'][^"\']*BottomTitle[^"\']*["\'][^>]*>(.*?)</h[1-3]>', html_chunk, re.S | re.I) or
            re.search(r'<h[1-3][^>]*>(.*?)</h[1-3]>', html_chunk, re.S | re.I) or
            re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', html_chunk) or
            re.search(r'<a[^>]+title=["\']([^"\']+)["\']', html_chunk)
        )
        if title_match:
            title = self._clean_title(title_match.group(1))
        
        if not title:
            title = self._clean_title(re.sub(r'<[^>]+>', ' ', html_chunk).strip())

        # Extract poster
        poster = self._pick_real_image(html_chunk)
        if poster:
            poster = self._full_url(poster)
            poster = re.sub(r'-\d+x\d+(?=\.\w+$)', '', poster)
        else:
            poster = ""

        # Extract category
        cat_match = re.search(r'<span[^>]*class=["\'][^"\']*cat_name[^"\']*["\'][^>]*>(.*?)</span>', html_chunk, re.S | re.I)
        category = self._strip_tags(cat_match.group(1)) if cat_match else ""

        # Extract quality/label
        label_match = re.search(r'<span[^>]*class=["\'][^"\']*label[^"\']*["\'][^>]*>(.*?)</span>', html_chunk, re.S | re.I)
        quality = self._strip_tags(label_match.group(1)) if label_match else ""
        
        # Also check URL for quality indicators
        if not quality:
            quality = self._extract_quality_from_url(url)

        # Determine item type from URL
        url_low = url.lower()
        
        if "/episode/" in url_low:
            item_type = "episode"
        elif "/season/" in url_low:
            item_type = "season"
        elif "/serie/" in url_low or "/series/" in url_low:
            item_type = "series"
        elif "/assembly/" in url_low:
            item_type = "collection"
        else:
            item_type = "movie"

        # Build display title
        display_title = title
        if quality and quality not in display_title:
            display_title = "{} [{}]".format(display_title, quality)

        if display_title:
            items.append({
                "title": display_title,
                "url": url,
                "poster": poster,
                "plot": quality or category,
                "type": item_type,
                "_action": "details",
                "quality": quality,
                "category": category,
            })
    
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

        eps_patterns = [
            r'<div[^>]*class=["\'][^"\']*EpsList[^"\']*["\'][^>]*>(.*?)</div>',
            r'<ul[^>]*class=["\'][^"\']*episodes-list[^"\']*["\'][^>]*>(.*?)</ul>',
            r'<div[^>]*id=["\']episodes["\'][^>]*>(.*?)</div>',
        ]
        
        eps_html = None
        for pattern in eps_patterns:
            match = re.search(pattern, html, re.S | re.I)
            if match:
                eps_html = match.group(1)
                break
        
        if not eps_html:
            # Fallback: find all episode links
            for a in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
                url = self._full_url(a.group(1))
                if '/episode/' in url.lower() and url not in seen:
                    seen.add(url)
                    title = self._strip_tags(a.group(2)).strip()
                    if title and not title.startswith('#'):
                        items.append({
                            "title": title,
                            "url": url,
                            "type": "episode",
                            "_action": "details",
                        })
            items.sort(key=self._episode_number)
            return items

        for ep in re.finditer(r'<li>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>\s*</li>', eps_html, re.S | re.I):
            url = self._full_url(ep.group(1))
            if url in seen or not url:
                continue
            seen.add(url)
            title = self._strip_tags(ep.group(2)).strip()
            items.append({
                "title": title or f"Episode {len(items) + 1}",
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

        season_patterns = [
            r'<div[^>]*class=["\'][^"\']*seasons-list[^"\']*["\'][^>]*>(.*?)</div>',
            r'<ul[^>]*class=["\'][^"\']*seasons-list[^"\']*["\'][^>]*>(.*?)</ul>',
        ]
        
        season_html = None
        for pattern in season_patterns:
            match = re.search(pattern, html, re.S | re.I)
            if match:
                season_html = match.group(1)
                break

        if not season_html:
            return items

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
        """Parse pagination with enhanced pattern matching."""
        # Look for next page link with various patterns
        next_patterns = [
            r'<a[^>]+class=["\'][^"\']*next[^"\']*(?:page-numbers)?["\'][^>]+href=["\']([^"\']+)["\']',
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>.*?(?:التالي|Next|»).*?</a>',
            r'<a[^>]+class=["\'][^"\']*page-numbers[^"\']*["\'][^>]+href=["\']([^"\']+)["\'][^>]*>.*?».*?</a>',
        ]
        
        for pattern in next_patterns:
            match = re.search(pattern, html, re.I)
            if match:
                raw_href = html_unescape(match.group(1).strip())
                if raw_href.startswith("http"):
                    next_url = raw_href
                elif raw_href.startswith("//"):
                    next_url = "https:" + raw_href
                else:
                    next_url = urljoin(current_url, raw_href)
                
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
            raw = title_match.group(1).split('|')[0]
            raw = re.sub(r'\s*egydead\s*$', '', raw, flags=re.I)
            title = self._clean_title(raw)

        if not title:
            title_match = re.search(r'<title>(.*?)</title>', html, re.I)
            if title_match:
                raw = title_match.group(1).split('|')[0]
                raw = re.sub(r'\s*egydead\s*$', '', raw, flags=re.I)
                title = self._clean_title(raw)

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
            if not plot:
                story_match = re.search(r'<div[^>]*class=["\'][^"\']*story[^"\']*["\'][^>]*>(.*?)</div>', html, re.S | re.I)
                if story_match:
                    plot = self._strip_tags(story_match.group(1))

        year = ""
        year_match = re.search(r'\b(19\d{2}|20\d{2})\b', title + " " + plot)
        if year_match:
            year = year_match.group(1)
        if not year:
            year_match = re.search(r'/(\d{4})/', html)
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

        log("EgyDeadCoupons: Found {} watch servers for {}".format(len(servers), page_url))
        return servers
    
    def _find_servers_html(self, html):
        m = re.search(
            r'<ul[^>]+class=["\'][^"\']*serversList[^"\']*["\'][^>]*>(.*?)</ul>',
            html, re.S | re.I
        )
        return m.group(1) if m else ""
    
    # ── Public API ───────────────────────────────────────────────────────────
    # Uses Arabic URLs for categories based on actual site structure

    def get_categories(self, mtype="movie"):
        base = self._get_base()
        
        if mtype == "movie":
            return [
                {"title": "🎬 افلام اجنبي",      "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d8%ac%d9%86%d8%a8%d9%8a/"),      "type": "category", "_action": "category"},
                {"title": "🌏 افلام اسيوية",       "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d8%b3%d9%8a%d9%88%d9%8a%d8%a9/"),     "type": "category", "_action": "category"},
                {"title": "🇹🇷 افلام تركية",       "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9/"),      "type": "category", "_action": "category"},
                {"title": "🇪🇬 افلام عربي",         "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%b9%d8%b1%d8%a8%d9%8a/"),           "type": "category", "_action": "category"},
                {"title": "🇮🇳 افلام هندي",         "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d9%87%d9%86%d8%af%d9%8a/"),           "type": "category", "_action": "category"},
                {"title": "🎌 افلام انمي",          "url": self._full_url("/category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d9%86%d9%85%d9%8a/"),           "type": "category", "_action": "category"},
                {"title": "🎬 All Movies",         "url": self._full_url("/%d8%a7%d9%81%d9%84%d8%a7%d9%85/"),                                  "type": "category", "_action": "category"},
            ]

        return [
            {"title": "📺 مسلسلات اجنبي",        "url": self._full_url("/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%a7%d8%ac%d9%86%d8%a8%d9%8a/"),    "type": "category", "_action": "category"},
            {"title": "🌏 مسلسلات اسيوية",       "url": self._full_url("/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%a7%d8%b3%d9%8a%d9%88%d9%8a%d8%a9/"),      "type": "category", "_action": "category"},
            {"title": "🇹🇷 مسلسلات تركية",       "url": self._full_url("/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9/"),    "type": "category", "_action": "category"},
            {"title": "🇪🇬 مسلسلات عربي",        "url": self._full_url("/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b9%d8%b1%d8%a8%d9%8a/"),     "type": "category", "_action": "category"},
            {"title": "🎭 مسلسلات مدبلجة",       "url": self._full_url("/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d9%85%d8%af%d8%a8%d9%84%d8%ac%d8%a9/"),    "type": "category", "_action": "category"},
            {"title": "🇮🇳 مسلسلات هندية",       "url": self._full_url("/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d9%87%d9%86%d8%af%d9%8a%d8%a9/"),     "type": "category", "_action": "category"},
            {"title": "🎌 مسلسلات انمي",         "url": self._full_url("/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%a7%d9%86%d9%85%d9%8a/"),      "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات رمضان 2026",   "url": self._full_url("/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2026/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات رمضان 2025",   "url": self._full_url("/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2025/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات رمضان 2024",   "url": self._full_url("/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2024/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات رمضان 2023",   "url": self._full_url("/category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2023/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات رمضان 2022",   "url": self._full_url("/category/%d8%b1%d9%85%d8%b6%d8%a7%d9%86-2022/"),                          "type": "category", "_action": "category"},
            {"title": "📺 All Series",           "url": self._full_url("/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa/"),                            "type": "category", "_action": "category"},
            {"title": "📡 برامج تلفزيونية",      "url": self._full_url("/category/%d8%a8%d8%b1%d8%a7%d9%85%d8%ac-%d8%aa%d9%84%d9%81%d8%b2%d9%8a%d9%88%d9%86%d9%8a%d8%a9/"), "type": "category", "_action": "category"},
            {"title": "🤼 عروض مصارعة",          "url": self._full_url("/category/%d8%b9%d8%b1%d9%88%d8%b6-%d9%85%d8%b5%d8%a7%d8%b1%d8%b9%d8%a9/"),    "type": "category", "_action": "category"},
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

        log("EgyDeadCoupons: Fetching category page: {}".format(fetch_url))
        html, final_url = self._fetch(fetch_url)
        if not html:
            log("EgyDeadCoupons: get_category_items failed: {}".format(fetch_url))
            return []

        items = self._parse_movie_items(html)

        if not page or page == 1:
            nxt = self._parse_pagination(html, fetch_url)
            if nxt:
                items.append(nxt)

        log("EgyDeadCoupons: category {} page {} → {} items".format(url, page or 1, len(items)))
        return items

    def search(self, query, page=1):
        search_url = self._get_base().rstrip("/") + "/?s=" + quote_plus(query)
        if page > 1:
            search_url += "&paged={}".format(page)

        html, final_url = self._fetch(search_url)
        if not html:
            log("EgyDeadCoupons: search failed for '{}'".format(query))
            return []

        items = self._parse_movie_items(html)

        if page == 1:
            nxt = self._parse_pagination(html, search_url)
            if nxt:
                items.append(nxt)

        log("EgyDeadCoupons: search '{}' → {} items".format(query, len(items)))
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
            log("EgyDeadCoupons: get_page failed: {}".format(url))
            return result

        url_low = url.lower()

        if "/episode/" in url_low:
            log("EgyDeadCoupons: parsing episode page")
            title, poster, plot, year = self._extract_detail_meta(html)
            result["title"] = title
            result["poster"] = poster
            result["plot"] = plot
            result["year"] = year
            result["type"] = "episode"

            servers = self._extract_watch_servers(html, final_url or url)
            if not servers:
                watch_url = (final_url or url).rstrip("/") + "/watch"
                log("EgyDeadCoupons: no servers on initial load, fetching watch page: {}".format(watch_url))
                watch_html, watch_final_url = self._fetch(watch_url)
                if watch_html:
                    servers = self._extract_watch_servers(watch_html, watch_final_url or watch_url)
            if not servers:
                log("EgyDeadCoupons: still no servers, retrying with View=1 POST")
                post_html, post_final_url = self._fetch(url, post_data={"View": "1"})
                if post_html:
                    servers = self._extract_watch_servers(post_html, post_final_url or url)

            result["servers"] = servers
            log("EgyDeadCoupons: episode {} → {} servers".format(title, len(servers)))
            return result

        if "/season/" in url_low:
            log("EgyDeadCoupons: parsing season page")
            title, poster, plot, year = self._extract_detail_meta(html)
            result["title"] = title
            result["poster"] = poster
            result["plot"] = plot
            result["year"] = year
            result["type"] = "season"

            episodes = self._parse_episode_list(html)
            result["items"] = episodes
            log("EgyDeadCoupons: season {} → {} episodes".format(title, len(episodes)))
            return result

        if "/serie/" in url_low or "/series/" in url_low:
            log("EgyDeadCoupons: parsing series page")
            title, poster, plot, year = self._extract_detail_meta(html)
            result["title"] = title
            result["poster"] = poster
            result["plot"] = plot
            result["year"] = year
            result["type"] = "series"

            seasons = self._parse_season_list(html)
            result["items"] = seasons
            log("EgyDeadCoupons: series {} → {} seasons".format(title, len(seasons)))
            return result

        log("EgyDeadCoupons: parsing movie page (fallback)")
        title, poster, plot, year = self._extract_detail_meta(html)
        result["title"] = title
        result["poster"] = poster
        result["plot"] = plot
        result["year"] = year
        result["type"] = "movie"

        servers = self._extract_watch_servers(html, final_url or url)
        if not servers:
            watch_url = (final_url or url).rstrip("/") + "/watch"
            log("EgyDeadCoupons: no servers on initial load, fetching watch page: {}".format(watch_url))
            watch_html, watch_final_url = self._fetch(watch_url)
            if watch_html:
                servers = self._extract_watch_servers(watch_html, watch_final_url or watch_url)
        if not servers:
            log("EgyDeadCoupons: still no servers, retrying with View=1 POST")
            post_html, post_final_url = self._fetch(url, post_data={"View": "1"})
            if post_html:
                servers = self._extract_watch_servers(post_html, post_final_url or url)

        result["servers"] = servers
        log("EgyDeadCoupons: movie {} → {} servers".format(title, len(servers)))
        return result

    def extract_stream(self, url):
        """Delegate to base extractor for stream resolution."""
        from .base import extract_stream as base_extract_stream
        return base_extract_stream(url)