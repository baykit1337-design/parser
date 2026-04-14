"""
Базовый класс для скраперов сторонних сайтов.

Использует цепочку фолбэков для обхода защит:
1. requests с браузерными заголовками
2. cloudscraper (для CloudFlare)
3. httpx (HTTP/2)
"""

import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper  # type: ignore
    HAS_CLOUDSCRAPER = True
except Exception:
    HAS_CLOUDSCRAPER = False

try:
    import httpx  # type: ignore
    HAS_HTTPX = True
except Exception:
    HAS_HTTPX = False


DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)


class BaseScraper:
    """Базовый скрапер с цепочкой фолбэков для обхода защит."""

    def __init__(self):
        self.session = requests.Session()
        self._cloudscraper = None
        self._httpx_client = None
        self._setup_headers()

    def _default_headers(self, mobile: bool = False) -> dict:
        return {
            "User-Agent": MOBILE_UA if mobile else DEFAULT_UA,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?1" if mobile else "?0",
            "sec-ch-ua-platform": '"iOS"' if mobile else '"Windows"',
        }

    def _setup_headers(self):
        """Настройка заголовков по умолчанию."""
        self.session.headers.update(self._default_headers())

    def _fetch_requests(self, url: str, timeout: int = 20) -> Optional[str]:
        """Обычный requests-запрос."""
        try:
            response = self.session.get(url, timeout=timeout, allow_redirects=True)
            if response.status_code == 200 and response.text:
                return response.text
        except requests.exceptions.RequestException:
            pass
        return None

    def _fetch_cloudscraper(self, url: str, timeout: int = 20) -> Optional[str]:
        """Фолбэк через cloudscraper (обходит CloudFlare)."""
        if not HAS_CLOUDSCRAPER:
            return None
        try:
            if self._cloudscraper is None:
                self._cloudscraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False}
                )
                # Пробрасываем заголовки из основной сессии
                self._cloudscraper.headers.update(self.session.headers)
            response = self._cloudscraper.get(url, timeout=timeout)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception:
            pass
        return None

    def _fetch_httpx(self, url: str, timeout: int = 20) -> Optional[str]:
        """Фолбэк через httpx (HTTP/2)."""
        if not HAS_HTTPX:
            return None
        try:
            if self._httpx_client is None:
                self._httpx_client = httpx.Client(
                    http2=True,
                    headers=dict(self.session.headers),
                    follow_redirects=True,
                    timeout=timeout,
                )
            response = self._httpx_client.get(url)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception:
            pass
        return None

    def _fetch_mobile(self, url: str, timeout: int = 20) -> Optional[str]:
        """Запрос с мобильным User-Agent."""
        try:
            headers = self._default_headers(mobile=True)
            response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            if response.status_code == 200 and response.text:
                return response.text
        except Exception:
            pass
        return None

    def _fetch_html(self, url: str, retries: int = 2, delay: int = 2) -> Optional[str]:
        """
        Цепочка фолбэков: requests → cloudscraper → httpx → mobile.
        Возвращает HTML или None.
        """
        for attempt in range(retries):
            for fetcher in (
                self._fetch_requests,
                self._fetch_cloudscraper,
                self._fetch_httpx,
                self._fetch_mobile,
            ):
                html = fetcher(url)
                if html:
                    return html
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))

        print(f"Ошибка загрузки {url}: все фолбэки исчерпаны")
        return None

    def _get_soup(self, url: str, retries: int = 2, delay: int = 2) -> Optional[BeautifulSoup]:
        """Загружает страницу и возвращает BeautifulSoup объект."""
        html = self._fetch_html(url, retries=retries, delay=delay)
        if not html:
            return None
        return BeautifulSoup(html, "html.parser")

    def get_book_info(self, url):
        raise NotImplementedError

    def get_chapters_list(self, url):
        raise NotImplementedError

    def get_chapter_text(self, chapter_url):
        raise NotImplementedError
