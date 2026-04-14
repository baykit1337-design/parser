"""
Скрапер для webnovel.com.

URL-паттерны:
- Книга:   https://www.webnovel.com/book/{slug}_{bookId}
- Каталог: https://www.webnovel.com/book/{bookId}/catalog
- Глава:   https://www.webnovel.com/book/{bookId}/{chapterId} (иногда со слагом)

Мобильная версия m.webnovel.com часто отдаёт меньше защиты и более простой HTML.
"""

import json
import re
import time
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base import BaseScraper, MOBILE_UA


class WebnovelScraper(BaseScraper):
    """Скрапер для webnovel.com."""

    BASE = "https://www.webnovel.com"
    MOBILE_BASE = "https://m.webnovel.com"

    def _setup_headers(self):
        super()._setup_headers()
        self.session.headers.update({
            "Referer": "https://www.webnovel.com/",
            "Origin": "https://www.webnovel.com",
        })

    # --- helpers --------------------------------------------------------

    @staticmethod
    def _extract_book_id(url: str) -> Optional[str]:
        """Извлекает bookId из URL (обычно 17+ цифр после подчёркивания)."""
        # /book/slug_1234567890
        m = re.search(r"/book/[^/]*?_(\d{8,})", url)
        if m:
            return m.group(1)
        # /book/1234567890/...
        m = re.search(r"/book/(\d{8,})(?:/|$)", url)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _extract_chapter_id(url: str) -> Optional[str]:
        """Извлекает chapterId из URL главы."""
        # /book/bookId/chapterId
        m = re.search(r"/book/\d+/(\d+)", url)
        if m:
            return m.group(1)
        # /book/bookId/slug_chapterId
        m = re.search(r"/book/[^/]+/[^/]*?_(\d{8,})", url)
        if m:
            return m.group(1)
        m = re.search(r"/chapter/(\d+)", url)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _parse_next_data(soup: BeautifulSoup) -> dict:
        """Вытаскивает JSON из <script id="__NEXT_DATA__">."""
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script or not script.string:
            return {}
        try:
            return json.loads(script.string)
        except Exception:
            return {}

    @staticmethod
    def _parse_initial_state(html: str) -> dict:
        """Вытаскивает JSON из window.__INITIAL_STATE__ = {...};."""
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;\s*</script>", html, re.DOTALL)
        if not m:
            return {}
        try:
            return json.loads(m.group(1))
        except Exception:
            return {}

    # --- book info ------------------------------------------------------

    def get_book_info(self, url: str) -> dict:
        """Получение информации о книге."""
        book_id = self._extract_book_id(url)
        soup = self._get_soup(url)
        if not soup:
            return {"title": "Без названия", "url": url, "book_id": book_id}

        title = None

        # Попытка 1: Open Graph
        og = soup.find("meta", {"property": "og:title"})
        if og and og.get("content"):
            title = og["content"].strip()

        # Попытка 2: h1 или h2
        if not title:
            for selector in ("h1.pt4", "h1", ".g_book_name", "h2"):
                tag = soup.select_one(selector)
                if tag:
                    text = tag.get_text(strip=True)
                    if text and len(text) > 1:
                        title = text
                        break

        # Попытка 3: <title>
        if not title and soup.title:
            title = re.sub(r"\s*[\|\-–—]\s*(WebNovel|Webnovel).*$", "", soup.title.get_text(strip=True))

        return {
            "title": title or "Без названия",
            "url": url,
            "book_id": book_id,
        }

    # --- chapters list --------------------------------------------------

    def _get_chapters_from_catalog_html(self, book_id: str) -> List[dict]:
        """Пробует получить список глав со страницы /catalog."""
        catalog_url = f"{self.BASE}/book/{book_id}/catalog"
        soup = self._get_soup(catalog_url)
        if not soup:
            return []

        chapters: List[dict] = []
        seen = set()

        # Варианты селекторов для списка глав в каталоге
        link_selectors = [
            "a[href*='/chapter_']",
            "a[href*='/book/'][href*='/chapter']",
            ".volume-item a, .j_catalog_list a, .chapter_item a",
            "ol li a, ul li a",
        ]

        current_volume = "1"
        # Пытаемся разбить по томам
        for vol in soup.select(".volume-item, .j_volume, .volume"):
            vol_title = vol.find(["h4", "h3", "h2"])
            if vol_title:
                vm = re.search(r"(\d+)", vol_title.get_text())
                if vm:
                    current_volume = vm.group(1)

            for a in vol.select("a[href]"):
                self._maybe_add_chapter(a, seen, chapters, current_volume)

        # Если по томам ничего не нашли, берём все ссылки
        if not chapters:
            for selector in link_selectors:
                for a in soup.select(selector):
                    self._maybe_add_chapter(a, seen, chapters, "1")
                if chapters:
                    break

        return chapters

    def _maybe_add_chapter(self, a, seen, chapters, volume):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not href or not text:
            return
        # Фильтр по похожести на ссылку главы
        if not re.search(r"/chapter|/book/\d+/\d+", href):
            return
        full_url = urljoin(self.BASE, href)
        if full_url in seen:
            return
        seen.add(full_url)

        ch_match = re.search(r"chapter\s*(\d+)", text, re.IGNORECASE)
        ch_number = ch_match.group(1) if ch_match else str(len(chapters) + 1)
        ch_name = re.sub(
            r"^\s*chapter\s*\d+[\s:.\-–—]*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip() or text

        chapters.append({
            "number": ch_number,
            "name": ch_name,
            "url": full_url,
            "volume": volume,
        })

    def _get_chapters_from_next_data(self, url: str) -> List[dict]:
        """Пробует извлечь список глав из __NEXT_DATA__ страницы книги."""
        soup = self._get_soup(url)
        if not soup:
            return []

        data = self._parse_next_data(soup)
        if not data:
            return []

        # Обход: ищем массив с объектами, у которых есть chapterId/chapterName
        chapters: List[dict] = []

        def walk(obj, volume="1"):
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict) and (
                        "chapterId" in item or "chapter_id" in item or "cId" in item
                    ):
                        cid = item.get("chapterId") or item.get("chapter_id") or item.get("cId")
                        name = (
                            item.get("chapterName")
                            or item.get("chapter_name")
                            or item.get("cN")
                            or item.get("name")
                            or f"Chapter {cid}"
                        )
                        idx = item.get("chapterIndex") or item.get("index") or len(chapters) + 1
                        book_id = self._extract_book_id(url) or ""
                        chapters.append({
                            "number": str(idx),
                            "name": str(name),
                            "url": f"{self.BASE}/book/{book_id}/{cid}",
                            "volume": str(volume),
                        })
                    else:
                        walk(item, volume)
            elif isinstance(obj, dict):
                vol = obj.get("volumeId") or obj.get("volume") or volume
                for v in obj.values():
                    walk(v, vol)

        walk(data)
        return chapters

    def _get_chapters_from_mobile(self, book_id: str) -> List[dict]:
        """Пробует мобильную версию каталога."""
        url = f"{self.MOBILE_BASE}/book/{book_id}/catalog"
        html = self._fetch_mobile(url) or self._fetch_html(url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        chapters: List[dict] = []
        seen = set()
        for a in soup.select("a[href]"):
            self._maybe_add_chapter(a, seen, chapters, "1")
        return chapters

    def get_chapters_list(self, url: str) -> List[dict]:
        """Получение списка глав с фолбэками."""
        book_id = self._extract_book_id(url)

        # 1. Страница каталога (HTML)
        if book_id:
            chapters = self._get_chapters_from_catalog_html(book_id)
            if chapters:
                return chapters

        # 2. __NEXT_DATA__ со страницы книги
        chapters = self._get_chapters_from_next_data(url)
        if chapters:
            return chapters

        # 3. Мобильная версия каталога
        if book_id:
            chapters = self._get_chapters_from_mobile(book_id)
            if chapters:
                return chapters

        return []

    # --- chapter text ---------------------------------------------------

    def _extract_text_from_soup(self, soup: BeautifulSoup) -> str:
        """Извлекает текст главы по списку селекторов."""
        selectors = [
            ".cha-words",
            ".cha-content",
            ".chapter_content",
            ".chapter-content",
            ".read-content",
            ".j_contentWrap",
            ".cha-page .cha-content",
            "#chapterContent",
            "article",
            "main",
        ]

        for selector in selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            # Убираем мусор
            for tag in node.find_all(["script", "style", "img", "noscript", "iframe", "button"]):
                tag.decompose()
            for ad in node.find_all(class_=re.compile(r"ad|banner|promo|piracy|lock|pay", re.I)):
                ad.decompose()

            paragraphs = []
            for p in node.find_all("p"):
                text = p.get_text(" ", strip=True)
                if text and len(text) > 1:
                    paragraphs.append(text)

            if paragraphs:
                return "\n".join(paragraphs)

            # fallback: текст всего контейнера
            text = node.get_text("\n", strip=True)
            lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 1]
            if lines:
                return "\n".join(lines)

        return ""

    def _extract_text_from_next_data(self, soup: BeautifulSoup) -> str:
        """Извлекает HTML-контент главы из __NEXT_DATA__."""
        data = self._parse_next_data(soup)
        if not data:
            return ""

        def walk(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    key_lower = str(key).lower()
                    if key_lower in ("content", "chaptercontent", "chapter_content", "contents"):
                        if isinstance(value, str) and len(value) > 200:
                            return value
                        if isinstance(value, list):
                            joined = "\n".join(
                                item.get("content", "")
                                for item in value
                                if isinstance(item, dict)
                            )
                            if joined.strip():
                                return joined
                    result = walk(value)
                    if result:
                        return result
            elif isinstance(obj, list):
                for item in obj:
                    result = walk(item)
                    if result:
                        return result
            return None

        raw = walk(data)
        if not raw:
            return ""

        if "<" in raw and ">" in raw:
            inner = BeautifulSoup(raw, "html.parser")
            paragraphs = [p.get_text(" ", strip=True) for p in inner.find_all("p")]
            paragraphs = [p for p in paragraphs if p and len(p) > 1]
            if paragraphs:
                return "\n".join(paragraphs)
            return inner.get_text("\n", strip=True)

        return raw

    def _extract_text_from_mobile(self, url: str) -> str:
        """Фолбэк через мобильную версию страницы главы."""
        book_id = self._extract_book_id(url)
        chapter_id = self._extract_chapter_id(url)
        if not book_id or not chapter_id:
            return ""

        mobile_url = f"{self.MOBILE_BASE}/book/{book_id}/{chapter_id}"
        html = self._fetch_mobile(mobile_url) or self._fetch_html(mobile_url)
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")
        text = self._extract_text_from_soup(soup)
        if text:
            return text
        return self._extract_text_from_next_data(soup)

    def get_chapter_text(self, chapter_url: str) -> str:
        """Получение текста главы с цепочкой фолбэков."""
        time.sleep(0.8)

        soup = self._get_soup(chapter_url)
        if soup:
            text = self._extract_text_from_soup(soup)
            if text.strip():
                return text

            text = self._extract_text_from_next_data(soup)
            if text.strip():
                return text

        # Фолбэк через мобильную версию
        return self._extract_text_from_mobile(chapter_url)
