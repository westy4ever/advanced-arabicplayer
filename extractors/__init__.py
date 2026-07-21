# -*- coding: utf-8 -*-
"""
ArabicPlayer Extractors Package
================================
Each site has its own extractor module that inherits from BaseExtractor.
This keeps code clean, separated, and maintainable.
"""

from .base import BaseExtractor, fetch, log, set_browser_proxy, get_proxy_used, get_curl_failed_needs_proxy
from .registry import get_extractor, get_site_names, get_site_metadata, get_search_site_order

__all__ = [
    'BaseExtractor',
    'fetch',
    'log',
    'set_browser_proxy',
    'get_proxy_used',
    'get_curl_failed_needs_proxy',
    'get_extractor',
    'get_site_names',
    'get_site_metadata',
    'get_search_site_order',
]