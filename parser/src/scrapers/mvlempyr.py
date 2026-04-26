"""
Скрапер для mvlempyr.io (My Virtual Library Empire).

URL-паттерны:
- Книга:  https://www.mvlempyr.io/novel/{slug}
- Глава:  https://www.mvlempyr.io/chapter/{book_id}-{chapter_number}

Список глав на странице рендерится JavaScript'ом. Стратегия:
1. Найти book_id из HTML (скрипты, мета-теги, ссылки, data-атрибуты)
2. Определить кол-во глав пробингом GET-запросами (бинарный поиск)
3. Сгенерировать URL-ы /chapter/{id}-1 … /chapter/{id}-N
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
        """Ищет book_id из HTML всеми доступными способами."""

        # 1. Ссылки <a href="..."> с /chapter/{id}-{num}
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            m = re.search(r"/chapter/(\d+)-\d+", href)
            if m:
                print(f"mvlempyr: book_id найден в ссылке: {href}")
                return int(m.group(1))

        # 2. Любые URL с /chapter/{id}-{num} в тексте скриптов
        for script in soup.find_all("script"):
            text = script.string or ""
            if not text:
                # Попробуем взять содержимое через .text
                text = script.get_text() or ""
            m = re.search(r"/chapter/(\d{3,})-\d+", text)
            if m:
                print(f"mvlempyr: book_id найден в <script>")
                return int(m.group(1))

        # 3. JSON внутри __NEXT_DATA__
        next_data = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_data and next_data.string:
            try:
                data = json.loads(next_data.string)
                bid = self._walk_json_for_book_id(data)
                if bid:
                    print(f"mvlempyr: book_id из __NEXT_DATA__: {bid}")
                    return bid
            except Exception:
                pass

        # 4. Любой JSON в <script type="application/json"> или <script type="application/ld+json">
        for script in soup.find_all("script", {"type": re.compile(r"application/(json|ld\+json)")}):
            text = script.string or ""
            try:
                data = json.loads(text)
                bid = self._walk_json_for_book_id(data)
                if bid:
                    print(f"mvlempyr: book_id из JSON script: {bid}")
                    return bid
            except Exception:
                pass

        # 5. data-* атрибуты с числами (4+ цифр)
        for tag in soup.find_all(attrs={"data-id": True}):
            val = tag.get("data-id", "")
            if val.isdigit() and len(val) >= 3:
                print(f"mvlempyr: book_id из data-id: {val}")
                return int(val)
        for tag in soup.find_all(attrs={"data-novel-id": True}):
            val = tag.get("data-novel-id", "")
            if val.isdigit():
                print(f"mvlempyr: book_id из data-novel-id: {val}")
                return int(val)

        # 6. Мета-теги
        for meta in soup.find_all("meta"):
            content = meta.get("content", "")
            m = re.search(r"/chapter/(\d{3,})-\d+", content)
            if m:
                print(f"mvlempyr: book_id из meta: {content}")
                return int(m.group(1))

        # 7. Канонический URL
        canonical = soup.find("link", {"rel": "canonical"})
        if canonical:
            href = canonical.get("href", "")
            m = re.search(r"/chapter/(\d{3,})-\d+", href)
            if m:
                return int(m.group(1))

        # 8. Поиск паттерна "novel_id": N или "bookId": N в любом тексте скриптов
        for script in soup.find_all("script"):
            text = script.string or script.get_text() or ""
            for pattern in [
                r'"(?:novel_id|novelId|book_id|bookId|story_id|storyId|nid)"\s*:\s*(\d{3,})',
                r"(?:novel_id|novelId|book_id|bookId|story_id|storyId|nid)\s*=\s*(\d{3,})",
                r"'(?:novel_id|novelId|book_id|bookId|story_id|storyId|nid)'\s*:\s*(\d{3,})",
            ]:
                m = re.search(pattern, text)
                if m:
                    print(f"mvlempyr: book_id из JS переменной: {m.group(1)}")
                    return int(m.group(1))

        # 9. Ссылки на chap.mvlempyr.space (альтернативный домен)
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            m = re.search(r"chap\.mvlempyr\.\w+/chapter/(\d+)-\d+", href)
            if m:
                print(f"mvlempyr: book_id из chap.mvlempyr ссылки: {m.group(1)}")
                return int(m.group(1))

        # Диагностика: вывести все найденные ссылки для отладки
        all_links = [a.get("href", "") for a in soup.select("a[href]")]
        chapter_links = [l for l in all_links if "chapter" in l.lower()]
        if chapter_links:
            print(f"mvlempyr: найдены ссылки с 'chapter': {chapter_links[:5]}")
        else:
            print(f"mvlempyr: ссылок с 'chapter' не найдено. Всего ссылок: {len(all_links)}")
            if all_links:
                print(f"mvlempyr: примеры ссылок: {all_links[:10]}")

        return None

    @staticmethod
    def _walk_json_for_book_id(obj, depth=10):
        """Рекурсивно ищет book_id в JSON."""
        if depth <= 0:
            return None
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_lower = str(key).lower()
                if key_lower in ("novel_id", "novelid", "book_id", "bookid",
                                 "story_id", "storyid", "nid", "id"):
                    if isinstance(value, (int, float)) and value > 100:
                        return int(value)
                    if isinstance(value, str) and value.isdigit() and len(value) >= 3:
                        return int(value)
                if isinstance(value, str):
                    m = re.search(r"/chapter/(\d{3,})-\d+", value)
                    if m:
                        return int(m.group(1))
                result = MvlempyrScraper._walk_json_for_book_id(value, depth - 1)
                if result:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = MvlempyrScraper._walk_json_for_book_id(item, depth - 1)
                if result:
                    return result
        return None

    def _chapter_accessible(self, book_id: int, num: int) -> bool:
        """Проверяет существует ли глава (тихо, без сообщений об ошибках)."""
        url = f"{self.BASE}/chapter/{book_id}-{num}"
        return self._probe_url(url)

    def _find_max_chapter(self, book_id: int, known_num: int = 1) -> int:
        """Бинарным поиском находит последнюю доступную главу."""
        # Проверяем что первая глава вообще существует
        if not self._chapter_accessible(book_id, 1):
            print(f"mvlempyr: глава {book_id}-1 недоступна")
            return 0

        # Экспоненциально ищем верхнюю границу
        hi = max(known_num, 1)
        while hi <= 10000:
            if self._chapter_accessible(book_id, hi):
                hi *= 2
                time.sleep(0.2)
            else:
                break

        # Бинарный поиск
        lo = max(hi // 2, 1)
        hi = min(hi, 10000)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            time.sleep(0.2)
            if self._chapter_accessible(book_id, mid):
                lo = mid
            else:
                hi = mid - 1

        return lo

    # --- public API -----------------------------------------------------

    @staticmethod
    def _extract_slug(url: str) -> Optional[str]:
        """Извлекает slug из URL /novel/{slug}."""
        m = re.search(r"/novel/([a-z0-9\-]+)", url, re.IGNORECASE)
        return m.group(1) if m else None

    def _title_from_slug(self, slug: str) -> str:
        """Превращает slug в читаемое название."""
        return slug.replace("-", " ").title()

    def _get_book_id_with_fallbacks(self, url: str) -> Optional[int]:
        """Ищет book_id всеми способами."""
        book_id, ch_num = self._parse_chapter_url(url)
        if book_id:
            return book_id

        # 1. HTTP — загрузить страницу книги
        soup = self._get_soup(url, retries=1, delay=1)
        if soup:
            book_id = self._find_book_id_from_page(soup)
            if book_id:
                return book_id

        # 2. Браузер — загрузить страницу через Chrome пользователя
        from .base import HAS_DRISSION
        if HAS_DRISSION:
            print("mvlempyr: HTTP не работает, пробую через браузер...")
            html = self._fetch_browser(url)
            if html:
                soup = BeautifulSoup(html, "html.parser")
                book_id = self._find_book_id_from_page(soup)
                if book_id:
                    return book_id

        # 3. Брутфорс — пробуем популярные id (последние книги имеют id 6000-9000)
        slug = self._extract_slug(url)
        if slug:
            print(f"mvlempyr: пробую подобрать book_id для '{slug}'...")
            book_id = self._bruteforce_book_id(slug)
            if book_id:
                return book_id

        return None

    def _bruteforce_book_id(self, slug: str) -> Optional[int]:
        """Пробует загрузить первую главу с разными book_id,
        проверяя что slug совпадает с названием в HTML."""
        # Пробуем загрузить страницу /chapter/{id}-1 для нескольких id
        # mvlempyr перенаправляет или показывает slug в HTML
        # Диапазон последних книг: примерно 5000-9000
        for test_id in range(9000, 4000, -50):
            url = f"{self.BASE}/chapter/{test_id}-1"
            html = self._fetch_html(url, retries=1, delay=0, silent=True)
            if html and len(html) > 500:
                if slug.replace("-", " ").lower() in html.lower():
                    print(f"mvlempyr: book_id={test_id} соответствует slug '{slug}'")
                    return test_id
            time.sleep(0.1)
        return None

    def get_book_info(self, url: str) -> dict:
        book_id, ch_num = self._parse_chapter_url(url)

        title = None
        soup = None

        # Попробуем загрузить страницу
        soup = self._get_soup(url, retries=1, delay=1)
        if not soup:
            from .base import HAS_DRISSION
            if HAS_DRISSION:
                html = self._fetch_browser(url)
                if html:
                    soup = BeautifulSoup(html, "html.parser")

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

        # Если book_id не нашли через HTML — используем фолбэки
        if not book_id:
            book_id = self._get_book_id_with_fallbacks(url)

        # Если title не нашли — из slug
        if not title:
            slug = self._extract_slug(url)
            if slug:
                title = self._title_from_slug(slug)

        # Если есть book_id но нет title — из первой главы
        if not title and book_id:
            ch_soup = self._get_soup(f"{self.BASE}/chapter/{book_id}-1", retries=1, delay=1)
            if ch_soup:
                tag = ch_soup.select_one("h1, title")
                if tag:
                    title = re.sub(r"\s+", " ", tag.get_text()).strip()
                    title = re.sub(r"\s*[\|\-–—]\s*MVLEMPYR.*$", "", title, flags=re.IGNORECASE)
                    title = re.sub(r"\s*-?\s*Chapter\s*\d+.*$", "", title, flags=re.IGNORECASE).strip()

        return {
            "title": title or "Без названия",
            "url": url,
            "book_id": book_id,
        }

    def get_chapters_list(self, url: str) -> List[dict]:
        book_id, ch_num = self._parse_chapter_url(url)

        if not book_id:
            book_id = self._get_book_id_with_fallbacks(url)

        if not book_id:
            print("mvlempyr: не удалось определить book_id")
            return []

        print(f"mvlempyr: book_id = {book_id}, начинаем поиск глав...")

        max_ch = self._find_max_chapter(book_id, ch_num or 1)

        if max_ch < 1:
            print(f"mvlempyr: не удалось найти доступные главы для book_id={book_id}")
            return []

        print(f"mvlempyr: найдено {max_ch} глав")

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

    def get_chapter_text(self, chapter_url: str) -> str:
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
