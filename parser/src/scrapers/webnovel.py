"""
Скрапер для webnovel.com.

Стратегия (на основе реверс-инжиниринга API):
1. Получить _csrfToken cookie — визит на любую страницу webnovel.com
2. Список глав: GET /go/pcm/chapter/get-chapter-list?bookId=...&_csrfToken=...
3. Текст главы: GET /go/pcm/chapter/getContent?bookId=...&chapterId=...&_csrfToken=...

Фолбэк: если API недоступен — HTML-парсинг (soup) и DrissionPage (браузер).

URL-паттерны:
- Книга:   https://www.webnovel.com/book/{slug}_{bookId}
- Глава:   https://www.webnovel.com/book/{bookId}/{chapterId}
           или /book/{slug}_{bookId}/{num}.-{slug}_{chapterId}
"""

import json
import re
import time
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, HAS_CURL_CFFI, HAS_DRISSION

try:
    from curl_cffi import requests as cffi_requests  # type: ignore
except Exception:
    pass


class WebnovelScraper(BaseScraper):
    """Скрапер для webnovel.com с поддержкой REST API."""

    BASE = "https://www.webnovel.com"
    MOBILE_BASE = "https://m.webnovel.com"
    API_BASE = "https://www.webnovel.com/go/pcm"

    def __init__(self):
        super().__init__()
        self._csrf_token = ""
        self._cookies = {}

    def _setup_headers(self):
        self.session.headers.update({
            "Referer": "https://www.webnovel.com/",
            "Origin": "https://www.webnovel.com",
        })

    # --- CSRF token -------------------------------------------------------

    def _acquire_csrf_token(self) -> str:
        """Получает _csrfToken, пробуя все методы."""
        if self._csrf_token:
            return self._csrf_token

        # 1. curl_cffi (обходит CloudFlare TLS fingerprinting)
        if HAS_CURL_CFFI:
            try:
                r = cffi_requests.get(
                    f"{self.BASE}/stories/novel",
                    impersonate="chrome124",
                    timeout=20,
                    allow_redirects=True,
                    headers=dict(self.session.headers),
                )
                token = r.cookies.get("_csrfToken", "")
                if token:
                    self._csrf_token = token
                    self._cookies = dict(r.cookies)
                    print(f"webnovel: CSRF token получен через curl_cffi")
                    return token
            except Exception as e:
                print(f"webnovel: curl_cffi не смог получить CSRF: {e}")

        # 2. cloudscraper
        token = self._try_csrf_cloudscraper()
        if token:
            return token

        # 3. requests
        try:
            r = self.session.get(f"{self.BASE}/stories/novel", timeout=20, allow_redirects=True)
            token = r.cookies.get("_csrfToken", "")
            if token:
                self._csrf_token = token
                self._cookies = dict(r.cookies)
                print(f"webnovel: CSRF token получен через requests")
                return token
        except Exception:
            pass

        # 4. DrissionPage (браузер)
        if HAS_DRISSION:
            token = self._try_csrf_browser()
            if token:
                return token

        print("webnovel: не удалось получить CSRF token")
        return ""

    def _try_csrf_cloudscraper(self) -> str:
        from .base import HAS_CLOUDSCRAPER
        if not HAS_CLOUDSCRAPER:
            return ""
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows"}
            )
            scraper.headers.update(dict(self.session.headers))
            r = scraper.get(f"{self.BASE}/stories/novel", timeout=20)
            token = r.cookies.get("_csrfToken", "")
            if token:
                self._csrf_token = token
                self._cookies = dict(r.cookies)
                print(f"webnovel: CSRF token получен через cloudscraper")
                return token
        except Exception:
            pass
        return ""

    def _try_csrf_browser(self) -> str:
        """Получает CSRF через Chrome — сначала существующий, потом новый."""
        if not HAS_DRISSION:
            return ""

        from DrissionPage import ChromiumPage, ChromiumOptions

        # 1. Подключение к уже запущенному Chrome (с расширениями/VPN)
        try:
            co = ChromiumOptions()
            co.set_local_port(9222)
            page = ChromiumPage(co)
            tab = page.new_tab(f"{self.BASE}/stories/novel")
            time.sleep(6)
            cookies = tab.cookies()
            tab.close()

            for c in cookies:
                name = c.get("name", "")
                value = c.get("value", "")
                self._cookies[name] = value
                if name == "_csrfToken":
                    self._csrf_token = value

            if self._csrf_token:
                print("webnovel: CSRF token получен через существующий Chrome")
                return self._csrf_token
        except Exception:
            pass

        # 2. Новый Chrome
        page = None
        try:
            co = ChromiumOptions()
            co.set_argument("--disable-gpu")
            co.set_argument("--no-sandbox")
            co.set_argument("--disable-blink-features=AutomationControlled")
            page = ChromiumPage(co)
            page.set.timeouts(30)
            page.get(f"{self.BASE}/stories/novel")
            time.sleep(8)

            cookies = page.cookies()

            for c in cookies:
                name = c.get("name", "")
                value = c.get("value", "")
                self._cookies[name] = value
                if name == "_csrfToken":
                    self._csrf_token = value

            if self._csrf_token:
                print("webnovel: CSRF token получен через новый Chrome")
                return self._csrf_token
        except Exception as e:
            print(f"webnovel: браузер не смог получить CSRF: {e}")
        finally:
            if page:
                try:
                    page.quit()
                except Exception:
                    pass
        return ""

    # --- API requests -----------------------------------------------------

    def _api_get(self, endpoint: str, params: dict) -> Optional[dict]:
        """Делает GET-запрос к API webnovel.com."""
        url = f"{self.API_BASE}/{endpoint}"
        params["_csrfToken"] = self._csrf_token

        # curl_cffi (лучший шанс пройти CloudFlare)
        if HAS_CURL_CFFI:
            try:
                r = cffi_requests.get(
                    url,
                    params=params,
                    impersonate="chrome124",
                    timeout=20,
                    cookies=self._cookies,
                    headers=dict(self.session.headers),
                )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("code") == 0 and data.get("data"):
                        return data["data"]
                    print(f"webnovel API: code={data.get('code')}, msg={data.get('msg', '')}")
            except Exception as e:
                print(f"webnovel API (curl_cffi): {e}")

        # requests с cookies
        try:
            r = self.session.get(url, params=params, timeout=20, cookies=self._cookies)
            if r.status_code == 200:
                data = r.json()
                if data.get("code") == 0 and data.get("data"):
                    return data["data"]
        except Exception:
            pass

        return None

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _extract_book_id(url: str) -> Optional[str]:
        m = re.search(r"/book/[^/]*?_(\d{8,})", url)
        if m:
            return m.group(1)
        m = re.search(r"/book/(\d{8,})(?:/|$|\?)", url)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _extract_chapter_id(url: str) -> Optional[str]:
        m = re.search(r"_(\d{8,})/?$", url)
        if m:
            return m.group(1)
        m = re.search(r"/book/\d+/(\d+)", url)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _parse_next_data(soup: BeautifulSoup) -> dict:
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script or not script.string:
            return {}
        try:
            return json.loads(script.string)
        except Exception:
            return {}

    @staticmethod
    def _walk_for_key(obj, keys, max_depth=10):
        if max_depth <= 0:
            return None
        if isinstance(obj, dict):
            for key in keys:
                val = obj.get(key)
                if isinstance(val, str) and len(val) > 1:
                    return val
            for v in obj.values():
                r = WebnovelScraper._walk_for_key(v, keys, max_depth - 1)
                if r:
                    return r
        elif isinstance(obj, list):
            for item in obj:
                r = WebnovelScraper._walk_for_key(item, keys, max_depth - 1)
                if r:
                    return r
        return None

    # --- book info --------------------------------------------------------

    def get_book_info(self, url: str) -> dict:
        book_id = self._extract_book_id(url)
        self._acquire_csrf_token()

        title = None

        # API
        if book_id and self._csrf_token:
            data = self._api_get("book/GetBookDetail", {"bookId": book_id})
            if data:
                book_info = data.get("bookInfo", data)
                title = (
                    book_info.get("bookName")
                    or book_info.get("name")
                    or book_info.get("title")
                )

        # HTML фолбэк
        if not title:
            soup = self._get_soup_safe(url)
            if soup:
                title = self._extract_title_from_soup(soup)

        if title:
            title = re.sub(
                r"\s*[\|\-–—]\s*(WebNovel|Webnovel|webnovel).*$", "", title
            )

        return {
            "title": title or "Без названия",
            "url": url,
            "book_id": book_id,
        }

    def _extract_title_from_soup(self, soup: BeautifulSoup) -> Optional[str]:
        og = soup.find("meta", {"property": "og:title"})
        if og and og.get("content"):
            return og["content"].strip()

        for sel in ("h1", "h2", ".g_book_name", "title"):
            tag = soup.select_one(sel)
            if tag:
                text = tag.get_text(strip=True)
                if text and len(text) > 1:
                    return text

        data = self._parse_next_data(soup)
        return self._walk_for_key(data, ("bookName", "name", "title"))

    def _get_soup_safe(self, url: str) -> Optional[BeautifulSoup]:
        """HTML через HTTP, затем браузер."""
        soup = self._get_soup(url)
        if soup:
            return soup
        if HAS_DRISSION:
            html = self._fetch_browser(url)
            if html:
                return BeautifulSoup(html, "html.parser")
        return None

    # --- chapters list ----------------------------------------------------

    def get_chapters_list(self, url: str) -> List[dict]:
        book_id = self._extract_book_id(url) or ""
        if not book_id:
            print("webnovel: не удалось извлечь book_id из URL")
            return []

        self._acquire_csrf_token()

        # 1. REST API
        if self._csrf_token:
            chapters = self._get_chapters_via_api(book_id)
            if chapters:
                print(f"webnovel API: получено {len(chapters)} глав")
                return chapters

        # 2. HTML фолбэк (книга, каталог, мобильная)
        chapters = self._get_chapters_via_html(url, book_id)
        if chapters:
            return chapters

        # 3. DrissionPage браузер
        if HAS_DRISSION:
            print("webnovel: HTTP не сработал, пробую через браузер...")
            chapters = self._get_chapters_via_browser(url, book_id)
            if chapters:
                return chapters
        else:
            print(
                "\n[!] webnovel.com блокирует HTTP-запросы (CloudFlare).\n"
                "    Установите DrissionPage для обхода через браузер:\n"
                "    pip install DrissionPage --timeout 300 -i https://pypi.tuna.tsinghua.edu.cn/simple\n"
            )

        return []

    def _get_chapters_via_api(self, book_id: str) -> List[dict]:
        """Получает список глав через REST API."""
        data = self._api_get("chapter/get-chapter-list", {
            "bookId": book_id,
            "pageIndex": "0",
        })
        if not data:
            # Старый эндпоинт
            data = self._api_get("chapter/GetChapterList", {"bookId": book_id})
        if not data:
            return []

        chapters: List[dict] = []
        volume_items = data.get("volumeItems") or data.get("volumes") or []

        if not volume_items:
            # Может быть плоский список
            chapter_items = data.get("chapterItems") or data.get("chapters") or []
            volume_items = [{"volumeIndex": "1", "chapterItems": chapter_items}]

        for vol in volume_items:
            vol_idx = str(vol.get("volumeIndex") or vol.get("index") or "1")
            ch_items = vol.get("chapterItems") or vol.get("chapters") or []

            for ch in ch_items:
                cid = str(
                    ch.get("id")
                    or ch.get("chapterId")
                    or ch.get("cId")
                    or ""
                )
                name = (
                    ch.get("name")
                    or ch.get("chapterName")
                    or ch.get("cN")
                    or f"Chapter {cid}"
                )
                idx = ch.get("chapterIndex") or ch.get("index") or len(chapters) + 1
                is_auth = ch.get("isAuth", 1)
                is_vip = ch.get("isVip", 0)

                chapters.append({
                    "number": str(idx),
                    "name": str(name),
                    "url": f"{self.BASE}/book/{book_id}/{cid}",
                    "volume": vol_idx,
                    "chapter_id": cid,
                    "book_id": book_id,
                    "is_locked": is_auth == 0 or is_vip == 1,
                })

        return chapters

    def _get_chapters_via_html(self, url: str, book_id: str) -> List[dict]:
        """Фолбэк: HTML-парсинг."""
        targets = [url]
        if book_id:
            targets.append(f"{self.BASE}/book/{book_id}/catalog")
            targets.append(f"{self.MOBILE_BASE}/book/{book_id}")
            targets.append(f"{self.MOBILE_BASE}/book/{book_id}/catalog")

        for target_url in targets:
            soup = self._get_soup(target_url)
            chapters = self._try_extract_chapters(soup, book_id)
            if chapters:
                return chapters

        return []

    def _get_chapters_via_browser(self, url: str, book_id: str) -> List[dict]:
        """Фолбэк: DrissionPage браузер."""
        targets = [url]
        if book_id:
            targets.append(f"{self.BASE}/book/{book_id}/catalog")

        for target_url in targets:
            html = self._fetch_browser(target_url)
            if html:
                soup = BeautifulSoup(html, "html.parser")

                # Пытаемся извлечь CSRF из браузерного HTML
                if not self._csrf_token:
                    data = self._parse_next_data(soup)
                    token = self._walk_for_key(data, ("csrfToken", "_csrfToken"))
                    if token:
                        self._csrf_token = token
                        chapters = self._get_chapters_via_api(book_id)
                        if chapters:
                            return chapters

                chapters = self._try_extract_chapters(soup, book_id)
                if chapters:
                    return chapters

        return []

    def _try_extract_chapters(self, soup: Optional[BeautifulSoup], book_id: str) -> List[dict]:
        if not soup:
            return []
        chapters = self._extract_chapters_from_soup(soup, book_id)
        if chapters:
            return chapters
        data = self._parse_next_data(soup)
        if data:
            return self._extract_chapters_from_json(data, book_id)
        return []

    def _extract_chapters_from_soup(self, soup: BeautifulSoup, book_id: str) -> List[dict]:
        chapters: List[dict] = []
        seen = set()

        for a in soup.select("a[href]"):
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if not href or not text:
                continue
            if not re.search(r"/book/.*?/\d+|/chapter", href):
                continue
            full_url = urljoin(self.BASE, href)
            if full_url in seen:
                continue
            seen.add(full_url)

            ch_match = re.search(r"(?:chapter|ch\.?)\s*(\d+)", text, re.IGNORECASE)
            idx_match = re.search(r"^(\d+)\.\s*", text)
            ch_number = (ch_match and ch_match.group(1)) or (idx_match and idx_match.group(1)) or str(len(chapters) + 1)

            name = re.sub(
                r"^\s*(?:\d+\.\s*)?(?:chapter|ch\.?)\s*\d+[\s:.\-–—]*",
                "", text, flags=re.IGNORECASE,
            ).strip() or text

            chapter_id = self._extract_chapter_id(full_url)

            chapters.append({
                "number": ch_number,
                "name": name,
                "url": full_url,
                "volume": "1",
                "chapter_id": chapter_id or "",
                "book_id": book_id,
            })

        return chapters

    def _extract_chapters_from_json(self, data: dict, book_id: str) -> List[dict]:
        chapters: List[dict] = []

        def walk(obj, volume="1"):
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict) and any(
                        k in item for k in ("chapterId", "id", "cId", "chapter_id")
                    ):
                        cid = str(
                            item.get("chapterId")
                            or item.get("chapter_id")
                            or item.get("cId")
                            or item.get("id")
                            or ""
                        )
                        name = (
                            item.get("chapterName")
                            or item.get("chapter_name")
                            or item.get("cN")
                            or item.get("name")
                            or f"Chapter {cid}"
                        )
                        idx = item.get("chapterIndex") or item.get("index") or len(chapters) + 1
                        chapters.append({
                            "number": str(idx),
                            "name": str(name),
                            "url": f"{self.BASE}/book/{book_id}/{cid}",
                            "volume": str(volume),
                            "chapter_id": cid,
                            "book_id": book_id,
                        })
                    else:
                        walk(item, volume)
            elif isinstance(obj, dict):
                vol = obj.get("volumeId") or obj.get("volumeIndex") or volume
                for v in obj.values():
                    walk(v, vol)

        walk(data)
        return chapters

    # --- chapter text -----------------------------------------------------

    def get_chapter_text(self, chapter_url: str) -> str:
        time.sleep(0.8)

        book_id = self._extract_book_id(chapter_url)
        chapter_id = self._extract_chapter_id(chapter_url)

        # Из данных главы (переданных через chapter dict)
        # chapter_url может содержать book_id и chapter_id

        # 1. REST API
        if book_id and chapter_id and self._csrf_token:
            text = self._get_text_via_api(book_id, chapter_id)
            if text:
                return text

        # 2. HTML
        soup = self._get_soup(chapter_url)
        text = self._try_extract_text(soup)
        if text:
            return text

        # 3. Мобильная
        if book_id and chapter_id:
            mobile_url = f"{self.MOBILE_BASE}/book/{book_id}/{chapter_id}"
            soup = self._get_soup(mobile_url)
            text = self._try_extract_text(soup)
            if text:
                return text

        # 4. Браузер
        if HAS_DRISSION:
            html = self._fetch_browser(chapter_url)
            if html:
                soup = BeautifulSoup(html, "html.parser")
                text = self._try_extract_text(soup)
                if text:
                    return text

        return ""

    def _get_text_via_api(self, book_id: str, chapter_id: str) -> str:
        """Получает текст главы через REST API."""
        data = self._api_get("chapter/getContent", {
            "bookId": book_id,
            "chapterId": chapter_id,
            "encryptType": "3",
            "_fsae": "0",
        })
        if not data:
            return ""

        chapter_info = data.get("chapterInfo", {})

        # contents — массив абзацев
        contents = chapter_info.get("contents") or []
        if contents and isinstance(contents, list):
            paragraphs = []
            for item in contents:
                if isinstance(item, dict):
                    raw = item.get("content", "")
                elif isinstance(item, str):
                    raw = item
                else:
                    continue

                if "<" in raw and ">" in raw:
                    inner = BeautifulSoup(raw, "html.parser")
                    text = inner.get_text(" ", strip=True)
                else:
                    text = raw.strip()

                if text and len(text) > 1:
                    paragraphs.append(text)

            if paragraphs:
                return "\n".join(paragraphs)

        # content — единая строка
        raw_content = chapter_info.get("content", "")
        if raw_content:
            if "<" in raw_content and ">" in raw_content:
                inner = BeautifulSoup(raw_content, "html.parser")
                paragraphs = [
                    p.get_text(" ", strip=True)
                    for p in inner.find_all("p")
                    if p.get_text(strip=True)
                ]
                if paragraphs:
                    return "\n".join(paragraphs)
                return inner.get_text("\n", strip=True)
            return raw_content

        return ""

    def _try_extract_text(self, soup: Optional[BeautifulSoup]) -> str:
        if not soup:
            return ""
        text = self._extract_text_from_soup(soup)
        if text.strip():
            return text
        return self._extract_text_from_json(soup)

    def _extract_text_from_soup(self, soup: BeautifulSoup) -> str:
        selectors = [
            ".cha-words",
            ".cha-content",
            ".chapter_content",
            ".chapter-content",
            ".read-content",
            ".j_contentWrap",
            "#chapterContent",
            "article",
            "main",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            for tag in node.find_all(["script", "style", "img", "noscript", "iframe", "button"]):
                tag.decompose()
            for ad in node.find_all(class_=re.compile(r"ad|banner|promo|piracy|lock|pay", re.I)):
                ad.decompose()

            paragraphs = [
                p.get_text(" ", strip=True)
                for p in node.find_all("p")
                if p.get_text(strip=True) and len(p.get_text(strip=True)) > 1
            ]
            if paragraphs:
                return "\n".join(paragraphs)

            text = node.get_text("\n", strip=True)
            lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 1]
            if lines:
                return "\n".join(lines)
        return ""

    def _extract_text_from_json(self, soup: BeautifulSoup) -> str:
        data = self._parse_next_data(soup)
        if not data:
            return ""

        raw = self._walk_for_key(data, ("content", "chapterContent", "chapter_content", "contents"))
        if not raw:
            return ""

        if "<" in raw and ">" in raw:
            inner = BeautifulSoup(raw, "html.parser")
            paragraphs = [p.get_text(" ", strip=True) for p in inner.find_all("p") if p.get_text(strip=True)]
            return "\n".join(paragraphs) if paragraphs else inner.get_text("\n", strip=True)

        return raw
