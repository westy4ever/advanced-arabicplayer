# -*- coding: utf-8 -*-
"""
Advanced Arabic Player - State / persistence
==============================================
Config, favorites, history and saved-playback-position storage.

NOTE: This does NOT include the live in-memory position tracker
(_GLOBAL_POS_TIMER / _global_pos_tick / _start_pos_tracker / _stop_pos_tracker)
or the local proxy hit counters. Those are mutated via bare `global`
statements from many methods inside plugin.py's Screen classes, so they
stay defined in plugin.py itself rather than here - splitting them out
would mean rewriting every read/write site to go through a module
attribute (plugin_state.X = ...) instead of `global X`, which is a
correctness-risk refactor, not a mechanical file move.
"""

import os
import json
import time

from extractors.base import log as _log

_PLUGIN_OWNER = "ArabicPlayer Team"
_DEFAULT_TMDB_API_KEY = "01fd9e035ea1458748e99eb7216b0259"

PLUGIN_PATH = os.path.dirname(__file__)

_STATE_CACHE = None


def _state_path():
    for candidate in ("/etc/enigma2/advanced_arabic_player_state.json", os.path.join(PLUGIN_PATH, "advanced_arabic_player_state.json"), "/tmp/advanced_arabic_player_state.json"):
        try:
            parent = os.path.dirname(candidate)
            if parent and os.path.isdir(parent) and os.access(parent, os.W_OK):
                return candidate
        except Exception:
            pass
    return "/tmp/advanced_arabic_player_state.json"


def _default_state():
    return {
        "config": {
            "owner": _PLUGIN_OWNER,
            "tmdb_api_key": _DEFAULT_TMDB_API_KEY,
            "browser_proxy": "",   # external proxy URL
        },
        "favorites": [],
        "history": [],
    }


def _load_state():
    global _STATE_CACHE
    if _STATE_CACHE is not None:
        return _STATE_CACHE
    state = _default_state()
    path = _state_path()
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                state.update(loaded)
                state["config"] = dict(_default_state()["config"], **(loaded.get("config") or {}))
    except Exception as e:
        _log("State load error: {}".format(e))
    _STATE_CACHE = state
    return _STATE_CACHE


def _save_state(state=None):
    global _STATE_CACHE
    _STATE_CACHE = state or _load_state()
    path = _state_path()
    tmp  = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(_STATE_CACHE, f)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, path)
    except Exception as e:
        _log("State save error: {}".format(e))
        try: os.remove(tmp)
        except Exception: pass


def _get_config(key, default=""):
    value = (_load_state().get("config") or {}).get(key, default)
    if key == "tmdb_api_key" and not value:
        return _DEFAULT_TMDB_API_KEY
    if key == "owner" and not value:
        return _PLUGIN_OWNER
    return value


def _set_config(key, value):
    state = _load_state()
    state.setdefault("config", {})[key] = value
    _save_state(state)


def _entry_from_item(item, site, m_type, extra=None):
    entry = {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "poster": item.get("poster") or item.get("image") or "",
        "plot": item.get("plot", ""),
        "year": item.get("year", ""),
        "rating": item.get("rating", ""),
        "type": item.get("type", "") or m_type,
        "_action": item.get("_action", "details"),
        "_site": item.get("_site", site),
        "_m_type": item.get("_m_type", m_type),
        "_saved_at": int(time.time()),
    }
    if extra:
        entry.update(extra)
    return entry


def _upsert_library_item(bucket, entry, limit=100):
    state = _load_state()
    items = state.setdefault(bucket, [])
    key   = entry.get("url")
    if not entry.get("last_position_sec"):
        for _old in items:
            if _old.get("url") == key and _old.get("last_position_sec"):
                entry["last_position_sec"] = _old["last_position_sec"]
                break
    items = [i for i in items if i.get("url") != key]
    items.insert(0, entry)
    state[bucket] = items[:limit]
    _save_state(state)


def _toggle_favorite_entry(entry):
    state = _load_state()
    favorites = state.setdefault("favorites", [])
    key = entry.get("url")
    for idx, item in enumerate(favorites):
        if item.get("url") == key:
            favorites.pop(idx)
            _save_state(state)
            return False
    favorites.insert(0, entry)
    state["favorites"] = favorites[:100]
    _save_state(state)
    return True


def _is_favorite(url):
    return any(item.get("url") == url for item in (_load_state().get("favorites") or []))


def _history_items():
    return _load_state().get("history") or []


def _favorite_items():
    return _load_state().get("favorites") or []


def _get_saved_position(url):
    for item in (_load_state().get("history") or []):
        if item.get("url") == url:
            pos = int(item.get("last_position_sec") or 0)
            return pos if pos > 30 else 0
    return 0


def _save_position(url, seconds):
    seconds = int(seconds or 0)
    if 0 < seconds < 30:
        _log("_save_position: skipping {}s (< 30s threshold)".format(seconds))
        return
    state = _load_state()
    for item in (state.get("history") or []):
        if item.get("url") == url:
            item["last_position_sec"] = seconds
            _save_state(state)
            return


def _library_search_suggestions(query="", current_site="", limit=8):
    from plugin_util import _normalize_query
    q = _normalize_query(query)
    rows = []
    seen = set()
    for source_name, items, source_rank in (
        ("المفضلة", _favorite_items(), 0),
        ("السجل", _history_items(), 1),
    ):
        for item in items or []:
            import re
            title = re.sub(r"\s+", " ", item.get("title", "") or "").strip()
            if not title:
                continue
            norm = _normalize_query(title)
            if not norm or norm in seen:
                continue
            if q:
                if norm == q:
                    score = 0
                elif norm.startswith(q):
                    score = 1
                elif q in norm:
                    score = 2
                else:
                    continue
            else:
                score = 5
            if current_site and item.get("_site") == current_site:
                score -= 1
            seen.add(norm)
            rows.append((
                score,
                source_rank,
                -int(item.get("_saved_at") or 0),
                {
                    "title": title,
                    "query": title,
                    "source": source_name,
                    "site": item.get("_site", ""),
                    "kind": {"movie": "فيلم", "series": "مسلسل", "episode": "حلقة"}.get(item.get("type", ""), ""),
                    "year": item.get("year", ""),
                }
            ))
    rows.sort(key=lambda row: (row[0], row[1], row[2]))
    return [row[3] for row in rows[:limit]]
