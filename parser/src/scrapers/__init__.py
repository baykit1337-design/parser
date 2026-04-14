"""
Модули для парсинга различных сайтов с новеллами.
"""

from .webnovel import WebnovelScraper
from .mvlempyr import MvlempyrScraper
from .site_detector import detect_site, SITE_RANOBELIB, SITE_WEBNOVEL, SITE_MVLEMPYR

__all__ = [
    "WebnovelScraper",
    "MvlempyrScraper",
    "detect_site",
    "SITE_RANOBELIB",
    "SITE_WEBNOVEL",
    "SITE_MVLEMPYR",
]
