# -*- coding: utf-8 -*-
"""
Advanced Arabic Player - Custom grid widgets (Enigma2 eListboxPythonMultiContent)
===================================================================================
Two grid-based list renderers sharing one pagination/movement engine:

  HomeMenuGrid   - 4x3 site-tile grid for the Home site-selection screen
                   (bordered cards, cyan selection highlight, title +
                   tagline text; icon art is drawn by the owning Screen
                   via separate overlay Pixmap widgets painted with
                   setPixmapFromFile() - see resolve_icon_path /
                   build_pixmap_widgets_xml below). Ported from
                   plugin2.py's MainMenuGrid (originally 3x3, resized).

  PosterCardGrid - 8x2 poster grid for movie/series listing screens
                   (categories/search/favorites/history): a title+year
                   caption under the poster. Poster art itself is drawn
                   by the owning Screen via separate overlay Pixmap
                   widgets (also setPixmapFromFile()) - the same pattern
                   HomeMenuGrid uses for site icons, and the pattern a
                   real shipped Enigma2 plugin (westy4ever/XtreamNew)
                   uses for its own poster carousels/grids.

Both grids are self-contained GUIComponents. The owning Screen just feeds
them item dicts via setList()/getCurrent()/onSelectionChanged, the same
shape of interaction plugin.py's Home screen already has with MenuList -
so none of the surrounding navigation/search/favorites business logic
needs to change, only which widget is visible and which one gets fed
items.

Cells with no backing item (trailing slots on a partial page) render
nothing at all - no placeholder box - so a short last page doesn't leave
a row of empty dark rectangles.
"""

import os

from Components.GUIComponent import GUIComponent
from Components.MultiContent import MultiContentEntryText
from enigma import eListboxPythonMultiContent, eListbox, gFont, RT_HALIGN_CENTER, RT_VALIGN_CENTER

PLUGIN_PATH = os.path.dirname(__file__)

# Palette kept in sync BY VALUE with plugin.py's _CLR (self-contained,
# no back-import, matching the rest of the modular split).
_G_CLR = {
    "surface2": "#1C2333",
    "border":   "#30363D",
    "cyan":     "#00E5FF",
    "text":     "#F0F6FC",
    "text2":    "#8B949E",
    "gold":     "#FFD740",
    "badge_bg": "#000000",
}


def resolve_icon_path(item, plugin_path=PLUGIN_PATH):
    """Local site-branding icon lookup, used by HomeMenuGrid cells only."""
    action = item.get("_action", "")
    icon_path = None
    if action.startswith("site_"):
        site_key = action.replace("site_", "")
        icon_file = os.path.join(plugin_path, "images", "%s.png" % site_key)
        if os.path.exists(icon_file):
            icon_path = icon_file
    if not icon_path:
        default_icon = os.path.join(plugin_path, "plugin.png")
        if os.path.exists(default_icon):
            icon_path = default_icon
    return icon_path


def build_pixmap_widgets_xml(x0, y0, cols, rows, cell_w, cell_h, margin, border_w,
                              icon_pad_top, icon_w, icon_h, name_prefix="pic"):
    """Build <widget> XML for one Pixmap overlay per grid cell (icons)."""
    parts = []
    for r in range(rows):
        for c in range(cols):
            px = x0 + c * cell_w + margin + border_w
            py = y0 + r * cell_h + margin + border_w + icon_pad_top
            parts.append(
                '\n\t\t<widget name="%s_%d_%d" position="%d,%d" size="%d,%d" '
                'transparent="1" alphatest="blend" zPosition="3" />' % (name_prefix, r, c, px, py, icon_w, icon_h)
            )
    return "".join(parts)


# ─── Shared pagination/movement engine ───────────────────────────────────────

class _BaseCardGrid(GUIComponent):
    GUI_WIDGET = eListbox

    def __init__(self, cols, rows, cell_w, cell_h, font_size=24):
        GUIComponent.__init__(self)
        self.cols = cols
        self.rows = rows
        self.cell_w = cell_w
        self.cell_h = cell_h
        self.itemsPerPage = cols * rows
        self.l = eListboxPythonMultiContent()
        self.l.setFont(0, gFont("Regular", font_size))
        self.l.setFont(1, gFont("Regular", max(16, font_size - 6)))
        self._items = []
        self.currentPage = 0
        self.totalPages = 1
        self.currentRow = 0
        self.currentCol = 0
        self.currentIndex = 0
        self.totalItems = 0
        self.onSelectionChanged = None

    def _updatePageInfo(self):
        self.totalPages = max(1, (self.totalItems + self.itemsPerPage - 1) // self.itemsPerPage)
        if self.currentPage >= self.totalPages:
            self.currentPage = max(0, self.totalPages - 1)

    def _getPageStart(self):
        return self.currentPage * self.itemsPerPage

    def _getPageEnd(self):
        return min(self._getPageStart() + self.itemsPerPage, self.totalItems)

    def _getMaxRow(self):
        n = self._getPageEnd() - self._getPageStart()
        return 0 if n == 0 else (n - 1) // self.cols

    def _getMaxCol(self, row):
        n = self._getPageEnd() - self._getPageStart()
        rs = row * self.cols
        return -1 if rs >= n else min(self.cols - 1, n - rs - 1)

    def _updateIndex(self):
        if self.totalItems == 0:
            self.currentIndex = 0
            self.currentRow = 0
            self.currentCol = 0
            return
        self.currentIndex = self.currentPage * self.itemsPerPage + self.currentRow * self.cols + self.currentCol
        if self.currentIndex >= self.totalItems:
            self.currentIndex = max(0, self.totalItems - 1)
            self.currentPage = self.currentIndex // self.itemsPerPage
            self.currentRow = (self.currentIndex % self.itemsPerPage) // self.cols
            self.currentCol = (self.currentIndex % self.itemsPerPage) % self.cols

    def _notify(self):
        if self.onSelectionChanged:
            self.onSelectionChanged()

    def moveUp(self):
        if self.currentRow > 0:
            self.currentRow -= 1
        elif self.currentPage > 0:
            self.currentPage -= 1
            self.currentRow = self._getMaxRow()
            self.currentCol = min(self.currentCol, self._getMaxCol(self.currentRow))
        self._updateIndex(); self._redraw(); self._notify()

    def moveDown(self):
        mr = self._getMaxRow()
        if self.currentRow < mr:
            self.currentRow += 1
            self.currentCol = min(self.currentCol, self._getMaxCol(self.currentRow))
        elif self.currentPage < self.totalPages - 1:
            self.currentPage += 1
            self.currentRow = 0
            self.currentCol = min(self.currentCol, self._getMaxCol(0))
        self._updateIndex(); self._redraw(); self._notify()

    def moveLeft(self):
        if self.currentCol > 0:
            self.currentCol -= 1
        elif self.currentPage > 0:
            self.currentPage -= 1
            self.currentRow = min(self.currentRow, self._getMaxRow())
            self.currentCol = self._getMaxCol(self.currentRow)
        self._updateIndex(); self._redraw(); self._notify()

    def moveRight(self):
        mc = self._getMaxCol(self.currentRow)
        if self.currentCol < mc:
            self.currentCol += 1
        elif self.currentPage < self.totalPages - 1:
            self.currentPage += 1
            self.currentRow = min(self.currentRow, self._getMaxRow())
            self.currentCol = 0
        self._updateIndex(); self._redraw(); self._notify()

    def pageUp(self):
        if self.currentPage > 0:
            self.currentPage -= 1
            self.currentRow = min(self.currentRow, self._getMaxRow())
            self.currentCol = min(self.currentCol, self._getMaxCol(self.currentRow))
        self._updateIndex(); self._redraw(); self._notify()

    def pageDown(self):
        if self.currentPage < self.totalPages - 1:
            self.currentPage += 1
            self.currentRow = min(self.currentRow, self._getMaxRow())
            self.currentCol = min(self.currentCol, self._getMaxCol(self.currentRow))
        self._updateIndex(); self._redraw(); self._notify()

    def setList(self, items):
        self._items = items or []
        self.totalItems = len(self._items)
        self._updatePageInfo()
        self.currentPage = 0
        self.currentRow = 0
        self.currentCol = 0
        self._updateIndex(); self._redraw(); self._notify()

    def getCurrent(self):
        if self._items and 0 <= self.currentIndex < len(self._items):
            return self._items[self.currentIndex]
        return None

    def getSelectedIndex(self):
        return self.currentIndex

    def getPageInfo(self):
        return self.currentPage + 1, self.totalPages

    def getPageItems(self):
        s = self._getPageStart(); e = self._getPageEnd()
        return [((i - s) // self.cols, (i - s) % self.cols, self._items[i]) for i in range(s, e)]

    def _buildRow(self, row_idx):
        raise NotImplementedError

    def _redraw(self):
        n = self._getPageEnd() - self._getPageStart()
        num_rows = max(1, (n + self.cols - 1) // self.cols) if self.totalItems > 0 else 0
        num_rows = max(1, num_rows)
        entries = [self._buildRow(r) for r in range(num_rows)]
        while len(entries) < self.rows:
            entries.append([None])
        self.l.setList(entries)
        if self.instance:
            try:
                self.instance.setSelectionEnable(False)
            except Exception:
                pass
            if self.currentRow < len(entries):
                self.instance.moveSelectionTo(self.currentRow)

    def postWidgetCreate(self, instance):
        instance.setContent(self.l)
        instance.setItemHeight(self.cell_h)
        try:
            instance.setSelectionEnable(False)
        except Exception:
            pass
        try:
            instance.setScrollbarMode(eListbox.showOnDemand)
        except Exception:
            instance.setScrollbarMode(1)

    def preWidgetDelete(self, instance):
        instance.setContent(None)


# ─── Home site-menu grid (4x3 bordered cards) ────────────────────────────────

HOME_GRID_COLS = 4
HOME_GRID_ROWS = 3
HOME_CELL_W = 470
HOME_CELL_H = 300
HOME_CELL_MARGIN = 16
HOME_BORDER_W = 4
HOME_CELL_INNER_W = HOME_CELL_W - 2 * HOME_CELL_MARGIN
HOME_CELL_INNER_H = HOME_CELL_H - 2 * HOME_CELL_MARGIN
HOME_LABEL_H = 44
HOME_ICON_PAD_TOP = 12
HOME_ICON_W = HOME_CELL_INNER_W - 2 * HOME_BORDER_W
HOME_ICON_H = HOME_CELL_INNER_H - 2 * HOME_BORDER_W - HOME_ICON_PAD_TOP - HOME_LABEL_H
HOME_ITEMS_PER_PAGE = HOME_GRID_COLS * HOME_GRID_ROWS


class HomeMenuGrid(_BaseCardGrid):
    """Site-selection grid: bordered card, cyan highlight on selection,
    title + tagline text. Icons are separate Pixmap widgets overlaid by
    the owning Screen, matching plugin2.py's original MainMenuGrid design.
    """

    def __init__(self):
        _BaseCardGrid.__init__(self, HOME_GRID_COLS, HOME_GRID_ROWS, HOME_CELL_W, HOME_CELL_H, font_size=24)

    def _buildRow(self, row_idx):
        start = self._getPageStart()
        is_sr = (row_idx == self.currentRow)
        row = [None]

        for col_idx in range(self.cols):
            item_idx = start + row_idx * self.cols + col_idx
            if item_idx >= self._getPageEnd():
                continue  # no backing item - leave the cell fully blank

            cx = col_idx * self.cell_w + HOME_CELL_MARGIN
            cy = HOME_CELL_MARGIN

            item = self._items[item_idx]
            is_sel = is_sr and col_idx == self.currentCol

            bc = _G_CLR["cyan"] if is_sel else _G_CLR["border"]
            row.append(MultiContentEntryText(pos=(cx, cy), size=(HOME_CELL_INNER_W, HOME_CELL_INNER_H),
                font=0, text="", color=0, backcolor=bc, flags=0))

            row.append(MultiContentEntryText(pos=(cx + HOME_BORDER_W, cy + HOME_BORDER_W),
                size=(HOME_CELL_INNER_W - 2 * HOME_BORDER_W, HOME_CELL_INNER_H - 2 * HOME_BORDER_W),
                font=0, text="", color=0, backcolor=_G_CLR["surface2"], flags=0))

            title = item.get("title", "")
            tagline = item.get("tagline", "")

            ty = cy + HOME_BORDER_W + 8
            row.append(MultiContentEntryText(pos=(cx + HOME_BORDER_W + 8, ty),
                size=(HOME_CELL_INNER_W - 2 * HOME_BORDER_W - 16, 40), font=0, text=title,
                color=_G_CLR["text"], backcolor=_G_CLR["surface2"], flags=RT_HALIGN_CENTER))

            if tagline:
                tag_y = ty + 44
                row.append(MultiContentEntryText(pos=(cx + HOME_BORDER_W + 8, tag_y),
                    size=(HOME_CELL_INNER_W - 2 * HOME_BORDER_W - 16, 32), font=0, text=tagline,
                    color=_G_CLR["text2"], backcolor=_G_CLR["surface2"], flags=RT_HALIGN_CENTER))

        return row


# ─── Movie/series poster grid (8x2 cards with badges + caption) ─────────────

POSTER_GRID_COLS = 8
POSTER_GRID_ROWS = 2
POSTER_ITEMS_PER_PAGE = POSTER_GRID_COLS * POSTER_GRID_ROWS

POSTER_W = 210
POSTER_H = 315
POSTER_CAPTION_H = 30
POSTER_CELL_MARGIN_H = 10   # half of the horizontal gap between cards
POSTER_CELL_MARGIN_V = 16   # half of the vertical gap between cards
POSTER_CELL_W = POSTER_W + 2 * POSTER_CELL_MARGIN_H
POSTER_CELL_H = POSTER_H + POSTER_CAPTION_H + 2 * POSTER_CELL_MARGIN_V


class PosterCardGrid(_BaseCardGrid):
    """Movie/series listing grid: a title + year caption under the
    poster. No rating/index badges - just poster art and the caption.
    This widget only draws the card frame/caption - poster art itself
    is painted by separate overlay Pixmap widgets that the owning Screen
    manages (see build_poster_pixmap_widgets_xml and plugin.py's
    _updatePosterPixmaps), the same pattern already used for
    HomeMenuGrid's site icons. This widget does no network I/O and holds
    no pixmap state itself.
    """

    def __init__(self):
        _BaseCardGrid.__init__(self, POSTER_GRID_COLS, POSTER_GRID_ROWS, POSTER_CELL_W, POSTER_CELL_H, font_size=22)

    def _buildRow(self, row_idx):
        start = self._getPageStart()
        is_sr = (row_idx == self.currentRow)
        row = [None]
        cy = POSTER_CELL_MARGIN_V

        for col_idx in range(self.cols):
            item_idx = start + row_idx * self.cols + col_idx
            if item_idx >= self._getPageEnd():
                continue  # no backing item - leave the cell fully blank

            cx = col_idx * self.cell_w + POSTER_CELL_MARGIN_H
            item = self._items[item_idx]
            is_sel = is_sr and col_idx == self.currentCol

            # Selection frame around the poster art area
            frame_color = _G_CLR["cyan"] if is_sel else _G_CLR["border"]
            row.append(MultiContentEntryText(pos=(cx - 4, cy - 4), size=(POSTER_W + 8, POSTER_H + 8),
                font=0, text="", color=0, backcolor=frame_color, flags=0))

            # Placeholder behind the poster art area - the overlay Pixmap
            # widget for this slot sits on top and covers this once the
            # poster image is cached.
            row.append(MultiContentEntryText(pos=(cx, cy), size=(POSTER_W, POSTER_H),
                font=0, text="", color=0, backcolor=_G_CLR["surface2"], flags=0))

            # Caption: title + year, one line, no truncation
            title = item.get("title", "")
            year = item.get("year") or ""
            caption = u"{} {}".format(title, year).strip() if year else title
            cap_y = cy + POSTER_H + 2
            row.append(MultiContentEntryText(pos=(cx, cap_y), size=(POSTER_W, POSTER_CAPTION_H),
                font=0, text=caption, color=_G_CLR["text"],
                backcolor=_G_CLR["surface2"], flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER))

        return row


def build_poster_pixmap_widgets_xml(x0, y0, name_prefix="poster"):
    """Build <widget> XML for one Pixmap overlay per PosterCardGrid cell,
    positioned to exactly cover that cell's poster-art placeholder area."""
    parts = []
    for r in range(POSTER_GRID_ROWS):
        for c in range(POSTER_GRID_COLS):
            px = x0 + c * POSTER_CELL_W + POSTER_CELL_MARGIN_H
            py = y0 + r * POSTER_CELL_H + POSTER_CELL_MARGIN_V
            parts.append(
                '\n\t\t<widget name="%s_%d_%d" position="%d,%d" size="%d,%d" '
                'transparent="1" alphatest="blend" zPosition="3" />' % (name_prefix, r, c, px, py, POSTER_W, POSTER_H)
            )
    return "".join(parts)
