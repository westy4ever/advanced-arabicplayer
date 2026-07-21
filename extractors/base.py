# -*- coding: utf-8 -*-
"""
Base Extractor - Common utilities and BaseExtractor class.
All site extractors inherit from BaseExtractor.
"""

import re
import json
import time
import random
import base64
import threading
from urllib.request import Request, urlopen, build_opener, HTTPCookieProcessor, HTTPSHandler
from urllib.parse import urljoin, urlparse, unquote, urlencode, quote_plus
from urllib.error import URLError, HTTPError
import http.cookiejar as cookiejar
import ssl
import gzip
import zlib
import io
import sys

# brotli imports (try both common packages)
try:
    import brotli
except ImportError:
    try:
        import brotlicffi as brotli
    except ImportError:
        brotli = None

# ─── curl_cffi fallback (Cloudflare bypass) ───────────────────────────────────
try:
    from curl_cffi import requests as _curl_requests
    _CURL_CFFI_OK = True
except Exception:
    _CURL_CFFI_OK = False
    print("curl_cffi import failed — Cloudflare bypass unavailable")

# ─── External browser proxy integration ─────────────────────────────────────
_BROWSER_PROXY_URL = None

def set_browser_proxy(url):
    global _BROWSER_PROXY_URL
    _BROWSER_PROXY_URL = (url or "").strip()
    log("Browser proxy set to: {}".format(_BROWSER_PROXY_URL or "DISABLED"))

# ─── UI feedback flags ──────────────────────────────────────────────────────
_PROXY_USED = False
_CURL_FAILED_NEEDS_PROXY = False

def set_proxy_used(val=True):
    global _PROXY_USED
    _PROXY_USED = val

def get_proxy_used():
    return _PROXY_USED

def set_curl_failed_needs_proxy(val=True):
    global _CURL_FAILED_NEEDS_PROXY
    _CURL_FAILED_NEEDS_PROXY = val

def get_curl_failed_needs_proxy():
    return _CURL_FAILED_NEEDS_PROXY

UA      = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT = 30
ACCEPT_ENCODING = "gzip, deflate, br" if brotli is not None else "gzip, deflate"

_opener = None
_cookiejar = None

# ─── Thread-local quality variant storage ──────────────────────────────────
_quality_tls = threading.local()

_QUALITY_SUFFIX_LABELS = {
    "_o": "Original", "_x": "Original", "_h": "720p", "_n": "480p", "_l": "360p",
    "-f3-": "1080p", "-f2-": "720p", "-f1-": "480p",
}

# ─── Placeholder / demo-video blocklist ─────────────────────────────────────
_PLACEHOLDER_MEDIA_DOMAINS = (
    "test-videos.co.uk", "sample-videos.com", "samplelib.com",
    "file-examples.com", "learningcontainer.com",
    "commondatastorage.googleapis.com", "download.blender.org",
    "media.w3.org", "html5demos.com", "bitdash-a.akamaihd.net",
    "bitmovin-a.akamaihd.net", "devstreaming-cdn.apple.com",
    "vjs.zencdn.net",
)
_PLACEHOLDER_MEDIA_MARKERS = (
    "bigbuckbunny", "big_buck_bunny", "sintel", "tears_of_steel",
    "elephantsdream", "elephants_dream",
)


def _is_placeholder_media_url(url):
    if not url:
        return False
    lower = url.lower()
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        host = ""
    if any(d in host for d in _PLACEHOLDER_MEDIA_DOMAINS):
        return True
    if any(m in lower for m in _PLACEHOLDER_MEDIA_MARKERS):
        return True
    return False


def log(msg):
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = "[{}] {}\n".format(ts, msg)
        with open("/tmp/arabicplayer.log", "a") as f:
            f.write(line)
        print("[ArabicPlayer] {}".format(msg))
    except Exception:
        pass


def _get_opener():
    global _opener, _cookiejar
    if _opener:
        return _opener
    _cookiejar = cookiejar.CookieJar()
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    except AttributeError:
        ctx = ssl._create_unverified_context()
    _opener = build_opener(HTTPCookieProcessor(_cookiejar), HTTPSHandler(context=ctx))
    return _opener


def clear_cookies(domain=None):
    global _cookiejar
    _get_opener()
    if _cookiejar is None:
        return
    try:
        if domain:
            for cookie in list(_cookiejar):
                if domain in (cookie.domain or ""):
                    _cookiejar.clear(cookie.domain, cookie.path, cookie.name)
        else:
            _cookiejar.clear()
    except Exception as e:
        log("clear_cookies error: {}".format(e))


def _decode_response_body(raw, info):
    ce = info.get("Content-Encoding", "").lower()
    if "gzip" in ce:
        try:
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except Exception as e:
            log("Gzip decompression error: {}".format(e))
    elif "deflate" in ce:
        try:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        except Exception:
            try:
                raw = zlib.decompress(raw)
            except Exception as e:
                log("Deflate decompression error: {}".format(e))
    elif "br" in ce and brotli is not None:
        try:
            raw = brotli.decompress(raw)
        except Exception as e:
            log("Brotli decompression error: {}".format(e))
    charset = "utf-8"
    ctype = info.get("Content-Type", "").lower()
    charset_match = re.search(r'charset=([^\s;]+)', ctype, re.I)
    if charset_match:
        detected_charset = charset_match.group(1).strip()
        detected_charset = detected_charset.strip('"\'')
        if detected_charset:
            charset = detected_charset
    decoders = []
    if charset and charset not in ["utf-8", "utf8"]:
        decoders.append((charset, "Detected charset"))
    decoders.extend([
        ("utf-8", "UTF-8 fallback"),
        ("windows-1256", "Arabic Windows fallback"),
        ("iso-8859-6", "Arabic ISO fallback"),
        ("latin-1", "Latin-1 fallback (preserves bytes)"),
    ])
    for enc, name in decoders:
        try:
            result = raw.decode(enc)
            if enc != "utf-8" and enc != charset:
                log("Decoded with {} encoding".format(name))
            return result
        except (UnicodeDecodeError, LookupError):
            continue
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return raw.decode("latin-1", errors="replace")


def _encode_unicode_url(url):
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
        from urllib.parse import urlunparse
        encoded_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            encoded_path,
            parsed.params,
            encoded_query,
            parsed.fragment
        ))
        return encoded_url
    except Exception:
        return url


def _is_cloudflare_challenge(html):
    if not html:
        return False
    markers = [
        'cf-browser-verification', 'just a moment', 'checking your browser',
        'cf-challenge-running', 'challenge-platform', 'turnstile',
        'cf-im-under', 'ray id', 'cloudflare'
    ]
    html_lower = html.lower()
    return any(m in html_lower for m in markers)


def _fetch_via_browser_proxy(url, referer=None, post_data=None):
    if not _BROWSER_PROXY_URL:
        return None, url
    try:
        import json as _json
        payload = {'url': url, 'referer': referer or "", 'post_data': post_data}
        req = Request(
            _BROWSER_PROXY_URL + '/fetch',
            data=_json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'User-Agent': UA},
            method='POST'
        )
        with urlopen(req, timeout=60) as resp:
            result = _json.loads(resp.read().decode('utf-8'))
            if result.get('success') and result.get('html'):
                log("Browser proxy SUCCESS for {}".format(url[:60]))
                return result['html'], result.get('url', url)
    except Exception as e:
        log("Browser proxy FAILED: {} for {}".format(e, url[:60]))
    return None, url


def fetch(url, referer=None, extra_headers=None, post_data=None):
    """
    Robust fetch with:
    - Smart per-domain referer defaults
    - Auto retry on transient errors
    - curl_cffi fallback for Cloudflare-protected sites
    - External browser proxy fallback for Turnstile CAPTCHAs (if configured)
    - Brotli / gzip / deflate decompression
    - Cookie jar (shared session)
    - UI feedback flags (proxy used / curl failed & proxy missing)
    """
    # Reset UI feedback flags at the start of each fetch
    set_proxy_used(False)
    set_curl_failed_needs_proxy(False)

    max_retries = 2
    use_cffi = False
    parsed_quick = urlparse(url)
    domain_quick = parsed_quick.netloc.lower()
    cf_domains = ("egydead", "wecima", "mycima", "topcinema", "arabseed",
                "shaheed", "shahid", "fasel", "akwam", "akoam")
    if any(d in domain_quick for d in cf_domains):
        use_cffi = True

    for attempt in range(max_retries + 1):
        try:
            # ────────────────────────────────────────────────────────────────
            # PATH A: curl_cffi (Cloudflare JS challenge)
            # ────────────────────────────────────────────────────────────────
            if (use_cffi or attempt > 0) and _CURL_CFFI_OK:
                try:
                    cf_headers = {
                        "User-Agent": UA,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "ar,en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                        "Connection": "keep-alive",
                        "Upgrade-Insecure-Requests": "1",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                        "Sec-Fetch-User": "?1",
                    }
                    if not referer:
                        if "egydead" in domain_quick:
                            referer = "{}://{}/".format(parsed_quick.scheme, domain_quick)
                        elif "wecima" in domain_quick or "mycima" in domain_quick:
                            referer = "https://wecima.click/"
                        elif "topcinema" in domain_quick:
                            referer = "https://topcinemaa.top/"
                        elif "arabseed" in domain_quick:
                            referer = "https://arabseeds.cam/"
                        elif "shaheed" in domain_quick or "shahid" in domain_quick:
                            referer = "https://shahid4u.solar/"
                        elif "fasel" in domain_quick or "faselhdx" in domain_quick:
                            referer = "https://faselhd.rip/"
                        elif "akwam" in domain_quick or "akoam" in domain_quick:
                            referer = "https://akwam.com.co/"
                        else:
                            referer = "{}://{}/".format(parsed_quick.scheme, domain_quick)
                    cf_headers["Referer"] = referer
                    if extra_headers:
                        cf_headers.update(extra_headers)

                    log("curl_cffi fetch: {} (attempt {})".format(url, attempt + 1))
                    if post_data and isinstance(post_data, dict):
                        r = _curl_requests.post(
                            url,
                            data=post_data,
                            headers=cf_headers,
                            impersonate="chrome120",
                            timeout=30
                        )
                    else:
                        r = _curl_requests.get(
                            url,
                            headers=cf_headers,
                            impersonate="chrome120",
                            timeout=30
                        )
                    html = r.text
                    final_url = r.url
                    if any(x in final_url.lower() for x in ("alliance4creativity.com", "watch-it-legally")):
                        log("!!! ACE Redirect detected for {} !!!".format(url))
                        return None, final_url
                    log("curl_cffi OK: {} ({} bytes)".format(final_url, len(html)))
                    return html, final_url
                except Exception as e:
                    log("curl_cffi attempt {} failed: {}".format(attempt + 1, e))
                    if not _BROWSER_PROXY_URL:
                        set_curl_failed_needs_proxy(True)
                    if attempt < max_retries:
                        time.sleep(1.5)
                        continue

            # ────────────────────────────────────────────────────────────────
            # PATH B: Standard urllib (fast path)
            # ────────────────────────────────────────────────────────────────
            opener = _get_opener()
            encoded_url = _encode_unicode_url(url)
            parsed = urlparse(encoded_url)
            domain = parsed.netloc.lower()

            if not referer:
                if "faselhd.rip" in domain:
                    referer = "https://faselhd.rip/"
                elif "web596x.faselhdx.bid" in domain or "web5106x.faselhdx.bid" in domain:
                    referer = "https://web5106x.faselhdx.bid/"
                elif "govid.live" in domain:
                    referer = "https://faselhd.rip/"
                elif "datahowa.asia" in domain:
                    referer = "https://faselhd.rip/"
                elif "scdns.io" in domain:
                    referer = "https://web5106x.faselhdx.bid/"
                elif "fasel" in domain or "faselhdx" in domain or "fasel-hd" in domain:
                    referer = "https://www.fasel-hd.cam/"
                elif "egydead" in domain:
                    referer = "{}://{}/".format(parsed.scheme, domain)
                elif "wecima" in domain or "mycima" in domain:
                    referer = "https://wecima.click/"
                elif "downet.net" in domain:
                    referer = "https://akwam.com.co/"
                elif "topcinema" in domain:
                    referer = "https://topcinemaa.top/"
                elif "shaheed" in domain or "shahid" in domain:
                    referer = "https://shahid4u.solar/"
                elif "streamwish" in domain or "wishfast" in domain:
                    referer = "https://streamwish.to/"
                elif "filemoon" in domain:
                    referer = "https://filemoon.sx/"
                elif "lulustream" in domain:
                    referer = "https://lulustream.com/"
                elif "ok.ru" in domain:
                    referer = "https://ok.ru/"
                elif "vidguard" in domain or "vgfplay" in domain:
                    referer = "https://vidguard.to/"
                elif "filelion" in domain or "vidhide" in domain or "streamhide" in domain:
                    referer = "https://filelions.to/"
                elif "fastvid" in domain:
                    referer = "https://fastvid.cam/"
                elif "rpmvip" in domain:
                    referer = "https://shaaheid4u.rpmvip.com/"
                elif "upn.one" in domain or "upshare" in domain:
                    referer = "https://shiid4u.upn.one/"
                elif any(x in domain for x in ("savefiles.com", "mxcontent.net", "delucloud.xyz", "sprintcdn.com")):
                    referer = "https://wecima.cx/"
                elif "tnmr.org" in domain or "aurorafieldnetwork.store" in domain:
                    referer = "https://wecima.cx/"
                else:
                    referer = "{}://{}/".format(parsed.scheme, domain)

            headers = {
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ar,en-US,en;q=0.9",
                "Accept-Encoding": ACCEPT_ENCODING,
                "Connection": "keep-alive",
                "Referer": referer,
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            }
            if any(x in encoded_url.lower() for x in ["ajax", "get__watch", "get__quality", "api/", ".json"]):
                headers.update({
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                })
            if extra_headers:
                headers.update(extra_headers)

            data = post_data
            if data and isinstance(data, dict):
                data = urlencode(data).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            elif data and isinstance(data, (str, bytes)):
                if isinstance(data, str):
                    data = data.encode("utf-8")

            log("Fetching (attempt {}): {}".format(attempt + 1, encoded_url))
            req = Request(encoded_url, headers=headers, data=data)

            with opener.open(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                final_url = resp.geturl()
                info = resp.info()

                if any(x in final_url.lower() for x in ("alliance4creativity.com", "watch-it-legally")):
                    log("!!! ACE Redirect detected for {} !!!".format(encoded_url))
                    return None, final_url

                html = _decode_response_body(raw, info)

                if not use_cffi and _CURL_CFFI_OK and _is_cloudflare_challenge(html):
                    log("Cloudflare challenge detected in urllib response, switching to curl_cffi")
                    use_cffi = True
                    continue

                if _is_cloudflare_challenge(html):
                    if _BROWSER_PROXY_URL:
                        log("Cloudflare challenge ({} bytes), routing to browser proxy".format(len(html)))
                        proxy_html, proxy_url = _fetch_via_browser_proxy(encoded_url, referer, post_data)
                        if proxy_html:
                            set_proxy_used(True)
                            return proxy_html, proxy_url or final_url
                        log("Browser proxy failed, returning challenge HTML as-is")
                    else:
                        set_curl_failed_needs_proxy(True)
                        log("Cloudflare detected, but proxy is NOT configured. Please enable it in Settings.")

                log("Fetch OK: {} ({} bytes)".format(final_url, len(html)))
                return html, final_url

        except HTTPError as e:
            if attempt < max_retries and e.code in (503, 429, 502, 504):
                log("Fetch HTTPError {}, retrying in 2s: {}".format(e.code, url))
                time.sleep(2)
                continue
            try:
                raw = e.read()
                html = _decode_response_body(raw, e.info()) if raw else ""
                if not use_cffi and _CURL_CFFI_OK and e.code in (403, 503):
                    log("HTTPError {} + possible Cloudflare, switching to curl_cffi".format(e.code))
                    use_cffi = True
                    continue
                if e.code in (403, 503) and _is_cloudflare_challenge(html):
                    if _BROWSER_PROXY_URL:
                        log("HTTPError {} + Cloudflare, trying browser proxy".format(e.code))
                        proxy_html, proxy_url = _fetch_via_browser_proxy(encoded_url, referer, post_data)
                        if proxy_html:
                            set_proxy_used(True)
                            return proxy_html, proxy_url
                    else:
                        set_curl_failed_needs_proxy(True)
                        log("Cloudflare HTTPError, but proxy is NOT configured.")
                log("Fetch HTTPError: {} → {} {} ({} bytes)".format(url, e.code, e.reason, len(html)))
            except Exception:
                log("Fetch HTTPError: {} → {} {}".format(url, getattr(e, "code", "?"), getattr(e, "reason", e)))
            return None, url

        except URLError as e:
            if attempt < max_retries:
                log("Fetch URLError (retry {}): {} → {}".format(attempt + 1, url, e))
                _opener = None
                time.sleep(1.5)
                continue
            log("Fetch URLError: {} → {}".format(url, e))
            _opener = None
            return None, url

        except UnicodeEncodeError as e:
            log("Fetch UnicodeEncodeError: {} → {}".format(url, e))
            try:
                encoded_url = url.encode('utf-8').decode('ascii', errors='ignore')
                if encoded_url != url:
                    log("Retrying with encoded URL: {}".format(encoded_url))
                    return fetch(encoded_url, referer, extra_headers, post_data)
            except Exception:
                pass
            return None, url

        except Exception as e:
            if attempt < max_retries:
                log("Fetch Error (retry {}): {} → {}".format(attempt + 1, url, e))
                time.sleep(1)
                continue
            log("Fetch Error: {} → {}".format(url, e))
            return None, url

    return None, url


# ─── HTML helpers ─────────────────────────────────────────────────────────────

def extract_iframes(html, base_url=""):
    iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
    result = []
    for src in iframes:
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/") and base_url:
            p = urlparse(base_url)
            src = "{}://{}{}".format(p.scheme, p.netloc, src)
        if src.startswith("http"):
            result.append(src)
    return result


def find_m3u8_all(html):
    if not html:
        return []
    patterns = [
        r'["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'file\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'source\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'hls\.loadSource\(["\']([^"\']+)["\']',
        r'"url"\s*:\s*"([^"]+\.m3u8[^"]*)"',
        r'data-(?:url|src)=["\']([^"\']+\.m3u8[^"\']*)["\']',
        r'hlsManifestUrl["\']?\s*:\s*["\']([^"\']+)["\']',
    ]
    seen = set()
    result = []
    for p in patterns:
        for m in re.finditer(p, html, re.I):
            url = m.group(1).replace("\\/", "/").replace("&amp;", "&").replace("\\u0026", "&").strip()
            if url.startswith("//"):
                url = "https:" + url
            if not (url.startswith("http") and ".m3u8" in url):
                continue
            if _is_placeholder_media_url(url):
                log("find_m3u8_all: skipping known placeholder/demo URL: {}".format(url[:100]))
                continue
            if url in seen:
                continue
            seen.add(url)
            result.append(url)
    return result


def _label_quality_variant(url):
    lower = url.lower()
    for suffix, label in _QUALITY_SUFFIX_LABELS.items():
        if suffix in lower:
            return label
    for marker, label in (("1080", "1080p"), ("720", "720p"), ("480", "480p"), ("360", "360p"), ("240", "240p")):
        if marker in lower:
            return label
    return None


def _label_quality_variants(urls):
    _ORDER = {"Original": 0, "1080p": 1, "720p": 2, "480p": 3, "360p": 4, "240p": 5}
    labeled = []
    unlabeled = []
    for u in urls:
        lbl = _label_quality_variant(u)
        if lbl:
            labeled.append((lbl, u))
        else:
            unlabeled.append(u)
    labeled.sort(key=lambda pair: _ORDER.get(pair[0], 99))
    for i, u in enumerate(unlabeled, 1):
        labeled.append(("Quality {}".format(i), u))
    return labeled


def get_last_quality_variants():
    urls = getattr(_quality_tls, "variants", [])
    if len(urls) <= 1:
        return []
    return _label_quality_variants(urls)


def _synthesize_suffix_variants(url):
    if not url:
        return []
    try:
        domain = urlparse(url).netloc.lower()
    except Exception:
        domain = ""
    _SAFE_SYNTH_DOMAINS = (
        "streamruby.net", "cdn-video.xyz", "uqload.is",
        "systemorchestration.space", "highqualityprints.shop",
    )
    if not any(d in domain for d in _SAFE_SYNTH_DOMAINS):
        return []
    m = re.search(r'(_[lnhox])(?=/)', url)
    if m:
        try:
            domain = urlparse(url).netloc.lower()
        except Exception:
            domain = ""
        if "streamruby" in domain or "tnmr" in url.lower():
            quad = ("_l", "_n", "_h", "_o")
        else:
            quad = ("_l", "_n", "_h", "_x")
        base_part = url[:m.start(1)]
        rest = url[m.end(1):]
        out, seen = [], set()
        for s in quad:
            u = base_part + s + rest
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out
    m2 = re.search(r'(-f)(\d)(-)', url)
    if m2:
        prefix = m2.group(1)
        before = url[:m2.start(1)]
        after = url[m2.end(3):]
        out, seen = [], set()
        for d in ("1", "2", "3"):
            u = before + prefix + d + "-" + after
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out
    return []


def get_synthesized_variants(url):
    urls = _synthesize_suffix_variants(url)
    if len(urls) <= 1:
        return []
    return _label_quality_variants(urls)


def find_m3u8(html):
    urls = find_m3u8_all(html)
    _quality_tls.variants = urls
    return urls[0] if urls else None


def find_mp4_all(html):
    if not html:
        return []
    patterns = [
        r'["\']([^"\']+\.mp4[^"\']*)["\']',
        r'file\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
        r'source\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
        r'data-(?:url|src)=["\']([^"\']+\.mp4[^"\']*)["\']',
        r'"url"\s*:\s*"([^"]+\.mp4[^"]*)"',
    ]
    seen = set()
    result = []
    for p in patterns:
        for m in re.finditer(p, html, re.I):
            url = m.group(1).replace("\\/", "/").replace("&amp;", "&").replace("\\u0026", "&").strip()
            if url.startswith("//"):
                url = "https:" + url
            if not (url.startswith("http") and ".mp4" in url):
                continue
            if _is_placeholder_media_url(url):
                log("find_mp4_all: skipping known placeholder/demo URL: {}".format(url[:100]))
                continue
            if url in seen:
                continue
            seen.add(url)
            result.append(url)
    return result


def find_mp4(html):
    urls = find_mp4_all(html)
    _quality_tls.variants = urls
    return urls[0] if urls else None


def _best_media_url(text):
    if not text:
        return None
    candidates = []
    seen = set()

    def score(url):
        lowered = url.lower()
        if "2160" in lowered or "4k" in lowered:   return 5000
        if "1080" in lowered or "fhd" in lowered:  return 4000
        if "720" in lowered  or "hd" in lowered:   return 3000
        if "480" in lowered:                        return 2000
        if "360" in lowered:                        return 1000
        if "240" in lowered or "sd" in lowered:     return 500
        if ".m3u8" in lowered:                      return 3500
        return 100

    patterns = [
        r'sources\s*:\s*\[{[^}]*file\s*:\s*["\']([^"\']+)["\']',
        r'"file"\s*:\s*"([^"]+(?:m3u8|mp4)[^"]*)"',
        r"'file'\s*:\s*'([^']+(?:m3u8|mp4)[^']*)'",
        r'"source"\s*:\s*"([^"]+(?:m3u8|mp4)[^"]*)"',
        r"'source'\s*:\s*'([^']+(?:m3u8|mp4)[^']*)'",
        r'"src"\s*:\s*"([^"]+(?:m3u8|mp4)[^"]*)"',
        r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
        r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
        r'hlsManifestUrl["\']?\s*:\s*["\']([^"\']+)["\']',
        r'"(?:playlist|stream|hls|hls2|master)"\s*:\s*"([^"]+)"',
        r"'(?:playlist|stream|hls|hls2|master)'\s*:\s*'([^']+)'",
    ]
    for pat in patterns:
        for match in re.findall(pat, text, re.I):
            url = match.replace("\\/", "/").replace("&amp;", "&").replace("\\u0026", "&").strip()
            if url.startswith("//"):
                url = "https:" + url
            if not url.startswith("http"):
                continue
            if url in seen:
                continue
            if _is_placeholder_media_url(url):
                log("_best_media_url: skipping known placeholder/demo URL: {}".format(url[:100]))
                continue
            seen.add(url)
            candidates.append((score(url), url))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    best_url = candidates[0][1]
    best_ext = ".m3u8" if ".m3u8" in best_url.lower() else (".mp4" if ".mp4" in best_url.lower() else None)
    _quality_tls.variants = [u for _, u in candidates if not best_ext or best_ext in u.lower()]
    return best_url


# ─── BaseExtractor Class ─────────────────────────────────────────────────────

class BaseExtractor:
    """
    Base class for all site extractors.
    Each site should implement:
      - get_categories(self, mtype="movie") → list of category dicts
      - get_category_items(self, url, page=1) → list of item dicts
      - search(self, query, page=1) → list of item dicts
      - get_page(self, url, m_type=None) → detail dict
      - extract_stream(self, url) → (stream_url, quality, referer)
    """
    
    def __init__(self):
        self.main_url = None
        self.base_url = None
        self._resolved_base = None
    
    def get_categories(self, mtype="movie"):
        """Return categories for this site."""
        raise NotImplementedError("Subclasses must implement get_categories()")
    
    def get_category_items(self, url, page=1):
        """Return items from a category page."""
        raise NotImplementedError("Subclasses must implement get_category_items()")
    
    def search(self, query, page=1):
        """Search for content on this site."""
        raise NotImplementedError("Subclasses must implement search()")
    
    def get_page(self, url, m_type=None):
        """Get detail page data."""
        raise NotImplementedError("Subclasses must implement get_page()")
    
    def extract_stream(self, url):
        """Extract playable stream from a server URL."""
        return extract_stream(url)
    
    def _normalize_url(self, url):
        """Normalize URL with proper encoding."""
        if not url:
            return ""
        url = str(url).strip()
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return urljoin(self._get_base(), url)
        return url
    
    def _get_base(self):
        """Get the base URL for this site."""
        if self._resolved_base:
            return self._resolved_base
        return self.main_url or ""
    
    def _clean_title(self, title):
        """Clean and normalize title text."""
        if not title:
            return ""
        title = re.sub(r'<[^>]+>', ' ', title)
        title = title.replace("&amp;", "&")
        title = re.sub(r'\s+', ' ', title).strip()
        return title
    
    def _strip_tags(self, text):
        """Strip HTML tags from text."""
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()


# ─── Video Host Resolvers ─────────────────────────────────────────────────────

def resolve_streamtape(url):
    try:
        html, _ = fetch(url, referer="https://streamtape.com/")
        if not html:
            return None
        m = re.search(r"robotlink\)\.innerHTML\s*=\s*'([^']+)'\s*\+\s*'([^']+)'", html)
        if m:
            link = m.group(1) + m.group(2)
            if not link.startswith("http"):
                link = "https:" + link
            return link.replace("//streamtape.com", "https://streamtape.com")
        m = re.search(r"robotlink\)\.innerHTML\s*=\s*['\"]([^'\"]+)['\"]", html)
        if m:
            link = m.group(1)
            return ("https:" + link) if link.startswith("//") else link
        m = re.search(r'(/get_video\?[^"\'&\s]+)', html)
        if m:
            return "https://streamtape.com" + m.group(1)
        return find_mp4(html)
    except Exception:
        pass
    return None


def resolve_doodstream(url):
    DOOD_DOMAINS = [
        "dood.re", "dood.to", "dood.so", "dood.pm", "dood.ws",
        "dood.watch", "dood.sh", "dood.la", "dood.li", "dood.cx",
        "dood.xyz", "dood.wf", "d0o0d.com", "dsvplay.com",
        "doods.pro", "ds2play.com", "dooood.com", "doodstream.com",
    ]
    try:
        working_html = None
        working_url  = url
        for dom in DOOD_DOMAINS:
            candidate = re.sub(r'dood\.[a-z]+|dsvplay\.[a-z]+|d0o0d\.[a-z]+|doodstream\.[a-z]+', dom, url)
            html, final = fetch(candidate, referer=candidate)
            if html and "pass_md5" in html:
                working_html = html
                working_url  = candidate
                break
        if not working_html:
            working_html, _ = fetch(url, referer=url)
        if not working_html:
            return None
        m = re.search(r'\$\.get\(["\'](/pass_md5/[^"\']+)["\']', working_html)
        if not m:
            m = re.search(r'pass_md5/([^"\'.\s&]+)', working_html)
            if m:
                pass_path = "/pass_md5/" + m.group(1)
            else:
                return None
        else:
            pass_path = m.group(1)
        parsed = urlparse(working_url)
        dood_base = "{}://{}".format(parsed.scheme, parsed.netloc)
        token_html, _ = fetch(dood_base + pass_path, referer=working_url)
        if not token_html:
            return None
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        rand = "".join(random.choice(chars) for _ in range(10))
        token = pass_path.split("/")[-1]
        return "{}{}&token={}&expiry={}".format(
            token_html.strip(), rand, token, int(time.time() * 1000)
        )
    except Exception:
        pass
    return None


def resolve_vidbom(url):
    try:
        html, _ = fetch(url, referer=url)
        if not html:
            return None
        return find_m3u8(html) or find_mp4(html) or find_packed_links(html)
    except Exception:
        pass
    return None


def resolve_uqload(url):
    try:
        html, _ = fetch(url, referer=url)
        if not html:
            return None
        m = re.search(r'sources:\s*\["([^"]+)"\]', html)
        if m:
            main = m.group(1)
            variants = find_mp4_all(html) or find_m3u8_all(html)
            _quality_tls.variants = variants if main in variants else ([main] + variants)
            return main
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        pass
    return None


def resolve_govid(url):
    try:
        if '.m3u8' in url:
            log("resolve_govid: direct m3u8 URL")
            return url
        html, _ = fetch(url, referer="https://faselhd.rip/")
        if not html:
            return None
        m3u8 = find_m3u8(html)
        if m3u8:
            log("resolve_govid: found m3u8: {}".format(m3u8[:80]))
            return m3u8
        return find_mp4(html)
    except Exception:
        pass
    return None


def resolve_upstream(url):
    try:
        html, _ = fetch(url, referer=url)
        if not html:
            return None
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        pass
    return None


def resolve_mixdrop(url):
    try:
        html, _ = fetch(url, referer=url)
        if not html:
            return None
        m = re.search(r'MDCore\.wurl\s*=\s*"([^"]+)"', html)
        if m:
            link = m.group(1)
            return ("https:" + link) if link.startswith("//") else link
        for txt in _unpack_all(html):
            m = re.search(r'MDCore\.wurl\s*=\s*"([^"]+)"', txt)
            if m:
                link = m.group(1)
                return ("https:" + link) if link.startswith("//") else link
    except Exception:
        pass
    return None


def resolve_voe(url):
    try:
        html, final = fetch(url, referer="https://voe.sx/")
        if not html:
            return None
        for pat in [
            r"'hls'\s*:\s*'([^']+)'",
            r'"hls"\s*:\s*"([^"]+)"',
            r"sources\s*=\s*\[{[^}]*file\s*:\s*'([^']+)'",
            r'"file"\s*:\s*"([^"]+\.m3u8[^"]*)"',
        ]:
            m = re.search(pat, html, re.I)
            if m:
                return m.group(1).replace("\\/", "/")
        import base64
        for enc in re.finditer(r'atob\([\'"]([A-Za-z0-9+/=]+)[\'"]\)', html):
            try:
                dec = base64.b64decode(enc.group(1) + "==").decode("utf-8", errors="ignore")
                mm = re.search(r'(https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*)', dec)
                if mm:
                    return mm.group(1)
            except Exception:
                pass
        for txt in _unpack_all(html):
            best = _best_media_url(txt)
            if best:
                return best
        direct = find_m3u8(html) or find_mp4(html)
        if direct:
            return direct
        for embed_url in re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I):
            if not embed_url.startswith('http') or 'voe.sx' in embed_url:
                continue
            log("voe: Found wrapped embed iframe: {}".format(embed_url))
            result = resolve_host(embed_url)
            if result:
                return result
        return None
    except Exception:
        pass
    return None


def resolve_streamruby(url):
    try:
        html, _ = fetch(url, referer=url)
        if not html:
            return None
        res = find_m3u8(html) or find_mp4(html)
        if res:
            return res
        for txt in _unpack_all(html):
            res = find_m3u8(txt) or find_mp4(txt)
            if res:
                return res
    except Exception:
        pass
    return None


def resolve_hanerix_style(url):
    try:
        html, _ = fetch(url, referer=url)
        if not html:
            return None
        res = find_m3u8(html) or find_mp4(html)
        if res:
            return res
        all_variants = []
        best = None
        for txt in _unpack_all(html):
            m3u8s = find_m3u8_all(txt)
            mp4s = find_mp4_all(txt)
            found = m3u8s or mp4s
            if found:
                if best is None:
                    best = found[0]
                for u in found:
                    if u not in all_variants:
                        all_variants.append(u)
        if best:
            _quality_tls.variants = all_variants
            return best
        return _best_media_url(html)
    except Exception:
        pass
    return None


def resolve_hgcloud(url):
    try:
        html, final_url = fetch(url, referer="https://hgcloud.to/")
        if not html:
            return None
        from .base import resolve_host
        iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+masukestin\.com[^"\']+)["\']', html, re.I)
        if iframe_match:
            embed_url = iframe_match.group(1)
            log("hgcloud: Found masukestin embed: {}".format(embed_url))
            result = resolve_host(embed_url)
            if result:
                return result
        meta_refresh = re.search(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\']\d+;\s*url=([^"\']+)["\']', html, re.I)
        if meta_refresh:
            redirect_url = meta_refresh.group(1)
            if "masukestin" in redirect_url:
                log("hgcloud: Redirecting to masukestin: {}".format(redirect_url))
                result = resolve_host(redirect_url)
                if result:
                    return result
        if "masukestin" in html:
            masukestin_urls = re.findall(r'(https?://masukestin\.com/[^\s"\']+)', html)
            for masukestin_url in masukestin_urls:
                log("hgcloud: Found masukestin URL: {}".format(masukestin_url))
                result = resolve_host(masukestin_url)
                if result:
                    return result
        for embed_url in re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I):
            if not embed_url.startswith('http') or 'hgcloud.to' in embed_url or 'masukestin.com' in embed_url:
                continue
            log("hgcloud: Found non-masukestin embed iframe: {}".format(embed_url))
            result = resolve_host(embed_url)
            if result:
                return result
        for embed_url in re.findall(r'(https?://[a-z0-9.-]+\.[a-z]{2,}/[ev]/[a-zA-Z0-9]+)', html, re.I):
            if 'hgcloud.to' in embed_url or 'masukestin.com' in embed_url:
                continue
            log("hgcloud: Found non-masukestin embed URL in page script: {}".format(embed_url))
            result = resolve_host(embed_url)
            if result:
                return result
        js_redirect = _find_js_redirect(html)
        if js_redirect and "hgcloud.to" not in js_redirect:
            log("hgcloud: Following JS redirect: {}".format(js_redirect))
            result = resolve_host(js_redirect)
            if result:
                return result
            h2, final2 = fetch(js_redirect, referer=url)
            if h2:
                best = _best_media_url(h2)
                if best:
                    return best
                for txt in _unpack_all(h2):
                    best = _best_media_url(txt)
                    if best:
                        return best
        return None
    except Exception as e:
        log("resolve_hgcloud error: {}".format(e))
        return None


def resolve_vidtube(url):
    try:
        html, _ = fetch(url, referer="https://topcinema.fan/")
        if not html or "restricted for this domain" in html.lower():
            html, _ = fetch(url, referer="https://topcinema.fan/")
        if not html:
            return None
        best = _best_media_url(html)
        if best:
            return best
        for txt in _unpack_all(html):
            best = _best_media_url(txt)
            if best:
                return best
    except Exception:
        pass
    return None


def resolve_masukestin(url):
    try:
        html, final_url = fetch(url, referer="https://masukestin.com/")
        if not html:
            return None
        stream_patterns = [
            r'(https?://masukestin\.com/stream/[^\s"\']+\.m3u8[^\s"\']*)',
            r'(https?://masukestin\.com/stream/[^\s"\']+)',
            r'streamUrl\s*:\s*["\']([^"\']+)["\']',
            r'videoUrl\s*:\s*["\']([^"\']+)["\']',
            r'src:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
            r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        ]
        for pattern in stream_patterns:
            match = re.search(pattern, html, re.I)
            if match:
                stream_url = match.group(1)
                stream_url = stream_url.replace("\\/", "/").replace("&amp;", "&")
                if stream_url.startswith("//"):
                    stream_url = "https:" + stream_url
                if ".m3u8" in stream_url:
                    log("masukestin: Found m3u8 stream: {}".format(stream_url[:80]))
                    return stream_url
        script_tags = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S | re.I)
        for script in script_tags:
            for pattern in stream_patterns:
                match = re.search(pattern, script, re.I)
                if match:
                    stream_url = match.group(1)
                    if ".m3u8" in stream_url:
                        log("masukestin: Found m3u8 in script: {}".format(stream_url[:80]))
                        return stream_url
        b64_patterns = [
            r'atob\(["\']([A-Za-z0-9+/=]+)["\']\)',
            r'Base64\.decode\(["\']([A-Za-z0-9+/=]+)["\']\)',
        ]
        for pattern in b64_patterns:
            for match in re.findall(pattern, html):
                try:
                    import base64
                    decoded = base64.b64decode(match).decode('utf-8')
                    stream_match = re.search(r'(https?://masukestin\.com/stream/[^\s"\']+\.m3u8[^\s"\']*)', decoded)
                    if stream_match:
                        log("masukestin: Found m3u8 in base64: {}".format(stream_match.group(1)[:80]))
                        return stream_match.group(1)
                except:
                    pass
        log("masukestin: No stream URL found")
        return None
    except Exception as e:
        log("resolve_masukestin error: {}".format(e))
        return None


def resolve_streamwish(url):
    try:
        html, _ = fetch(url, referer=url)
        if not html:
            return None
        best = _best_media_url(html)
        if best:
            return best
        for txt in _unpack_all(html):
            best = _best_media_url(txt)
            if best:
                return best
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        pass
    return None


def resolve_filemoon(url):
    try:
        html, _ = fetch(url, referer="https://filemoon.sx/")
        if not html:
            return None
        best = _best_media_url(html)
        if best:
            return best
        for txt in _unpack_all(html):
            best = _best_media_url(txt)
            if best:
                return best
        import base64
        for b64 in re.findall(r'atob\(["\']([A-Za-z0-9+/=]{40,})["\']\)', html, re.I):
            try:
                dec = base64.b64decode(b64 + "==").decode("utf-8", "ignore")
                best = _best_media_url(dec)
                if best:
                    return best
            except Exception:
                pass
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        pass
    return None


def resolve_lulustream(url):
    try:
        html, _ = fetch(url, referer="https://1fo1ndyf09qz.tnmr.org",
                        extra_headers={"Origin": "https://lulustream.com"})
        if not html:
            html, _ = fetch(url, referer="https://lulustream.com/")
        if not html:
            return None
        best = _best_media_url(html)
        if best:
            return best
        for txt in _unpack_all(html):
            best = _best_media_url(txt)
            if best:
                return best
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        pass
    return None


def resolve_okru(url):
    try:
        m = re.search(r'ok\.ru/(?:video(?:embed)?/|videoembed/)(\d+)', url)
        if not m:
            m = re.search(r'/(\d{10,})', url)
        if not m:
            return None
        video_id = m.group(1)
        api_url = "https://ok.ru/dk/video.playJSON?movieId={}".format(video_id)
        mobile_ua = ("Mozilla/5.0 (iPad; U; CPU OS 3_2 like Mac OS X; en-us) "
                     "AppleWebKit/531.21.10 (KHTML, like Gecko) "
                     "Version/4.0.4 Mobile/7B334b Safari/531.21.10")
        body, _ = fetch(api_url,
                        referer=url,
                        extra_headers={
                            "User-Agent": mobile_ua,
                            "Accept": "application/json",
                        })
        if body:
            try:
                data = json.loads(body)
                hls = data.get("hlsManifestUrl", "")
                if hls:
                    return hls.replace("\\u0026", "&").replace("\\/", "/")
                for vid in (data.get("videos") or []):
                    u = vid.get("url") or ""
                    if u.startswith("http"):
                        return u.replace("\\u0026", "&").replace("\\/", "/")
            except Exception:
                pass
        embed_url = "https://ok.ru/videoembed/{}".format(video_id)
        html, _ = fetch(embed_url, referer="https://ok.ru/",
                        extra_headers={"User-Agent": mobile_ua})
        if html:
            best = _best_media_url(html)
            if best:
                return best
            m2 = re.search(r'"hlsManifestUrl"\s*:\s*"([^"]+)"', html)
            if m2:
                return m2.group(1).replace("\\u0026", "&").replace("\\/", "/")
    except Exception:
        pass
    return None


def resolve_vidguard(url):
    try:
        html, _ = fetch(url, referer="https://vidguard.to/")
        if not html:
            return None
        for pat in [
            r'stream_url\s*=\s*["\']([^"\']+)["\']',
            r'"(?:file|src|url)"\s*:\s*"([^"]+\.m3u8[^"]*)"',
            r"'(?:file|src|url)'\s*:\s*'([^']+\.m3u8[^']*)'",
        ]:
            m = re.search(pat, html, re.I)
            if m:
                u = m.group(1).replace("\\/", "/").replace("\\u0026", "&")
                return u
        for txt in _unpack_all(html):
            best = _best_media_url(txt)
            if best:
                return best
        import base64
        for b64 in re.findall(r'atob\(["\']([A-Za-z0-9+/=]{40,})["\']\)', html, re.I):
            try:
                dec = base64.b64decode(b64 + "==").decode("utf-8", "ignore")
                best = _best_media_url(dec)
                if best:
                    return best
            except Exception:
                pass
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        pass
    return None


def resolve_fastvid(url):
    try:
        html, final_url = fetch(url, referer="https://fastvid.cam/")
        if not html:
            return None
        patterns = [
            r'(https?://[^\s"\']+\.m3u8[^\s"\']*)',
            r'"(https?://[^"]+\.m3u8[^"]+)"',
            r"'(https?://[^']+\.m3u8[^']+)'",
            r'stream/([^\s"\']+\.m3u8)',
        ]
        found_urls = []
        for pattern in patterns:
            matches = re.findall(pattern, html, re.I)
            for match in matches:
                if match.startswith('/'):
                    parsed = urlparse(final_url or url)
                    full_url = f"{parsed.scheme}://{parsed.netloc}{match}"
                    found_urls.append(full_url)
                elif match.startswith('http'):
                    found_urls.append(match)
        for url in found_urls:
            if 'master.m3u8' in url:
                log(f"resolve_fastvid: found master.m3u8: {url}")
                return url
        for url in found_urls:
            if 'index-f2' in url:
                log(f"resolve_fastvid: found 720p stream: {url}")
                return url
        for url in found_urls:
            if 'index-f1' in url:
                log(f"resolve_fastvid: found 480p stream: {url}")
                return url
        for url in found_urls:
            if '.m3u8' in url:
                log(f"resolve_fastvid: found m3u8: {url}")
                return url
        jw_pattern = r'file:\s*["\']([^"\']+\.m3u8[^"\']*)["\']'
        match = re.search(jw_pattern, html, re.I)
        if match:
            stream_url = match.group(1)
            if stream_url.startswith('/'):
                parsed = urlparse(final_url or url)
                stream_url = f"{parsed.scheme}://{parsed.netloc}{stream_url}"
            log(f"resolve_fastvid: found JWPlayer stream: {stream_url}")
            return stream_url
        return None
    except Exception as e:
        log(f"resolve_fastvid error: {e}")
        return None


def resolve_rpmvip(url):
    if '.m3u8' in url:
        return url
    try:
        html, _ = fetch(url, referer=url)
        if not html:
            return None
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        return url if '.m3u8' in url else None


def resolve_upshare(url):
    if '.m3u8' in url:
        return url
    try:
        html, _ = fetch(url, referer=url)
        if not html:
            return None
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        return url if '.m3u8' in url else None


def resolve_cleantechworld(url):
    try:
        html, _ = fetch(url, referer=url)
        if not html:
            return None
        if "#EXTM3U" in html:
            return url
        m = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', html)
        if m:
            return m.group(1)
        return None
    except Exception as e:
        log(f"resolve_cleantechworld error: {e}")
        return None


def resolve_scdns(url):
    try:
        if '.m3u8' in url:
            log("resolve_scdns: direct m3u8 URL")
            return url
        html, final_url = fetch(url, referer="https://www.fasel-hd.cam/")
        if html:
            m3u8_patterns = [
                r'(https?://[^\s"\']+\.scdns\.io[^\s"\']+\.m3u8[^\s"\']*)',
                r'(https?://[^\s"\']+\.c\.scdns\.io[^\s"\']+\.m3u8[^\s"\']*)',
                r'(https?://master\.[^\s"\']+\.scdns\.io[^\s"\']+\.m3u8[^\s"\']*)',
                r'(https?://r[0-9]+--[^\s"\']+\.c\.scdns\.io[^\s"\']+\.m3u8[^\s"\']*)',
            ]
            for pattern in m3u8_patterns:
                matches = re.findall(pattern, html, re.I)
                for stream_url in matches:
                    stream_url = stream_url.replace('\\/', '/').replace('&amp;', '&')
                    if 'hd1080' in stream_url or '1080' in stream_url:
                        log("resolve_scdns: found 1080p stream")
                        return stream_url
                    elif 'hd720' in stream_url or '720' in stream_url:
                        log("resolve_scdns: found 720p stream")
                        return stream_url
            stream = find_m3u8(html)
            if stream:
                log("resolve_scdns: found m3u8 via generic finder")
                return stream
        return None
    except Exception as e:
        log(f"resolve_scdns error: {e}")
        return None


def resolve_datahowa(url):
    try:
        log("resolve_datahowa: processing {}".format(url[:80]))
        if '.ts' in url:
            base_m3u8 = re.sub(r'/seg_[0-9]+\.ts.*$', '/playlist.m3u8', url)
            if base_m3u8 != url:
                log("resolve_datahowa: converting segment to playlist: {}".format(base_m3u8[:80]))
                return base_m3u8
        if '.m3u8' in url:
            return url
        html, _ = fetch(url, referer="https://faselhd.rip/")
        if html:
            m3u8 = find_m3u8(html)
            if m3u8:
                return m3u8
        return None
    except Exception as e:
        log(f"resolve_datahowa error: {e}")
        return None


def resolve_downet(url):
    try:
        log("resolve_downet: processing {}".format(url[:80]))
        if '.mp4' in url or '.m3u8' in url:
            q = "HD"
            if "1080" in url:
                q = "1080p"
            elif "720" in url:
                q = "720p"
            return url
        html, _ = fetch(url, referer="https://akwam.com.co/")
        if html:
            mp4 = find_mp4(html) or find_m3u8(html)
            if mp4:
                return mp4
        return None
    except Exception as e:
        log(f"resolve_downet error: {e}")
        return None


def resolve_tnmr(url):
    try:
        html, _ = fetch(url, referer="https://wecima.cx/")
        if not html:
            return None
        m = re.search(r'(https?://[^\s"\']+\.tnmr\.org[^\s"\']+\.m3u8[^\s"\']*)', html)
        if m:
            return m.group(1)
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        return None


def resolve_mxcontent(url):
    try:
        if '.mp4' in url:
            return url
        html, _ = fetch(url, referer="https://wecima.cx/")
        if html:
            return find_mp4(html)
    except Exception:
        return None


def resolve_delucloud(url):
    try:
        html, _ = fetch(url, referer="https://wecima.cx/")
        if not html:
            return None
        m = re.search(r'(https?://[^\s"\']+\.delucloud\.xyz[^\s"\']+\.m3u8[^\s"\']*)', html)
        if m:
            return m.group(1)
        return find_m3u8(html)
    except Exception:
        return None


def resolve_savefiles(url):
    try:
        html, _ = fetch(url, referer="https://wecima.cx/")
        if not html:
            return None
        m = re.search(r'(https?://s[0-9]+\.savefiles\.com[^\s"\']+\.m3u8[^\s"\']*)', html)
        if m:
            return m.group(1)
        return find_m3u8(html)
    except Exception:
        return None


def resolve_sprintcdn(url):
    try:
        html, _ = fetch(url, referer="https://wecima.cx/")
        if not html:
            return None
        return find_m3u8(html)
    except Exception:
        return None


def resolve_aurorafieldnetwork(url):
    try:
        html, _ = fetch(url, referer="https://wecima.cx/")
        if not html:
            return None
        if '.txt' in url:
            content, _ = fetch(url, referer="https://wecima.cx/")
            if content:
                m = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', content)
                if m:
                    return m.group(1)
        return find_m3u8(html)
    except Exception:
        return None


def resolve_abstream(url):
    try:
        html, _ = fetch(url, referer="https://abstream.to/")
        if not html:
            return None
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        return None


def resolve_byselapuix(url):
    try:
        html, _ = fetch(url, referer="https://byselapuix.com/")
        if not html:
            return None
        best = _best_media_url(html)
        if best:
            return best
        for txt in _unpack_all(html):
            best = _best_media_url(txt)
            if best:
                return best
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        return None


def resolve_dhcplay(url):
    return resolve_doodstream(url)


def resolve_go_akwam(url):
    try:
        html, final_url = fetch(url, referer="https://akwam.com.co/")
        if not html:
            return None
        source_match = re.search(r'<source[^>]+src="([^"]+\.(?:mp4|m3u8)[^"]*)"', html, re.I)
        if source_match:
            return source_match.group(1)
        downet_match = re.search(r'(https?://s\d+\.downet\.net[^\s"\']+\.(?:mp4|m3u8)[^\s"\']*)', html, re.I)
        if downet_match:
            return downet_match.group(1)
        meta_match = re.search(r'<meta[^>]+http-equiv="refresh"[^>]+content="\d+;\s*url=([^"]+)"', html, re.I)
        if meta_match:
            redirect_url = meta_match.group(1)
            if redirect_url.startswith("//"):
                redirect_url = "https:" + redirect_url
            return resolve_host(redirect_url, referer=url)
        iframe_match = re.search(r'<iframe[^>]+src="([^"]+)"[^>]*>', html, re.I)
        if iframe_match:
            iframe_url = iframe_match.group(1)
            if iframe_url.startswith("//"):
                iframe_url = "https:" + iframe_url
            return resolve_host(iframe_url, referer=url)
        return None
    except Exception as e:
        log("resolve_go_akwam error: {}".format(e))
        return None


def resolve_savefiles_akwam(url):
    try:
        html, _ = fetch(url, referer="https://savefiles.com/")
        if not html:
            return None
        m = re.search(r'(https?://s[0-9]+\.savefiles\.com[^\s"\']+\.m3u8[^\s"\']*)', html)
        if m:
            return m.group(1)
        return find_m3u8(html) or find_mp4(html)
    except Exception:
        return None


# ─── Host dispatcher ──────────────────────────────────────────────────────────

HOST_RESOLVERS = {
    "streamtape":  resolve_streamtape,
    "dood":        resolve_doodstream,
    "dsvplay":     resolve_doodstream,
    "d0o0d":       resolve_doodstream,
    "doods":       resolve_doodstream,
    "ds2play":     resolve_doodstream,
    "dooood":      resolve_doodstream,
    "vidbom":      resolve_vidbom,
    "vidshare":    resolve_vidbom,
    "uqload":      resolve_uqload,
    "govid":       resolve_govid,
    "upstream":    resolve_upstream,
    "mixdrop":     resolve_mixdrop,
    "voe":         resolve_voe,
    "streamruby":  resolve_streamruby,
    "hgcloud":     resolve_hgcloud,
    "masukestin":  resolve_masukestin,
    "masukestin.com": resolve_masukestin,
    "vidtube":     resolve_vidtube,
    "streamwish":  resolve_streamwish,
    "wishfast":    resolve_streamwish,
    "filelion":    resolve_streamwish,
    "filelions":   resolve_streamwish,
    "vidhide":     resolve_streamwish,
    "streamhide":  resolve_streamwish,
    "dhtpre":      resolve_streamwish,
    "embedrise":   resolve_streamwish,
    "hglamioz":    resolve_streamwish,
    "filemoon":    resolve_filemoon,
    "lulustream":  resolve_lulustream,
    "ok.ru":       resolve_okru,
    "okru":        resolve_okru,
    "vidguard":    resolve_vidguard,
    "vgfplay":     resolve_vidguard,
    "fastvid":     resolve_fastvid,
    "fastvid.cam": resolve_fastvid,
    "rpmvip":      resolve_rpmvip,
    "upshare":     resolve_upshare,
    "upn.one":     resolve_upshare,
    "cleantechworld": resolve_cleantechworld,
    "cleantechworld.shop": resolve_cleantechworld,
    "scdns":              resolve_scdns,
    "scdns.io":           resolve_scdns,
    "c.scdns.io":         resolve_scdns,
    "datahowa":           resolve_datahowa,
    "datahowa.asia":      resolve_datahowa,
    "govid.live":         resolve_govid,
    "downet":             resolve_downet,
    "downet.net":         resolve_downet,
    "tnmr.org":        resolve_tnmr,
    "tnmr":            resolve_tnmr,
    "mxcontent":       resolve_mxcontent,
    "mxcontent.net":   resolve_mxcontent,
    "delucloud":       resolve_delucloud,
    "delucloud.xyz":   resolve_delucloud,
    "savefiles":       resolve_savefiles,
    "savefiles.com":   resolve_savefiles,
    "abstream":        resolve_abstream,
    "abstream.to":     resolve_abstream,
    "byselapuix":      resolve_byselapuix,
    "byselapuix.com":  resolve_byselapuix,
    "dhcplay":         resolve_dhcplay,
    "dhcplay.com":     resolve_dhcplay,
    "sprintcdn":       resolve_sprintcdn,
    "sprintcdn.com":   resolve_sprintcdn,
    "aurorafieldnetwork": resolve_aurorafieldnetwork,
    "aurorafieldnetwork.store": resolve_aurorafieldnetwork,
    "go.akwam.com.co":  resolve_go_akwam,
    "go.akwam":         resolve_go_akwam,
    "hanerix":          resolve_hanerix_style,
    "hanerix.com":      resolve_hanerix_style,
    "cdn-video":        resolve_hanerix_style,
    "cdn-video.xyz":    resolve_hanerix_style,
}


def _find_js_redirect(html):
    if not html:
        return None
    m = re.search(r'(?:top\.|window\.)?location(?:\.href)?\s*(?:=|\.replace\()\s*["\']([^"\']+)["\']', html, re.I)
    if not m:
        return None
    url = m.group(1).replace("\\/", "/")
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("http"):
        return url
    return None


def _extract_packer_blocks(html):
    blocks = []
    marker = "eval(function(p,a,c,k,e,d){"
    tail   = ".split('|')))"
    pos = 0
    while True:
        start = (html or "").find(marker, pos)
        if start == -1:
            break
        end = (html or "").find(tail, start)
        if end == -1:
            break
        blocks.append(html[start : end + len(tail)])
        pos = end + len(tail)
    return blocks


def decode_packer(packed):
    try:
        def read_js_string(text, start_idx):
            quote = text[start_idx]
            i = start_idx + 1
            out = []
            while i < len(text):
                ch = text[i]
                if ch == "\\" and i + 1 < len(text):
                    out.append(text[i + 1])
                    i += 2
                    continue
                if ch == quote:
                    return "".join(out), i + 1
                out.append(ch)
                i += 1
            return "", -1

        start = packed.find("}(")
        if start == -1:
            return ""
        idx = start + 2
        while idx < len(packed) and packed[idx] in " \t\r\n":
            idx += 1
        if idx >= len(packed) or packed[idx] not in ("'", '"'):
            return ""

        p, idx = read_js_string(packed, idx)
        if idx == -1:
            return ""

        nums = re.match(r"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*", packed[idx:], re.S)
        if not nums:
            return ""
        a, c = nums.group(1), nums.group(2)
        idx += nums.end()
        if idx >= len(packed) or packed[idx] not in ("'", '"'):
            return ""

        k, idx = read_js_string(packed, idx)
        if idx == -1:
            return ""

        a, c = int(a), int(c)
        k = k.split("|")

        def e(c_val):
            result = ""
            while True:
                result = "0123456789abcdefghijklmnopqrstuvwxyz"[c_val % a] + result
                c_val //= a
                if c_val == 0:
                    break
            return result

        d = {e(i): k[i] or e(i) for i in range(c)}
        return re.sub(r'\b(\w+)\b', lambda x: d.get(x.group(1), x.group(1)), p)
    except Exception:
        return ""


def find_packed_links(html):
    for ev in _extract_packer_blocks(html):
        dec = decode_packer(ev)
        if dec:
            res = find_m3u8(dec) or find_mp4(dec)
            if res:
                return res
    for ev in re.findall(r"eval\(function\(p,a,c,k,e,d\).*?}\(.*?\)\)", html, re.S):
        dec = decode_packer(ev)
        if dec:
            res = find_m3u8(dec) or find_mp4(dec)
            if res:
                return res
    return None


def _unpack_all(html):
    texts = [html]
    for block in _extract_packer_blocks(html):
        dec = decode_packer(block)
        if dec:
            texts.append(dec)
    return texts


def resolve_generic_embed(url):
    try:
        html, final = fetch(url, referer=url)
        if not html:
            return None
        best = _best_media_url(html)
        if best:
            return best
        for txt in _unpack_all(html):
            best = _best_media_url(txt)
            if best:
                return best
        js_redirect = _find_js_redirect(html)
        if js_redirect and js_redirect != url:
            log("resolve_generic_embed: following JS redirect to {}".format(js_redirect[:100]))
            h2, final2 = fetch(js_redirect, referer=url)
            if h2:
                best = _best_media_url(h2)
                if best:
                    return best
                for txt in _unpack_all(h2):
                    best = _best_media_url(txt)
                    if best:
                        return best
                for iframe_url in extract_iframes(h2, final2 or js_redirect)[:3]:
                    h3, _ = fetch(iframe_url, referer=js_redirect)
                    if h3:
                        best = _best_media_url(h3)
                        if best:
                            return best
        for iframe_url in extract_iframes(html, final or url)[:3]:
            h2, _ = fetch(iframe_url, referer=url)
            if h2:
                best = _best_media_url(h2)
                if best:
                    return best
    except Exception:
        pass
    return None


# ─── Main host dispatcher ─────────────────────────────────────────────────────

def resolve_host(url, referer=None):
    domain = urlparse(url).netloc.lower()
    log("resolve_host: domain={} url={}".format(domain, url[:80]))
    for key, resolver in HOST_RESOLVERS.items():
        if key in domain:
            log("Using resolver: {}".format(key))
            result = resolver(url)
            if result:
                return result
            log("Resolver {} returned nothing, trying generic".format(key))
            break
    log("Generic fallback for: {}".format(domain))
    return resolve_generic_embed(url)


# ─── iframe chain resolver ────────────────────────────────────────────────────

def resolve_iframe_chain(url, referer=None, depth=0, max_depth=8):
    if depth > max_depth:
        return None, ""
    html, final_url = fetch(url, referer=referer)
    if not html:
        return None, ""
    active_url = final_url or url
    domain = urlparse(active_url).netloc.lower()
    stream = find_m3u8(html) or find_mp4(html) or find_packed_links(html)
    if stream:
        return stream, domain
    m = re.search(
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\']\d+\s*;\s*url=([^"\']+)["\']',
        html, re.I
    )
    if m:
        new_url = m.group(1).strip()
        if new_url.startswith("//"):
            new_url = "https:" + new_url
        elif not new_url.startswith("http"):
            new_url = urljoin(active_url, new_url)
        if new_url != active_url:
            return resolve_iframe_chain(new_url, referer=active_url, depth=depth + 1, max_depth=max_depth)
    m = re.search(r'(?:window\.location(?:\.href)?\s*=|location\.replace\()\s*["\']([^"\']+)["\']', html, re.I)
    if m:
        new_url = m.group(1).strip()
        if new_url.startswith("//"):
            new_url = "https:" + new_url
        elif not new_url.startswith("http"):
            new_url = urljoin(active_url, new_url)
        if new_url != active_url and "://" in new_url:
            return resolve_iframe_chain(new_url, referer=active_url, depth=depth + 1, max_depth=max_depth)
    iframe_srcs = re.findall(
        r'<(?:iframe|embed|frame)[^>]+(?:src|data-src|data-url|data-lazy-src)=["\']([^"\']+)["\']',
        html, re.I
    )
    for src in iframe_srcs:
        if src.startswith("//"):
            src = "https:" + src
        elif not src.startswith("http"):
            p = urlparse(active_url)
            if src.startswith("/"):
                src = "{}://{}{}".format(p.scheme, p.netloc, src)
            else:
                continue
        if any(x in src.lower() for x in ("facebook.com", "twitter.com", "googletag", "doubleclick", "analytics")):
            continue
        src_domain = urlparse(src).netloc.lower()
        for key, resolver in HOST_RESOLVERS.items():
            if key in src_domain:
                result = resolver(src)
                if result:
                    return result, src_domain
                break
        res, h = resolve_iframe_chain(src, referer=active_url, depth=depth + 1, max_depth=max_depth)
        if res:
            return res, h
    return None, ""


# ─── extract_stream_all (multi-quality) ──────────────────────────────────────

def extract_stream_all(url):
    """
    Extract ALL quality variants from a server URL.
    Returns list of (stream_url, quality_label) tuples.
    """
    log("extract_stream_all: {}".format(url[:80]))
    
    # First try the main extract_stream
    result = extract_stream(url)
    
    variants = []
    if result and len(result) >= 4:
        main_url, quality, ref, extra_variants = result[0], result[1], result[2], result[3]
        if main_url:
            variants.append((main_url, quality or "HD"))
        for lbl, u in extra_variants:
            if u != main_url:
                variants.append((u, lbl))
    elif result and len(result) >= 3:
        main_url, quality, ref = result[0], result[1], result[2]
        if main_url:
            variants.append((main_url, quality or "HD"))
    elif result and len(result) >= 1:
        variants.append((result[0], "HD"))
    
    # If no variants found, try suffix synthesis
    if not variants:
        for lbl, u in get_synthesized_variants(url):
            if u not in [v[0] for v in variants]:
                variants.append((u, lbl))
    
    if not variants:
        return []
    
    # Sort by quality (best first)
    quality_order = {"Original": 0, "1080p": 1, "720p": 2, "480p": 3, "360p": 4, "240p": 5, "HD": 6}
    variants.sort(key=lambda v: quality_order.get(v[1], 99))
    
    return variants


# ─── extract_stream (main entry point) ──────────────────────────────────────

def extract_stream(url):
    """
    Standard entry point used by all extractors.
    Returns (stream_url, quality_label, referer, variants).
    """
    log("--- extract_stream START: {} ---".format(url))
    _quality_tls.variants = []
    raw_url = (url or "").strip()
    if not raw_url:
        return None, "", url, []

    piped_headers = {}
    main_url = raw_url
    if "|" in raw_url:
        main_url, raw_hdrs = raw_url.split("|", 1)
        for part in raw_hdrs.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                piped_headers[k.strip()] = v.strip()

    lower = main_url.lower()

    if main_url.startswith("http") and any(ext in lower for ext in (".m3u8", ".mp4", ".mkv", ".mp3", ".ts")):
        ref = piped_headers.get("Referer")
        if not ref:
            domain = urlparse(main_url).netloc.lower()
            if "scdns.io" in domain:
                ref = "https://web5106x.faselhdx.bid/"
            elif "govid.live" in domain or "datahowa.asia" in domain:
                ref = "https://faselhd.rip/"
            else:
                ref = "{}://{}/".format(*urlparse(main_url)[:2])
        q = "HD"
        if "1080" in lower or "fhd" in lower or "hd1080" in lower:
            q = "1080p"
        elif "720" in lower or "hd" in lower or "hd720" in lower:
            q = "720p"
        elif "480" in lower:
            q = "480p"
        elif "index-f2" in lower:
            q = "720p"
        elif "index-f1" in lower:
            q = "480p"
        elif "master.m3u8" in lower:
            q = "720p"
        log("extract_stream DIRECT: {}".format(main_url))
        return main_url, q, ref, []

    _, final_ref = fetch(main_url, referer=piped_headers.get("Referer"))
    stream = resolve_host(main_url, referer=piped_headers.get("Referer"))
    if not stream:
        log("resolve_host failed, trying iframe chain")
        stream, _ = resolve_iframe_chain(main_url, referer=piped_headers.get("Referer"))

    if stream:
        q = "HD"
        stream_lower = stream.lower()
        if "1080" in stream_lower or "fhd" in stream_lower or "hd1080" in stream_lower:
            q = "1080p"
        elif "720" in stream_lower or "hd" in stream_lower or "hd720" in stream_lower:
            q = "720p"
        elif "480" in stream_lower:
            q = "480p"
        elif "index-f2" in stream_lower:
            q = "720p"
        elif "index-f1" in stream_lower:
            q = "480p"

        variants = [(lbl, u) for lbl, u in get_last_quality_variants() if u != stream]
        if not variants:
            variants = [(lbl, u) for lbl, u in get_synthesized_variants(stream) if u != stream]

        log("extract_stream SUCCESS: {} ({}), {} extra variant(s)".format(stream[:120], q, len(variants)))
        return stream, q, final_ref or main_url, variants

    log("extract_stream FAILED for: {}".format(main_url))
    return None, "", final_ref or main_url, []