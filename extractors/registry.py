# -*- coding: utf-8 -*-
"""
Site Registry - Maps site names to their extractor classes.
"""

from .egydead import EgyDeadExtractor
from .egydead_coupons import EgyDeadCouponsExtractor
from .akwam import AkwamExtractor
from .akwams import AkwamsExtractor
from .arabseed import ArabseedExtractor
from .faselhd_rip import FaselhdRipExtractor
from .faselhd_hdx import FaselhdHdxExtractor
from .shaheed import ShaheedExtractor
from .shahid4u_solar import Shahid4uSolarExtractor
from .topcinema import TopCinemaExtractor
from .wecima import WecimaExtractor
from .arablionz import ArablionzExtractor  # NEW

# Site registry: maps site names to extractor classes
_SITE_REGISTRY = {
    "egydead": {
        "class": EgyDeadExtractor,
        "title": "EgyDead",
        "tagline": "واجهة حديثة وبوسترات ومكتبة متجددة",
    },
    "egydead_coupons": {
        "class": EgyDeadCouponsExtractor,
        "title": "EgyDead Coupons",
        "tagline": "النسخة العربية - تصنيفات وأقسام مترجمة",
    },
    "akwam": {
        "class": AkwamExtractor,
        "title": "Akwam (Classic)",
        "tagline": "موقع اكوام الكلاسيكي - افلام ومسلسلات عربية واجنبية",
    },
    "akwams": {
        "class": AkwamsExtractor,
        "title": "Akwams (Modern)",
        "tagline": "موقع اكوام الحديث - واجهة سريعة ومحتوى محدث",
    },
    "arabseed": {
        "class": ArabseedExtractor,
        "title": "Arabseed",
        "tagline": "تصنيفات عربية وأجنبية وحلقات مرتبة",
    },
    "fasel": {
        "class": FaselhdRipExtractor,
        "title": "FaselHD (RIP)",
        "tagline": "واجهة حديثة - سيرفرات متعددة بجودة عالية",
    },
    "faselhdx": {
        "class": FaselhdHdxExtractor,
        "title": "FaselHD (HDX)",
        "tagline": "النسخة الكلاسيكية - دقة عالية وسيرفرات متنوعة",
    },
    "shaheed": {
        "class": ShaheedExtractor,
        "title": "Shaheed4u",
        "tagline": "تحديثات المسلسلات والأفلام الحصرية بجميع الجودات",
    },
    "shahid4u": {  # NEW: Added shahid4u (renamed from solar)
        "class": Shahid4uSolarExtractor,
        "title": "Shahid4u",
        "tagline": "شاهد فور يو - أفلام ومسلسلات مترجمة",
    },
    "topcinema": {
        "class": TopCinemaExtractor,
        "title": "TopCinemaa",
        "tagline": "مكتبة ضخمة من الأفلام والمسلسلات والسلاسل",
    },
    "wecima": {
        "class": WecimaExtractor,
        "title": "Wecima",
        "tagline": "أقسام واسعة وبحث وسيرفرات مباشرة",
    },
    "arablionz": {  # NEW
        "class": ArablionzExtractor,
        "title": "Arablionz",
        "tagline": "عرب ليونز - افلام ومسلسلات سيرفر Lionz Tv",
    },
}

_SEARCH_SITE_ORDER = ("egydead", "egydead_coupons", "akwam", "akwams", "arabseed", "wecima", "topcinema", "fasel", "faselhdx", "shaheed", "shahid4u", "arablionz")


def get_extractor(site_name):
    """Get an extractor instance for the given site name."""
    entry = _SITE_REGISTRY.get(site_name)
    if not entry:
        entry = _SITE_REGISTRY.get("egydead")
    return entry["class"]()


def get_site_names():
    """Get list of all registered site names."""
    return list(_SITE_REGISTRY.keys())


def get_site_metadata(site_name):
    """Get metadata (title, tagline) for a site."""
    entry = _SITE_REGISTRY.get(site_name)
    if entry:
        return {"title": entry["title"], "tagline": entry["tagline"]}
    return {"title": site_name, "tagline": ""}


def get_search_site_order():
    """Get the order of sites for search."""
    return _SEARCH_SITE_ORDER