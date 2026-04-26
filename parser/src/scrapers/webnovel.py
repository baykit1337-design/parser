"""
Скрапер для webnovel.com.

Сайт защищён CloudFlare + доступен только через VPN.
HTTP-запросы (curl_cffi, requests) не проходят — используем Chrome
пользователя через DrissionPage для всех операций.

URL-паттерны:
- Книга:   https://www.webnovel.com/book/{slug}_{bookId}
- Глава:   https://www.webnovel.com/book/{bookId}/{chapterId}
"""

import json
import re
import time
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, HAS_DRISSION


class WebnovelScraper(BaseScraper):
    """Скрапер для webnovel.com — работает через Chrome пользователя."""

    BASE = "https://www.webnovel.com"

    def _setup_headers(self):
        self.session.headers.update({
            "Referer": "https://www.webnovel.com/",
            "Origin": "https://www.webnovel.com",
        })

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
        title = None

        # Загружаем страницу (HTTP → браузер)
        soup = self._get_soup_with_browser(url)

        if soup:
            # og:title
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

            if not title:
                data = self._parse_next_data(soup)
                title = self._walk_for_key(data, ("bookName", "name", "title"))

        if title:
            title = re.sub(
                r"\s*[\|\-–—]\s*(WebNovel|Webnovel|webnovel).*$", "", title
            )

        return {
            "title": title or "Без названия",
            "url": url,
            "book_id": book_id,
        }

    # --- chapters list ----------------------------------------------------

    def get_chapters_list(self, url: str) -> List[dict]:
        book_id = self._extract_book_id(url) or ""
        if not book_id:
            print("webnovel: не удалось извлечь book_id из URL")
            return []

        # 1. Загружаем страницу книги (HTTP → браузер)
        soup = self._get_soup_with_browser(url)
        chapters = self._try_extract_chapters(soup, book_id)
        if chapters:
            print(f"webnovel: извлечено {len(chapters)} глав со страницы книги")
            return chapters

        # 2. Каталог
        catalog_url = f"{self.BASE}/book/{book_id}/catalog"
        print(f"webnovel: загружаю каталог...")
        soup = self._get_soup_with_browser(catalog_url)
        chapters = self._try_extract_chapters(soup, book_id)
        if chapters:
            print(f"webnovel: извлечено {len(chapters)} глав из каталога")
            return chapters

        if not HAS_DRISSION:
            print(
                "\n[!] webnovel.com требует браузер для загрузки.\n"
                "    Установите DrissionPage:\n"
                "    pip install DrissionPage --timeout 300 -i https://pypi.tuna.tsinghua.edu.cn/simple\n"
            )

        return []

    def _try_extract_chapters(self, soup: Optional[BeautifulSoup], book_id: str) -> List[dict]:
        if not soup:
            return []

        # Из HTML-ссылок
        chapters = self._extract_chapters_from_soup(soup, book_id)
        if chapters:
            return chapters

        # Из __NEXT_DATA__
        data = self._parse_next_data(soup)
        if data:
            chapters = self._extract_chapters_from_json(data, book_id)
            if chapters:
                return chapters

        # Из любых JSON-скриптов на странице
        for script in soup.find_all("script"):
            text = script.string or ""
            if not text or len(text) < 100:
                continue
            # Ищем JSON с массивами глав
            for json_match in re.finditer(r'\{[^{}]{50,}\}', text):
                try:
                    obj = json.loads(json_match.group())
                    chapters = self._extract_chapters_from_json(obj, book_id)
                    if chapters:
                        return chapters
                except Exception:
                    continue

        return []

    def _extract_chapters_from_soup(self, soup: BeautifulSoup, book_id: str) -> List[dict]:
        chapters: List[dict] = []
        seen = set()

        # Webnovel chapter links: /book/{bookId}/{chapterId}
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

        # Структурированные данные (volumeItems)
        volume_items = None
        if isinstance(data, dict):
            volume_items = (
                data.get("volumeItems")
                or data.get("volumes")
                or data.get("data", {}).get("volumeItems") if isinstance(data.get("data"), dict) else None
            )

        if volume_items and isinstance(volume_items, list):
            for vol in volume_items:
                if not isinstance(vol, dict):
                    continue
                vol_idx = str(vol.get("volumeIndex") or vol.get("index") or "1")
                ch_items = vol.get("chapterItems") or vol.get("chapters") or []
                for ch in ch_items:
                    if not isinstance(ch, dict):
                        continue
                    cid = str(ch.get("id") or ch.get("chapterId") or ch.get("cId") or "")
                    name = (ch.get("name") or ch.get("chapterName") or ch.get("cN") or f"Chapter {cid}")
                    idx = ch.get("chapterIndex") or ch.get("index") or len(chapters) + 1
                    chapters.append({
                        "number": str(idx),
                        "name": str(name),
                        "url": f"{self.BASE}/book/{book_id}/{cid}",
                        "volume": vol_idx,
                        "chapter_id": cid,
                        "book_id": book_id,
                    })
            if chapters:
                return chapters

        # Рекурсивный поиск
        def walk(obj, volume="1"):
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict) and any(
                        k in item for k in ("chapterId", "id", "cId", "chapter_id")
                    ):
                        cid = str(
                            item.get("chapterId") or item.get("chapter_id")
                            or item.get("cId") or item.get("id") or ""
                        )
                        name = (
                            item.get("chapterName") or item.get("chapter_name")
                            or item.get("cN") or item.get("name") or f"Chapter {cid}"
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

        # HTTP → браузер
        soup = self._get_soup_with_browser(chapter_url)
        text = self._try_extract_text(soup)
        if text:
            return text

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
