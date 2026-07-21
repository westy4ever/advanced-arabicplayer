# -*- coding: utf-8 -*-
"""
TopCinema extractor - topcinemaa.top
Inherits from BaseExtractor.
"""

import sys
import re
from .base import BaseExtractor, fetch, urljoin, log, resolve_iframe_chain

if sys.version_info[0] == 3:
    from urllib.parse import quote_plus, urlparse, urlunparse, quote, urlencode
    from html import unescape as html_unescape
else:
    from urllib import quote_plus, quote, urlencode
    from urlparse import urlparse, urlunparse
    from HTMLParser import HTMLParser
    html_unescape = HTMLParser().unescape


class TopCinemaExtractor(BaseExtractor):
    """Extractor for TopCinema - topcinemaa.top"""
    
    DOMAINS = [
        "https://topcinemaa.top/",
        "https://topcinma.com/",
        "https://topcinema.vip/",
        "https://topcima.info/",
        "https://topcinma.red/",
    ]
    VALID_HOST_MARKERS = ("topcinemaa.top", "topcinma.com", "topcinema.vip", "topcima.info", "topcinma.red", "topcinema", "topcinma", "topcima")
    BLOCKED_HOST_MARKERS = ("alliance4creativity.com",)
    
    def __init__(self):
        super(TopCinemaExtractor, self).__init__()
        self.main_url = self.DOMAINS[0]
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
    
    def _looks_like_topcinema_page(self, html):
        text = html or ""
        return (
            "movie__block" in text
            or "allepcont" in text
            or "server--item" in text
            or "topcinema" in text.lower()
            or "توب سينما" in text
        )
    
    def _site_root(self, url):
        parts = urlparse(url)
        return "{}://{}/".format(parts.scheme or "https", parts.netloc)
    
    def _get_base(self):
        if self._resolved_base:
            return self._resolved_base
        for domain in self.DOMAINS:
            log("TopCinema: probing {}".format(domain))
            html, final_url = fetch(domain, referer=domain)
            final_url = final_url or domain
            if not self._is_valid_site_url(final_url):
                log("TopCinema: unexpected host after redirect {}".format(final_url))
                continue
            if self._is_blocked_page(html, final_url):
                log("TopCinema: blocked {}".format(final_url))
                continue
            if html and self._looks_like_topcinema_page(html):
                self._resolved_base = self._site_root(final_url)
                self.main_url = self._resolved_base
                log("TopCinema: selected base {}".format(self._resolved_base))
                return self._resolved_base
        self._resolved_base = self.DOMAINS[0]
        self.main_url = self._resolved_base
        log("TopCinema: all probes failed, falling back to {}".format(self._resolved_base))
        return self._resolved_base
    
    def _normalize_url(self, url):
        if not url:
            return ""
        url = html_unescape(url.strip())
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return urljoin(self._get_base(), url)
        return url
    
    def _clean_title(self, title):
        title = html_unescape(title or "")
        title = title.replace("&amp;", "&")
        title = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\ufeff]+', '', title)
        title = re.sub(r'\[[^\]]*\]\s*', '', title)
        title = re.sub(r'\s*[-|]\s*ت[ةه]?وب\s*سينما\s*$', '', title, flags=re.I)
        title = re.sub(r'ت[ةه]?وب\s*سينما', '', title, flags=re.I)
        noise_phrases = (
            "مشاهدة وتحميل", "مشاهدة وتحميل مباشر", "مشاهدة", "تحميل",
            "مترجمة", "مترجم", "مدبلجة", "مدبلج",
            "اون لاين", "اونلاين", "بجودة عالية", "بجودة", "حصريا", "كامل",
        )
        for phrase in noise_phrases:
            title = re.sub(r'\s*' + re.escape(phrase) + r'\s*', ' ', title, flags=re.I)
        type_words = ("فيلم", "افلام", "مسلسل", "مسلسلات", "انمي", "برنامج", "عرض")
        words = title.split()
        while words and words[0] in type_words:
            words.pop(0)
        return " ".join(words).strip()
    
    def _arabic_ordinals(self):
        return {
            "الاول": 1, "الأول": 1,
            "الثاني": 2,
            "الثالث": 3,
            "الرابع": 4,
            "الخامس": 5,
            "السادس": 6,
            "السابع": 7,
            "الثامن": 8,
            "التاسع": 9,
            "العاشر": 10,
        }
    
    def _season_number(self, title):
        ordinals = self._arabic_ordinals()
        for word, num in ordinals.items():
            if word in title:
                return num
        m = re.search(r'(?<!\d)(\d+)(?!\d)', title)
        return int(m.group(1)) if m else 9999
    
    def _extract_blocks(self, html):
        items = []
        pattern = r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*title=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
        for m in re.finditer(pattern, html, re.I | re.S):
            href = m.group(1)
            title = m.group(2)
            inner = m.group(3)
    
            if re.search(r'/(?:category|search|page|tag|author)/', href, re.I):
                continue
    
            img_match = re.search(r'<img[^>]+(?:data-src|src)=["\']([^"\']+)["\']', inner, re.I)
            if not img_match:
                continue
            poster = img_match.group(1)
    
            if not poster or poster.startswith('data:') or 'placeholder' in poster.lower():
                continue
    
            link = self._normalize_url(href)
            poster = self._normalize_url(poster)
    
            if "الحلقة" in title and "/series/" not in link:
                item_type = "episode"
            elif "/series/" in link:
                item_type = "series"
            elif "مسلسل" in title or "انمي" in title:
                item_type = "series"
            else:
                item_type = "movie"
    
            title = self._clean_title(title)
    
            items.append({
                "title": title,
                "url": link,
                "poster": poster,
                "type": item_type,
                "_action": "details"
            })
        return items
    
    def get_categories(self, mtype="movie"):
        base = self._get_base()
        return [
            {"title": "🎬 المضاف حديثا", "url": base + "recent/", "type": "category", "_action": "category"},
            {"title": "🎬 أفلام أجنبية", "url": base + "category/%D8%A7%D9%81%D9%84%D8%A7%D9%85-%D8%A7%D8%AC%D9%86%D8%A8%D9%8A-8/", "type": "category", "_action": "category"},
            {"title": "🎬 أفلام أنمي", "url": base + "category/%D8%A7%D9%81%D9%84%D8%A7%D9%85-%D8%A7%D9%86%D9%85%D9%8A-2/", "type": "category", "_action": "category"},
            {"title": "🎬 أفلام أسيوية", "url": base + "category/%D8%A7%D9%81%D9%84%D8%A7%D9%85-%D8%A7%D8%B3%D9%8A%D9%88%D9%8A/", "type": "category", "_action": "category"},
            {"title": "🎬 أفلام نتفليكس", "url": base + "netflix-movies/", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات أجنبية", "url": base + "category/%D9%85%D8%B3%D9%84%D8%B3%D9%84%D8%A7%D8%AA-%D8%A7%D8%AC%D9%86%D8%A8%D9%8A/", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات أسيوية", "url": base + "category/%D9%85%D8%B3%D9%84%D8%B3%D9%84%D8%A7%D8%AA-%D8%A7%D8%B3%D9%8A%D9%88%D9%8A%D8%A9/", "type": "category", "_action": "category"},
            {"title": "📺 مسلسلات أنمي", "url": base + "category/%D9%85%D8%B3%D9%84%D8%B3%D9%84%D8%A7%D8%AA-%D8%A7%D9%86%D9%85%D9%8A/", "type": "category", "_action": "category"},
        ]
    
    def get_category_items(self, url, page=1):
        html, final_url = fetch(url, referer=self._get_base())
        if not html:
            log("TopCinema: fetch returned no content for {}".format(url))
            return []
    
        items = self._extract_blocks(html)
    
        next_url = None
        m = re.search(r'<a[^>]+rel=["\']next["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
        if not m:
            m = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']next["\']', html, re.I)
        if not m:
            m = re.search(r'<a[^>]+class=["\'][^"\']*\bnext\b[^"\']*["\'][^>]+href=["\']([^"\']+)["\']', html, re.I)
        if not m:
            m = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(?:(?!</a>).)*?»(?:(?!</a>).)*?</a>', html, re.I | re.S)
        if m:
            next_url = self._normalize_url(m.group(1))
        if next_url:
            items.append({
                "title": "➡️ الصفحة التالية",
                "url": next_url,
                "type": "category",
                "_action": "category"
            })
        return items
    
    def search(self, query, page=1):
        url = self._get_base() + "search/?query=" + quote_plus(query) + "&type=all"
        html, final_url = fetch(url, referer=self._get_base())
        return self._extract_blocks(html)
    
    def get_page(self, url, m_type=None):
        html, final_url = fetch(url, referer=self._get_base())
    
        title_m = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
        raw_title = title_m.group(1) if title_m else "Unknown Title"
        title = self._clean_title(raw_title)
    
        poster_m = re.search(r'property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        poster = self._normalize_url(poster_m.group(1)) if poster_m else ""
        if not poster:
            for img_m in re.finditer(r'<img[^>]+(?:data-src|src)=["\']([^"\']+)["\']', html, re.I):
                candidate = img_m.group(1)
                if "wp-content/uploads" in candidate and "logo" not in candidate.lower():
                    poster = self._normalize_url(candidate)
                    break
    
        plot_m = re.search(r'class=["\']description["\'][^>]*>(.*?)</', html, re.S | re.I)
        plot = self._clean_title(re.sub(r'<[^>]+>', '', plot_m.group(1))) if plot_m else ""
    
        servers = []
        episodes = []
        item_type = "movie"
    
        watch_url_m = re.search(
            r'<a[^>]+class=["\'][^"\']*watch[^"\']*["\'][^>]+href=["\']([^"\']+/watch/?)[\"\']',
            html, re.I
        )
        watch_page_html = html
        watch_url = final_url
        if watch_url_m:
            watch_url = self._normalize_url(watch_url_m.group(1))
            watch_page_html, _ = fetch(watch_url, referer=final_url)
            watch_page_html = watch_page_html or ""
    
        post_id = ""
        for pat in [
            r'data-id=["\'](\d+)["\']',
            r'\?p=(\d+)',
            r'postid["\']?\s*[:=]\s*["\']?(\d+)["\']?',
            r'post_id["\']?\s*[:=]\s*["\']?(\d+)["\']?'
        ]:
            m = re.search(pat, watch_page_html, re.I)
            if m:
                post_id = m.group(1)
                break
    
        server_candidates = []
        li_matches = re.findall(
            r'<li(?=[^>]*class=["\'][^"\']*server--item)(?=[^>]*data-id=["\'](\d+))(?=[^>]*data-server=["\'](\d+))[^>]*>(.*?)</li>',
            watch_page_html, re.I | re.S
        )
        for pid, idx, inner in li_matches:
            name = re.sub(r'<[^>]+>', ' ', inner)
            name = self._clean_title(re.sub(r'\s+', ' ', name)).strip()
            if name:
                server_candidates.append((pid, idx, name))
    
        if not server_candidates:
            generic_matches = re.findall(
                r'<(?:li|a|button|div)[^>]*data-id=["\'](\d+)["\'][^>]*data-server=["\'](\d+)["\'][^>]*>(.*?)</(?:li|a|button|div)>',
                watch_page_html, re.I | re.S
            )
            for pid, idx, inner in generic_matches:
                name = re.sub(r'<[^>]+>', ' ', inner)
                name = self._clean_title(re.sub(r'\s+', ' ', name)).strip()
                if name:
                    server_candidates.append((pid, idx, name))
    
        if not server_candidates and post_id:
            known_servers = [
                "متعدد الجودات", "UpDown", "StreamWish", "Doodstream",
                "Filelions", "Streamtape", "LuluStream", "Filemoon",
                "Mixdrop", "VidGuard", "Okru"
            ]
            for i, srv in enumerate(known_servers, 1):
                if re.search(re.escape(srv), watch_page_html, re.I):
                    server_candidates.append((post_id, str(i), srv))
    
        ajax_endpoint = self._get_base() + "wp-content/themes/movies2023/Ajaxat/Single/Server.php"
        seen = set()
        for pid, idx, name in server_candidates:
            if not pid or not idx:
                continue
            key = (pid, idx)
            if key in seen:
                continue
            seen.add(key)
            clean_name = self._clean_title(name or "").strip()
            if not clean_name:
                continue
            s_url = "topcinema_server|{}|{}|{}|{}".format(
                ajax_endpoint, pid, idx, watch_url
            )
            servers.append({
                "name": "توب سينما " + clean_name,
                "url": s_url,
            })
    
        is_hub_or_season = "/series/" in (final_url or url)
    
        if is_hub_or_season:
            eps_m = re.search(
                r'<section[^>]+class=["\'][^"\']*allepcont[^"\']*["\'][^>]*>(.*?)</section>',
                html, re.S | re.I
            )
            if eps_m:
                for e_link, e_title in re.findall(
                    r'<a[^>]+href=["\']([^"\']+)["\'][^>]+title=["\']([^"\']+)["\']',
                    eps_m.group(1), re.S | re.I
                ):
                    e_link_norm = self._normalize_url(e_link)
                    if not e_link_norm or e_link_norm == final_url:
                        continue
                    e_text = self._clean_title(e_title)
                    e_num_m = re.search(r'الحلقة\s*(\d+)', e_title)
                    episodes.append({
                        "title": ("حلقة " + e_num_m.group(1)) if e_num_m else e_text,
                        "url": e_link_norm,
                        "type": "episode",
                        "_action": "item",
                        "_num": int(e_num_m.group(1)) if e_num_m else 9999,
                    })
                episodes.sort(key=lambda e: e["_num"])
                for e in episodes:
                    del e["_num"]
    
            if not episodes:
                seasons_m = re.search(
                    r'<section[^>]+class=["\'][^"\']*allseasonss[^"\']*["\'][^>]*>(.*?)</section>',
                    html, re.S | re.I
                )
                found_seasons = []
                if seasons_m:
                    for s_block in re.finditer(
                        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                        seasons_m.group(1), re.S | re.I
                    ):
                        s_link, s_inner = s_block.group(1), s_block.group(2)
                        h3_m = re.search(r'<h3[^>]*class=["\']title["\'][^>]*>(.*?)</h3>', s_inner, re.S)
                        s_text = h3_m.group(1).strip() if h3_m else re.sub(r'<[^>]+>', ' ', s_inner).strip()
                        s_link_norm = self._normalize_url(s_link)
                        if s_link_norm and s_link_norm != final_url:
                            s_clean = self._clean_title(s_text) or "موسم"
                            found_seasons.append({
                                "title": s_clean,
                                "url": s_link_norm,
                                "type": "series",
                                "_action": "item",
                                "_num": self._season_number(s_text),
                            })
                found_seasons.sort(key=lambda s: s["_num"])
                for s in found_seasons:
                    del s["_num"]
                episodes = found_seasons
    
            if episodes:
                return {
                    "url": final_url,
                    "title": title,
                    "plot": plot,
                    "poster": poster,
                    "servers": [],
                    "items": episodes,
                    "type": "series"
                }
    
        is_series_like = (
            "مسلسل" in raw_title or
            "الحلقة" in watch_page_html or
            "episodes" in watch_page_html.lower() or
            "season" in watch_page_html.lower()
        )
        if is_series_like:
            eps_container = ""
            m = re.search(
                r'<div[^>]+class=["\'][^"\']*episodes--list--side[^"\']*["\'][^>]*>(.*?)</div>',
                watch_page_html, re.S | re.I
            )
            if m:
                eps_container = m.group(1)
            else:
                for container_pat in [
                    r'<div[^>]+class=["\'][^"\']*(?:episodes|series-episodes|season-episodes|ep_list|episodes-list|series-list|all-episodes)[^"\']*["\'][^>]*>(.*?)</div>',
                    r'<ul[^>]*class=["\'][^"\']*(?:episodes|series-episodes|list-episodes|ep_list)[^"\']*["\'][^>]*>(.*?)</ul>',
                    r'<section[^>]*class=["\'][^"\']*(?:episodes|series)[^"\']*["\'][^>]*>(.*?)</section>',
                    r'<div[^>]+id=["\'][^"\']*(?:episodes|episodes-list|episodes-all)[^"\']*["\'][^>]*>(.*?)</div>'
                ]:
                    m = re.search(container_pat, watch_page_html, re.S | re.I)
                    if m:
                        eps_container = m.group(1)
                        break
            if not eps_container:
                eps_container = watch_page_html
    
            eps_matches = re.findall(
                r'<a[^>]+href=["\']([^"\']+/(?:watch|episode)[^"\']*)["\'][^>]*>(.*?)</a>',
                eps_container, re.DOTALL | re.I
            )
            seen_eps = set()
            for e_link, e_inner in eps_matches:
                full_link = self._normalize_url(e_link)
                if not full_link or full_link == watch_url:
                    continue
                if full_link in seen_eps:
                    continue
                seen_eps.add(full_link)
    
                e_text = re.sub(r'<[^>]+>', '', e_inner).strip()
                e_num_m = re.search(r'الحلقة\s*(\d+)', e_text)
                if not e_num_m:
                    e_num_m = re.search(r'(\d+)', e_text)
    
                e_num = e_num_m.group(1).strip() if e_num_m else (e_text[:30] if e_text else "Episode")
                episodes.append({
                    "title": "حلقة " + e_num if e_num.isdigit() else e_num,
                    "url": full_link,
                    "type": "episode",
                    "_action": "item",
                    "_num": int(e_num) if e_num.isdigit() else 9999,
                })
            episodes.sort(key=lambda e: e["_num"])
            for e in episodes:
                del e["_num"]
    
        if servers and episodes:
            item_type = "episode"
        elif episodes:
            item_type = "series"
    
        return {
            "url": final_url,
            "title": title,
            "plot": plot,
            "poster": poster,
            "servers": servers,
            "items": episodes,
            "type": item_type
        }
    
    def extract_stream(self, url):
        log("TopCinema: resolving {}".format(url))
        if url.startswith("topcinema_server|"):
            parts = url.split("|")
            ajax_url = parts[1]
            post_id = parts[2]
            server_index = parts[3]
            referer_url = parts[4] if len(parts) > 4 else self._get_base()
    
            postdata = {
                "id": post_id,
                "i": server_index
            }
            html, _ = fetch(ajax_url, referer=referer_url,
                            extra_headers={"X-Requested-With": "XMLHttpRequest"},
                            post_data=postdata)
    
            ifr_m = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html)
            if ifr_m:
                v_url = self._normalize_url(ifr_m.group(1))
                log("TopCinema: Found iframe '{}'".format(v_url))
                from .base import get_last_quality_variants, get_synthesized_variants
    
                def _variants_for(stream):
                    v = [(lbl, u) for lbl, u in get_last_quality_variants() if u != stream]
                    if not v:
                        v = [(lbl, u) for lbl, u in get_synthesized_variants(stream) if u != stream]
                    return v
    
                resolved = resolve_iframe_chain(v_url, referer=self._get_base())
                if resolved:
                    if isinstance(resolved, tuple):
                        final_stream = resolved[0]
                        final_referer = resolved[1] if len(resolved) > 1 and resolved[1] else self._get_base()
                    else:
                        final_stream = resolved
                        final_referer = self._get_base()
                    variants = _variants_for(final_stream)
                    quality = self._quality_from_url(final_stream)
                    return final_stream, quality, final_referer, variants
                variants = _variants_for(v_url)
                quality = self._quality_from_url(v_url)
                return v_url, quality, self._get_base(), variants
    
        return url, None, self._get_base(), []
    
    def _quality_from_url(self, url):
        if not url:
            return ""
        lower = url.lower()
        if "1080" in lower or "fhd" in lower or "-f3-" in lower or "_o" in lower or "_x" in lower:
            return "1080p"
        if "720" in lower or "-f2-" in lower or "_h" in lower:
            return "720p"
        if "480" in lower or "-f1-" in lower or "_n" in lower:
            return "480p"
        if "360" in lower or "_l" in lower:
            return "360p"
        return "HD"