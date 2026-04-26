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
    print(
        "[!] curl_cffi не установлен. Установите: pip install curl_cffi\n"
        "    Без него webnovel.com и другие сайты с CloudFlare не будут работать."
    )

try:
    import cloudscraper  # type: ignore
    HAS_CLOUDSCRAPER = True
except Exception:
    HAS_CLOUDSCRAPER = False

try:
    from DrissionPage import ChromiumPage, ChromiumOptions  # type: ignore
    HAS_DRISSION = True
except Exception:
    HAS_DRISSION = False


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

    def _fetch_browser(self, url: str, timeout: int = 30) -> Optional[str]:
        """Фолбэк через Chrome (DrissionPage).

        Сначала пробует подключиться к уже запущенному Chrome пользователя
        (с его расширениями, VPN, куками). Если не удаётся — запускает новый
        с профилем по умолчанию (не инкогнито).
        """
        if not HAS_DRISSION:
            return None

        # 1. Подключение к уже запущенному Chrome
        html = self._fetch_browser_existing(url, timeout)
        if html:
            return html

        # 2. Запуск нового Chrome с профилем пользователя
        html = self._fetch_browser_new(url, timeout)
        if html:
            return html

        return None

    def _fetch_browser_existing(self, url: str, timeout: int = 30) -> Optional[str]:
        """Подключается к уже запущенному Chrome через debug port."""
        page = None
        try:
            co = ChromiumOptions()
            co.set_local_port(9222)
            page = ChromiumPage(co)
            tab = page.new_tab(url)
            time.sleep(6)
            html = tab.html
            tab.close()
            if html and len(html) > 500:
                print(f"DrissionPage (existing Chrome): загружено {len(html)} символов")
                return html
        except Exception:
            pass
        return None

    def _fetch_browser_new(self, url: str, timeout: int = 30) -> Optional[str]:
        """Запускает новый Chrome с профилем пользователя."""
        page = None
        try:
            co = ChromiumOptions()
            co.set_argument("--disable-gpu")
            co.set_argument("--no-sandbox")
            co.set_argument("--disable-blink-features=AutomationControlled")
            page = ChromiumPage(co)
            page.set.timeouts(timeout)
            page.get(url)
            time.sleep(8)
            html = page.html
            if html and len(html) > 500:
                print(f"DrissionPage: загружено {len(html)} символов")
                return html
            print(f"DrissionPage: страница пустая ({len(html) if html else 0} символов)")
        except Exception as e:
            print(f"DrissionPage: {e}")
        finally:
            if page:
                try:
                    page.quit()
                except Exception:
                    pass
        return None

    def _fetch_html(self, url: str, retries: int = 2, delay: int = 2,
                     silent: bool = False) -> Optional[str]:
        """
        Цепочка: curl_cffi → cloudscraper → requests.
        silent=True подавляет сообщение об ошибке (для пробинга).
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

        if not silent:
            print(f"Ошибка загрузки {url}: HTTP-фолбэки исчерпаны")
        return None

    def _probe_url(self, url: str) -> bool:
        """Тихо проверяет доступность URL (без сообщений об ошибках)."""
        html = self._fetch_html(url, retries=1, delay=1, silent=True)
        return html is not None and len(html) > 500

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
