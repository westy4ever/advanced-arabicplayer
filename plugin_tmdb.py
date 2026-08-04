# -*- coding: utf-8 -*-
"""
Advanced Arabic Player - TMDb client
=======================================
Self-contained TMDb (themoviedb.org) lookups used to enrich scraped
titles/posters/plots. No Enigma2 or UI dependency.
"""

import re
from urllib.parse import urlencode

from extractors.base import fetch as base_fetch, log as _log

from plugin_state import _get_config
from plugin_util import _clean_title_for_tmdb, _normalize_query

_TMDB_API_BASE  = "https://api.themoviedb.org/3"
_TMDB_IMG_BASE  = "https://image.tmdb.org/t/p/w500"


def _tmdb_enabled():
    return bool((_get_config("tmdb_api_key", "") or "").strip())


def _tmdb_request(path, params=None):
    api_key = (_get_config("tmdb_api_key", "") or "").strip()
    if not api_key:
        return None
    base_payload = {"api_key": api_key}
    if params:
        base_payload.update(params)
    for language in ("ar", "en-US"):
        payload = dict(base_payload)
        payload["language"] = language
        url = "{}{}?{}".format(_TMDB_API_BASE, path, urlencode(payload))
        try:
            raw, _ = base_fetch(
                url,
                referer="https://www.themoviedb.org/",
                extra_headers={"Accept": "application/json"}
            )
            if not raw:
                continue
            import json
            data = json.loads(raw)
            if isinstance(data, dict):
                if data.get("overview") or data.get("results") or language == "en-US":
                    return data
        except Exception as e:
            _log("TMDb request failed {} [{}]: {}".format(path, language, e))
    return None


def _tmdb_request_language(path, language="ar", params=None, accept_any=False):
    api_key = (_get_config("tmdb_api_key", "") or "").strip()
    if not api_key:
        return None
    payload = {"api_key": api_key, "language": language}
    if params:
        payload.update(params)
    url = "{}{}?{}".format(_TMDB_API_BASE, path, urlencode(payload))
    try:
        raw, _ = base_fetch(
            url,
            referer="https://www.themoviedb.org/",
            extra_headers={"Accept": "application/json"}
        )
        if not raw:
            return None
        import json
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        if accept_any or data.get("overview") or data.get("results"):
            return data
    except Exception as e:
        _log("TMDb language request failed {} [{}]: {}".format(path, language, e))
    return None


def _tmdb_poster_url(path):
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return _TMDB_IMG_BASE + path


def _tmdb_pick_poster(media_kind, tmdb_id, fallback_path=""):
    if not tmdb_id:
        return _tmdb_poster_url(fallback_path or "")
    images = _tmdb_request_language(
        "/{}/{}/images".format(media_kind, tmdb_id),
        language="en-US",
        params={"include_image_language": "ar,en,null"},
        accept_any=True,
    ) or {}
    posters = images.get("posters") or []
    for wanted_lang in ("ar", None, "en"):
        for poster in posters:
            if poster.get("iso_639_1") == wanted_lang and poster.get("file_path"):
                return _tmdb_poster_url(poster.get("file_path"))
    return _tmdb_poster_url(fallback_path or "")


def _tmdb_media_kind(item_type):
    if item_type in ("series", "episode", "tv"):
        return "tv"
    return "movie"


def _tmdb_pick_best(results, query, year=""):
    query_norm = _normalize_query(query)
    target_year = (year or "")[:4]
    scored = []
    for result in results or []:
        title = result.get("title") or result.get("name") or ""
        title_norm = _normalize_query(title)
        score = 9
        if title_norm == query_norm:
            score = 0
        elif title_norm.startswith(query_norm):
            score = 1
        elif query_norm and query_norm in title_norm:
            score = 2
        release = str(result.get("release_date") or result.get("first_air_date") or "")
        if target_year and release[:4] == target_year:
            score -= 1
        scored.append((score, title.lower(), result))
    scored.sort(key=lambda row: (row[0], row[1]))
    return scored[0][2] if scored else None


def _tmdb_search_metadata(title, year="", item_type="movie"):
    if not title or not _tmdb_enabled():
        return None
    media_kind = _tmdb_media_kind(item_type)
    variants = [title.strip()]
    simple = re.sub(r"\s*\(\d{4}\)\s*$", "", title).strip()
    if simple and simple not in variants:
        variants.append(simple)
    plain = re.sub(r"[:|_\-]+", " ", simple).strip()
    if plain and plain not in variants:
        variants.append(plain)
    clean = re.sub(r"\b(bluray|webrip|web-dl|hdrip|hdcam|cam|1080p|720p|480p|360p)\b", "", plain, flags=re.I).strip()
    clean = re.sub(r"\s+", " ", clean).strip(" -|")
    if clean and clean not in variants:
        variants.append(clean)
    arabic_clean = re.sub(
        r"\b(مشاهدة|فيلم|مسلسل|الحلقة|حلقة|الموسم|مترجم(?:ة)?|مدبلج(?:ة)?|اون لاين|أون لاين)\b",
        "",
        clean,
        flags=re.I,
    ).strip()
    arabic_clean = re.sub(r"\s+", " ", arabic_clean).strip(" -|")
    if arabic_clean and arabic_clean not in variants:
        variants.append(arabic_clean)

    best = None
    for query in variants:
        params = {"query": query}
        if year:
            if media_kind == "movie":
                params["year"] = year[:4]
            else:
                params["first_air_date_year"] = year[:4]
        data = _tmdb_request("/search/{}".format(media_kind), params) or {}
        best = _tmdb_pick_best(data.get("results") or [], query, year)
        if not best:
            params.pop("year", None)
            params.pop("first_air_date_year", None)
            best = _tmdb_pick_best((_tmdb_request("/search/{}".format(media_kind), params) or {}).get("results") or [], query, "")
        if best:
            break
    if not best:
        return None
    detail_ar = _tmdb_request_language(
        "/{}/{}".format(media_kind, best.get("id")),
        language="ar",
        params={"append_to_response": "credits"},
        accept_any=True,
    ) or {}
    detail_en = _tmdb_request_language(
        "/{}/{}".format(media_kind, best.get("id")),
        language="en-US",
        params={"append_to_response": "credits"},
        accept_any=True,
    ) or {}
    detail = detail_ar or detail_en
    if not detail:
        detail = _tmdb_request("/{}/{}".format(media_kind, best.get("id"))) or {}
    if not detail:
        detail = best
    genres_source = detail_ar or detail_en or detail
    genres = ", ".join([g.get("name", "") for g in genres_source.get("genres") or [] if g.get("name")])
    localized_plot = (
        (detail_ar.get("overview") or "").strip()
        or (detail_en.get("overview") or "").strip()
        or (best.get("overview") or "").strip()
    )
    localized_title = (
        detail_ar.get("title")
        or detail_ar.get("name")
        or detail_en.get("title")
        or detail_en.get("name")
        or detail.get("title")
        or detail.get("name")
        or title
    )
    return {
        "title": localized_title,
        "plot": localized_plot,
        "poster": _tmdb_pick_poster(media_kind, best.get("id"), detail_ar.get("poster_path") or detail_en.get("poster_path") or detail.get("poster_path") or ""),
        "rating": "{:.1f}".format(float(detail.get("vote_average") or 0)) if detail.get("vote_average") else "",
        "year": str(detail.get("release_date") or detail.get("first_air_date") or "")[:4],
        "genres": genres,
        "tmdb_id": detail.get("id"),
        "tmdb_kind": media_kind,
    }


def _merge_tmdb_data(data):
    if not data or not data.get("title"):
        return data
    data = dict(data)
    if not data.get("plot") and data.get("desc"):
        data["plot"] = data.get("desc")
    item_type = data.get("type", "movie")
    if item_type == "episode":
        return data
    tmdb = _tmdb_search_metadata(data.get("title"), data.get("year", ""), item_type)
    if not tmdb:
        return data
    merged = dict(data)
    if tmdb.get("title") and len((data.get("title") or "").strip()) < 2:
        merged["title"] = tmdb["title"]
    if tmdb.get("poster") and (not merged.get("poster")):
        merged["poster"] = tmdb["poster"]
    if tmdb.get("plot") and len(tmdb.get("plot", "")) > len(merged.get("plot", "")):
        merged["plot"] = tmdb["plot"]
    if tmdb.get("rating") and not merged.get("rating"):
        merged["rating"] = tmdb["rating"]
    if tmdb.get("year") and not merged.get("year"):
        merged["year"] = tmdb["year"]
    if tmdb.get("genres"):
        merged["genres"] = tmdb["genres"]
    if tmdb.get("plot") or tmdb.get("poster") or tmdb.get("rating") or tmdb.get("genres") or tmdb.get("year"):
        merged["_tmdb"] = tmdb
    return merged


def _tmdb_search_suggestions(query, limit=8):
    query = re.sub(r"\s+", " ", query or "").strip()
    if len(query) < 2 or not _tmdb_enabled():
        return []

    suggestions = []
    seen = set()
    for media_kind, kind_label in (("movie", "فيلم"), ("tv", "مسلسل")):
        try:
            data = _tmdb_request("/search/{}".format(media_kind), {"query": query, "page": 1}) or {}
            for result in data.get("results") or []:
                title = (result.get("title") or result.get("name") or "").strip()
                if not title:
                    continue
                norm = _normalize_query(title)
                if not norm or norm in seen:
                    continue
                seen.add(norm)
                year = str(result.get("release_date") or result.get("first_air_date") or "")[:4]
                suggestions.append({
                    "title": title,
                    "query": title,
                    "source": "TMDb",
                    "site": "",
                    "kind": kind_label,
                    "year": year,
                })
                if len(suggestions) >= limit:
                    return suggestions[:limit]
        except Exception as e:
            _log("TMDb suggestions failed for {}: {}".format(media_kind, e))
    return suggestions[:limit]
