"""
Базовый класс для скраперов сторонних сайтов.

Цепочка фолбэков для обхода защит:
1. curl_cffi (имитация TLS-отпечатка браузера — главный обход CloudFlare)
2. cloudscraper
3. requests с браузерными заголовками
4. мобильный User-Agent
"""

import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as cffi_requests  # type: ignore
    HAS_CURL_CFFI = True
except Exception:
    HAS_CURL_CFFI = False

try:
    import cloudscraper  # type: ignore
    HAS_CLOUDSCRAPER = True
except Exception:
    HAS_CLOUDSCRAPER = False


DEFAULT_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class BaseScraper:
    """Базовый скрапер с цепочкой фолбэков для обхода защит."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.session.headers["User-Agent"] = DEFAULT_UA
        self._cloudscraper = None
        self._setup_headers()

    def _setup_headers(self):
        """Переопределяется подклассами для дополнительных заголовков."""
        pass

    # --- fetch methods --------------------------------------------------

    def _fetch_curl_cffi(self, url: str, timeout: int = 20) -> Optional[str]:
        """curl_cffi с имитацией Chrome TLS-отпечатка."""
        if not HAS_CURL_CFFI:
            return None
        try:
            r = cffi_requests.get(
                url,
                impersonate="chrome124",
                timeout=timeout,
                allow_redirects=True,
                headers=dict(self.session.headers),
            )
            if r.status_code == 200 and r.text and len(r.text) > 200:
                return r.text
        except Exception:
            pass
        return None

    def _fetch_cloudscraper(self, url: str, timeout: int = 20) -> Optional[str]:
        if not HAS_CLOUDSCRAPER:
            return None
        try:
            if self._cloudscraper is None:
                self._cloudscraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows"}
                )
                self._cloudscraper.headers.update(dict(self.session.headers))
            r = self._cloudscraper.get(url, timeout=timeout)
            if r.status_code == 200 and r.text and len(r.text) > 200:
                return r.text
        except Exception:
            pass
        return None

    def _fetch_requests(self, url: str, timeout: int = 20) -> Optional[str]:
        try:
            r = self.session.get(url, timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and r.text and len(r.text) > 200:
                return r.text
        except Exception:
            pass
        return None

    def _fetch_html(self, url: str, retries: int = 2, delay: int = 2) -> Optional[str]:
        """
        Цепочка: curl_cffi → cloudscraper → requests.
        """
        for attempt in range(retries):
            for fetcher in (
                self._fetch_curl_cffi,
                self._fetch_cloudscraper,
                self._fetch_requests,
            ):
                html = fetcher(url)
                if html:
                    return html
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))

        print(f"Ошибка загрузки {url}: все фолбэки исчерпаны")
        return None

    def _head_ok(self, url: str, timeout: int = 10) -> bool:
        """Проверяет доступность URL через HEAD (или GET маленький)."""
        if HAS_CURL_CFFI:
            try:
                r = cffi_requests.head(
                    url, impersonate="chrome124", timeout=timeout, allow_redirects=True,
                )
                return r.status_code == 200
            except Exception:
                pass
        try:
            r = self.session.head(url, timeout=timeout, allow_redirects=True)
            return r.status_code == 200
        except Exception:
            pass
        return False

    def _get_soup(self, url: str, retries: int = 2, delay: int = 2) -> Optional[BeautifulSoup]:
        html = self._fetch_html(url, retries=retries, delay=delay)
        if not html:
            return None
        return BeautifulSoup(html, "html.parser")

    # --- public API (переопределяются) ----------------------------------

    def get_book_info(self, url):
        raise NotImplementedError

    def get_chapters_list(self, url):
        raise NotImplementedError

    def get_chapter_text(self, chapter_url):
        raise NotImplementedError
