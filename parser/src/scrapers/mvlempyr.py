"""
Скрапер для mvlempyr.io (My Virtual Library Empire).

URL-паттерны:
- Книга:    https://www.mvlempyr.io/novel/{slug}
- Глава:    https://www.mvlempyr.io/chapter/{book_id}-{chapter_number}

Известные CSS-селекторы (из сообщества WebToEpub/LNReader):
- Контент главы: #chapter (основной), #chapter-content (резерв)
- Заголовок:     h1 на странице главы
- Список глав:   ссылки на странице книги с href="/chapter/..."
"""

import json
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base import BaseScraper


class MvlempyrScraper(BaseScraper):
    """Скрапер для mvlempyr.io."""

    BASE = "https://www.mvlempyr.io"

    # --- helpers --------------------------------------------------------

    def _get_base_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.hostname:
            return f"{parsed.scheme or 'https'}://{parsed.hostname}"
        return self.BASE

    def _extract_slug(self, url: str) -> Optional[str]:
        match = re.search(r"/novel/([^/?#]+)", url)
        return match.group(1) if match else None

    def _is_chapter_href(self, href: str) -> bool:
        """Ссылка вида /chapter/5663-1."""
        return bool(re.search(r"/chapter/\d+-\d+(?:[/?#]|$)", href))

    @staticmethod
    def _chapter_key(href: str):
        """Ключ сортировки по числу главы (последнее число в пути)."""
        match = re.search(r"/chapter/(\d+)-(\d+)", href)
        if not match:
            return (0, 0)
        return (int(match.group(1)), int(match.group(2)))

    @staticmethod
    def _clean_title(text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # --- public API -----------------------------------------------------

    def get_book_info(self, url: str) -> dict:
        """Получение информации о книге."""
        soup = self._get_soup(url)
        if not soup:
            return {"title": "Без названия", "url": url}

        title = None
        for selector in ("h1", ".novel-title", ".entry-title", "title"):
            tag = soup.select_one(selector)
            if tag:
                text = self._clean_title(tag.get_text())
                if text and len(text) > 2:
                    title = text
                    break

        # Обрезать хвост " | MVLEMPYR" из <title>
        if title:
            title = re.sub(r"\s*[\|\-–—]\s*MVLEMPYR.*$", "", title, flags=re.IGNORECASE)

        return {
            "title": title or "Без названия",
            "url": url,
            "slug": self._extract_slug(url),
        }

    def get_chapters_list(self, url: str) -> List[dict]:
        """Получение списка глав со страницы книги."""
        soup = self._get_soup(url)
        if not soup:
            return []

        base = self._get_base_url(url)

        # Собираем все ссылки вида /chapter/{id}-{num}
        raw_links = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            if not self._is_chapter_href(href):
                continue
            full_url = urljoin(base, href)
            text = self._clean_title(a.get_text())
            raw_links.append((full_url, text))

        # Удаляем дубликаты, сохраняя первый встретившийся текст
        seen = {}
        for full_url, text in raw_links:
            if full_url not in seen:
                seen[full_url] = text

        # Сортируем по номеру главы (последнее число в URL)
        sorted_urls = sorted(seen.keys(), key=self._chapter_key)

        chapters = []
        for i, full_url in enumerate(sorted_urls, start=1):
            text = seen[full_url] or ""

            # Пытаемся извлечь номер главы из URL
            m = re.search(r"/chapter/\d+-(\d+)", full_url)
            ch_number = m.group(1) if m else str(i)

            # Имя главы из текста ссылки, без префикса "Chapter N"
            name = re.sub(
                r"^\s*(?:chapter|ch\.?|глава)\s*\d+[\s:.\-–—]*",
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()

            chapters.append({
                "number": ch_number,
                "name": name or text or f"Chapter {ch_number}",
                "url": full_url,
                "volume": "1",
            })

        return chapters

    # --- chapter content ------------------------------------------------

    def _extract_content_div(self, soup: BeautifulSoup):
        """Находит элемент с текстом главы."""
        # Приоритетные селекторы для mvlempyr
        selectors = [
            "#chapter",
            "#chapter-content",
            "div[id='chapter']",
            "div[id^='chapter-']",
            ".chapter-content",
            ".entry-content",
            ".reading-content",
            ".post-content",
            "article .content",
            "article",
            "main",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if node and len(node.get_text(strip=True)) > 100:
                return node
        return None

    def _extract_from_next_data(self, soup: BeautifulSoup) -> str:
        """Попытка извлечь текст главы из __NEXT_DATA__ (Next.js)."""
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script or not script.string:
            return ""
        try:
            data = json.loads(script.string)
        except Exception:
            return ""

        # Рекурсивный поиск поля с HTML-контентом главы
        def walk(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    key_lower = str(key).lower()
                    if key_lower in ("content", "html", "body", "chaptercontent", "chapter_content"):
                        if isinstance(value, str) and len(value) > 200:
                            return value
                    result = walk(value)
                    if result:
                        return result
            elif isinstance(obj, list):
                for item in obj:
                    result = walk(item)
                    if result:
                        return result
            return None

        html = walk(data)
        if not html:
            return ""

        inner = BeautifulSoup(html, "html.parser")
        return self._node_to_text(inner)

    @staticmethod
    def _node_to_text(node) -> str:
        # Удаляем служебные элементы
        for tag in node.find_all(["script", "style", "img", "noscript", "iframe", "nav", "button"]):
            tag.decompose()
        for ad in node.find_all(class_=re.compile(r"ad|banner|promo|share|social", re.I)):
            ad.decompose()

        paragraphs = []
        for p in node.find_all(["p", "div"]):
            # Пропускаем контейнеры, содержащие другие параграфы
            if p.find("p") or p.find("div"):
                continue
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

    def get_chapter_text(self, chapter_url: str) -> str:
        """Получение текста одной главы."""
        soup = self._get_soup(chapter_url)
        if not soup:
            return ""

        content_div = self._extract_content_div(soup)
        if content_div:
            text = self._node_to_text(content_div)
            if text.strip():
                return text

        # Фолбэк: вытащить из __NEXT_DATA__
        text = self._extract_from_next_data(soup)
        if text.strip():
            return text

        return ""
