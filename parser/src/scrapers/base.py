"""
Базовый класс для скраперов сторонних сайтов.

Цепочка фолбэков для обхода защит:
1. curl_cffi (имитация TLS-отпечатка браузера)
2. cloudscraper
3. requests с браузерными заголовками
4. Chrome пользователя через DrissionPage (с расширениями, VPN и т.д.)
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

CF_MARKERS = (
    "cf-browser-verification",
    "challenge-platform",
    "cf-challenge",
    "Just a moment",
    "Checking your browser",
    "Verify you are human",
)


class BaseScraper:
    """Базовый скрапер с цепочкой фолбэков для обхода защит."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.session.headers["User-Agent"] = DEFAULT_UA
        self._cloudscraper = None
        self._browser_page = None
        self._setup_headers()

    def _setup_headers(self):
        """Переопределяется подклассами для дополнительных заголовков."""
        pass

    # --- fetch methods (HTTP) ---------------------------------------------

    def _fetch_curl_cffi(self, url: str, timeout: int = 20) -> Optional[str]:
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

    # --- fetch methods (браузер) ------------------------------------------

    def _get_browser_page(self) -> Optional["ChromiumPage"]:
        """Возвращает переиспользуемое подключение к Chrome."""
        if self._browser_page is not None:
            try:
                _ = self._browser_page.url
                return self._browser_page
            except Exception:
                self._browser_page = None

        if not HAS_DRISSION:
            return None

        try:
            co = ChromiumOptions()
            co.auto_port()
            self._browser_page = ChromiumPage(co)
            print("DrissionPage: подключено к Chrome")
            return self._browser_page
        except Exception as e:
            print(f"DrissionPage: не удалось подключиться к Chrome: {e}")
        return None

    @staticmethod
    def _is_cloudflare_challenge(html: str) -> bool:
        if not html:
            return True
        for marker in CF_MARKERS:
            if marker in html:
                return True
        return False

    def _fetch_browser(self, url: str, wait: int = 12) -> Optional[str]:
        """Загружает URL через Chrome пользователя.

        Подключается к уже запущенному Chrome (с расширениями, VPN, куками).
        Открывает новую вкладку, ждёт рендеринга, забирает HTML, закрывает вкладку.
        """
        page = self._get_browser_page()
        if not page:
            return None

        tab = None
        try:
            tab = page.new_tab(url)
            html = self._wait_for_content(tab, wait)
            if html and len(html) > 500 and not self._is_cloudflare_challenge(html):
                print(f"DrissionPage: загружено {len(html)} символов с {url}")
                return html
            if html:
                print(f"DrissionPage: страница пустая или CloudFlare ({len(html)} символов)")
        except Exception as e:
            print(f"DrissionPage: {e}")
        finally:
            if tab:
                try:
                    tab.close()
                except Exception:
                    pass
        return None

    def _wait_for_content(self, tab, max_wait: int = 15) -> Optional[str]:
        """Ждёт пока страница прогрузится (CloudFlare challenge + JS рендеринг)."""
        last_html = ""
        stable_count = 0

        for i in range(max_wait // 2):
            time.sleep(2)
            try:
                html = tab.html or ""
            except Exception:
                return last_html

            if self._is_cloudflare_challenge(html):
                stable_count = 0
                last_html = html
                continue

            if len(html) > 1000:
                if abs(len(html) - len(last_html)) < 100:
                    stable_count += 1
                    if stable_count >= 2:
                        return html
                else:
                    stable_count = 0
                last_html = html

        return last_html

    def _fetch_browser_quick(self, url: str, wait: int = 4) -> Optional[str]:
        """Быстрая проверка URL через браузер (для пробинга)."""
        page = self._get_browser_page()
        if not page:
            return None

        tab = None
        try:
            tab = page.new_tab(url)
            time.sleep(wait)
            html = tab.html
            if html and len(html) > 500 and not self._is_cloudflare_challenge(html):
                return html
        except Exception:
            pass
        finally:
            if tab:
                try:
                    tab.close()
                except Exception:
                    pass
        return None

    def close_browser(self):
        """Закрывает подключение к Chrome."""
        if self._browser_page:
            try:
                self._browser_page.quit()
            except Exception:
                pass
            self._browser_page = None

    # --- unified fetch chain ----------------------------------------------

    def _fetch_html(self, url: str, retries: int = 2, delay: int = 2,
                     silent: bool = False) -> Optional[str]:
        """Цепочка: curl_cffi → cloudscraper → requests."""
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
        """Тихо проверяет доступность URL (HTTP only)."""
        html = self._fetch_html(url, retries=1, delay=1, silent=True)
        return html is not None and len(html) > 500

    def _probe_url_browser(self, url: str) -> bool:
        """Проверяет доступность URL через браузер."""
        html = self._fetch_browser_quick(url)
        return html is not None and len(html) > 500

    def _get_soup(self, url: str, retries: int = 2, delay: int = 2) -> Optional[BeautifulSoup]:
        html = self._fetch_html(url, retries=retries, delay=delay)
        if not html:
            return None
        return BeautifulSoup(html, "html.parser")

    def _get_soup_with_browser(self, url: str) -> Optional[BeautifulSoup]:
        """HTTP → браузер. Возвращает BeautifulSoup."""
        html = self._fetch_html(url, retries=1, delay=1, silent=True)
        if not html:
            html = self._fetch_browser(url)
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
