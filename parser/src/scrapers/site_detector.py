"""
Модуль автоопределения сайта по URL
"""

from urllib.parse import urlparse

SITE_RANOBELIB = "ranobelib"
SITE_WEBNOVEL = "webnovel"
SITE_MVLEMPYR = "mvlempyr"


def detect_site(url):
    """Определяет сайт-источник по домену в URL.
    Возвращает одну из констант SITE_* или None.
    """
    if not url:
        return None

    parsed = urlparse(url)
    host = parsed.hostname or ""
    host = host.lower()

    if "ranobelib" in host:
        return SITE_RANOBELIB
    if "webnovel" in host:
        return SITE_WEBNOVEL
    if "mvlempyr" in host:
        return SITE_MVLEMPYR

    return None
