# -*- coding: utf-8 -*-
"""
Extractor for Akwam - Multi-domain support
Updated for akwam.it layout, categories, and stream extraction.
Inherits from BaseExtractor.
"""

import re
import sys
from .base import BaseExtractor, fetch, log, urljoin


class AkwamExtractor(BaseExtractor):
    """Extractor for Akwam - supports multiple domains"""
    
    MAIN_URL = "https://akwam.it/"
    
    DOMAINS = [
        "https://akwam.it/",
        "https://akwam.co/",
        "https://akwam.cx/",
        "https://akwam.to/",
        "https://akwam.run/",
        "https://akwam.one/",
        "https://akwam.net/",
        "https://akwam.com.co/",
    ]
    
    def __init__(self):
        super(AkwamExtractor, self).__init__()
        self.main_url = self.MAIN_URL
        self._resolved_base = None
    
    def _get_base(self):
        """Probe known domains and return the first working one."""
        if self._resolved_base:
            return self._resolved_base
        
        for domain in self.DOMAINS:
            try:
                log("Akwam: Probing domain {}".format(domain))
                html, final_url = fetch(domain, referer=domain)
                if not html:
                    continue
                
                # Check for Cloudflare or dead redirects
                lower_html = html.lower()
                if "just a moment" in lower_html or "cf-chl" in lower_html:
                    log("Akwam: Domain {} blocked by Cloudflare".format(domain))
                    continue
                
                # Check if it redirected away to a non-akwam domain
                final_host = re.search(r'https?://([^/]+)', final_url or "")
                if final_host and not any(d in final_host.group(1) for d in ("akwam", "akoam")):
                    log("Akwam: Domain {} redirected to unknown host {}".format(domain, final_host.group(1)))
                    continue

                # If it passes all checks, use this domain
                self._resolved_base = domain
                self.main_url = domain
                log("Akwam: Selected working domain: {}".format(domain))
                return self._resolved_base
            except Exception as e:
                log("Akwam: Domain {} failed with error: {}".format(domain, e))
                continue

        # Fallback if all fail
        log("Akwam: All domains failed, falling back to {}".format(self.MAIN_URL))
        self._resolved_base = self.MAIN_URL
        return self._resolved_base

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
            url = url.replace(" ", "%20")
            
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return urljoin(self._get_base(), url)
        
        return url
    
    def get_categories(self, mtype="movie"):
        """Return all available categories based on the new akwam.it layout."""
        base = self._get_base()
        return [
            {"title": "🎬 English Movies", "url": urljoin(base, "movies?section=30&category=0"), "type": "category", "_action": "category"},
            {"title": "🎬 Arabic Movies", "url": urljoin(base, "movies?section=29&category=0"), "type": "category", "_action": "category"},
            {"title": "🎬 Indian Movies", "url": urljoin(base, "movies?section=31&category=0"), "type": "category", "_action": "category"},
            {"title": "🎬 Turkish Movies", "url": urljoin(base, "movies?section=32&category=0"), "type": "category", "_action": "category"},
            {"title": "🎬 Asian Movies", "url": urljoin(base, "movies?section=33&category=0"), "type": "category", "_action": "category"},
            {"title": "🎬 Anime Movies", "url": urljoin(base, "movies?section=30&category=30"), "type": "category", "_action": "category"},
            {"title": "🎬 Netflix Movies", "url": urljoin(base, "movies?section=30&category=72"), "type": "category", "_action": "category"},
            {"title": "📺 English Series", "url": urljoin(base, "series?section=30&category=0"), "type": "category", "_action": "category"},
            {"title": "📺 Arabic Series", "url": urljoin(base, "series?section=29&category=0"), "type": "category", "_action": "category"},
            {"title": "📺 Turkish Series", "url": urljoin(base, "series?section=32&category=0"), "type": "category", "_action": "category"},
            {"title": "📺 Anime Series", "url": urljoin(base, "series?section=30&category=30"), "type": "category", "_action": "category"},
            {"title": "📡 TV Shows", "url": urljoin(base, "shows"), "type": "category", "_action": "category"},
            {"title": "🤼 Wrestling Shows", "url": urljoin(base, "shows?section=43&category=0"), "type": "category", "_action": "category"},
            {"title": "🎞️ Documentary Shows", "url": urljoin(base, "shows?section=46&category=0"), "type": "category", "_action": "category"},
            {"title": "🎭 Variety", "url": urljoin(base, "mix"), "type": "category", "_action": "category"},
            {"title": "🆕 Recent", "url": urljoin(base, "recent"), "type": "category", "_action": "category"},
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
    
        # Broader split for entry boxes to handle slight class name changes
        entry_boxes = re.split(r'<div class="entry-box', html)
        log("Akwam: Found {} entry-box sections".format(len(entry_boxes) - 1))
        
        for box in entry_boxes[1:]:
            # Find the main link
            link_match = re.search(r'<a\s+href="([^"]+)"', box, re.I)
            if not link_match:
                continue
                
            movie_url = link_match.group(1)
            
            # Filter out non-content links
            if any(x in movie_url for x in ('/category/', '/page/', '/recent', '/movies', '/series', '/shows', '/mix', '#')):
                continue
                
            full_url = self._normalize_url(movie_url)
            if not full_url or full_url in seen:
                continue
                
            title = ""
            title_match = re.search(r'<h3[^>]*>(.*?)</h3>', box, re.S | re.I)
            if title_match:
                title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
            else:
                # fallback to alt or title attr
                title_match = re.search(r'(?:alt|title)="([^"]+)"', box, re.I)
                if title_match:
                    title = title_match.group(1)
            
            if not title:
                continue
                
            seen.add(full_url)
            
            poster = ""
            img_match = re.search(r'<img[^>]+(?:data-src|data-lazy-src|data-original|src)="([^"]+)"', box, re.I)
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
        if not next_match:
            next_match = re.search(r'<a\s+[^>]*href="([^"]+)"[^>]*>.*?التالي.*?</a>', html, re.I | re.S)
        
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
        base = self._get_base()
        search_url = urljoin(base, "search?q=" + query.replace(" ", "+"))
        if page > 1:
            search_url = urljoin(base, "search?q={}&page={}".format(query.replace(" ", "+"), page))
    
        log("Akwam: Searching for: {}".format(query))
        
        html, _ = fetch(search_url, referer=base)
        if not html:
            return []
    
        items = []
        entry_boxes = re.split(r'<div class="entry-box', html)
        
        for box in entry_boxes[1:]:
            link_match = re.search(r'<a\s+href="([^"]+)"', box, re.I)
            if not link_match:
                continue
                
            movie_url = link_match.group(1)
            if any(x in movie_url for x in ('/category/', '/page/', '/recent', '/movies', '/series', '/shows', '/mix', '#')):
                continue
                
            full_url = self._normalize_url(movie_url)
            title = ""
            title_match = re.search(r'<h3[^>]*>(.*?)</h3>', box, re.S | re.I)
            if title_match:
                title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
            else:
                title_match = re.search(r'(?:alt|title)="([^"]+)"', box, re.I)
                if title_match:
                    title = title_match.group(1)
            
            if title and full_url:
                items.append({
                    "title": self._clean_title(title),
                    "url": full_url,
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
        watch_html = html
        
        # If the current URL is not a watch page, try to find the watch link
        if "/watch/" not in url:
            # Aggressive search for the watch URL anywhere in the HTML
            watch_match = re.search(r'(https?://[^"\'\s<>]+/watch/\d+)', html, re.I)
            if watch_match:
                watch_url = watch_match.group(1)
            else:
                rel_watch_match = re.search(r'href="(/watch/\d+)"', html, re.I)
                if rel_watch_match:
                    watch_url = self._normalize_url(rel_watch_match.group(1))
            
            if watch_url:
                log("Akwam: Fetching watch page: {}".format(watch_url))
                watch_html, _ = fetch(watch_url, referer=url)
        
        if watch_html:
            source_matches = []
            
            # 1. Akwam's specific downet.net links (catches vlc://, intent:, and missing colon https//)
            # Stops matching at .mp4 to avoid capturing Android intent (#) garbage
            raw_links = re.findall(r'(https?:?//[^"\'\s<>#]+\.downet\.net/[^"\'\s<>#]+\.mp4)', watch_html, re.I)
            for m in raw_links:
                if m.startswith("https//"):
                    m = "https://" + m[6:]
                elif m.startswith("http//"):
                    m = "http://" + m[5:]
                source_matches.append(m)

            # 2. Standard <source> tags (STRICTLY require .mp4 or .m3u8 to ignore images)
            if not source_matches:
                source_matches = re.findall(r'<source\s+src="([^"]+\.(?:mp4|m3u8)[^"]*)"', watch_html, re.I)
            
            # 3. Fallback to JS-based sources (STRICTLY require .mp4 or .m3u8 to ignore images)
            if not source_matches:
                for pattern in [
                    r'file\s*:\s*["\']([^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
                    r'source\s*:\s*["\']([^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
                    r'data-(?:url|src|video)=["\']([^"\']+\.(?:mp4|m3u8)[^"\']*)["\']',
                    r'"(?:file|src|url)"\s*:\s*"([^"]+\.(?:mp4|m3u8)[^"]*)"',
                ]:
                    source_matches = re.findall(pattern, watch_html, re.I)
                    if source_matches:
                        break
            
            if source_matches:
                seen_urls = set()
                seen_qualities = set()
                for src in source_matches:
                    video_url = src.strip()
                    if video_url in seen_urls:
                        continue
                    seen_urls.add(video_url)
                    
                    quality = "HD"
                    lowered = video_url.lower()
                    if "1080" in lowered:
                        quality = "1080p"
                    elif "720" in lowered:
                        quality = "720p"
                    elif "480" in lowered:
                        quality = "480p"
                    
                    # Deduplicate by quality so we don't get 14 different CDNs for 720p
                    if quality in seen_qualities:
                        continue
                    seen_qualities.add(quality)
                    
                    if '|' in video_url:
                        video_url = video_url.split('|')[0]
                    
                    if "downet.net" in video_url:
                        video_url = video_url.replace(" ", "%20")
                    
                    video_url = self._normalize_url(video_url)
                    
                    result["servers"].append({
                        "name": "🎬 {} - Akwam".format(quality),
                        "url": video_url,
                        "type": "direct"
                    })
                    log("Akwam: Added {} quality: {}".format(quality, video_url[:80]))
                
                log("Akwam: Found {} quality variants".format(len(result["servers"])))
                return result
            else:
                # Fallback: iframes (embedded players)
                iframe_matches = re.findall(r'<iframe[^>]+src="([^"]+)"', watch_html, re.I)
                for iframe_url in iframe_matches:
                    if any(x in iframe_url.lower() for x in ('youtube', 'facebook', 'twitter')):
                        continue
                    full_url = self._normalize_url(iframe_url)
                    result["servers"].append({
                        "name": "🎬 Embed Player",
                        "url": full_url,
                        "type": "embed"
                    })
    
        # Domain-agnostic regex for go.akwam redirect
        watch_match = re.search(r'href="(https?://go\.[^"]*akwam[^"]*/watch/\d+)"', html, re.I)
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