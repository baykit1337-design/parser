"""
Скрапер для mvlempyr.io (My Virtual Library Empire).

URL-паттерны:
- Книга:  https://www.mvlempyr.io/novel/{slug}
- Глава:  https://www.mvlempyr.io/chapter/{book_id}-{chapter_number}

Список глав на странице книги рендерится JavaScript'ом и недоступен
через простой HTTP-запрос. Поэтому используется стратегия:
1. Найти book_id из любой ссылки /chapter/{id}-N на странице
2. Методом бинарного поиска определить кол-во глав
3. Сгенерировать список URL /chapter/{id}-1 … /chapter/{id}-N
"""

import json
import re
import time
from typing import List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .base import BaseScraper


class MvlempyrScraper(BaseScraper):
    """Скрапер для mvlempyr.io."""

    BASE = "https://www.mvlempyr.io"

    def _setup_headers(self):
        self.session.headers.update({
            "Referer": "https://www.mvlempyr.io/",
        })

    # --- helpers --------------------------------------------------------

    @staticmethod
    def _parse_chapter_url(url: str):
        """Извлекает (book_id, chapter_num) из URL /chapter/{id}-{num}."""
        m = re.search(r"/chapter/(\d+)-(\d+)", url)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None, None

    def _find_book_id_from_page(self, soup: BeautifulSoup) -> Optional[int]:
        """Ищет book_id в ссылках /chapter/{id}-{num} на странице."""
        for a in soup.select("a[href*='/chapter/']"):
            href = a.get("href", "")
            bid, _ = self._parse_chapter_url(href)
            if bid:
                return bid

        # Фолбэк: искать в тексте скриптов
        for script in soup.find_all("script"):
            text = script.string or ""
            m = re.search(r"/chapter/(\d+)-\d+", text)
            if m:
                return int(m.group(1))

        return None

    def _chapter_exists(self, book_id: int, num: int) -> bool:
        """Проверяет существует ли глава."""
        url = f"{self.BASE}/chapter/{book_id}-{num}"
        return self._head_ok(url)

    def _find_max_chapter(self, book_id: int, known_num: int = 1) -> int:
        """Бинарным поиском находит последнюю доступную главу."""
        # Сначала экспоненциально ищем верхнюю границу
        hi = max(known_num, 1)
        while hi <= 10000 and self._chapter_exists(book_id, hi):
            hi *= 2
            time.sleep(0.1)

        # Бинарный поиск между hi//2 и hi
        lo = max(hi // 2, 1)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            time.sleep(0.1)
            if self._chapter_exists(book_id, mid):
                lo = mid
            else:
                hi = mid - 1

        return lo

    # --- public API -----------------------------------------------------

    def get_book_info(self, url: str) -> dict:
        """Получение информации о книге."""
        book_id, ch_num = self._parse_chapter_url(url)

        soup = self._get_soup(url)
        title = None

        if soup:
            for sel in ("h1", ".novel-title", ".entry-title", "title"):
                tag = soup.select_one(sel)
                if tag:
                    text = re.sub(r"\s+", " ", tag.get_text()).strip()
                    if text and len(text) > 2:
                        title = text
                        break
            if title:
                title = re.sub(r"\s*[\|\-–—]\s*MVLEMPYR.*$", "", title, flags=re.IGNORECASE)

            if not book_id:
                book_id = self._find_book_id_from_page(soup)

        return {
            "title": title or "Без названия",
            "url": url,
            "book_id": book_id,
        }

    def get_chapters_list(self, url: str) -> List[dict]:
        """Получение списка глав."""
        book_id, ch_num = self._parse_chapter_url(url)

        if not book_id:
            # Это URL книги — загружаем страницу и ищем book_id
            soup = self._get_soup(url)
            if soup:
                book_id = self._find_book_id_from_page(soup)

        if not book_id:
            print("mvlempyr: не удалось определить book_id")
            return []

        # Определяем количество глав бинарным поиском
        start_num = ch_num or 1
        max_ch = self._find_max_chapter(book_id, start_num)

        if max_ch < 1:
            return []

        chapters = []
        for i in range(1, max_ch + 1):
            chapters.append({
                "number": str(i),
                "name": f"Chapter {i}",
                "url": f"{self.BASE}/chapter/{book_id}-{i}",
                "volume": "1",
            })

        return chapters

    # --- chapter content ------------------------------------------------

    @staticmethod
    def _node_to_text(node) -> str:
        for tag in node.find_all(["script", "style", "img", "noscript", "iframe", "nav", "button"]):
            tag.decompose()
        for ad in node.find_all(class_=re.compile(r"ad|banner|promo|share|social", re.I)):
            ad.decompose()

        paragraphs = []
        for p in node.find_all("p"):
            text = p.get_text(" ", strip=True)
            if text and len(text) > 1:
                paragraphs.append(text)

        if not paragraphs:
            text = node.get_text("\n", strip=True)
            for line in text.splitlines():
                line = line.strip()
                if line and len(line) > 1:
                    paragraphs.append(line)

        return "\n".join(paragraphs)

    def _extract_chapter_title(self, soup: BeautifulSoup) -> str:
        """Извлекает название главы со страницы."""
        for sel in ("h1", ".chapter-title", "#chapter-title", "h2"):
            tag = soup.select_one(sel)
            if tag:
                text = tag.get_text(strip=True)
                if text and len(text) > 1:
                    return text
        return ""

    def get_chapter_text(self, chapter_url: str) -> str:
        """Получение текста одной главы."""
        time.sleep(0.3)
        soup = self._get_soup(chapter_url)
        if not soup:
            return ""

        selectors = [
            "#chapter",
            "#chapter-content",
            ".chapter-content",
            ".entry-content",
            ".reading-content",
            ".text-content",
            "article",
            "main",
        ]

        for selector in selectors:
            node = soup.select_one(selector)
            if node and len(node.get_text(strip=True)) > 100:
                text = self._node_to_text(node)
                if text.strip():
                    return text

        # Фолбэк: __NEXT_DATA__
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if script and script.string:
            try:
                data = json.loads(script.string)
                return self._walk_json_for_content(data)
            except Exception:
                pass

        return ""

    def _walk_json_for_content(self, obj) -> str:
        """Рекурсивно ищет HTML-контент главы в JSON."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if str(key).lower() in ("content", "html", "body", "chaptercontent"):
                    if isinstance(value, str) and len(value) > 200:
                        inner = BeautifulSoup(value, "html.parser")
                        return self._node_to_text(inner)
                result = self._walk_json_for_content(value)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._walk_json_for_content(item)
                if result:
                    return result
        return ""
