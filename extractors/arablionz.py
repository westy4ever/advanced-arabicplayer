# -*- coding: utf-8 -*-
"""
Plugin for arablionz.live (formerly arablionztv.xyz)
Inherits from BaseExtractor.
FIX: Replaced f-strings with .format() for Python 2/3.5 compatibility.
FIX: Improved card/episode regex to match modern layouts.
FIX: get_page() now catches data-src/data-lazy-src iframe patterns.
FIX: Added extract_stream_all for multi-quality support.
FIX: Updated domain to arablionz.live.
FIX: Added all categories from the new site navigation.
FIX: Added search functionality.
FIX: Fixed pagination with proper ?page=N format.
FIX: Improved server extraction with data-href attributes.
"""

import re
from urllib.parse import urljoin
from .base import BaseExtractor, fetch, log, extract_stream as base_extract_stream, extract_stream_all


class ArablionzExtractor(BaseExtractor):
    """Extractor for arablionz.live"""
    
    MAIN_URL = "https://arablionz.live/"
    
    def __init__(self):
        super(ArablionzExtractor, self).__init__()
        self.main_url = self.MAIN_URL
        self._resolved_base = self.MAIN_URL
    
    def _get_base(self):
        return self._resolved_base or self.MAIN_URL
    
    def _clean_title(self, title):
        return (
            (title or "")
            .replace("&amp;", "&")
            .replace("مشاهدة", "")
            .replace("تحميل", "")
            .replace("فيلم", "")
            .replace("مسلسل", "")
            .strip()
        )
    
    def _full_url(self, path):
        if not path:
            return ""
        path = path.strip()
        if path.startswith("http"):
            return path
        if path.startswith("//"):
            return "https:" + path
        return urljoin(self._get_base(), path)
    
    def _extract_boxes(self, html):
        """
        Reworked to use a more general card-finding strategy that works
        across common WordPress / custom CMS layouts.
        Returns list of (link, img, title) tuples.
        """
        results = []
        seen = set()

        # Strategy 1: article or post-type containers
        for container in re.findall(
            r'<(?:article|div)[^>]+class="[^"]*(?:item|post|movie|entry|Box)[^"]*"[^>]*>(.*?)</(?:article|div)>',
            html or "", re.S | re.I
        ):
            link_m  = re.search(r'href=["\']([^"\']+)["\']', container)
            title_m = (
                re.search(r'title=["\']([^"\']+)["\']', container) or
                re.search(r'alt=["\']([^"\']+)["\']', container) or
                re.search(r'<h[1-4][^>]*>([^<]+)</h[1-4]>', container, re.I)
            )
            img_m   = re.search(r'(?:data-src|data-lazy-src|src)=["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']', container, re.I)

            if link_m and title_m:
                link  = self._full_url(link_m.group(1))
                title = self._clean_title(title_m.group(1))
                img   = self._full_url(img_m.group(1)) if img_m else ""
                if link and link not in seen:
                    seen.add(link)
                    results.append((link, img, title))

        if results:
            return results

        # Strategy 2: plain <a href> + <img> pattern (broad fallback)
        for m in re.finditer(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*'
            r'(?:[^<]*<[^>]+>[^<]*)*?'
            r'<img[^>]+(?:data-src|data-lazy-src|src)=["\']([^"\']+)["\'][^>]+alt=["\']([^"\']+)["\']',
            html or "", re.S | re.I
        ):
            link  = self._full_url(m.group(1))
            img   = self._full_url(m.group(2))
            title = self._clean_title(m.group(3))
            if link and link not in seen:
                seen.add(link)
                results.append((link, img, title))

        return results
    
    def _extract_episodes(self, html, base_url):
        episodes = []
        seen = set()

        # Pattern: links containing episode/حلقة with a number
        for m in re.finditer(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(?:[^<]*<[^>]*>)*?'
            r'(?:حلقة|Episode|EP)\s*(\d+)',
            html or "", re.I | re.S
        ):
            url    = self._full_url(m.group(1).replace("&amp;", "&"))
            ep_num = m.group(2)
            if url in seen:
                continue
            seen.add(url)
            episodes.append({
                "title":    "حلقة {}".format(ep_num),
                "url":      url,
                "type":     "episode",
                "_action":  "details",
            })
            if len(episodes) >= 100:
                return episodes

        # Fallback: any link containing episode/season in URL
        if not episodes:
            for link in re.findall(r'href=["\']([^"\']*(?:episode|season|ep)[^"\']*)["\']', html, re.I):
                url = self._full_url(link.replace("&amp;", "&"))
                if url in seen or "category" in url:
                    continue
                seen.add(url)
                episodes.append({
                    "title":   "حلقة",
                    "url":     url,
                    "type":    "episode",
                    "_action": "details",
                })
        return episodes
    
    def _extract_quality_from_url(self, url):
        """Extract quality label from a stream URL."""
        if not url:
            return ""
        lower = url.lower()
        if "1080" in lower or "fhd" in lower or "hd1080" in lower:
            return "1080p"
        elif "720" in lower or "hd" in lower or "hd720" in lower:
            return "720p"
        elif "480" in lower:
            return "480p"
        elif "360" in lower:
            return "360p"
        elif "master.m3u8" in lower or "playlist" in lower:
            return "HD"
        return ""
    
    def get_categories(self, mtype="movie"):
        """Return all categories from arablionz.live navigation."""
        base = self._get_base().rstrip("/")
        return [
            {"title": "🎬 أفلام نتفليكس", "url": urljoin(base, "category/%d8%a3%d9%81%d9%84%d8%a7%d9%85-%d9%86%d8%aa%d9%81%d9%84%d9%8a%d9%83%d8%b3/"), "type": "category", "_action": "category"},
            {"title": "🎬 افلام اجنبي", "url": urljoin(base, "category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d8%ac%d9%86%d8%a8%d9%8a/"), "type": "category", "_action": "category"},
            {"title": "🎬 افلام انيميشن", "url": urljoin(base, "category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d9%86%d9%8a%d9%85%d9%8a%d8%b4%d9%86/"), "type": "category", "_action": "category"},
            {"title": "🎬 افلام تركية", "url": urljoin(base, "category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%aa%d8%b1%d9%83%d9%8a%d8%a9/"), "type": "category", "_action": "category"},
            {"title": "🎬 افلام عربي", "url": urljoin(base, "category/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%b9%d8%b1%d8%a8%d9%8a/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات Netfilx", "url": urljoin(base, "category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-netfilx/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات اجنبي", "url": urljoin(base, "category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%a7%d8%ac%d9%86%d8%a8%d9%8a/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات تركيه", "url": urljoin(base, "category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%aa%d8%b1%d9%83%d9%8a%d9%87/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات عربي", "url": urljoin(base, "category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%b9%d8%b1%d8%a8%d9%8a/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات كرتون", "url": urljoin(base, "category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d9%83%d8%b1%d8%aa%d9%88%d9%86/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات كوريه", "url": urljoin(base, "category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d9%83%d9%88%d8%b1%d9%8a%d9%87/"), "type": "category", "_action": "category"},
            {"title": "📡 برامج تلفزيونية", "url": urljoin(base, "category/%d8%a8%d8%b1%d8%a7%d9%85%d8%ac-%d8%aa%d9%84%d9%81%d8%b2%d9%8a%d9%88%d9%86%d9%8a%d8%a9/"), "type": "category", "_action": "category"},
            {"title": "🎬 أفلام أجنبية", "url": urljoin(base, "category/%d8%a3%d9%81%d9%84%d8%a7%d9%85-%d8%a3%d8%ac%d9%86%d8%a8%d9%8a%d8%a9/"), "type": "category", "_action": "category"},
            {"title": "🎬 أفلام آسيوية", "url": urljoin(base, "category/%d8%a3%d9%81%d9%84%d8%a7%d9%85-%d8%a2%d8%b3%d9%8a%d9%88%d9%8a%d8%a9/"), "type": "category", "_action": "category"},
            {"title": "🎬 أفلام عربية", "url": urljoin(base, "category/%d8%a3%d9%81%d9%84%d8%a7%d9%85-%d8%b9%d8%b1%d8%a8%d9%8a%d8%a9/"), "type": "category", "_action": "category"},
            {"title": "🎬 أفلام انمي", "url": urljoin(base, "category/%d8%a3%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d9%86%d9%85%d9%8a/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات اجنبية", "url": urljoin(base, "category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d8%a7%d8%ac%d9%86%d8%a8%d9%8a%d8%a9/"), "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات كورية", "url": urljoin(base, "category/%d9%85%d8%b3%d9%84%d8%b3%d9%84%d8%a7%d8%aa-%d9%83%d9%88%d8%b1%d9%8a%d8%a9/"), "type": "category", "_action": "category"},
        ]
    
    def get_category_items(self, url, page=1):
        html, final_url = fetch(url, referer=self._get_base())
        if not html:
            return []

        items = []
        seen = set()

        for link, img, title in self._extract_boxes(html):
            if link in seen:
                continue
            seen.add(link)
            low = link.lower() + " " + title.lower()
            is_series = "/series/" in low or "مسلسل" in low or "مسلسلات" in low
            items.append({
                "title":   title,
                "url":     link,
                "poster":  img,
                "type":    "series" if is_series else "movie",
                "_action": "details",
            })

        # Pagination - handle both /page/N/ and ?page=N formats
        next_m = (
            re.search(r'<a[^>]+class="next"[^>]+href=["\']([^"\']+)["\']', html, re.I) or
            re.search(r'<link[^>]+rel="next"[^>]+href=["\']([^"\']+)["\']', html, re.I) or
            re.search(r'<a[^>]+href=["\']([^"\']+/\?page=\d+)["\']', html, re.I) or
            re.search(r'<a[^>]+href=["\']([^"\']+page/\d+/)["\']', html, re.I)
        )
        if next_m:
            next_url = next_m.group(1).replace("&amp;", "&")
            if next_url and next_url != url:
                items.append({
                    "title":   "➡️ الصفحة التالية",
                    "url":     next_url,
                    "type":    "category",
                    "_action": "category",
                })

        return items
    
    def search(self, query, page=1):
        """Search functionality for arablionz.live."""
        base = self._get_base()
        search_url = urljoin(base, "?s=" + query.replace(" ", "+"))
        if page > 1:
            search_url = urljoin(base, "?s={}&paged={}".format(query.replace(" ", "+"), page))
        
        html, _ = fetch(search_url, referer=base)
        if not html:
            return []
        
        items = []
        seen = set()
        
        for link, img, title in self._extract_boxes(html):
            if link in seen:
                continue
            seen.add(link)
            low = link.lower() + " " + title.lower()
            is_series = "/series/" in low or "مسلسل" in low or "مسلسلات" in low
            items.append({
                "title":   title,
                "url":     link,
                "poster":  img,
                "type":    "series" if is_series else "movie",
                "_action": "details",
            })
        
        return items
    
    def get_page(self, url, m_type=None):
        html, final_url = fetch(url, referer=self._get_base())
        result = {
            "url":     url,
            "title":   "",
            "poster":  "",
            "plot":    "",
            "servers": [],
            "items":   [],
            "type":    "movie",
        }
        if not html:
            return result

        # Title
        title_m = (
            re.search(r'<h1[^>]*class="[^"]*post-title[^"]*"[^>]*>(.*?)</h1>', html, re.S | re.I) or
            re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S | re.I) or
            re.search(r'<meta[^>]+property="og:title"[^>]+content=["\']([^"\']+)["\']', html, re.I)
        )
        if title_m:
            result["title"] = self._clean_title(title_m.group(1))

        # Poster
        poster_m = (
            re.search(r'<img[^>]+class="[^"]*(?:poster|cover|img-fluid)[^"]*"[^>]+src=["\']([^"\']+)["\']', html, re.I) or
            re.search(r'<meta[^>]+property="og:image"[^>]+content=["\']([^"\']+)["\']', html, re.I) or
            re.search(r'<div[^>]*class="[^"]*poster[^"]*"[^>]*>.*?<img[^>]+src=["\']([^"\']+)["\']', html, re.S | re.I)
        )
        if poster_m:
            result["poster"] = poster_m.group(1).replace("&amp;", "&")

        # Plot
        plot_m = (
            re.search(r'<div[^>]*class="[^"]*(?:description|summary|plot|singleStory)[^"]*"[^>]*>(.*?)</div>', html, re.S | re.I) or
            re.search(r'<p[^>]*class="[^"]*desc[^"]*"[^>]*>(.*?)</p>', html, re.S | re.I) or
            re.search(r'<meta[^>]+name="description"[^>]+content=["\']([^"\']+)["\']', html, re.I)
        )
        if plot_m:
            result["plot"] = re.sub(r'<[^>]+>', ' ', plot_m.group(1)).strip()

        # Series check
        is_series = "/series/" in (final_url or url) or "مسلسل" in result["title"] or "مسلسلات" in result["title"]
        if is_series:
            result["type"]  = "series"
            result["items"] = self._extract_episodes(html, final_url or url)
            return result

        # ── Servers Extraction (FIXED for arablionz.live) ──
        seen_servers = set()
        
        # Look for server buttons with data-href attribute
        # Pattern: <button class="btn-server" data-href="URL">السيرفر 1</button>
        server_buttons = re.findall(
            r'<button[^>]*class="[^"]*btn-server[^"]*"[^>]*data-href=["\']([^"\']+)["\'][^>]*>(.*?)</button>',
            html, re.I | re.S
        )
        
        if not server_buttons:
            # Try alternative: any button with data-href
            server_buttons = re.findall(
                r'<button[^>]*data-href=["\']([^"\']+)["\'][^>]*>(.*?)</button>',
                html, re.I | re.S
            )
        
        if not server_buttons:
            # Try: a tags with data-href or href inside server containers
            server_buttons = re.findall(
                r'<a[^>]*data-href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                html, re.I | re.S
            )
        
        if server_buttons:
            for server_url, inner_html in server_buttons:
                server_url = server_url.strip()
                if not server_url or server_url in seen_servers:
                    continue
                seen_servers.add(server_url)
                
                # Clean server name
                name = re.sub(r'<[^>]+>', '', inner_html).strip()
                if not name:
                    name = "سيرفر {}".format(len(result["servers"]) + 1)
                
                # If URL is relative, make it absolute
                if server_url.startswith("/"):
                    server_url = self._full_url(server_url)
                
                # Try to extract quality from URL or context
                quality = self._extract_quality_from_url(server_url)
                
                # Check for multiple quality variants
                variants = extract_stream_all(server_url)
                if variants:
                    for stream_url, quality_label in variants:
                        result["servers"].append({
                            "name":  "{} - {}".format(name, quality_label),
                            "url":   stream_url,
                            "type":  "direct",
                            "quality": quality_label,
                        })
                else:
                    result["servers"].append({
                        "name":  name,
                        "url":   server_url,
                        "type":  "direct",
                        "quality": quality,
                    })
        
        # Fallback: look for iframes with src
        if not result["servers"]:
            for m in re.finditer(
                r'<iframe[^>]+(?:src|data-src|data-lazy-src)=["\']([^"\']+)["\']',
                html, re.I
            ):
                iframe_url = m.group(1).strip()
                if iframe_url.startswith("//"):
                    iframe_url = "https:" + iframe_url
                if not iframe_url.startswith("http") or iframe_url in seen_servers:
                    continue
                seen_servers.add(iframe_url)
                
                quality = self._extract_quality_from_url(iframe_url)
                variants = extract_stream_all(iframe_url)
                if variants:
                    for stream_url, quality_label in variants:
                        result["servers"].append({
                            "name":  "سيرفر {} - {}".format(len(result["servers"]) + 1, quality_label),
                            "url":   stream_url,
                            "type":  "direct",
                            "quality": quality_label,
                        })
                else:
                    result["servers"].append({
                        "name":  "سيرفر {}".format(len(result["servers"]) + 1),
                        "url":   iframe_url,
                        "type":  "direct",
                        "quality": quality,
                    })
        
        # Fallback: direct video host links
        if not result["servers"]:
            for m in re.finditer(
                r'href=["\']'
                r'(https?://(?:streamtape|dood|mixdrop|uqload|voe|vidbom|upstream|'
                r'streamwish|filemoon|lulustream|ok\.ru|govid|savefiles|mxcontent|'
                r'hgcloud|vidguard|fastvid|free-wd\.online)[^"\']+)'
                r'["\']',
                html, re.I
            ):
                link = m.group(1)
                if link in seen_servers:
                    continue
                seen_servers.add(link)
                
                variants = extract_stream_all(link)
                if variants:
                    for stream_url, quality_label in variants:
                        result["servers"].append({
                            "name":  "مشاهدة {} - {}".format(len(result["servers"]) + 1, quality_label),
                            "url":   stream_url,
                            "type":  "direct",
                            "quality": quality_label,
                        })
                else:
                    quality = self._extract_quality_from_url(link)
                    result["servers"].append({
                        "name":  "مشاهدة {}".format(len(result["servers"]) + 1),
                        "url":   link,
                        "type":  "direct",
                        "quality": quality,
                    })

        # Direct media URL fallback
        if not result["servers"]:
            for pat in (
                r'file\s*:\s*["\']([^"\']+)["\']',
                r'src\s*:\s*["\']([^"\']+)["\']',
                r'data-video=["\']([^"\']+)["\']',
                r'data-url=["\']([^"\']+)["\']',
                r'<source[^>]+src=["\']([^"\']+)["\']',
            ):
                m = re.search(pat, html, re.I)
                if m:
                    video_url = m.group(1)
                    quality = self._extract_quality_from_url(video_url)
                    result["servers"].append({
                        "name":  "مشاهدة",
                        "url":   video_url,
                        "type":  "direct",
                        "quality": quality,
                    })
                    break

        log("Arablionz: Found {} servers for {}".format(len(result["servers"]), result["title"]))
        return result
    
    def extract_stream(self, url):
        """Extract stream from a server URL with multi-quality support."""
        # Direct media URL
        if url.startswith("http") and any(x in url.lower() for x in (".m3u8", ".mp4", ".mkv")):
            quality = self._extract_quality_from_url(url)
            return url, quality, self._get_base()
        
        # Try to extract all quality variants
        variants = extract_stream_all(url)
        if variants:
            best_url, best_quality = variants[0]
            return best_url, best_quality, self._get_base()
        
        # Fallback to base extractor
        return base_extract_stream(url)