# -*- coding: utf-8 -*-
"""
Extractor for Akwam - akwam.com.co/
Now supports multi-quality: shows all available video qualities as separate server entries.
Inherits from BaseExtractor.
"""

import re
import sys
from .base import BaseExtractor, fetch, log
from urllib.parse import urljoin, urlparse, quote_plus, quote, unquote

if sys.version_info[0] == 3:
    from urllib.parse import quote_plus, urlparse, quote, unquote
else:
    from urllib import quote_plus, quote
    from urlparse import urlparse


class AkwamExtractor(BaseExtractor):
    """Extractor for Akwam - akwam.com.co/"""
    
    MAIN_URL = "https://akwam.com.co/"
    
    def __init__(self):
        super(AkwamExtractor, self).__init__()
        self.main_url = self.MAIN_URL
        self._resolved_base = self.MAIN_URL
    
    def _get_base(self):
        return self._resolved_base or self.MAIN_URL
    
    def _clean_title(self, title):
        if not title:
            return ""
        title = title.replace("&amp;", "&")
        title = title.replace("مشاهدة", "")
        title = title.replace("تحميل", "")
        title = title.replace("فيلم", "")
        title = title.replace("مسلسل", "")
        title = re.sub(r'\s*[-|]\s*أكوام.*$', '', title)
        title = re.sub(r'\s*[-|]\s*Akwam.*$', '', title, flags=re.I)
        return title.strip()
    
    def _normalize_url(self, url):
        if not url:
            return ""
        url = str(url).strip()
        url = url.replace('&amp;', '&')
        
        if "downet.net" in url:
            return url.replace(" ", "%20")
        
        try:
            raw_url = unquote(url)
            return quote(raw_url, safe=':/?&=#+')
        except Exception:
            return url
    
    def get_categories(self, mtype="movie"):
        """Return all available categories."""
        return [
            {"title": "🎬 English Movies", "url": urljoin(self._get_base(), "movies?section=30"), "type": "category", "_action": "category"},
            {"title": "🎬 Arabic Movies", "url": urljoin(self._get_base(), "movies?section=29"), "type": "category", "_action": "category"},
            {"title": "🎬 Indian Movies", "url": urljoin(self._get_base(), "movies?section=31"), "type": "category", "_action": "category"},
            {"title": "🎬 Turkish Movies", "url": urljoin(self._get_base(), "movies?section=32"), "type": "category", "_action": "category"},
            {"title": "🎬 Asian Movies", "url": urljoin(self._get_base(), "movies?section=33"), "type": "category", "_action": "category"},
            {"title": "🎬 Anime Movies", "url": urljoin(self._get_base(), "movies?category=30"), "type": "category", "_action": "category"},
            {"title": "🎬 Netflix Movies", "url": urljoin(self._get_base(), "movies?category=72"), "type": "category", "_action": "category"},
            {"title": "📺 TV Series", "url": urljoin(self._get_base(), "series"), "type": "category", "_action": "category"},
            {"title": "📡 TV Shows", "url": urljoin(self._get_base(), "shows"), "type": "category", "_action": "category"},
            {"title": "🎭 Variety", "url": urljoin(self._get_base(), "mix"), "type": "category", "_action": "category"},
            {"title": "🆕 Recent", "url": urljoin(self._get_base(), "recent"), "type": "category", "_action": "category"},
        ]
    
    def get_category_items(self, url, page=1):
        url = url.replace('&amp;', '&')
        
        if 'page=' not in url:
            if '?' in url:
                url += '&page=1'
            else:
                url += '?page=1'
        
        log("Akwam: Fetching category URL: {}".format(url))
        
        html, final_url = fetch(url, referer=self._get_base())
        if not html:
            log("Akwam: get_category_items failed for {}".format(url))
            return []
    
        items = []
        seen = set()
    
        current_page = 1
        page_match = re.search(r'[?&]page=(\d+)', url)
        if page_match:
            current_page = int(page_match.group(1))
        
        log("Akwam: Current page: {}".format(current_page))
        
        items.append({
            "title": "━━━ Page {} ━━━".format(current_page),
            "type": "separator",
            "_action": "separator",
        })
    
        entry_boxes = re.split(r'<div class="entry-box entry-box-1">', html)
        
        log("Akwam: Found {} entry-box sections".format(len(entry_boxes) - 1))
        
        for box in entry_boxes[1:]:
            title_match = re.search(r'<h3[^>]*class="[^"]*entry-title[^"]*"[^>]*>.*?<a\s+href="([^"]+)"[^>]*class="[^"]*text-white[^"]*"[^>]*>([^<]+)</a>', box, re.S | re.I)
            
            if not title_match:
                continue
                
            movie_url = title_match.group(1)
            title = title_match.group(2).strip()
            
            if movie_url in seen:
                continue
            seen.add(movie_url)
            
            full_url = self._normalize_url(movie_url)
            
            poster = ""
            img_match = re.search(r'data-src="([^"]+)"', box, re.I)
            if not img_match:
                img_match = re.search(r'src="([^"]+)"', box, re.I)
            if img_match:
                poster = img_match.group(1)
                if "placeholder" in poster.lower():
                    poster = ""
                else:
                    poster = self._normalize_url(poster)
            
            items.append({
                "title": self._clean_title(title),
                "url": full_url,
                "poster": poster,
                "type": "movie",
                "_action": "details",
            })
    
        log("Akwam: Extracted {} movie items from page {}".format(len(items) - 1, current_page))
    
        next_url = None
        next_page_num = current_page + 1
        
        next_match = re.search(r'<a\s+class="page-link"[^>]+href="([^"]+)"[^>]*>{}</a>'.format(next_page_num), html, re.I)
        
        if next_match:
            next_url = self._normalize_url(next_match.group(1))
            if next_url and next_url != url:
                log("Akwam: Found next page: {}".format(next_url))
                items.append({
                    "title": "➡️ Page {} (Next)".format(current_page + 1),
                    "url": next_url,
                    "type": "category",
                    "_action": "category",
                })
    
        log("Akwam: Total items returned: {}".format(len(items)))
        return items
    
    def search(self, query, page=1):
        search_url = urljoin(self._get_base(), "search?q=" + query.replace(" ", "+"))
        if page > 1:
            search_url = urljoin(self._get_base(), "search?q={}&page={}".format(query.replace(" ", "+"), page))
    
        log("Akwam: Searching for: {}".format(query))
        
        html, _ = fetch(search_url, referer=self._get_base())
        if not html:
            return []
    
        items = []
        
        entry_boxes = re.split(r'<div class="entry-box entry-box-1">', html)
        
        for box in entry_boxes[1:]:
            title_match = re.search(r'<h3[^>]*class="[^"]*entry-title[^"]*"[^>]*>.*?<a\s+href="([^"]+)"[^>]*class="[^"]*text-white[^"]*"[^>]*>([^<]+)</a>', box, re.S | re.I)
            if title_match:
                movie_url = title_match.group(1)
                title = title_match.group(2).strip()
                items.append({
                    "title": self._clean_title(title),
                    "url": self._normalize_url(movie_url),
                    "poster": "",
                    "type": "movie",
                    "_action": "details",
                })
    
        log("Akwam: Search found {} results".format(len(items)))
        return items
    
    def get_page(self, url, m_type=None):
        if not url or url.startswith("javascript"):
            return {"title": "Error", "servers": [], "items": [], "type": "movie"}
    
        log("Akwam: Getting movie page: {}".format(url))
        
        html, final_url = fetch(url, referer=self._get_base())
        if not html:
            log("Akwam: get_page failed for {}".format(url))
            return {"title": "Error", "servers": [], "items": []}
    
        result = {
            "url": final_url or url,
            "title": "",
            "poster": "",
            "plot": "",
            "servers": [],
            "items": [],
            "type": "movie",
        }
    
        title_match = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html, re.I)
        if title_match:
            result["title"] = self._clean_title(title_match.group(1))
    
        poster_match = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.I)
        if poster_match:
            result["poster"] = self._normalize_url(poster_match.group(1))
    
        plot_match = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html, re.I)
        if plot_match:
            result["plot"] = self._clean_title(plot_match.group(1))
    
        watch_url = None
        watch_link_match = re.search(r'href="(https?://akwam\.com\.co/watch/\d+)"', html, re.I)
        if watch_link_match:
            watch_url = watch_link_match.group(1)
        else:
            base = url.rstrip('/')
            watch_url = base + '/watch'
        
        if watch_url:
            log("Akwam: Fetching watch page: {}".format(watch_url))
            watch_html, _ = fetch(watch_url, referer=url)
            if watch_html:
                source_matches = re.findall(r'<source\s+src="([^"]+)"\s+type="video/mp4"[^>]*>', watch_html, re.I)
                if not source_matches:
                    source_matches = re.findall(r'<source\s+src="([^"]+)"', watch_html, re.I)
                
                if source_matches:
                    seen = set()
                    for src in source_matches:
                        video_url = src.strip()
                        if video_url in seen:
                            continue
                        seen.add(video_url)
                        
                        quality = "HD"
                        lowered = video_url.lower()
                        if "1080" in lowered:
                            quality = "1080p"
                        elif "720" in lowered:
                            quality = "720p"
                        elif "480" in lowered:
                            quality = "480p"
                        
                        if '|' in video_url:
                            video_url = video_url.split('|')[0]
                        
                        if "downet.net" in video_url:
                            video_url = video_url.replace(" ", "%20")
                        
                        try:
                            raw_url = unquote(video_url)
                            video_url = quote(raw_url, safe=':/?&=#+')
                        except Exception:
                            pass
                        
                        result["servers"].append({
                            "name": "🎬 {} - Akwam".format(quality),
                            "url": video_url,
                            "type": "direct"
                        })
                        log("Akwam: Added {} quality: {}".format(quality, video_url[:80]))
                    
                    log("Akwam: Found {} quality variants".format(len(result["servers"])))
                    return result
    
        watch_match = re.search(r'href="(https?://go\.akwam\.com\.co/watch/\d+)"', html, re.I)
        if watch_match:
            normalized_url = self._normalize_url(watch_match.group(1))
            if normalized_url:
                from .base import extract_stream_all
                variants = extract_stream_all(normalized_url)
                if variants:
                    for stream_url, quality in variants:
                        result["servers"].append({
                            "name": "🎬 {} - Akwam (Redirect)".format(quality),
                            "url": stream_url,
                            "type": "direct"
                        })
                else:
                    result["servers"].append({
                        "name": "🎬 Play Movie",
                        "url": normalized_url,
                        "type": "redirect"
                    })
    
        log("Akwam: Found {} servers for {}".format(len(result["servers"]), result["title"]))
        return result
    
    def extract_stream(self, url):
        """Delegate to base extractor."""
        from .base import extract_stream as base_extract_stream
        return base_extract_stream(url)