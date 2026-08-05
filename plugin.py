# -*- coding: utf-8 -*-
"""
Advanced Arabic Player Plugin for Enigma2
=========================================
تشغيل مواقع الأفلام العربية مباشرة من الرسيفر
الموقع الأول: EgyDead

الأزرار:
  OK         → فتح / تشغيل
  Back       → رجوع
  Red        → أحدث أفلام
  Green      → أحدث مسلسلات
  Yellow     → بحث
  Blue       → إعدادات
  Info       → معلومات العنصر

Module layout
-------------
This file owns the Enigma2 Screen classes and anything that is mutated
via a bare `global` statement from inside them (the live playback
position tracker, the local HTTP proxy hit counters). Everything else
that has no Enigma2/UI coupling has been split out for easier isolated
debugging:
  plugin_util.py  - text/formatting/ranking helpers, poster-cache download
  plugin_state.py - config/favorites/history/saved-position persistence
  plugin_tmdb.py  - TMDb metadata client
"""

import os
import sys
import json
import re
import threading
import time
import http.server
import urllib.request as urllib2

try:
    from urllib.parse import quote, unquote, urlparse, parse_qs, urlencode
except ImportError:
    from urllib import quote, unquote, urlencode
    from urlparse import urlparse, parse_qs

# Dynamic plugin path
PLUGIN_PATH = os.path.dirname(__file__)
if PLUGIN_PATH not in sys.path:
    sys.path.insert(0, PLUGIN_PATH)

from Plugins.Plugin          import PluginDescriptor
from Screens.Screen          import Screen
from Screens.MessageBox      import MessageBox
from Components.ActionMap    import ActionMap
from Components.Label        import Label
from Components.Pixmap       import Pixmap
from Components.MenuList     import MenuList
from Components.ScrollLabel  import ScrollLabel
from enigma import eTimer, ePicLoad, eServiceReference, iPlayableService
from Components.ServiceEventTracker import ServiceEventTracker

# ─── Import from extractors package ─────────────────────────────────────────
from extractors import get_extractor, get_site_names, get_site_metadata
from extractors import get_search_site_order

# ─── Import from split-out helper modules ────────────────────────────────────
from extractors.base import log as base_log, UA, fetch as base_fetch
from extractors.base import set_browser_proxy, get_proxy_used, get_curl_failed_needs_proxy

from plugin_util import (
    SAFE_UA,
    _site_label, _site_tagline, _site_search_item,
    _normalize_query, _strip_arabic_from_english_title, _clean_title_for_tmdb,
    _wrap_ui_text, _single_line_text, _search_scope_label,
    _dedupe_items, _rank_search_items, _quality_rank, _sort_servers,
    _decorate_item_title,
    _display_plot_text, _pick_plot_text_with_source, _pick_plot_text,
    _poster_cache_path, _normalize_poster_url,
    _get_cached_poster, _fetch_poster_bytes,
)
from plugin_state import (
    _PLUGIN_OWNER, _DEFAULT_TMDB_API_KEY,
    _state_path, _default_state, _load_state, _save_state,
    _get_config, _set_config, _entry_from_item, _upsert_library_item,
    _toggle_favorite_entry, _is_favorite, _history_items, _favorite_items,
    _get_saved_position, _save_position, _library_search_suggestions,
)
from plugin_tmdb import (
    _tmdb_enabled, _tmdb_search_metadata, _merge_tmdb_data,
    _tmdb_search_suggestions,
)
from plugin_gridlist import (
    HomeMenuGrid, PosterCardGrid, resolve_icon_path,
    build_pixmap_widgets_xml, build_poster_pixmap_widgets_xml,
    HOME_GRID_COLS, HOME_GRID_ROWS, HOME_CELL_W, HOME_CELL_H,
    HOME_CELL_MARGIN, HOME_BORDER_W, HOME_ICON_PAD_TOP, HOME_ICON_W, HOME_ICON_H,
    POSTER_GRID_COLS, POSTER_GRID_ROWS, POSTER_W, POSTER_H,
)
import plugin_imagecache

_PLUGIN_VERSION = "3.0.0"
_PLUGIN_NAME    = "Advanced Arabic Player"
_TYPE_LABELS    = {"movie": "فيلم", "series": "مسلسل", "episode": "حلقة"}

# ─── Get search order from registry ──────────────────────────────────────────
_SEARCH_SITE_ORDER = get_search_site_order()

# ─── Neon Color Palette ──────────────────────────────────────────────────────
_CLR = {
    "bg":           "#0D1117",
    "surface":      "#161B22",
    "surface2":     "#1C2333",
    "selected":     "#21262D",
    "border":       "#30363D",
    "cyan":         "#00E5FF",
    "purple":       "#E040FB",
    "gold":         "#FFD740",
    "green":        "#39D98A",
    "red":          "#FF6B6B",
    "blue":         "#58A6FF",
    "text":         "#F0F6FC",
    "text2":        "#8B949E",
    "text_dim":     "#484F58",
}

def my_log(msg):
    base_log(msg)


def _get_extractor(site):
    """Get extractor instance from the registry."""
    return get_extractor(site)


def _drain_cmit_queue():
    with _CMIT_LOCK:
        items = list(_CMIT_QUEUE)
        del _CMIT_QUEUE[:]
    for _f, _a, _kw in items:
        try: _f(*_a, **_kw)
        except Exception as _e:
            try: my_log("CMIT drain: {}".format(_e))
            except Exception: pass
    with _CMIT_LOCK:
        pending = bool(_CMIT_QUEUE)
    if pending and _CMIT_TIMER is not None:
        try: _CMIT_TIMER.start(50, True)
        except Exception: pass


_CMIT_QUEUE = []
_CMIT_LOCK  = threading.Lock()
_CMIT_TIMER = None


def callInMainThread(func, *args, **kwargs):
    global _CMIT_TIMER
    with _CMIT_LOCK:
        _CMIT_QUEUE.append((func, args, kwargs))
        if _CMIT_TIMER is None:
            try:
                _CMIT_TIMER = eTimer()
                _CMIT_TIMER.callback.append(_drain_cmit_queue)
            except Exception:
                _CMIT_TIMER = None
        if _CMIT_TIMER is not None:
            try:
                _CMIT_TIMER.start(50, True)
            except Exception:
                pass
            return

    try:
        from twisted.internet import reactor
        reactor.callFromThread(_drain_cmit_queue)
    except Exception:
        pass


# ─── Live playback position tracker ──────────────────────────────────────────
# NOTE: these globals are read AND reassigned via bare `global NAME` from
# many methods inside AdvancedArabicPlayerSimplePlayer below (pause/seek/OSD
# update). That cross-method mutation pattern is why this block stays in
# plugin.py rather than moving to plugin_state.py - splitting it would mean
# rewriting every one of those call sites to go through a module attribute.
_GLOBAL_POS_TIMER      = None
_GLOBAL_POS_SESSION    = None
_GLOBAL_POS_ITEM       = ""
_GLOBAL_PLAY_START_WALL  = 0.0
_GLOBAL_PLAY_START_POS   = 0
_GLOBAL_LAST_SEEK_TARGET = -1


def _global_pos_tick():
    global _GLOBAL_POS_ITEM, _GLOBAL_PLAY_START_WALL, _GLOBAL_PLAY_START_POS
    if not _GLOBAL_POS_ITEM or not _GLOBAL_PLAY_START_WALL:
        return
    try:
        elapsed = time.time() - _GLOBAL_PLAY_START_WALL
        secs    = int(_GLOBAL_PLAY_START_POS + elapsed)
        if secs < 5:
            my_log("Pos tracker: skipping suspicious pos {}s".format(secs))
            return
        _save_position(_GLOBAL_POS_ITEM, secs)
        my_log("Pos tracker saved: {}s for {}".format(secs, _GLOBAL_POS_ITEM[:50]))
    except Exception as e:
        my_log("Pos tracker error: {}".format(e))


def _start_pos_tracker(session, item_url, start_pos=0):
    global _GLOBAL_POS_TIMER, _GLOBAL_POS_SESSION, _GLOBAL_POS_ITEM
    global _GLOBAL_PLAY_START_WALL, _GLOBAL_PLAY_START_POS
    global _GLOBAL_LAST_SEEK_TARGET
    _GLOBAL_LAST_SEEK_TARGET = -1
    _GLOBAL_POS_SESSION     = session
    _GLOBAL_POS_ITEM        = item_url or ""
    _GLOBAL_PLAY_START_WALL = time.time()
    _GLOBAL_PLAY_START_POS  = int(start_pos or 0)
    if _GLOBAL_POS_TIMER is None:
        _GLOBAL_POS_TIMER = eTimer()
        _GLOBAL_POS_TIMER.callback.append(_global_pos_tick)
    try:
        _GLOBAL_POS_TIMER.stop()
    except Exception:
        pass
    if _GLOBAL_POS_ITEM:
        _GLOBAL_POS_TIMER.start(20000, False)
        my_log("Pos tracker started (wall-clock base={}s): {}".format(
            _GLOBAL_PLAY_START_POS, item_url[:50]))


def _stop_pos_tracker():
    global _GLOBAL_POS_ITEM
    _GLOBAL_POS_ITEM = ""
    try:
        if _GLOBAL_POS_TIMER:
            _GLOBAL_POS_TIMER.stop()
    except Exception:
        pass


# ─── Local HTTP Proxy (HiSilicon SSL Shield) ─────────────────────────────────
_PROXY_PORT = 19888
_PROXY_STARTED = False
_PROXY_LAST_HIT = 0
_PROXY_LAST_BYTES = 0
_PROXY_LAST_URL = ""

def start_proxy():
    global _PROXY_STARTED
    if _PROXY_STARTED: return
    try:
        def run_server():
            server = http.server.HTTPServer(('0.0.0.0', _PROXY_PORT), LocalProxyHandler)
            server.serve_forever()
        t = threading.Thread(target=run_server)
        t.daemon = True
        t.start()
        _PROXY_STARTED = True
        my_log("LocalProxy Shield: ACTIVE (Port {})".format(_PROXY_PORT))
    except Exception as e:
        my_log("start_proxy failure: {}".format(e))

class LocalProxyHandler(http.server.BaseHTTPRequestHandler):

    def do_HEAD(self):
        self._handle("HEAD")

    def do_GET(self):
        self._handle("GET")

    def _handle(self, method):
        try:
            global _PROXY_LAST_HIT, _PROXY_LAST_BYTES, _PROXY_LAST_URL
            raw = self.path[1:]
            parsed_req = urlparse(self.path)
            query = parse_qs(parsed_req.query or "")

            piped_headers = ""
            if parsed_req.path == "/stream" and query.get("url"):
                stream_url = unquote(query.get("url", [""])[0]).strip()
                explicit_referer = unquote(query.get("referer", [""])[0]).strip()
                explicit_ua = unquote(query.get("ua", [""])[0]).strip()
            else:
                explicit_referer = ""
                explicit_ua = ""
                if not raw or "://" not in raw:
                    self.send_error(400, "Bad URL")
                    return
                if "|" in raw:
                    stream_url, piped_headers = raw.split("|", 1)
                    stream_url = stream_url.strip()
                else:
                    stream_url = raw.strip()

            headers = {"User-Agent": SAFE_UA}

            if explicit_ua:
                headers["User-Agent"] = explicit_ua

            if piped_headers:
                for part in piped_headers.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        headers[k.strip()] = v.strip()

            if explicit_referer:
                headers["Referer"] = explicit_referer
            elif "Referer" not in headers:
                try:
                    parts = stream_url.split("/")
                    headers["Referer"] = parts[0] + "//" + parts[2] + "/"
                except Exception:
                    pass

            range_hdr = self.headers.get("Range") or self.headers.get("range")
            if range_hdr:
                headers["Range"] = range_hdr
                my_log("Proxy: Range={}".format(range_hdr))

            my_log("Proxy: {} {}".format(method, stream_url[:80]))
            _PROXY_LAST_HIT = time.time()
            _PROXY_LAST_BYTES = 0
            _PROXY_LAST_URL = stream_url

            req = urllib2.Request(stream_url, headers=headers)

            try:
                resp = urllib2.urlopen(req, timeout=30)
                status = resp.getcode()
            except urllib2.HTTPError as http_err:
                my_log("Proxy: Upstream HTTP {} for {}".format(http_err.code, stream_url[:60]))
                status = http_err.code
                resp = http_err
            except Exception as e:
                my_log("Proxy: Upstream connection error: {}".format(e))
                try:
                    self.send_error(502, str(e))
                except Exception:
                    pass
                return

            self.send_response(status)

            resp_hdrs = {}
            try:
                for k, v in resp.getheaders():
                    resp_hdrs[k.lower()] = v
            except Exception:
                pass

            for key in ("content-type", "content-length",
                        "content-range", "accept-ranges",
                        "last-modified", "etag"):
                if key in resp_hdrs:
                    self.send_header(key.title(), resp_hdrs[key])

            if "accept-ranges" not in resp_hdrs:
                self.send_header("Accept-Ranges", "bytes")

            self.end_headers()

            if method == "HEAD":
                return

            try:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    _PROXY_LAST_BYTES += len(chunk)
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except Exception:
                pass

        except Exception as e:
            my_log("Proxy FATAL: {}".format(e))
            try:
                self.send_error(500)
            except Exception:
                pass

    def log_message(self, *args):
        pass


# ─── Home Screen ─────────────────────────────────────────────────────────────
class AdvancedArabicPlayerHome(Screen):
    skin = """
    <screen name="AdvancedArabicPlayerHome" position="center,center" size="1920,1080"
            title="Advanced Arabic Player" flags="wfNoBorder">
        <ePixmap position="0,0" size="1920,1080" pixmap="{plugin_path}/images/bg.png" zPosition="0" alphatest="blend" />

        <!-- ═══ Header Bar (shrunk to grow the grid area) ═══ -->
        <widget name="title_bar"  position="0,0"     size="1920,80" backgroundColor="#0D1117" zPosition="1" />
        <widget name="title_text" position="45,6"    size="1100,36" font="Regular;28" foregroundColor="#00E5FF" transparent="1" zPosition="3" />
        <widget name="subtitle"   position="45,42"   size="1100,28" font="Regular;20" foregroundColor="#8B949E" transparent="1" zPosition="3" />
        <widget name="status"     position="1150,8"  size="725,30"  font="Regular;22" foregroundColor="#FFD740" transparent="1" halign="right" zPosition="3" />
        <widget name="footer"     position="1150,40" size="725,26"  font="Regular;18" foregroundColor="#58A6FF" transparent="1" halign="right" zPosition="3" />

        <!-- ═══ Menu Panel - full width now (category-link pickers only) ═══ -->
        <widget name="menu_box"   position="20,90"   size="1880,915" backgroundColor="#161B22" zPosition="1" />
        <widget name="menu"       position="40,105"  size="1840,885" zPosition="2"
                scrollbarMode="showOnDemand"
                foregroundColor="#F0F6FC"
                foregroundColorSelected="#00E5FF"
                backgroundColor="#161B22"
                backgroundColorSelected="#21262D"
                font="Regular;39" itemHeight="81" transparent="1" />

        <!-- ═══ Home site-selection grid (plugin2.py layout: 4x3, border+icon+cyan effect) ═══ -->
        <widget name="home_grid" position="20,90" size="1880,900" scrollbarMode="showNever" transparent="1" zPosition="2" />
{home_grid_pics}

        <!-- ═══ Movie/series poster grid (categories/search/favorites/history) ═══ -->
        <widget name="poster_grid" position="40,90" size="1840,754" scrollbarMode="showNever" transparent="1" zPosition="2" />
{poster_grid_pics}
        <widget name="grid_status_left"  position="40,860"  size="900,32" font="Regular;22" foregroundColor="#8B949E" transparent="1" halign="left" zPosition="3" />
        <widget name="grid_status_right" position="940,860" size="900,32" font="Regular;22" foregroundColor="#8B949E" transparent="1" halign="right" zPosition="3" />

        <!-- ═══ Button Bar (shrunk to grow the grid area) ═══ -->
        <widget name="btn_bar"    position="0,1015"  size="1920,65" backgroundColor="#0D1117" zPosition="1" />
        <widget name="key_red"    position="45,1028" size="420,32" font="Regular;22" foregroundColor="#FF6B6B" transparent="1" halign="center" zPosition="3" />
        <widget name="key_green"  position="510,1028" size="420,32" font="Regular;22" foregroundColor="#39D98A" transparent="1" halign="center" zPosition="3" />
        <widget name="key_yellow" position="975,1028" size="420,32" font="Regular;22" foregroundColor="#FFD740" transparent="1" halign="center" zPosition="3" />
        <widget name="key_blue"   position="1440,1028" size="420,32" font="Regular;22" foregroundColor="#58A6FF" transparent="1" halign="center" zPosition="3" />
    </screen>
    """

    _HOME_GRID_X = 20
    _HOME_GRID_Y = 90
    _POSTER_GRID_X = 40
    _POSTER_GRID_Y = 90

    def __init__(self, session):
        self.skin = AdvancedArabicPlayerHome.skin.format(
            plugin_path=PLUGIN_PATH,
            home_grid_pics=build_pixmap_widgets_xml(
                self._HOME_GRID_X, self._HOME_GRID_Y,
                HOME_GRID_COLS, HOME_GRID_ROWS, HOME_CELL_W, HOME_CELL_H,
                HOME_CELL_MARGIN, HOME_BORDER_W, HOME_ICON_PAD_TOP, HOME_ICON_W, HOME_ICON_H,
            ),
            poster_grid_pics=build_poster_pixmap_widgets_xml(
                self._POSTER_GRID_X, self._POSTER_GRID_Y,
            ),
        )
        Screen.__init__(self, session)
        self.session = session
        self._items  = []
        self._page   = 1
        self._source = "home"
        self._site   = "egydead"
        self._m_type = "movie"
        self._last_query = ""
        self._nav_stack = []
        self._content_title_base = ""
        self._content_subtitle = ""

        self["title_bar"]  = Label("")
        self["title_text"] = Label("Advanced Arabic Player  v{}".format(_PLUGIN_VERSION))
        self["subtitle"]   = Label("المشغل العربي المتقدم")
        self["status"]     = Label("جاري التحميل...")
        self["footer"]     = Label("TMDb  |  المفضلة  |  السجل")
        self["menu_box"]   = Label("")
        self["menu"]       = MenuList([])
        self["btn_bar"]    = Label("")
        self["key_red"]    = Label("خروج")
        self["key_green"]  = Label("المفضلة")
        self["key_yellow"] = Label("بحث")
        self["key_blue"]   = Label("الإعدادات")

        # ── Home site-menu grid (plugin2.py layout, 4x3) ──
        self["home_grid"] = HomeMenuGrid()
        self["home_grid"].onSelectionChanged = self._onGridSelectionChanged
        for _r in range(HOME_GRID_ROWS):
            for _c in range(HOME_GRID_COLS):
                self["pic_%d_%d" % (_r, _c)] = Pixmap()

        # ── Movie/series poster grid (categories/search/favorites/history) ──
        self["poster_grid"] = PosterCardGrid()
        self["poster_grid"].onSelectionChanged = self._onPosterGridSelectionChanged
        for _r in range(POSTER_GRID_ROWS):
            for _c in range(POSTER_GRID_COLS):
                self["poster_%d_%d" % (_r, _c)] = Pixmap()
        self["grid_status_left"] = Label("")
        self["grid_status_right"] = Label("")
        self._posterPollTimer = eTimer()
        self._posterPollTimer.callback.append(self._onPosterPollTick)

        self._display_mode = "home"  # "home" | "poster" | "list"

        self.onClose.append(self._onPluginClose)

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions", "InfobarMenuActions"],
            {
                "ok":     self._onOk,
                "cancel": self._onBack,
                "red":    self._onRed,
                "green":  self._onGreen,
                "yellow": self._onSearch,
                "blue":   self._onBlue,
                "up":     self._navUp,
                "down":   self._navDown,
                "left":   self._navLeft,
                "right":  self._navRight,
            },
            -1
        )

        self.onLayoutFinish.append(self._init)

    def _init(self):
        for _r in range(HOME_GRID_ROWS):
            for _c in range(HOME_GRID_COLS):
                try:
                    self["pic_%d_%d" % (_r, _c)].instance.setScale(1)
                except Exception:
                    pass
        self._showHome()

    def _setHeader(self, title, subtitle="", status=None):
        self["title_text"].setText(_single_line_text(title, width=42, fallback="Advanced Arabic Player"))
        self["subtitle"].setText(_wrap_ui_text(subtitle, width=56, max_lines=2))
        if status is not None:
            self["status"].setText(status)

    def _showHome(self):
        self._source = "home"
        self._display_mode = "home"
        self._page   = 1
        self._nav_stack = []
        self._setHeader(
            "Advanced Arabic Player  v{}".format(_PLUGIN_VERSION),
            "المشغل العربي المتقدم",
            "الرئيسية"
        )
        # NOTE: this is the site-selection grid only (plugin2.py's own
        # MainMenuGrid held just the 12 sites too - favorites/search/
        # settings are reachable via the button bar instead, matching
        # plugin2's red=exit/green=favorites/yellow=search/blue=settings
        # mapping applied below).
        site_items = [
            ("EgyDead", "واجهة حديثة وبوسترات", "site_egydead"),
            ("EgyDead Coupons", "النسخة العربية - تصنيفات مترجمة", "site_egydead_coupons"),
            ("Akwam (Classic)", "موقع اكوام الكلاسيكي", "site_akwam"),
            ("Akwams (Modern)", "موقع اكوام الحديث", "site_akwams"),
            ("Arabseed", "تصنيفات مرتبة", "site_arabseed"),
            ("Wecima", "أقسام واسعة وبحث سريع", "site_wecima"),
            ("Shaheed4u", "أفلام ومسلسلات حصرية", "site_shaheed"),
            ("Shahid4u", "شاهد فور يو - أفلام ومسلسلات مترجمة", "site_shahid4u"),
            ("TopCinemaa", "مكتبة ضخمة", "site_topcinema"),
            ("FaselHD (RIP)", "واجهة حديثة - سيرفرات متعددة", "site_fasel"),
            ("FaselHD (HDX)", "النسخة الكلاسيكية - دقة عالية", "site_faselhdx"),
            ("Arablionz", "عرب ليونز - افلام ومسلسلات سيرفر Lionz Tv", "site_arablionz"),
        ]
        self._items = [{"title": t, "tagline": tag, "_action": a} for t, tag, a in site_items]

        self._showHomeMode()
        self["home_grid"].setList(self._items)

        self["key_red"].setText("خروج")
        self["key_green"].setText("المفضلة")
        self["key_yellow"].setText("بحث")
        self["key_blue"].setText("الإعدادات")

        self["footer"].setText("TMDb  |  {} مفضلة  |  {} سجل".format(len(_favorite_items()), len(_history_items())))
        self._onGridSelectionChanged()

    # ── Visibility toggles between the three Home render modes ──────────────

    def _hidePosterPixmaps(self):
        for _r in range(POSTER_GRID_ROWS):
            for _c in range(POSTER_GRID_COLS):
                self["poster_%d_%d" % (_r, _c)].hide()

    def _showHomeMode(self):
        self._posterPollTimer.stop()
        self["menu"].hide()
        self["poster_grid"].hide()
        self._hidePosterPixmaps()
        self["grid_status_left"].hide()
        self["grid_status_right"].hide()
        self["home_grid"].show()

    def _showPosterMode(self):
        self["home_grid"].hide()
        for _r in range(HOME_GRID_ROWS):
            for _c in range(HOME_GRID_COLS):
                self["pic_%d_%d" % (_r, _c)].hide()
        self["menu"].hide()
        self["poster_grid"].show()
        self["grid_status_left"].show()
        self["grid_status_right"].show()
        self._posterPollTimer.start(600, False)

    def _showListMode(self):
        self._posterPollTimer.stop()
        self["home_grid"].hide()
        for _r in range(HOME_GRID_ROWS):
            for _c in range(HOME_GRID_COLS):
                self["pic_%d_%d" % (_r, _c)].hide()
        self["poster_grid"].hide()
        self._hidePosterPixmaps()
        self["grid_status_left"].hide()
        self["grid_status_right"].hide()
        self["menu"].show()

    # ── Home site grid: icon overlay + selection status ─────────────────────

    def _updateIcons(self):
        for _r in range(HOME_GRID_ROWS):
            for _c in range(HOME_GRID_COLS):
                self["pic_%d_%d" % (_r, _c)].hide()
        for row, col, item in self["home_grid"].getPageItems():
            icon_path = resolve_icon_path(item, PLUGIN_PATH)
            if not icon_path:
                continue
            widget = self["pic_%d_%d" % (row, col)]
            try:
                widget.instance.setPixmapFromFile(icon_path)
                widget.show()
            except Exception as e:
                my_log("_updateIcons setPixmapFromFile failed: {}".format(e))

    def _onGridSelectionChanged(self):
        item = self["home_grid"].getCurrent()
        if item:
            page, total_pages = self["home_grid"].getPageInfo()
            tagline = item.get("tagline", "")
            if total_pages > 1:
                self["status"].setText("{}  |  صفحة {}/{}".format(tagline, page, total_pages) if tagline else "صفحة {}/{}".format(page, total_pages))
            else:
                self["status"].setText(tagline or "الرئيسية")
        self._updateIcons()

    def _onOk(self):
        if self._display_mode == "home":
            item = self["home_grid"].getCurrent()
            if not item:
                return
            a = item.get("_action", "")
            if a.startswith("site_"):
                self._site = a.replace("site_", "")
                self._showSiteCategories()
            return

        if self._display_mode == "poster":
            item = self["poster_grid"].getCurrent()
            if not item:
                return
            self._openItem(item)
            return

        # ── everything below is the original menu/category/search/
        #    favorites/history logic, unchanged ──
        idx = self["menu"].getSelectedIndex()
        if idx < 0 or idx >= len(self._items):
            return
        item = self._items[idx]

        if item.get("_action") == "separator" or item.get("type") == "separator":
            return

        if "_action" in item:
            a = item["_action"]
            if a.startswith("site_"):
                self._site = a.replace("site_", "")
                self._showSiteCategories()
                return
            elif a == "search":
                self._onSearch()
                return
            elif a == "search_site":
                self._onSearch(item.get("_site", self._site))
                return
            elif a == "favorites":
                self._showLibrary("favorites")
                return
            elif a == "history":
                self._showLibrary("history")
                return
            elif a == "settings":
                self._openSettings()
                return

        curr_type = item.get("type", item.get("_action"))

        if curr_type == "category":
            if item.get("_m_type") in ("movie", "series"):
                self._m_type = item.get("_m_type")
            self._loadCategory(item["url"], item["title"])
            return

        if curr_type in ("season", "series", "episode", "movie", "details"):
            self._openItem(item)
            return

    # ── Mode-aware navigation (grid on Home/poster screens, list elsewhere) ─

    def _navUp(self):
        if self._display_mode == "home":
            self["home_grid"].moveUp()
        elif self._display_mode == "poster":
            self["poster_grid"].moveUp()
        else:
            self["menu"].up()

    def _navDown(self):
        if self._display_mode == "home":
            self["home_grid"].moveDown()
        elif self._display_mode == "poster":
            self["poster_grid"].moveDown()
        else:
            self["menu"].down()

    def _navLeft(self):
        if self._display_mode == "home":
            self["home_grid"].moveLeft()
        elif self._display_mode == "poster":
            self["poster_grid"].moveLeft()
        else:
            self["menu"].pageUp()

    def _navRight(self):
        if self._display_mode == "home":
            self["home_grid"].moveRight()
        elif self._display_mode == "poster":
            self["poster_grid"].moveRight()
        else:
            self["menu"].pageDown()

    # ── Mode-aware colored buttons: plugin2 mapping on Home only, original
    #    meanings preserved everywhere else ──────────────────────────────

    def _onRed(self):
        if self._source == "home":
            self.close()
        else:
            self._loadMovies()

    def _onGreen(self):
        if self._source == "home":
            self._showLibrary("favorites")
        else:
            self._loadSeries()

    def _onBlue(self):
        if self._source == "home":
            self._openSettings()
        else:
            self._nextPage()

    def _onPluginClose(self):
        try:
            self._posterPollTimer.stop()
        except Exception:
            pass
        try:
            plugin_imagecache.cancelAsyncImages()
        except Exception:
            pass

    def _onBack(self):
        if self._nav_stack:
            state = self._nav_stack.pop()
            self._source = state.get("source", "home")

            # Restoring to "home" always goes through _showHome() (which
            # cheaply rebuilds the same 12-site list) rather than replaying
            # stored items through _setList - home items carry no "type"
            # field for _setList's poster/list content-detection to key
            # off, so a generic replay would land in plain list mode
            # instead of the site grid.
            if self._source == "home":
                self._showHome()
                return

            self._site = state.get("site", self._site)
            self._m_type = state.get("m_type", self._m_type)
            self._page = state.get("page", 1)
            self._cat_url = state.get("cat_url", getattr(self, "_cat_url", None))
            self._cat_name = state.get("cat_name", getattr(self, "_cat_name", ""))
            self._next_page_url = state.get("next_page_url", None)
            self._content_title_base = state.get("content_title_base", "")
            self._content_subtitle = state.get("content_subtitle", "")
            items = state.get("items", [])
            header = state.get("header", {})
            if items:
                self._setList(items)
                # Poster mode already set its own header (category/site +
                # live page number) via _updatePosterHeader - only replay
                # the plain snapshot for list-mode (category-link) screens.
                if self._display_mode != "poster":
                    self._setHeader(**header)
            else:
                self._showHome()
        elif self._source != "home":
            self._showHome()
        else:
            self.close()

    def _push_nav_state(self):
        self._nav_stack.append({
            "source": self._source,
            "site": self._site,
            "m_type": self._m_type,
            "page": self._page,
            "cat_url": getattr(self, "_cat_url", None),
            "cat_name": getattr(self, "_cat_name", ""),
            "next_page_url": getattr(self, "_next_page_url", None),
            "content_title_base": getattr(self, "_content_title_base", ""),
            "content_subtitle": getattr(self, "_content_subtitle", ""),
            "items": list(self._items),
            "header": {
                "title": self["title_text"].getText(),
                "subtitle": self["subtitle"].getText(),
                "status": self["status"].getText(),
            },
        })

    def _setListButtons(self):
        # Non-home screens keep the original button meanings (unaffected
        # by the plugin2-style relabeling that only applies to Home).
        self["key_red"].setText("أحدث أفلام")
        self["key_green"].setText("أحدث مسلسلات")
        self["key_yellow"].setText("بحث")
        self["key_blue"].setText("الصفحة التالية")

    def _setList(self, items):
        self._setListButtons()

        # Only real movie/series/episode entries go to the poster grid -
        # pseudo "next page" links (type="category", appended by the
        # extractors' own network-level pagination) are dropped here so
        # they never render as a broken card or open a Detail screen on
        # OK; the blue button (_nextPage) already fetches the next page
        # via self._next_page_url independent of what's in this list.
        content_items = [i for i in items if i.get("type") in ("movie", "series", "episode")]

        if content_items:
            self._items = content_items
            self._display_mode = "poster"
            self._showPosterMode()
            self["poster_grid"].setList(content_items)
            self._onPosterGridSelectionChanged()
            return

        self._items = items
        self._display_mode = "list"
        self._showListMode()
        self["footer"].setText("")
        self["menu"].setList([_decorate_item_title(i, self._site) for i in items])
        self["status"].setText("{} عنصر".format(len(items)))

    # ── Poster grid: live artwork-cache counter + async downloads ───────────
    # Poster art is painted by separate overlay Pixmap widgets (poster_r_c),
    # not embedded in the grid's MultiContent rows - see plugin_gridlist.py.
    # Downloads go through plugin_imagecache's bounded worker-pool queue
    # (ported from westy4ever/XtreamNew) instead of one thread per image.

    def _updateGridFooter(self):
        page, total_pages = self["poster_grid"].getPageInfo()
        total = len(self._items)
        start = (page - 1) * (POSTER_GRID_COLS * POSTER_GRID_ROWS) + 1
        end = min(start + POSTER_GRID_COLS * POSTER_GRID_ROWS - 1, total)
        cached = sum(1 for i in self._items if plugin_imagecache.getCachedImage(i.get("poster") or "", target_size=(POSTER_W, POSTER_H)))
        self["grid_status_left"].setText("Shows {}-{} / {} | Page {} / {}".format(start, end, total, page, total_pages))
        self["grid_status_right"].setText("Artwork cache: {} / {}".format(cached, total))

    def _updatePosterHeader(self):
        """Category name + live grid page number in the title, source
        site name only (no 'المصدر:' label) in the subtitle, and no
        TMDb/favorites/history counts while browsing the poster grid."""
        page, total_pages = self["poster_grid"].getPageInfo()
        base = self._content_title_base or ""
        if total_pages > 1:
            title = "{} \u2014 {}/{}".format(base, page, total_pages) if base else "{}/{}".format(page, total_pages)
        else:
            title = base
        self._setHeader(title, self._content_subtitle or "")
        self["footer"].setText("")

    def _onPosterGridSelectionChanged(self):
        self._updateGridFooter()
        self._updatePosterHeader()
        self._updatePosterPixmaps()
        self._requestVisiblePosters()

    def _requestVisiblePosters(self):
        """Queue downloads for whatever's on the current page. The
        selected item jumps the queue via requestImageAsyncPriority so
        navigation doesn't sit behind a full page of unrelated artwork."""
        selected = self["poster_grid"].getCurrent()
        for row, col, item in self["poster_grid"].getPageItems():
            url = item.get("poster") or ""
            if not url:
                continue
            if item is selected:
                plugin_imagecache.requestImageAsyncPriority(url, target_size=(POSTER_W, POSTER_H))
            else:
                plugin_imagecache.requestImageAsync(url, target_size=(POSTER_W, POSTER_H))

    def _updatePosterPixmaps(self):
        visible = {}
        for row, col, item in self["poster_grid"].getPageItems():
            visible[(row, col)] = item

        for r in range(POSTER_GRID_ROWS):
            for c in range(POSTER_GRID_COLS):
                widget = self["poster_%d_%d" % (r, c)]
                item = visible.get((r, c))
                url = item.get("poster") if item else ""
                path = plugin_imagecache.getCachedImage(url, target_size=(POSTER_W, POSTER_H)) if url else ""
                if path:
                    try:
                        widget.instance.setPixmapFromFile(path)
                        widget.show()
                    except Exception as e:
                        my_log("_updatePosterPixmaps setPixmapFromFile failed: {}".format(e))
                        widget.hide()
                else:
                    widget.hide()

    def _onPosterPollTick(self):
        if self._display_mode != "poster":
            self._posterPollTimer.stop()
            return
        self._updatePosterPixmaps()
        self._updateGridFooter()

    def _nextPage(self):
        cat_url  = getattr(self, "_cat_url",  None)
        cat_name = getattr(self, "_cat_name", "")
        next_url = getattr(self, "_next_page_url", None)
        if self._source == "category" and cat_url:
            self._page += 1
            fetch_url = next_url if (next_url and self._site != "egydead") else cat_url
            self._loadCategory(fetch_url, cat_name)

    def _showSiteCategories(self):
        self._push_nav_state()
        try:
            extractor = _get_extractor(self._site)
            get_categories = getattr(extractor, "get_categories", None)
            if not get_categories:
                cats = [{"title": "لا توجد أقسام", "type": "error"}]
            else:
                if self._site == "egydead" or self._site == "egydead_coupons":
                    movie_cats = get_categories("movie")
                    series_cats = get_categories("series")
                    cats = [_site_search_item(self._site)]
                    for item in movie_cats:
                        updated = dict(item)
                        updated["title"] = updated.get("title", "").replace("[فيلم] ", "").replace("[مسلسل] ", "")
                        updated["_m_type"] = "movie"
                        cats.append(updated)
                    for item in series_cats:
                        updated = dict(item)
                        updated["title"] = updated.get("title", "").replace("[فيلم] ", "").replace("[مسلسل] ", "")
                        updated["_m_type"] = "series"
                        cats.append(updated)
                else:
                    cats = [_site_search_item(self._site)] + (get_categories() or [])
        except Exception as e:
            my_log("_showSiteCategories error for site {}: {}".format(self._site, e))
            cats = [{"title": "فشل جلب الأقسام", "type": "error"}]

        self._source = "categories"
        self._setList(cats)
        self._setHeader(
            "تصنيفات {}".format(_site_label(self._site)),
            _site_tagline(self._site),
            "اختر القسم"
        )

    def _showCategories(self, m_type):
        self._push_nav_state()
        extractor = _get_extractor("egydead")
        get_categories = getattr(extractor, "get_categories", None)
        self._source = "categories"
        self._m_type = m_type
        cats = get_categories(m_type) if get_categories else []
        self._setList(cats)
        self._setHeader(
            "تصنيفات " + ("الأفلام" if m_type == "movie" else "المسلسلات"),
            "استعراض منظم حسب النوع داخل {}".format(_site_label("egydead")),
            "اختر التصنيف"
        )

    def _loadCategory(self, url, name):
        self._push_nav_state()
        self._source = "category"
        self._cat_url = url
        self._cat_name = name
        self["status"].setText("جاري تحميل {}...".format(name))
        self["menu"].setList(["جاري التحميل..."])
        threading.Thread(target=self._bgLoadCategory, args=(url,), daemon=True).start()

    def _bgLoadCategory(self, url):
        try:
            my_log("_bgLoadCategory started: {}, site={}, page={}".format(url, self._site, self._page))
            extractor = _get_extractor(self._site)
            get_category_items = getattr(extractor, "get_category_items", None)
            if not get_category_items:
                callInMainThread(self["status"].setText, "لا توجد نتائج")
                return
            if self._site in ["egydead", "egydead_coupons", "fasel", "faselhdx"]:
                items = get_category_items(url, page=self._page)
            else:
                items = get_category_items(url)
            my_log("_bgLoadCategory got {} items".format(len(items) if items else 0))
            callInMainThread(self._onCategoryLoaded, items)
        except Exception as e:
            my_log("_bgLoadCategory error: {}".format(e))
            callInMainThread(self["status"].setText, "فشل: {}".format(str(e)[:60]))

    def _onCategoryLoaded(self, items):
        if not items:
            self["status"].setText("لا توجد نتائج")
            self["menu"].setList(["لا توجد نتائج"])
            return
        next_page_item = next(
            (i for i in items if i.get("_action") == "category" and i.get("url")),
            None
        )
        self._next_page_url = next_page_item["url"] if next_page_item else None
        self._content_title_base = self._cat_name
        self._content_subtitle = _site_label(self._site)
        self._setHeader(self._content_title_base, self._content_subtitle)
        self._setList(_dedupe_items(items))

    def _loadMovies(self):
        self._showCategories("movie")

    def _loadSeries(self):
        self._showCategories("series")

    def _openSettings(self):
        self.session.open(AdvancedArabicPlayerSettings, self._site)

    def _showLibrary(self, kind):
        self._push_nav_state()
        self._source = kind
        if kind == "favorites":
            items = _favorite_items()
            title = "المفضلة"
            subtitle = "العناصر المحفوظة للوصول السريع"
        else:
            items = _history_items()
            title = "السجل"
            subtitle = "آخر العناصر التي تم تشغيلها"
        if not items:
            self._setHeader(title, subtitle, "لا توجد عناصر بعد")
            self["menu"].setList(["القائمة فارغة"])
            self._items = []
            return
        self._content_title_base = title
        self._content_subtitle = subtitle
        self._setHeader(title, subtitle)
        self._setList(items)

    def _onSearch(self, forced_scope=None):
        self.session.openWithCallback(
            self._onSearchQuery,
            AdvancedArabicPlayerSearch,
            current_site=self._site,
            default_scope=forced_scope or "all",
            query=self._last_query
        )

    def _onSearchQuery(self, result=None):
        if not result:
            return
        scope = "all"
        query = result
        if isinstance(result, tuple):
            query, scope = result
        query = (query or "").strip()
        if not query:
            return
        self._last_query = query
        self._source = "search"
        self._search_scope = scope
        self["status"].setText("بحث عن: {}...".format(query))
        self["menu"].setList(["جاري البحث..."])
        threading.Thread(
            target=self._bgSearch, args=(query, scope), daemon=True
        ).start()

    def _bgSearch(self, query, scope="all"):
        try:
            items = []
            extractors = []
            target_site = scope if scope not in ("", None, "all") else ""
            if target_site in _SEARCH_SITE_ORDER:
                extractors = [(target_site, _get_extractor(target_site))]
            else:
                for name in _SEARCH_SITE_ORDER:
                    try:
                        extractors.append((name, _get_extractor(name)))
                    except Exception:
                        pass
            for site_name, extractor in extractors:
                search_fn = getattr(extractor, "search", None)
                if not callable(search_fn):
                    continue
                try:
                    for item in search_fn(query) or []:
                        item["_site"] = site_name
                        item["_m_type"] = item.get("type", "movie")
                        items.append(item)
                except Exception as e:
                    my_log("Search failed for {}: {}".format(site_name, e))
            callInMainThread(self._onSearchResults, items, query, scope)
        except Exception as e:
            my_log("_bgSearch error: {}".format(e))
            callInMainThread(self["status"].setText, "فشل البحث")

    def _onSearchResults(self, items, query, scope="all"):
        if not items:
            self["status"].setText("لا توجد نتائج لـ: {}".format(query))
            self["menu"].setList(["مفيش نتائج"])
            return
        items = _rank_search_items(items, query)
        if not items:
            self["status"].setText("لا توجد نتائج مطابقة لـ: {}".format(query))
            self["menu"].setList(["لا توجد نتائج مطابقة"])
            return
        self._content_title_base = "نتائج: {}".format(query)
        self._content_subtitle = _search_scope_label(scope)
        self._setHeader(self._content_title_base, self._content_subtitle)
        self._setList(items)

    def _openItem(self, item):
        item_type = item.get("type", self._m_type)

        if item_type == "series":
            m_type = "series"
        elif item_type == "season":
            m_type = "season"
        elif item_type == "episode":
            m_type = "episode"
        elif item_type == "movie":
            m_type = "movie"
        else:
            m_type = item_type or self._m_type

        self.session.open(
            AdvancedArabicPlayerDetail,
            item=item,
            site=item.get("_site", self._site),
            m_type=m_type
        )


# ─── Search Screen ────────────────────────────────────────────────────────────
class AdvancedArabicPlayerSearch(Screen):
    skin = """
    <screen name="AdvancedArabicPlayerSearch" position="center,center" size="1920,1080"
            flags="wfNoBorder">
        <ePixmap position="0,0" size="1920,1080" pixmap="{}/images/bg_search.png" zPosition="0" alphatest="blend" />
        <widget name="bg"       position="0,0"   size="1920,1080" backgroundColor="#0D1117" zPosition="1" />

        <!-- Header -->
        <widget name="title"    position="60,30" size="900,54"  font="Regular;45" foregroundColor="#00E5FF" transparent="1" zPosition="3" />
        <widget name="subtitle" position="60,90" size="1800,36" font="Regular;26" foregroundColor="#8B949E" transparent="1" zPosition="3" />

        <!-- Query Box -->
        <widget name="query_box" position="60,150" size="1800,105" backgroundColor="#161B22" zPosition="2" />
        <widget name="query_label" position="90,165" size="180,27" font="Regular;24" foregroundColor="#00E5FF" transparent="1" zPosition="3" />
        <widget name="query"    position="90,198" size="1740,39" font="Regular;33" foregroundColor="#F0F6FC" transparent="1" zPosition="3" />

        <!-- Scope Box -->
        <widget name="scope_box" position="60,278" size="1800,72" backgroundColor="#1C2333" zPosition="2" />
        <widget name="scope_label" position="90,296" size="165,30" font="Regular;24" foregroundColor="#E040FB" transparent="1" zPosition="3" />
        <widget name="scope"    position="270,294" size="1560,33" font="Regular;28" foregroundColor="#F0F6FC" transparent="1" zPosition="3" />

        <!-- Suggestions -->
        <widget name="suggestions_box" position="60,372" size="1800,570" backgroundColor="#161B22" zPosition="2" />
        <widget name="suggestions_title" position="90,390" size="450,30" font="Regular;24" foregroundColor="#FFD740" transparent="1" zPosition="3" />
        <widget name="suggestions" position="87,435" size="1746,480" zPosition="3"
                scrollbarMode="showOnDemand"
                foregroundColor="#F0F6FC"
                foregroundColorSelected="#00E5FF"
                backgroundColor="#161B22"
                backgroundColorSelected="#21262D"
                font="Regular;32" itemHeight="38" />

        <!-- Footer -->
        <widget name="hint"     position="60,960" size="1800,33" font="Regular;22" foregroundColor="#8B949E" transparent="1" zPosition="3" halign="center" />
        <widget name="key_red"  position="60,1002" size="420,33" font="Regular;24" foregroundColor="#FF6B6B" transparent="1" zPosition="3" halign="center" />
        <widget name="key_green" position="522,1002" size="420,33" font="Regular;24" foregroundColor="#39D98A" transparent="1" zPosition="3" halign="center" />
        <widget name="key_yellow" position="984,1002" size="420,33" font="Regular;24" foregroundColor="#FFD740" transparent="1" zPosition="3" halign="center" />
        <widget name="key_blue" position="1446,1002" size="420,33" font="Regular;24" foregroundColor="#58A6FF" transparent="1" zPosition="3" halign="center" />
    </screen>
    """.format(PLUGIN_PATH)

    def __init__(self, session, current_site="egydead", default_scope="all", query=""):
        Screen.__init__(self, session)
        self._current_site = current_site
        self._query = query or ""
        self._scope = default_scope or "all"

        self["bg"] = Label("")
        self["title"] = Label("بحث احترافي")
        self["subtitle"] = Label("اكتب الاسم واختر النطاق للبحث في المصدر الحالي أو كل المصادر.")
        self["query_box"] = Label("")
        self["query_label"] = Label("نص البحث")
        self["query"] = Label("")
        self["scope_box"] = Label("")
        self["scope_label"] = Label("النطاق")
        self["scope"] = Label("")
        self["suggestions_box"] = Label("")
        self["suggestions_title"] = Label("اقتراحات سريعة")
        self["suggestions"] = MenuList([])
        self["hint"] = Label("OK يفتح الاقتراح  |  أعلى/أسفل للتنقل  |  أحمر: مسح  |  أصفر: اكتب  |  أزرق: نطاق")
        self["key_red"] = Label("مسح")
        self["key_green"] = Label("ابحث الآن")
        self["key_yellow"] = Label("اكتب")
        self["key_blue"] = Label("تبديل النطاق")
        self._suggestions = []
        self._suggestion_ticket = 0

        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions"],
            {
                "ok": self._submit_or_edit,
                "cancel": self.close,
                "up": self._suggestion_up,
                "down": self._suggestion_down,
                "left": self._toggle_scope,
                "right": self._toggle_scope,
                "red": self._clear_query,
                "green": self._submit,
                "yellow": self._edit_query,
                "blue": self._toggle_scope,
            },
            -1
        )

        self.onLayoutFinish.append(self._init_search)

    def _init_search(self):
        self._refresh_suggestions()
        self._refresh()

    def _refresh(self):
        preview = self._query or "اكتب اسم فيلم أو مسلسل أو ممثل"
        self["query"].setText(_wrap_ui_text(preview, width=42, max_lines=2))
        self["scope"].setText(_search_scope_label(self._scope if self._scope else "all"))
        self._refresh_suggestion_list()

    def _refresh_suggestion_list(self):
        if not self._suggestions:
            self["suggestions_title"].setText("اقتراحات سريعة")
            self["suggestions"].setList(["لا توجد اقتراحات حالياً"])
            return
        self["suggestions_title"].setText("اقتراحات سريعة: {}".format(len(self._suggestions)))
        rows = []
        for item in self._suggestions:
            meta = []
            if item.get("source"):
                meta.append(item.get("source"))
            if item.get("kind"):
                meta.append(item.get("kind"))
            if item.get("year"):
                meta.append(item.get("year"))
            label = _single_line_text(item.get("title", ""), width=34, fallback="اقتراح")
            meta_text = " | ".join([x for x in meta if x])
            if meta_text:
                label = "{} [{}]".format(label, meta_text)
            rows.append(label)
        self["suggestions"].setList(rows)

    def _refresh_suggestions(self):
        self._suggestions = _library_search_suggestions(self._query, self._current_site, limit=6)
        self._refresh_suggestion_list()
        ticket = self._suggestion_ticket = self._suggestion_ticket + 1
        if len((self._query or "").strip()) >= 2 and _tmdb_enabled():
            threading.Thread(target=self._bg_tmdb_suggestions, args=(self._query, ticket), daemon=True).start()

    def _bg_tmdb_suggestions(self, query, ticket):
        suggestions = _tmdb_search_suggestions(query, limit=6)
        callInMainThread(self._merge_tmdb_suggestions, query, ticket, suggestions)

    def _merge_tmdb_suggestions(self, query, ticket, suggestions):
        if ticket != self._suggestion_ticket:
            return
        if (query or "").strip() != (self._query or "").strip():
            return
        seen = set(_normalize_query(item.get("query", item.get("title", ""))) for item in self._suggestions)
        for item in suggestions:
            norm = _normalize_query(item.get("query", item.get("title", "")))
            if not norm or norm in seen:
                continue
            seen.add(norm)
            self._suggestions.append(item)
        self._suggestions = self._suggestions[:8]
        self._refresh_suggestion_list()

    def _toggle_scope(self):
        self._scope = self._current_site if self._scope == "all" else "all"
        self._refresh_suggestions()
        self._refresh()

    def _clear_query(self):
        self._query = ""
        self._refresh_suggestions()
        self._refresh()

    def _edit_query(self):
        from Screens.VirtualKeyBoard import VirtualKeyBoard
        self.session.openWithCallback(
            self._onKeyboard,
            VirtualKeyBoard,
            title="ابحث عن فيلم أو مسلسل",
            text=self._query
        )

    def _onKeyboard(self, result):
        if result is None:
            return
        self._query = result.strip()
        self._refresh_suggestions()
        self._refresh()

    def _suggestion_up(self):
        if self._suggestions:
            self["suggestions"].up()

    def _suggestion_down(self):
        if self._suggestions:
            self["suggestions"].down()

    def _submit_or_edit(self):
        idx = self["suggestions"].getSelectedIndex()
        if self._suggestions and idx >= 0 and idx < len(self._suggestions):
            chosen = self._suggestions[idx]
            self.close(((chosen.get("query") or chosen.get("title") or "").strip(), self._scope or "all"))
            return
        if self._query.strip():
            self._submit()
        else:
            self._edit_query()

    def _submit(self):
        query = self._query.strip()
        if not query:
            self._edit_query()
            return
        self.close((query, self._scope or "all"))


class AdvancedArabicPlayerSettings(Screen):
    skin = """
    <screen name="AdvancedArabicPlayerSettings" position="center,center" size="1920,1080"
            flags="wfNoBorder">
        <ePixmap position="0,0" size="1920,1080" pixmap="{}/images/bg_settings.png" zPosition="0" alphatest="blend" />
        <widget name="bg"     position="0,0"   size="1920,1080" backgroundColor="#0D1117" zPosition="1" />

        <!-- Header -->
        <widget name="title"  position="60,30" size="900,57"  font="Regular;45" foregroundColor="#00E5FF" transparent="1" zPosition="3" />
        <widget name="owner"  position="60,96" size="600,36"  font="Regular;27" foregroundColor="#FFD740" transparent="1" zPosition="3" />
        <widget name="site"   position="60,138" size="1800,36" font="Regular;24" foregroundColor="#8B949E" transparent="1" zPosition="3" />

        <!-- Body -->
        <widget name="body_box" position="60,195" size="1800,720" backgroundColor="#161B22" zPosition="2" />
        <widget name="body"   position="90,218" size="1740,675" font="Regular;28" foregroundColor="#F0F6FC" transparent="1" zPosition="3" />

        <!-- Footer -->
        <widget name="hint"   position="60,939" size="1800,36" font="Regular;22" foregroundColor="#8B949E" transparent="1" zPosition="3" halign="center" />
        <widget name="key_red_label"   position="60,987" size="300,36" font="Regular;24" foregroundColor="#FF6B6B" transparent="1" zPosition="3" halign="center" />
        <widget name="key_yellow_label" position="450,987" size="450,36" font="Regular;24" foregroundColor="#FFD740" transparent="1" zPosition="3" halign="center" />
        <widget name="key_blue_label"   position="990,987" size="450,36" font="Regular;24" foregroundColor="#58A6FF" transparent="1" zPosition="3" halign="center" />
    </screen>
    """.format(PLUGIN_PATH)

    def __init__(self, session, current_site):
        Screen.__init__(self, session)
        self._current_site = current_site
        self["bg"] = Label("")
        self["title"] = Label("الإعدادات وحول النسخة")
        self["owner"] = Label("")
        self["site"] = Label("")
        self["body_box"] = Label("")
        self["body"] = ScrollLabel("")
        self["hint"] = Label("OK / Back للإغلاق  |  أحمر: Proxy  |  أصفر: TMDb  |  أزرق: حذف المفتاح")
        self["key_red_label"] = Label("تعيين Proxy")
        self["key_yellow_label"] = Label("تعديل مفتاح TMDb")
        self["key_blue_label"] = Label("حذف المفتاح")
        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions"],
            {
                "ok": self.close,
                "cancel": self.close,
                "up": self["body"].pageUp,
                "down": self["body"].pageDown,
                "left": self["body"].pageUp,
                "right": self["body"].pageDown,
                "red": self._edit_proxy,
                "yellow": self._edit_tmdb_key,
                "blue": self._clear_tmdb_key,
            },
            -1
        )
        self._refresh()

    def _refresh(self):
        self["owner"].setText("المالك: {}".format(_get_config("owner", _PLUGIN_OWNER)))
        self["site"].setText("المصدر الحالي: {}  |  {}".format(_site_label(self._current_site), _site_tagline(self._current_site)))
        api_key = (_get_config("tmdb_api_key", "") or "").strip()
        proxy = (_get_config("browser_proxy", "") or "").strip()
        body = (
            "Advanced Arabic Player v{version}\n\n"
            "TMDb:\n"
            "• الحالة: {tmdb_status}\n"
            "• المفتاح الحالي: {tmdb_key}\n\n"
            "Browser Proxy:\n"
            "• الحالة: {proxy_status}\n"
            "• العنوان: {proxy_addr}\n\n"
            "المكتبة:\n"
            "• المفضلة: {fav_count}\n"
            "• السجل: {hist_count}\n\n"
            "ما الجديد في النسخة الحالية:\n"
            "• إثراء معلومات الفيلم أو المسلسل من TMDb عند توفر المفتاح\n"
            "• دعم مفضلة وسجل محفوظين محليًا\n"
            "• دعم curl_cffi لتجاوز Cloudflare تلقائياً\n"
            "• دعم Proxy خارجي لحل Turnstile (اختياري)\n"
            "• واجهة إعدادات حقيقية بدل الرسالة القديمة\n"
            "• ترتيب أنظف للنتائج والسيرفرات\n"
            "• دعم EgyDead Coupons - النسخة العربية الجديدة\n"
            "• هيكلة كود نظيفة مع نظام BaseExtractor\n\n"
            "طريقة الاستخدام:\n"
            "• اضغط الأحمر لإدخال عنوان خادم Proxy (مثال: http://192.168.1.100:5000)\n"
            "• اضغط الأصفر لإدخال أو تعديل مفتاح TMDb\n"
            "• اضغط الأزرق لحذف المفتاح الحالي\n"
            "• من شاشة التفاصيل استخدم الأحمر لإضافة العنصر إلى المفضلة"
        ).format(
            version=_PLUGIN_VERSION,
            tmdb_status="مفعل" if api_key else "غير مفعل",
            tmdb_key=("********" + api_key[-4:]) if api_key else "غير مضبوط",
            proxy_status="مفعل" if proxy else "غير مفعل",
            proxy_addr=proxy or "غير مضبوط",
            fav_count=len(_favorite_items()),
            hist_count=len(_history_items()),
        )
        self["body"].setText(body)

    def _edit_proxy(self):
        from Screens.VirtualKeyBoard import VirtualKeyBoard
        self.session.openWithCallback(
            self._on_proxy_entered,
            VirtualKeyBoard,
            title="أدخل عنوان خادم المتصفح (مثال: http://192.168.1.100:5000)",
            text=_get_config("browser_proxy", "")
        )

    def _on_proxy_entered(self, value):
        if value is None:
            return
        _set_config("browser_proxy", value.strip())
        try:
            from extractors.base import set_browser_proxy
            set_browser_proxy(value.strip())
        except Exception:
            pass
        self._refresh()

    def _edit_tmdb_key(self):
        from Screens.VirtualKeyBoard import VirtualKeyBoard
        self.session.openWithCallback(
            self._on_tmdb_key_entered,
            VirtualKeyBoard,
            title="أدخل TMDb API Key",
            text=_get_config("tmdb_api_key", "")
        )

    def _on_tmdb_key_entered(self, value):
        if value is None:
            return
        _set_config("tmdb_api_key", value.strip())
        self._refresh()

    def _clear_tmdb_key(self):
        _set_config("tmdb_api_key", "")
        self._refresh()


# ─── Detail / Episode Screen ──────────────────────────────────────────────────
class AdvancedArabicPlayerDetail(Screen):
    skin = """
    <screen name="AdvancedArabicPlayerDetail" position="center,center" size="1920,1080"
            flags="wfNoBorder">
        <ePixmap position="0,0" size="1920,1080" pixmap="{}/images/bg_detail.png" zPosition="0" alphatest="blend" />
        <widget name="bg"          position="0,0"    size="1920,1080" backgroundColor="#0D1117" zPosition="1" />

        <!-- Poster Panel -->
        <widget name="poster_box"  position="45,30"  size="420,600" backgroundColor="#1C2333" zPosition="2" />
        <widget name="poster"      position="68,52"  size="375,555" zPosition="4" alphatest="blend" />

        <!-- Info Panel -->
        <widget name="info_box"    position="495,30" size="1380,405" backgroundColor="#161B22" zPosition="2" />
        <widget name="badge"       position="525,52" size="1320,33"  font="Regular;26" foregroundColor="#E040FB" transparent="1" zPosition="4" />
        <widget name="title"       position="525,93" size="1320,90"  font="Regular;42" foregroundColor="#00E5FF" transparent="1" zPosition="4" />
        <widget name="meta"        position="525,189" size="1320,60" font="Regular;27" foregroundColor="#FFD740" transparent="1" zPosition="4" />
        <widget name="facts"       position="525,255" size="1320,42" font="Regular;24" foregroundColor="#8B949E" transparent="1" zPosition="4" />
        <widget name="source"      position="525,300" size="1320,42" font="Regular;24" foregroundColor="#58A6FF" transparent="1" zPosition="4" />
        <widget name="tmdb_note"   position="525,348" size="1320,33" font="Regular;22" foregroundColor="#39D98A" transparent="1" zPosition="4" />
        <!-- Proxy warning badge -->
        <widget name="proxy_warning" position="525,52" size="400,33" font="Regular;24" foregroundColor="#FF4444" transparent="1" zPosition="4" halign="right" />

        <!-- Plot Panel -->
        <widget name="plot_box"    position="495,450" size="1380,180" backgroundColor="#1C2333" zPosition="2" />
        <widget name="plot_title"  position="525,465" size="600,30"  font="Regular;24" foregroundColor="#FFD740" transparent="1" zPosition="4" />
        <widget name="plot"        position="525,504" size="1320,150"  font="Regular;27" foregroundColor="#F0F6FC" transparent="1" halign="block" valign="top" zPosition="4" />

        <!-- Menu Panel -->
        <widget name="menu_box"    position="45,652" size="1830,315" backgroundColor="#161B22" zPosition="2" />
        <widget name="section"     position="75,663" size="1770,36"  font="Regular;26" foregroundColor="#FFD740" transparent="1" zPosition="4" />
        <widget name="menu"        position="72,708" size="1776,240" zPosition="4"
                scrollbarMode="showOnDemand"
                foregroundColor="#F0F6FC"
                foregroundColorSelected="#00E5FF"
                backgroundColor="#161B22"
                backgroundColorSelected="#21262D"
                font="Regular;32" itemHeight="57" />

        <!-- Footer -->
        <widget name="key_red"     position="45,990" size="420,36" font="Regular;24" foregroundColor="#FF6B6B" transparent="1" zPosition="4" />
        <widget name="key_yellow"  position="510,990" size="420,36" font="Regular;24" foregroundColor="#FFD740" transparent="1" zPosition="4" />
        <widget name="status"      position="990,990" size="870,36"  font="Regular;22" foregroundColor="#8B949E" transparent="1" halign="right" zPosition="4" />
    </screen>
    """.format(PLUGIN_PATH)

    def __init__(self, session, item, site="egydead", m_type="movie"):
        Screen.__init__(self, session)
        self.session = session
        self._item   = item
        self._site   = site
        self._m_type = m_type
        self._data   = None
        self._servers = []
        self._episodes = []
        self._tmp_posters = []
        self._poster_loaded = False
        self._raw_title = ""
        self._closed = False
        self._proxy_warning_shown = False

        self._extract_lock = threading.Lock()
        self._extract_token = 0
        self._extracting = False
        self._quality_choices = []

        self["bg"]     = Label("")
        self["poster_box"] = Label("")
        self["info_box"] = Label("")
        self["plot_box"] = Label("")
        self["menu_box"] = Label("")
        self["poster"] = Pixmap()
        self["badge"]  = Label("")
        self["title"]  = Label(item.get("title", ""))
        self["meta"]   = Label("")
        self["facts"]  = Label("")
        self["source"] = Label("")
        self["tmdb_note"] = Label("")
        self["proxy_warning"] = Label("")
        self["plot_title"] = Label("القصة")
        self["plot"]   = Label("")
        self["section"] = Label("جاري التحضير...")
        self["menu"]   = MenuList([])
        self["key_red"] = Label("المفضلة")
        self["key_yellow"] = Label("تحديث TMDb")
        self["status"] = Label("جاري تحميل التفاصيل...")

        self.picLoad = ePicLoad()
        self.picLoad.PictureData.get().append(self._paintPoster)

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "ok":     self._onOk,
                "cancel": self._onCancel,
                "red":    self._toggleFavorite,
                "yellow": self._refreshTMDb,
                "up":     lambda: self["menu"].up(),
                "down":   lambda: self["menu"].down(),
                "left":   lambda: self["menu"].pageUp(),
                "right":  lambda: self["menu"].pageDown(),
            },
            -1
        )

        self.onLayoutFinish.append(self._load)
        self.onExecBegin.append(self._refreshPoster)

    def _onOk(self):
        """Handle OK button press in the detail screen."""
        idx = self["menu"].getSelectedIndex()
        if idx < 0:
            return

        if self._quality_choices:
            if idx >= len(self._quality_choices):
                return
            choice = self._quality_choices[idx]
            self._quality_choices = []
            self._onStreamFound(choice["url"], choice["label"], choice["final_ref"], choice["server"])
            return

        data = self._data or {}
        item_type = data.get("type") or self._item.get("type")
        episode_has_servers = (item_type == "episode" and self._servers)

        if episode_has_servers:
            if idx >= len(self._servers):
                return
            with self._extract_lock:
                if self._extracting:
                    return
                self._extracting = True
                self._extract_token += 1
                token = self._extract_token
            server = self._servers[idx]
            self["status"].setText("Extracting stream...")
            self["status"].show()
            threading.Thread(target=self._bgExtract, args=(server, token), daemon=True).start()
        elif self._episodes:
            if idx >= len(self._episodes):
                return
            ep = self._episodes[idx]
            self.session.open(AdvancedArabicPlayerDetail, ep, self._site, ep.get("type", "episode"))
        elif self._servers:
            if idx >= len(self._servers):
                return
            with self._extract_lock:
                if self._extracting:
                    return
                self._extracting = True
                self._extract_token += 1
                token = self._extract_token
            server = self._servers[idx]
            self["status"].setText("Extracting stream...")
            self["status"].show()
            threading.Thread(target=self._bgExtract, args=(server, token), daemon=True).start()

    def _load(self):
        item_snapshot = self._item
        threading.Thread(target=self._bgLoad, args=(self._site, item_snapshot, self._m_type), daemon=True).start()

    def _bgLoad(self, site, item, m_type):
        url = item["url"]
        _done = [False]
        def _watchdog():
            if not _done[0] and not getattr(self, "_closed", False):
                my_log("_bgLoad watchdog: timeout for {}".format(url[:60]))
                callInMainThread(self["status"].setText, u"Timeout — please try again")
        _wt = threading.Timer(30, _watchdog)
        _wt.daemon = True
        _wt.start()
        try:
            from extractors.base import log
            log("Detail _bgLoad: START site={}, m_type={}".format(site, m_type))
            extractor = _get_extractor(site)
            get_page = getattr(extractor, "get_page", None)
            if not get_page:
                if not getattr(self, "_closed", False):
                    callInMainThread(self["status"].setText, u"لا توجد بيانات")
                return
            if site in ["egydead", "egydead_coupons", "akwam", "akwams", "wecima"]:
                data = get_page(url, m_type=m_type)
            else:
                data = get_page(url)
            merged_seed = dict(item or {})
            merged_seed.update(data or {})
            data = _merge_tmdb_data(merged_seed)
            _done[0] = True
            if getattr(self, "_closed", False):
                log("Detail _bgLoad: screen closed before load finished, discarding result for {}".format(url[:60]))
                return
            callInMainThread(self._onLoaded, data)
        except Exception as e:
            _done[0] = True
            from extractors.base import log
            log("_bgLoad error: {} -- trying TMDb fallback".format(e))
            if getattr(self, "_closed", False):
                log("Detail _bgLoad: screen closed during error handling, skipping fallback for {}".format(url[:60]))
                return
            try:
                fallback = _merge_tmdb_data(dict(item or {}))
                if getattr(self, "_closed", False):
                    return
                if fallback and (fallback.get("plot") or fallback.get("poster")):
                    callInMainThread(self._onLoaded, fallback)
                else:
                    callInMainThread(self["status"].setText,
                        u"فشل التحميل — {}".format(str(e)[:40]))
            except Exception as e2:
                log("TMDb fallback failed: {}".format(e2))
                if not getattr(self, "_closed", False):
                    callInMainThread(self["status"].setText,
                        u"فشل التحميل — {}".format(str(e)[:40]))
        finally:
            _wt.cancel()

    def _onCancel(self):
        if self._quality_choices:
            self._quality_choices = []
            self["section"].setText(_single_line_text("السيرفرات المتاحة: {}  |  اختر الجودة أو السيرفر".format(len(self._servers)), width=90))
            self["menu"].setList(["{}. {}".format(i + 1, _single_line_text(s.get("name", "Server"), width=58, fallback="Server")) for i, s in enumerate(self._servers)])
            self["status"].setText(self._status_hint("اختار سيرفر — OK"))
            return
        self._closed = True
        try:
            self.picLoad.PictureData.get().remove(self._paintPoster)
        except Exception:
            pass
        for p in self._tmp_posters:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        self.close()

    def _paintPoster(self, picData=None):
        ptr = self.picLoad.getData()
        if ptr:
            self["poster"].instance.setPixmap(ptr)
            self["poster"].show()
            self._poster_loaded = True
        else:
            my_log("_paintPoster (detail): native decode returned empty picture data")

    def _onLoaded(self, data):
        if getattr(self, "_closed", False):
            return
        if not data:
            self["status"].setText("تعذر تحميل الصفحة")
            return

        self._data = data
        self._quality_choices = []
        current_title = _strip_arabic_from_english_title(
            data.get("title") or self._item.get("title", ""))
        self._raw_title = re.sub(r"\s+", " ", current_title).strip()
        self["title"].setText(_wrap_ui_text(current_title, width=30, max_lines=2, fallback="بدون عنوان"))

        meta = []
        if data.get("year"):   meta.append(data["year"])
        if data.get("rating"): meta.append("{}/10".format(data["rating"]))
        if data.get("type"):   meta.append(_TYPE_LABELS.get(data["type"], "عنصر"))
        if data.get("genres"): meta.append(data["genres"])
        self["meta"].setText(_wrap_ui_text("   ".join(meta), width=58, max_lines=2))
        self["badge"].setText("{}  •  {}".format(_site_label(self._site), _TYPE_LABELS.get(data.get("type"), "عنصر")))
        facts = [
            "المفضلة: {}  |  النسخة: {}  |  الوصف: {}".format(
                "محفوظ" if _is_favorite(self._item.get("url")) else "غير محفوظ",
                _PLUGIN_VERSION,
                "موجود" if _pick_plot_text(data, self._item) != "القصة غير متوفرة حالياً لهذا العنصر." else "غير متوفر"
            ),
        ]
        self["facts"].setText(_single_line_text("".join(facts), width=62))
        counts = []
        _nav_items = [e for e in data.get("items", []) if e.get("type") in ("episode", "series", "season")]
        has_episodes = bool(_nav_items)
        has_servers = bool([s for s in data.get("servers", []) if s.get("url")])
        is_series_item = (
            data.get("type") in ("series", "show")
            or self._item.get("type") in ("series", "show")
            or has_episodes
        )
        if has_episodes:
            _nav_label = "المواسم" if all(e.get("type") in ("series", "season") for e in _nav_items) else "الحلقات"
            counts.append("{}: {}".format(_nav_label, len(_nav_items)))
        else:
            counts.append("السيرفرات: {}".format(len([s for s in data.get("servers", []) if s.get("url")])))
        if data.get("year"):
            counts.append("السنة: {}".format(data.get("year")))
        self["source"].setText(_wrap_ui_text("المصدر: {}  |  {}".format(_site_label(self._site), "  |  ".join(counts)), width=58, max_lines=2))
        self["tmdb_note"].setText("TMDb: تم تعزيز البيانات والبوستر" if data.get("_tmdb") else "TMDb: لا توجد بيانات إضافية حالياً")
        if has_episodes:
            plot_label = "قصة المسلسل"
        elif has_servers:
            plot_label = "قصة الفيلم"
        elif is_series_item:
            plot_label = "قصة المسلسل"
        else:
            plot_label = "قصة الفيلم"
        if current_title:
            plot_label = "{}: {}".format(plot_label, current_title[:32])
        self["plot_title"].setText(_single_line_text(plot_label, width=46, fallback="القصة"))

        plot_text, plot_source = _pick_plot_text_with_source(data, self._item)
        plot_text = re.sub(r"^\[.*?\]\s*|^المصدر:\s*.*?\|\s*", "", plot_text)
        _MID_SITES = (
            "EgyDead", "Wecima", "Akoam", "ArabSeed",
            "TopCinema", "TopCinemaa", "FaselHD", "Shaheed", "Shaheed4u",
        )
        for _ms in _MID_SITES:
            plot_text = re.sub(
                r"\s*[|\-]\s*" + re.escape(_ms) + r"[^\u0600-\u06ff\n]{0,25}",
                " ", plot_text, flags=re.I)
            plot_text = re.sub(
                r"\u0639\u0644\u0649\s+\u0645\u0648\u0642\u0639\s+" + re.escape(_ms)
                + r"[^\u0600-\u06ff\n]{0,30}",
                " ", plot_text, flags=re.I)
        plot_text = re.sub(r"  +", " ", plot_text).strip()
        my_log("Detail plot source: {} | len={}".format(plot_source, len(plot_text)))

        _pt = (plot_text or "").strip()
        if len(_pt) > 500:
            _pt = _pt[:500].rsplit(" ", 1)[0] + "…"
        _ar_count = sum(1 for _c in _pt[:80] if "\u0600" <= _c <= "\u06ff")
        if _ar_count > int(len(_pt[:80]) * 0.3):
            _pt = "\u200f" + _pt
        self["plot"].setText(_pt)

        self._servers = _sort_servers([s for s in data.get("servers", []) if s.get("url")])
        self._episodes = [e for e in data.get("items", []) if e.get("type") in ("episode", "series", "season")]

        my_log("Detail _onLoaded: servers={}, items={}".format(len(self._servers), len(self._episodes)))

        is_series = (
            data.get("type") in ("series", "show")
            or self._item.get("type") in ("series", "show")
            or bool(self._episodes)
        )

        item_type = data.get("type") or self._item.get("type")
        episode_has_servers = (item_type == "episode" and self._servers)

        def _get_quality_badge(quality):
            if not quality:
                return ""
            q_lower = quality.lower()
            if "1080" in q_lower or "fhd" in q_lower or "hd1080" in q_lower:
                return " 🔵 1080p"
            elif "720" in q_lower or "hd" in q_lower or "hd720" in q_lower:
                return " 🟢 720p"
            elif "480" in q_lower:
                return " 🟡 480p"
            elif "360" in q_lower:
                return " ⚪ 360p"
            else:
                return " 🟣 {}".format(quality)

        if episode_has_servers:
            self["section"].setText(_single_line_text("السيرفرات المتاحة: {}  |  اختر الجودة أو السيرفر".format(len(self._servers)), width=90))
            server_labels = []
            for i, s in enumerate(self._servers):
                name = s.get("name", "Server")
                quality = s.get("quality", "")
                badge = _get_quality_badge(quality)
                server_labels.append("{}. {}{}".format(i + 1, _single_line_text(name, width=40, fallback="Server"), badge))
            self["menu"].setList(server_labels)
            self["status"].setText(self._status_hint("اختار سيرفر — OK"))
        elif self._episodes:
            _all_seasons = all(e.get("type") in ("series", "season") for e in self._episodes)
            _list_label = "المواسم المتاحة" if _all_seasons else "الحلقات المتاحة"
            _pick_hint = "اختار الموسم المطلوب" if _all_seasons else "اختار الحلقة المطلوبة"
            _ok_hint = "اختار موسم — OK" if _all_seasons else "اختار حلقة — OK"
            self["section"].setText(_single_line_text("{}: {}  |  {}".format(_list_label, len(self._episodes), _pick_hint), width=90))
            self["menu"].setList(["{}. {}".format(i + 1, _single_line_text(ep.get("title", "Episode"), width=58, fallback="حلقة")) for i, ep in enumerate(self._episodes)])
            self["status"].setText(self._status_hint(_ok_hint))
        elif self._servers:
            self["section"].setText(_single_line_text("السيرفرات المتاحة: {}  |  اختر الجودة أو السيرفر".format(len(self._servers)), width=90))
            server_labels = []
            for i, s in enumerate(self._servers):
                name = s.get("name", "Server")
                quality = s.get("quality", "")
                badge = _get_quality_badge(quality)
                server_labels.append("{}. {}{}".format(i + 1, _single_line_text(name, width=40, fallback="Server"), badge))
            self["menu"].setList(server_labels)
            self["status"].setText(self._status_hint("اختار سيرفر — OK"))
        elif is_series:
            self["section"].setText("الحلقات المتاحة: 0")
            self["menu"].setList(["لا توجد حلقات متاحة حالياً"])
            self["status"].setText("لا توجد حلقات")
        else:
            self["section"].setText("السيرفرات المتاحة: 0")
            self["menu"].setList(["لا توجد سيرفرات متاحة"])
            self["status"].setText("لا توجد سيرفرات")

        poster_url = data.get("poster") or self._item.get("poster", "")
        if poster_url:
            threading.Thread(
                target=self._downloadPoster, args=(poster_url,), daemon=True
            ).start()

    def _status_hint(self, prefix):
        fav_state = "محفوظ" if _is_favorite(self._item.get("url")) else "غير محفوظ"
        tmdb_state = "TMDb مفعل" if _tmdb_enabled() else "TMDb غير مفعل"
        return "{}  |  {}  |  {}".format(prefix, fav_state, tmdb_state)

    def _refreshPoster(self):
        if getattr(self, "_poster_loaded", False):
            try:
                self["poster"].show()
            except Exception:
                pass
            return
        poster_url = None
        if self._data and self._data.get("poster"):
            poster_url = self._data["poster"]
        elif self._item.get("poster"):
            poster_url = self._item["poster"]
        if poster_url:
            self._downloadPoster(poster_url)
        else:
            callInMainThread(self["poster"].hide)

    def _downloadPoster(self, url):
        try:
            if not url: return
            url = _normalize_poster_url(url)

            import urllib.request as urllib2

            cached = _get_cached_poster(url)
            if cached:
                my_log("_downloadPoster (detail): using cached file for {}".format(url))
                callInMainThread(self.picLoad.setPara, (self["poster"].instance.size().width(), self["poster"].instance.size().height(), 1, 1, 0, 1, "#000000"))
                callInMainThread(self.picLoad.startDecode, cached)
                return

            cache_path = _poster_cache_path(url)
            from urllib.parse import urlparse as _urlparse
            _p = _urlparse(url)
            referer = "{}://{}/".format(_p.scheme, _p.netloc)
            my_log("_downloadPoster (detail): fetching {}".format(url))
            data = _fetch_poster_bytes(url, referer, timeout=10)
            my_log("_downloadPoster (detail): downloaded {} bytes for {}".format(len(data) if data else 0, url))

            save_path = cache_path or "/tmp/ap_detail_{}.jpg".format(int(time.time()))
            with open(save_path, "wb") as f:
                f.write(data)
            if not cache_path:
                self._tmp_posters.append(save_path)
            my_log("_downloadPoster (detail): saved to {}, handing to picLoad".format(save_path))
            callInMainThread(self.picLoad.setPara, (self["poster"].instance.size().width(), self["poster"].instance.size().height(), 1, 1, 0, 1, "#000000"))
            callInMainThread(self.picLoad.startDecode, save_path)
        except Exception as e:
            my_log("_downloadPoster error: {} (URL: {})".format(e, url))

    def _toggleFavorite(self):
        base = self._data or self._item
        entry = _entry_from_item(
            dict(self._item, **(base or {})),
            self._site,
            self._m_type,
            {"type": (base or {}).get("type", self._item.get("type", self._m_type))}
        )
        added = _toggle_favorite_entry(entry)
        self["status"].setText("تمت الإضافة إلى المفضلة" if added else "تم الحذف من المفضلة")
        if self._data:
            self._onLoaded(self._data)

    def _refreshTMDb(self):
        if not _tmdb_enabled():
            self["status"].setText("أضف TMDb API Key من الإعدادات أولاً")
            return
        self["status"].setText("جاري تحديث البيانات من TMDb...")
        threading.Thread(target=self._bgRefreshTMDb, daemon=True).start()

    def _bgRefreshTMDb(self):
        try:
            merged = _merge_tmdb_data(self._data or self._item)
            callInMainThread(self._onLoaded, merged)
        except Exception as e:
            my_log("TMDb refresh failed: {}".format(e))
            callInMainThread(self["status"].setText, "فشل تحديث TMDb")

    def _bgExtract(self, server, token=None):
        try:
            from extractors.base import log
            log("Detail _bgExtract: START extracting for server={} (token={})".format(server.get("name", "Unknown"), token))

            extract_fn = None
            try:
                extractor = _get_extractor(self._site)
                extract_fn = getattr(extractor, "extract_stream", None)
            except Exception:
                extract_fn = None

            if extract_fn is None:
                from extractors.base import extract_stream as extract_fn

            result = extract_fn(server["url"])
            if len(result) >= 4:
                url, qual, final_ref, variants = result[0], result[1], result[2], result[3]
            else:
                url, qual, final_ref = result[0], result[1], result[2]
                variants = []

            if getattr(self, "_closed", False):
                log("Detail _bgExtract: screen closed before extraction finished, discarding result")
                return

            if token is not None and token != getattr(self, "_extract_token", token):
                log("Detail _bgExtract: superseded by a newer selection (token={}, current={}), discarding".format(
                    token, getattr(self, "_extract_token", None)))
                return

            if url:
                log("Detail _bgExtract: SUCCESS! URL: {}".format(url))
                if variants:
                    log("Detail _bgExtract: {} extra quality variant(s) found".format(len(variants)))
                    callInMainThread(self._onQualityChoices, url, qual, final_ref, variants, server)
                else:
                    callInMainThread(self._onStreamFound, url, qual, final_ref, server)
            else:
                log("Detail _bgExtract: FAILED to resolve stream")
                if get_curl_failed_needs_proxy():
                    if not self._proxy_warning_shown:
                        self._proxy_warning_shown = True
                        msg = "⚠️ curl_cffi فشل في تجاوز Cloudflare.\n"
                        msg += "الرجاء تفعيل الـ Proxy من الإعدادات (أزرق ← أحمر)."
                        callInMainThread(self._showProxyWarningPopup, msg)
                    callInMainThread(self["proxy_warning"].setText, "⚠️ تفعيل Proxy")
                    callInMainThread(self["status"].setText, "⚠️ Proxy مطلوب — راجع الإعدادات")
                else:
                    callInMainThread(self["status"].setText, "فشل استخراج الرابط — جرب سيرفر تاني")
        except Exception as e:
            log("Detail _bgExtract CRITICAL ERROR: {}".format(e))
            if not getattr(self, "_closed", False):
                callInMainThread(self["status"].setText, "خطأ في النظام: {}".format(str(e)[:30]))
        finally:
            if token is not None:
                with self._extract_lock:
                    if token == self._extract_token:
                        self._extracting = False

    def _showProxyWarningPopup(self, msg):
        from Screens.MessageBox import MessageBox
        self.session.open(MessageBox, msg, MessageBox.TYPE_WARNING, timeout=8)

    def _onQualityChoices(self, url, qual, final_ref, variants, server):
        if getattr(self, "_closed", False):
            return
        choices = [{
            "label": qual or "افتراضي",
            "url": url,
            "final_ref": final_ref,
            "server": server,
        }]
        seen_urls = {url}
        for lbl, vurl in variants:
            if vurl in seen_urls:
                continue
            seen_urls.add(vurl)
            choices.append({
                "label": lbl,
                "url": vurl,
                "final_ref": final_ref,
                "server": server,
            })
        self._quality_choices = choices

        quality_labels = []
        for i, c in enumerate(choices):
            label = c["label"]
            if "1080" in label or "Original" in label:
                badge = "🔵"
            elif "720" in label:
                badge = "🟢"
            elif "480" in label:
                badge = "🟡"
            elif "360" in label:
                badge = "⚪"
            else:
                badge = "🟣"
            quality_labels.append("{}. {} {} — {}".format(i + 1, badge, server.get("name", "Server"), label))

        self["section"].setText(_single_line_text(
            "الجودات المتاحة: {}  |  اختر الجودة المطلوبة".format(len(choices)), width=90))
        self["menu"].setList(quality_labels)
        self["status"].setText(self._status_hint("اختار جودة — OK"))

    def _onStreamFound(self, stream_url, quality, final_ref, server):
        if getattr(self, "_closed", False):
            return
        if not stream_url:
            self["status"].setText("{} — غير متاح، جرب سيرفر آخر".format(server["name"]))
            return
        my_log("Stream found: {} [{}]".format(stream_url, quality))
        history_entry = _entry_from_item(
            dict(self._item, **(self._data or {})),
            self._site,
            self._m_type,
            {
                "server_name": server.get("name", ""),
                "quality": quality or "",
                "last_stream_url": stream_url,
            }
        )
        _upsert_library_item("history", history_entry, limit=120)

        title = getattr(self, "_raw_title", None) or \
                re.sub(r"\s+", " ", self["title"].getText()).strip()

        try:
            raw_url = stream_url.strip()
            if "|" in raw_url:
                main_url, old_params = raw_url.split("|", 1)
            else:
                main_url, old_params = raw_url, ""

            lower_main_url = main_url.lower()
            is_media_url = any(marker in lower_main_url for marker in (
                ".m3u8", ".mp4", ".mkv", ".mp3", ".ts", ".avi",
                "master.txt", "/hls", "/stream", "/playlist"
            ))
            is_embed_page = any(marker in lower_main_url for marker in (
                "/embed-", "/embed/", "/e/", "/watch/"
            ))
            if is_embed_page and not is_media_url:
                self["status"].setText("الرابط صفحة تشغيل وليس ملف فيديو — جرب سيرفر آخر")
                return

            headers = {"User-Agent": SAFE_UA}

            if final_ref:
                headers["Referer"] = final_ref

            if old_params:
                for p in old_params.split("&"):
                    if "=" in p:
                        k, v = p.split("=", 1)
                        if k not in headers: headers[k] = v

            header_str = "&".join(["{}={}".format(k, v) for k, v in headers.items()])
            pure_url = main_url.split("|")[0].strip()
            url = pure_url + "#" + header_str if header_str else pure_url

            _item_url = self._item.get("url", "")
            _saved_pos = _get_saved_position(_item_url)
            if _saved_pos > 30:
                if _saved_pos >= 3600:
                    _hours_r = _saved_pos // 3600
                    _mins_r = (_saved_pos % 3600) // 60
                    _secs_r = _saved_pos % 60
                    resume_text = "Resume from {:02d}:{:02d}:{:02d}?".format(_hours_r, _mins_r, _secs_r)
                else:
                    _mins_r = _saved_pos // 60
                    _secs_r = _saved_pos % 60
                    resume_text = "Resume from {}:{:02d}?".format(_mins_r, _secs_r)

                def _on_resume(_ans, _u=url, _t=title, _iu=_item_url, _sp=_saved_pos):
                    if not _ans:
                        _save_position(_iu, 0)
                    _play(self.session, _u, _t, resume_pos=_sp if _ans else 0, item_url=_iu)
                self["status"].setText("جاري فتح المشغل...")
                self.session.openWithCallback(
                    _on_resume, MessageBox,
                    resume_text,
                    MessageBox.TYPE_YESNO, timeout=8, default=True)
            else:
                self["status"].setText("Opening player...")
                _play(self.session, url, title, resume_pos=0, item_url=_item_url)
            self["status"].hide()
            if get_proxy_used():
                self["status"].setText("✓ Proxy  " + self["status"].getText())
                self["proxy_warning"].setText("")
        except Exception as e:
            my_log("Error opening player: {}".format(e))
            self["status"].setText("خطأ في المشغل: {}".format(str(e)[:60]))


from Screens.InfoBar import InfoBar

def _build_remote_play_candidates(url):
    url = str(url).strip()
    plain_url = url.split("#", 1)[0].strip()
    headers = {}
    if "#" in url:
        for part in url.split("#", 1)[1].split("&"):
            if "=" in part:
                key, value = part.split("=", 1)
                headers[key] = value
    candidates = []
    seen = set()

    def add_candidate(p_type, svc_url, label, uses_proxy=False):
        key = (p_type, svc_url)
        if not svc_url or key in seen:
            return
        seen.add(key)
        candidates.append((p_type, svc_url, label, uses_proxy))

    if plain_url.startswith("https://") or plain_url.startswith("http://"):
        proxy_params = {"url": plain_url}
        if headers.get("Referer"):
            proxy_params["referer"] = headers["Referer"]
        if headers.get("User-Agent"):
            proxy_params["ua"] = headers["User-Agent"]
        proxied = "http://127.0.0.1:{}/stream?{}".format(_PROXY_PORT, urlencode(proxy_params))
        start_proxy()
        legacy_raw = url.replace("#", "|") if "#" in url else url
        legacy_proxied = "http://127.0.0.1:{}/{}".format(_PROXY_PORT, legacy_raw)
    else:
        proxied = ""
        legacy_proxied = ""

    is_hls = any(x in plain_url.lower() for x in (".m3u8", "master.txt", "/hls", "/playlist"))
    has_exteplayer = os.path.exists("/usr/bin/exteplayer3")

    # ─── OPTIMIZED ORDER: FAST PLAYERS FIRST, SLOWER PLAYERS SECOND, PROXY LAST ──
    if is_hls:
        # 1st: Native HLS (4097) - FASTEST for HLS
        add_candidate(4097, plain_url, "4097 مباشر HLS")
        add_candidate(4097, url, "4097 + headers HLS")

        # 2nd: Native Movie Player (8193) - FAST
        add_candidate(8193, plain_url, "8193 مباشر")
        add_candidate(5001, plain_url, "5001 مباشر")

        # 3rd: exteplayer3 (5002) - SLOWER but more compatible
        if has_exteplayer:
            add_candidate(5002, plain_url, "5002 exteplayer3")
            add_candidate(5002, url, "5002 exteplayer3 + headers")

        # LAST: Proxy fallbacks
        if proxied:
            add_candidate(4097, proxied, "4097 + proxy HLS", True)
            add_candidate(5001, proxied, "5001 + proxy", True)
            if has_exteplayer:
                add_candidate(5002, proxied, "5002 exteplayer3 + proxy", True)
        if legacy_proxied:
            add_candidate(4097, legacy_proxied, "4097 + proxy قديم", True)
    else:
        # 1st: HTTP Player (5001) - FASTEST for MP4
        add_candidate(5001, plain_url, "5001 مباشر")
        add_candidate(4097, plain_url, "4097 مباشر")
        add_candidate(8193, plain_url, "8193 مباشر")
        add_candidate(4097, url, "4097 + headers")

        # 2nd: exteplayer3 (5002) - SLOWER but more compatible
        if has_exteplayer:
            add_candidate(5002, plain_url, "5002 exteplayer3")
            add_candidate(5002, url, "5002 exteplayer3 + headers")

        # LAST: Proxy fallbacks
        if proxied:
            add_candidate(5001, proxied, "5001 + proxy", True)
            add_candidate(4097, proxied, "4097 + proxy", True)
            if has_exteplayer:
                add_candidate(5002, proxied, "5002 exteplayer3 + proxy", True)
        if legacy_proxied:
            add_candidate(4097, legacy_proxied, "4097 + proxy قديم", True)

    return candidates


def _copy_service_ref(sref):
    if not sref:
        return None
    try:
        return eServiceReference(sref.toString())
    except Exception:
        try:
            return eServiceReference(str(sref.toString()))
        except Exception:
            return sref


def _capture_previous_service(session):
    try:
        return _copy_service_ref(session.nav.getCurrentlyPlayingServiceReference())
    except Exception as e:
        my_log("Capture previous service failed: {}".format(e))
        return None


def _restore_previous_service(session, previous_service):
    if not previous_service:
        return
    try:
        session.nav.stopService()
    except Exception:
        pass
    try:
        session.nav.playService(previous_service)
        my_log("Previous service restored")
    except Exception as e:
        my_log("Restore previous service failed: {}".format(e))


# ─── Simple Player ────────────────────────────────────────────────────────────
class AdvancedArabicPlayerSimplePlayer(Screen):
    skin = """
    <screen name="AdvancedArabicPlayerSimplePlayer" position="0,0" size="1920,1080" flags="wfNoBorder" backgroundColor="transparent">

        <widget name="osd_shadow"   position="148,856" size="1624,230" backgroundColor="#000000" zPosition="9" />
        <widget name="overlay_bg"   position="160,860" size="1600,210" backgroundColor="#0A0E14" zPosition="10" />
        <widget name="osd_topline"  position="160,860" size="1600,3" backgroundColor="#00E5FF" zPosition="11" />
        <widget name="osd_titlebar" position="160,860" size="1600,52" backgroundColor="#0D1520" zPosition="11" />
        <widget name="osd_title"    position="180,868" size="1180,38" font="Regular;30" foregroundColor="#00E5FF" transparent="1" zPosition="12" halign="left" />
        <widget name="osd_durtext"  position="1380,868" size="360,38" font="Regular;26" foregroundColor="#8B949E" transparent="1" zPosition="12" halign="right" />
        <widget name="prog_bar"     position="160,906" size="1600,30" font="Regular;22" foregroundColor="#00B4D8" transparent="1" zPosition="12" halign="left" />
        <widget name="osd_elapsed"  position="180,938" size="320,44" font="Regular;36" foregroundColor="#FFD740" transparent="1" zPosition="12" />
        <widget name="status"       position="640,938" size="640,44" font="Regular;36" foregroundColor="#39D98A" transparent="1" zPosition="12" halign="center" />
        <widget name="osd_hints"    position="1220,938" size="520,44" font="Regular;26" foregroundColor="#8B949E" transparent="1" zPosition="12" halign="right" />
        <widget name="osd_divider"  position="160,982" size="1600,2" backgroundColor="#1C2333" zPosition="11" />
        <widget name="osd_keybar"   position="160,984" size="1600,46" backgroundColor="#0D1520" zPosition="11" />
        <widget name="osd_keys"     position="180,992" size="1560,34" font="Regular;24" foregroundColor="#484F58" transparent="1" zPosition="12" halign="center" />
        <widget name="osd_botline"  position="160,1027" size="1600,3" backgroundColor="#0A2040" zPosition="11" />
    </screen>
    """

    def __init__(self, session, title, candidates, previous_service=None, resume_pos=0, item_url=""):
        Screen.__init__(self, session)
        self["overlay_bg"]   = Label("")
        self["status"]       = Label("جاري التشغيل...")
        self["osd_shadow"]   = Label("")
        self["osd_titlebar"] = Label("")
        self["osd_title"]    = Label("")
        self["osd_durtext"]  = Label("")
        self["osd_topline"]  = Label("")
        self["prog_bar"]     = Label("")
        self["osd_elapsed"]  = Label("")
        self["osd_hints"]    = Label("")
        self["osd_divider"]  = Label("")
        self["osd_keybar"]   = Label("")
        self["osd_keys"]     = Label("")
        self["osd_botline"]  = Label("")
        _raw = (title or "").strip()
        _qtag_m = re.search(r'\s*(\[\d+p\])\s*$', _raw)
        _qtag = _qtag_m.group(1) if _qtag_m else ""
        _bare = _raw[:_qtag_m.start()].strip() if _qtag_m else _raw
        if len(_bare) > 34:
            _bare = _bare[:32].rstrip() + u"\u2026"
        self.title = (_bare + " " + _qtag).strip() if _qtag else _bare
        self.candidates = candidates or []
        self.previous_service = _copy_service_ref(previous_service)
        self.sref = None
        self._play_confirmed = False
        self._candidate_idx = -1
        self._candidate_start_ts = 0
        self._candidate_uses_proxy = False
        self._candidate_label = ""
        self._handoff = False
        self._restored_previous = False
        self._resume_pos = int(resume_pos or 0)
        self._item_url  = item_url or ""
        self._seek_timer = eTimer()
        self._seek_timer.callback.append(self.__doSeek)
        self._seek_retry_count = 0
        self._seek_verify_timer = eTimer()
        self._seek_verify_timer.callback.append(self.__verifySeek)
        self._hide_timer = eTimer()
        self._hide_timer.callback.append(self.__hideOSD)
        self._osd_update_timer = eTimer()
        self._osd_update_timer.callback.append(self.__updateOSD)
        self._osd_visible = False
        self._total_secs  = 0
        self._osd_auto_hide_secs = 4
        self._paused = False
        self._paused_elapsed = 0
        self._force_confirmation_timer = eTimer()
        self._force_confirmation_timer.callback.append(self.__forceConfirm)

        self["actions"] = ActionMap(
            ["OkCancelActions", "MediaPlayerActions", "InfobarSeekActions", "DirectionActions", "ColorActions"],
            {
                "cancel":           self.__onExit,
                "stop":             self.__onExit,
                "ok":               self.__togglePause,
                "playpauseService": self.__togglePause,
                "right":            lambda: self.__seek(+10),
                "left":             lambda: self.__seek(-10),
                "seekFwd":          lambda: self.__seek(+60),
                "seekBack":         lambda: self.__seek(-60),
                "green":            self.__onRestart,
            },
            -1
        )
        self._retry_timer = eTimer()
        self._retry_timer.callback.append(self.__onTimeout)
        eventmap = {
            iPlayableService.evTuneFailed: self.__onFailed,
            iPlayableService.evEOF: self.__onFailed,
        }
        ev_video = getattr(iPlayableService, "evVideoSizeChanged", None)
        if ev_video is not None:
            eventmap[ev_video] = self.__onConfirmed
        self._events = ServiceEventTracker(screen=self, eventmap=eventmap)
        self.onLayoutFinish.append(self.__initOSD)
        self.onLayoutFinish.append(self.__playNext)
        self.onClose.append(self.__stop)

    _OSD_WIDGETS = [
        "osd_shadow","overlay_bg","osd_topline","osd_botline",
        "osd_titlebar","osd_title","osd_durtext",
        "prog_bar","osd_elapsed",
        "status","osd_hints","osd_divider",
        "osd_keybar","osd_keys",
    ]

    def __initOSD(self):
        for w in self._OSD_WIDGETS:
            try: self[w].hide()
            except: pass

    def __hideOSD(self):
        self._osd_visible = False
        try: self._osd_update_timer.stop()
        except: pass
        for w in self._OSD_WIDGETS:
            try: self[w].hide()
            except: pass

    def __showOSD(self, auto_hide=True):
        self._osd_visible = True
        for w in self._OSD_WIDGETS:
            try: self[w].show()
            except: pass
        self.__updateOSD()
        try:
            self._osd_update_timer.start(1000, False)
        except: pass
        if auto_hide:
            try:
                self._hide_timer.stop()
                self._hide_timer.start(self._osd_auto_hide_secs * 1000, True)
            except: pass

    def __updateOSD(self):
        if not self._osd_visible:
            try: self._osd_update_timer.stop()
            except: pass
            return
        try:
            if self._paused:
                elapsed = self._paused_elapsed
            else:
                wall = _GLOBAL_PLAY_START_WALL
                base = _GLOBAL_PLAY_START_POS
                if wall and base >= 0:
                    elapsed = max(0, int((time.time() - wall) + base))
                else:
                    elapsed = 0
            he = elapsed // 3600; me = (elapsed % 3600) // 60; se = elapsed % 60
            self["osd_elapsed"].setText("{:02d}:{:02d}:{:02d}".format(he, me, se))
            total = self._total_secs
            if not total:
                try:
                    svc = self.session.nav.getCurrentService()
                    seek = svc and svc.seek()
                    if seek:
                        r = seek.getLength()
                        if r and r[0] == 0 and r[1] > 0:
                            total = r[1] // 90000
                            self._total_secs = total
                except: pass
            if total > 0:
                rem = max(0, total - elapsed)
                pct = min(1.0, float(elapsed) / float(total))
                hr = rem // 3600
                mr = (rem % 3600) // 60
                sr = rem % 60
                ht = total // 3600
                mt = (total % 3600) // 60
                st = total % 60
                self["osd_durtext"].setText("-{:02d}:{:02d}:{:02d}  {:02d}:{:02d}:{:02d}".format(hr, mr, sr, ht, mt, st))
                BAR_W = 96
                filled = max(0, min(BAR_W, int(pct * BAR_W)))
                bar = u"█" * filled + u"░" * (BAR_W - filled)
                self["prog_bar"].setText(u"{} {:.1f}%".format(bar, pct * 100))
            else:
                self["osd_durtext"].setText("")
                self["prog_bar"].setText("")
            self["osd_keys"].setText("OK=Pause   << -10s   +10s >>   <<< -60s   +60s >>>   Green=إعادة+استئناف   Stop=حفظ&خروج")
        except Exception as e:
            my_log("updateOSD error: {}".format(e))

    def __forceConfirm(self):
        if self._play_confirmed:
            return
        if self._candidate_uses_proxy and _PROXY_LAST_HIT >= self._candidate_start_ts and _PROXY_LAST_BYTES > 0:
            my_log("Play proxy confirmed early by traffic: {} bytes".format(_PROXY_LAST_BYTES))
            self.__onConfirmed()

    def __playNext(self):
        global _PROXY_LAST_HIT, _PROXY_LAST_BYTES
        self._candidate_idx += 1
        if self._candidate_idx >= len(self.candidates):
            self["status"].setText("تعذر تشغيل الرابط على كل المحاولات")
            return

        p_type, svc_url, label, uses_proxy = self.candidates[self._candidate_idx]
        self._play_confirmed = False
        self._candidate_start_ts = time.time()
        self._candidate_uses_proxy = uses_proxy
        self._candidate_label = label
        if uses_proxy:
            _PROXY_LAST_HIT = 0
            _PROXY_LAST_BYTES = 0
        self.sref = eServiceReference(p_type, 0, svc_url)
        if sys.version_info[0] == 3:
            self.sref.setName(str(self.title))
        else:
            self.sref.setName(self.title.encode("utf-8", "ignore"))

        self["status"].setText("جاري التشغيل... {}".format(label))
        self.__showOSD(False)  # <--- ADD THIS LINE (False means DO NOT auto-hide yet)
        my_log("Play attempt: {}".format(label))
        try:
            self.session.nav.stopService()
        except: pass
        try:
            self.session.nav.playService(self.sref)
            self._retry_timer.start(12000, True)
            self._force_confirmation_timer.start(3000, True)
        except Exception as e:
            my_log("SimplePlayer fallback error: {}".format(e))
            self.__playNext()

    def __onConfirmed(self):
        if self._play_confirmed:
            return
        self._play_confirmed = True
        try:
            self._retry_timer.stop()
            self._force_confirmation_timer.stop()
        except: pass
        my_log("Play confirmed: {}".format(self._candidate_label))
        _start_pos_tracker(self.session, self._item_url, start_pos=0)
        if self._resume_pos > 30:
            self._seek_retry_count = 0
            self._seek_timer.start(6000, True)
        self["osd_title"].setText(self.title)
        self["status"].setText(u"▶ Playing")
        self._total_secs = 0
        self.__showOSD(True)

    def __togglePause(self):
        try:
            svc = self.session.nav.getCurrentService()
            if not svc:
                self.__showOSD(True); return
            p = svc.pause()
            if not p:
                self.__showOSD(True); return
            if self._paused:
                p.unpause()
                self._paused = False
                global _GLOBAL_PLAY_START_WALL, _GLOBAL_PLAY_START_POS
                _GLOBAL_PLAY_START_POS = self._paused_elapsed
                _GLOBAL_PLAY_START_WALL = time.time()
                self["status"].setText(u"▶ Playing")
            else:
                wall = _GLOBAL_PLAY_START_WALL
                base = _GLOBAL_PLAY_START_POS
                if wall:
                    elapsed = int((time.time() - wall) + base)
                else:
                    elapsed = 0
                self._paused_elapsed = max(0, elapsed)
                p.pause()
                self._paused = True
                self["status"].setText(u"⏸ Paused")
            self.__showOSD(True)
        except Exception as e:
            my_log("togglePause error: {}".format(e))
            self.__showOSD(True)

    def __seek(self, delta_secs):
        try:
            svc = self.session.nav.getCurrentService()
            if not svc: return
            sk = svc.seek()
            if not sk: return
            global _GLOBAL_PLAY_START_WALL, _GLOBAL_PLAY_START_POS
            global _GLOBAL_LAST_SEEK_TARGET
            _wall = _GLOBAL_PLAY_START_WALL
            _base = _GLOBAL_PLAY_START_POS
            if _wall:
                elapsed = time.time() - _wall
            else:
                elapsed = 0
            current_est = int(_base + elapsed)
            target = max(0, current_est + int(delta_secs))
            _tot = self._total_secs
            if _tot > 0:
                target = min(target, _tot - 3)
            sk.seekTo(target * 90000)
            _GLOBAL_LAST_SEEK_TARGET = target
            _GLOBAL_PLAY_START_POS = max(0, target - 2)
            _GLOBAL_PLAY_START_WALL = time.time()
            if self._paused:
                self._paused_elapsed = target
            self._total_secs = 0
            _th = target // 3600; _tm = (target % 3600) // 60; _ts = target % 60
            _arr = u"➡" if delta_secs > 0 else u"⬅"
            self["status"].setText(u"{} {:02d}:{:02d}:{:02d}".format(_arr, _th, _tm, _ts))
            self.__showOSD(True)
            self._hide_timer.start(2500, True)
        except Exception as e:
            my_log("seek error: {}".format(e))

    def __onRestart(self):
        my_log("Restart+Resume requested by green button")
        if self._item_url:
            try:
                if self._paused:
                    secs = self._paused_elapsed
                else:
                    wall = _GLOBAL_PLAY_START_WALL
                    base = _GLOBAL_PLAY_START_POS
                    secs = int((time.time() - wall) + base) if wall else 0
                if secs > 30:
                    _save_position(self._item_url, secs)
                    self._resume_pos = secs
                    my_log("Restart: saved pos={}s, will re-seek after restart".format(secs))
            except Exception as e:
                my_log("Restart pos-save error: {}".format(e))
        try:
            self._seek_timer.stop()
            self._seek_verify_timer.stop()
        except: pass
        self._play_confirmed = False
        self._seek_retry_count = 0
        try:
            self.session.nav.stopService()
        except: pass
        self._candidate_idx = -1
        self["status"].setText(u"إعادة التشغيل + استئناف من {}:{:02d}...".format(
            self._resume_pos // 60, self._resume_pos % 60) if self._resume_pos > 30 else u"إعادة التشغيل...")
        self.__showOSD(True)
        restart_timer = eTimer()
        restart_timer.callback.append(self.__playNext)
        restart_timer.start(500, True)

    def __onExit(self):
        try:
            if self._item_url:
                if self._paused:
                    secs = self._paused_elapsed
                else:
                    wall = _GLOBAL_PLAY_START_WALL
                    base = _GLOBAL_PLAY_START_POS
                    if wall:
                        secs = int((time.time() - wall) + base)
                    else:
                        secs = 0
                _tot = self._total_secs
                if _tot > 0:
                    secs = min(secs, _tot - 5)
                secs = max(0, secs)
                if secs > 30:
                    _save_position(self._item_url, secs)
                    my_log("Exit save: {}s".format(secs))
        except Exception as e:
            my_log("Exit save error: {}".format(e))
        try:
            self.session.nav.stopService()
        except: pass
        _stop_pos_tracker()
        _restore_previous_service(self.session, self.previous_service)
        self.close()

    def __stop(self):
        self.__hideOSD()
        for t in ("_seek_timer","_seek_verify_timer","_retry_timer","_hide_timer","_osd_update_timer","_force_confirmation_timer"):
            try: getattr(self, t).stop()
            except: pass

    def __onFailed(self):
        if self._play_confirmed:
            return
        try:
            self._retry_timer.stop()
            self._force_confirmation_timer.stop()
        except: pass
        my_log("Play failed event: {}".format(self._candidate_label))
        self.__playNext()

    def __onTimeout(self):
        global _PROXY_LAST_HIT, _PROXY_LAST_BYTES
        if self._play_confirmed:
            return
        if self._candidate_uses_proxy and _PROXY_LAST_HIT >= self._candidate_start_ts and _PROXY_LAST_BYTES > 0:
            my_log("Play proxy confirmed by traffic: {} bytes".format(_PROXY_LAST_BYTES))
            self.__onConfirmed()
            return
        my_log("Play timeout: {}".format(self._candidate_label))
        self.__playNext()

    def __doSeek(self):
        if not self._resume_pos or self._resume_pos <= 30:
            my_log("Seek skipped: resume_pos={}".format(self._resume_pos))
            return
        try:
            svc = self.session.nav.getCurrentService()
            seek = svc and svc.seek()
            if not seek:
                self._seek_retry_count += 1
                if self._seek_retry_count <= 3:
                    my_log("doSeek: no seek interface, retry {}/3 in 4s".format(self._seek_retry_count))
                    self._seek_timer.start(4000, True)
                else:
                    my_log("doSeek: giving up after 3 retries")
                return

            seek.seekTo(self._resume_pos * 90000)
            my_log("Resume seekTo: {}s (attempt {})".format(self._resume_pos, self._seek_retry_count + 1))
            self._total_secs = 0

            self._seek_verify_timer.start(4000, True)

            if self._osd_visible:
                self.__updateOSD()
        except Exception as e:
            my_log("doSeek failed: {} — retry {}/3".format(e, self._seek_retry_count))
            self._seek_retry_count += 1
            if self._seek_retry_count <= 3:
                self._seek_timer.start(4000, True)

    def __verifySeek(self):
        if not self._resume_pos or self._resume_pos <= 30:
            return
        global _GLOBAL_PLAY_START_WALL, _GLOBAL_PLAY_START_POS, _GLOBAL_LAST_SEEK_TARGET
        try:
            svc = self.session.nav.getCurrentService()
            seek = svc and svc.seek()
            actual_pos = -1

            if seek:
                try:
                    r = seek.getPlayPosition()
                    if r and r[0] == 0 and r[1] > 0:
                        actual_pos = int(r[1] // 90000)
                except Exception:
                    pass

            if actual_pos >= 0:
                if actual_pos >= max(0, self._resume_pos - 60):
                    _GLOBAL_PLAY_START_POS = actual_pos
                    _GLOBAL_PLAY_START_WALL = time.time()
                    _GLOBAL_LAST_SEEK_TARGET = actual_pos
                    if self._paused:
                        self._paused_elapsed = actual_pos
                    my_log("verifySeek OK via PTS: actual={}s target={}s".format(
                        actual_pos, self._resume_pos))
                else:
                    if seek and self._seek_retry_count <= 3:
                        self._seek_retry_count += 1
                        seek.seekTo(self._resume_pos * 90000)
                        my_log("verifySeek double-tap {}/3: actual={}s target={}s".format(
                            self._seek_retry_count, actual_pos, self._resume_pos))
                        self._seek_verify_timer.start(3000, True)
                    else:
                        _GLOBAL_PLAY_START_POS = max(0, self._resume_pos - 2)
                        _GLOBAL_PLAY_START_WALL = time.time()
                        my_log("verifySeek giving up, setting display to target {}s".format(
                            self._resume_pos))
            else:
                if self._seek_retry_count <= 2:
                    if seek:
                        seek.seekTo(self._resume_pos * 90000)
                    self._seek_retry_count += 1
                    _GLOBAL_PLAY_START_POS = max(0, self._resume_pos - 2)
                    _GLOBAL_PLAY_START_WALL = time.time()
                    _GLOBAL_LAST_SEEK_TARGET = self._resume_pos
                    if self._paused:
                        self._paused_elapsed = self._resume_pos
                    my_log("verifySeek double-tap {}/3 (no PTS), target={}s".format(
                        self._seek_retry_count, self._resume_pos))
                    self._seek_verify_timer.start(3000, True)
                else:
                    my_log("verifySeek: max retries reached, target={}s".format(self._resume_pos))
        except Exception as e:
            my_log("verifySeek error: {}".format(e))

    def __restorePrevious(self):
        if self._restored_previous:
            return
        self._restored_previous = True
        _restore_previous_service(self.session, self.previous_service)


# ─── Global play function ─────────────────────────────────────────────────────
def _play(session, url, title, resume_pos=0, item_url=""):
    try:
        svc_url = str(url).strip()
        is_remote = svc_url.startswith("http://") or svc_url.startswith("https://")
        previous_service = _capture_previous_service(session)

        if is_remote:
            session.open(AdvancedArabicPlayerSimplePlayer, title, _build_remote_play_candidates(svc_url), previous_service, resume_pos=resume_pos, item_url=item_url)
            return

        sref = eServiceReference(4097, 0, svc_url)
        if sys.version_info[0] == 3:
            sref.setName(str(title))
        else:
            sref.setName(title.encode("utf-8", "ignore"))

        try:
            from Screens.InfoBar import MoviePlayer
            callback = lambda *args: _restore_previous_service(session, previous_service)
            try:
                if is_remote:
                    session.openWithCallback(callback, MoviePlayer, sref, streamMode=True, askBeforeLeaving=False)
                else:
                    session.openWithCallback(callback, MoviePlayer, sref, askBeforeLeaving=False)
            except TypeError:
                session.openWithCallback(callback, MoviePlayer, sref)
        except Exception as e:
            my_log("[PLAY_INFOBAR_FALLBACK] " + str(e))
            session.open(AdvancedArabicPlayerSimplePlayer, title, _build_remote_play_candidates(svc_url), previous_service)
    except Exception as e:
        my_log("[PLAY_ERROR] " + str(e))

# ─── Splash Screen ───────────────────────────────────────────────────────────
class AdvancedArabicPlayerSplash(Screen):
    skin = """
    <screen name="AdvancedArabicPlayerSplash" position="0,0" size="1920,1080" flags="wfNoBorder" backgroundColor="#000000">
        <widget name="splash_pic" position="0,0" size="1920,1080" zPosition="1" alphatest="blend" />
    </screen>
    """

    def __init__(self, session):
        self.skin = AdvancedArabicPlayerSplash.skin.format(PLUGIN_PATH)
        Screen.__init__(self, session)
        self["splash_pic"] = Pixmap()
        self._timer = eTimer()
        self._timer.callback.append(self._onFinish)

        self.picLoad = ePicLoad()
        self.picLoad.PictureData.get().append(self._paintSplash)

        self.onLayoutFinish.append(self._start)

    def _start(self):
        splash_path = os.path.join(PLUGIN_PATH, "images", "splash.png")
        if os.path.exists(splash_path):
            self.picLoad.setPara((1920, 1080, 1, 1, 0, 1, "#000000"))
            self.picLoad.startDecode(splash_path)
        self._timer.start(2500, True)

    def _paintSplash(self, picData=None):
        ptr = self.picLoad.getData()
        if ptr:
            self["splash_pic"].instance.setPixmap(ptr)
            self["splash_pic"].show()

    def _onFinish(self):
        self._timer.stop()
        try:
            self.picLoad.PictureData.get().remove(self._paintSplash)
        except Exception:
            pass
        self.session.open(AdvancedArabicPlayerHome)
        self.close()


# ─── Plugin Entry Points ──────────────────────────────────────────────────────
# Initialize browser proxy from saved config on module load
try:
    from extractors.base import set_browser_proxy
    set_browser_proxy(_get_config("browser_proxy", ""))
except Exception:
    pass

def main(session, **kwargs):
    session.open(AdvancedArabicPlayerSplash)


def Plugins(**kwargs):
    return [
        PluginDescriptor(
            name        = _PLUGIN_NAME,
            description = "تشغيل أفلام ومسلسلات من مواقع عربية",
            where       = PluginDescriptor.WHERE_PLUGINMENU,
            icon        = "plugin.png",
            fnc         = main
        ),
        PluginDescriptor(
            name        = _PLUGIN_NAME,
            description = "تشغيل أفلام ومسلسلات من مواقع عربية",
            where       = PluginDescriptor.WHERE_EXTENSIONSMENU,
            fnc         = main
        ),
    ]
