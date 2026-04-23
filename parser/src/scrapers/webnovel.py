"""
Скрапер для webnovel.com.

URL-паттерны:
- Книга:   https://www.webnovel.com/book/{slug}_{bookId}
- Глава:   https://www.webnovel.com/book/{bookId}/{chapterId}
           или /book/{slug}_{bookId}/{num}.-{slug}_{chapterId}
- Мобильная: https://m.webnovel.com/book/{bookId}

Для обхода CloudFlare используется curl_cffi (TLS-имитация Chrome).
"""

import json
import re
import time
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper

try:
    from curl_cffi import requests as cffi_requests  # type: ignore
    HAS_CURL_CFFI = True
except Exception:
    HAS_CURL_CFFI = False


class WebnovelScraper(BaseScraper):
    """Скрапер для webnovel.com."""

    BASE = "https://www.webnovel.com"
    MOBILE_BASE = "https://m.webnovel.com"

    def _setup_headers(self):
        self.session.headers.update({
            "Referer": "https://www.webnovel.com/",
            "Origin": "https://www.webnovel.com",
        })

    # --- helpers --------------------------------------------------------

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

    # --- book info ------------------------------------------------------

    def get_book_info(self, url: str) -> dict:
        book_id = self._extract_book_id(url)
        soup = self._get_soup(url)
        title = None

        if soup:
            og = soup.find("meta", {"property": "og:title"})
            if og and og.get("content"):
                title = og["content"].strip()

            if not title:
                for sel in ("h1", "h2", ".g_book_name", "title"):
                    tag = soup.select_one(sel)
                    if tag:
                        text = tag.get_text(strip=True)
                        if text and len(text) > 1:
                            title = text
                            break

            if title:
                title = re.sub(
                    r"\s*[\|\-–—]\s*(WebNovel|Webnovel|webnovel).*$", "", title
                )

            # Попробуем __NEXT_DATA__
            if not title:
                data = self._parse_next_data(soup)
                title = self._walk_for_key(data, ("bookName", "name", "title"))

        return {
            "title": title or "Без названия",
            "url": url,
            "book_id": book_id,
        }

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

    # --- chapters list --------------------------------------------------

    def _extract_chapters_from_soup(self, soup: BeautifulSoup, book_id: str) -> List[dict]:
        """Извлекает главы из HTML-ссылок на странице."""
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

            chapters.append({
                "number": ch_number,
                "name": name,
                "url": full_url,
                "volume": "1",
            })

        return chapters

    def _extract_chapters_from_json(self, data: dict, book_id: str) -> List[dict]:
        """Извлекает главы из __NEXT_DATA__ JSON."""
        chapters: List[dict] = []

        def walk(obj, volume="1"):
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict) and any(
                        k in item for k in ("chapterId", "id", "cId", "chapter_id")
                    ):
                        cid = (
                            item.get("chapterId")
                            or item.get("chapter_id")
                            or item.get("cId")
                            or item.get("id")
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
                        })
                    else:
                        walk(item, volume)
            elif isinstance(obj, dict):
                vol = obj.get("volumeId") or obj.get("volumeIndex") or volume
                for v in obj.values():
                    walk(v, vol)

        walk(data)
        return chapters

    def get_chapters_list(self, url: str) -> List[dict]:
        book_id = self._extract_book_id(url) or ""

        # 1. Страница книги
        soup = self._get_soup(url)
        if soup:
            chapters = self._extract_chapters_from_soup(soup, book_id)
            if chapters:
                return chapters
            data = self._parse_next_data(soup)
            if data:
                chapters = self._extract_chapters_from_json(data, book_id)
                if chapters:
                    return chapters

        # 2. Страница каталога
        if book_id:
            catalog_url = f"{self.BASE}/book/{book_id}/catalog"
            soup = self._get_soup(catalog_url)
            if soup:
                chapters = self._extract_chapters_from_soup(soup, book_id)
                if chapters:
                    return chapters
                data = self._parse_next_data(soup)
                if data:
                    chapters = self._extract_chapters_from_json(data, book_id)
                    if chapters:
                        return chapters

        # 3. Мобильная версия
        if book_id:
            for path in (f"/book/{book_id}", f"/book/{book_id}/catalog"):
                mobile_url = self.MOBILE_BASE + path
                soup = self._get_soup(mobile_url)
                if soup:
                    chapters = self._extract_chapters_from_soup(soup, book_id)
                    if not chapters:
                        data = self._parse_next_data(soup)
                        if data:
                            chapters = self._extract_chapters_from_json(data, book_id)
                    if chapters:
                        return chapters

        return []

    # --- chapter text ---------------------------------------------------

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

    def get_chapter_text(self, chapter_url: str) -> str:
        time.sleep(0.8)

        soup = self._get_soup(chapter_url)
        if soup:
            text = self._extract_text_from_soup(soup)
            if text.strip():
                return text
            text = self._extract_text_from_json(soup)
            if text.strip():
                return text

        # Мобильная версия
        book_id = self._extract_book_id(chapter_url)
        chapter_id = self._extract_chapter_id(chapter_url)
        if book_id and chapter_id:
            mobile_url = f"{self.MOBILE_BASE}/book/{book_id}/{chapter_id}"
            soup = self._get_soup(mobile_url)
            if soup:
                text = self._extract_text_from_soup(soup)
                if text.strip():
                    return text
                text = self._extract_text_from_json(soup)
                if text.strip():
                    return text

        return ""
