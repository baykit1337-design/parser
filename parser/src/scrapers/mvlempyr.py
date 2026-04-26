"""
Скрапер для mvlempyr.io (My Virtual Library Empire).

URL-паттерны:
- Книга:  https://www.mvlempyr.io/novel/{slug}
- Глава:  https://www.mvlempyr.io/chapter/{book_id}-{chapter_number}

Сайт защищён CloudFlare — HTTP-запросы не проходят.
Используем Chrome пользователя (DrissionPage) для загрузки страниц.
"""

import json
import re
import time
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper


class MvlempyrScraper(BaseScraper):
    """Скрапер для mvlempyr.io."""

    BASE = "https://www.mvlempyr.io"

    def _setup_headers(self):
        self.session.headers.update({
            "Referer": "https://www.mvlempyr.io/",
        })

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _parse_chapter_url(url: str):
        """Извлекает (book_id, chapter_num) из URL /chapter/{id}-{num}."""
        m = re.search(r"/chapter/(\d+)-(\d+)", url)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None, None

    @staticmethod
    def _extract_slug(url: str) -> Optional[str]:
        m = re.search(r"/novel/([a-z0-9\-]+)", url, re.IGNORECASE)
        return m.group(1) if m else None

    def _find_book_id_from_soup(self, soup: BeautifulSoup) -> Optional[int]:
        """Ищет book_id из HTML."""
        # Ссылки /chapter/{id}-{num}
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            m = re.search(r"/chapter/(\d+)-\d+", href)
            if m:
                return int(m.group(1))

        # Скрипты
        for script in soup.find_all("script"):
            text = script.string or script.get_text() or ""
            m = re.search(r"/chapter/(\d{3,})-\d+", text)
            if m:
                return int(m.group(1))

        # __NEXT_DATA__
        next_data = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_data and next_data.string:
            try:
                data = json.loads(next_data.string)
                bid = self._walk_json_for_book_id(data)
                if bid:
                    return bid
            except Exception:
                pass

        # JSON скрипты
        for script in soup.find_all("script", {"type": re.compile(r"application/(json|ld\+json)")}):
            text = script.string or ""
            try:
                data = json.loads(text)
                bid = self._walk_json_for_book_id(data)
                if bid:
                    return bid
            except Exception:
                pass

        # JS переменные с book/novel id
        for script in soup.find_all("script"):
            text = script.string or script.get_text() or ""
            for pattern in [
                r'"(?:novel_id|novelId|book_id|bookId|story_id|storyId|nid)"\s*:\s*(\d{3,})',
                r"(?:novel_id|novelId|book_id|bookId|story_id|storyId|nid)\s*=\s*(\d{3,})",
            ]:
                m = re.search(pattern, text)
                if m:
                    return int(m.group(1))

        return None

    @staticmethod
    def _walk_json_for_book_id(obj, depth=10):
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

    # --- chapter discovery (browser-first) --------------------------------

    def _extract_chapters_from_rendered_html(self, soup: BeautifulSoup, book_id: int) -> List[dict]:
        """Извлекает список глав из отрендеренного HTML (после JS)."""
        chapters: List[dict] = []
        seen = set()

        # a.chapter-item с data-listing-index (из скриншота пользователя)
        for item in soup.select("a.chapter-item, a[data-listing-index]"):
            href = item.get("href", "")
            idx = item.get("data-listing-index", "")
            text = item.get_text(strip=True)

            if href and "/chapter/" in href:
                full_url = urljoin(self.BASE, href)
                if full_url in seen:
                    continue
                seen.add(full_url)

                m = re.search(r"/chapter/\d+-(\d+)", href)
                ch_num = m.group(1) if m else (idx or str(len(chapters) + 1))

                chapters.append({
                    "number": str(ch_num),
                    "name": text or f"Chapter {ch_num}",
                    "url": full_url,
                    "volume": "1",
                })

        if chapters:
            return chapters

        # Любые ссылки на /chapter/{book_id}-{num}
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            m = re.search(rf"/chapter/{book_id}-(\d+)", href)
            if not m:
                continue
            full_url = urljoin(self.BASE, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            ch_num = m.group(1)
            text = a.get_text(strip=True)

            chapters.append({
                "number": ch_num,
                "name": text or f"Chapter {ch_num}",
                "url": full_url,
                "volume": "1",
            })

        return chapters

    def _find_novel_url_from_chapter(self, soup: BeautifulSoup) -> Optional[str]:
        """Находит URL страницы новеллы из страницы главы."""
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "/novel/" in href and "/chapter/" not in href:
                return urljoin(self.BASE, href)
        return None

    def _find_max_chapter_browser(self, book_id: int, known_num: int = 1) -> int:
        """Бинарным поиском через браузер находит последнюю главу."""
        print(f"mvlempyr: бинарный поиск глав через браузер (от {known_num})...")

        # Проверяем что known_num доступна
        if not self._probe_url_browser(f"{self.BASE}/chapter/{book_id}-{known_num}"):
            # Пробуем главу 1
            if known_num != 1 and self._probe_url_browser(f"{self.BASE}/chapter/{book_id}-1"):
                known_num = 1
            else:
                return 0

        # Экспоненциально ищем верхнюю границу (от known_num)
        hi = known_num
        while hi <= 10000:
            next_hi = hi * 2 if hi > known_num else known_num * 2
            if next_hi <= hi:
                next_hi = hi * 2
            if self._probe_url_browser(f"{self.BASE}/chapter/{book_id}-{next_hi}"):
                hi = next_hi
                time.sleep(0.5)
            else:
                break

        lo = hi // 2 if hi > known_num else known_num
        hi = min(hi * 2 if hi == known_num else hi, 10000)

        while lo < hi:
            mid = (lo + hi + 1) // 2
            time.sleep(0.5)
            if self._probe_url_browser(f"{self.BASE}/chapter/{book_id}-{mid}"):
                lo = mid
                print(f"  глава {mid} — есть")
            else:
                hi = mid - 1
                print(f"  глава {mid} — нет")

        print(f"mvlempyr: последняя глава = {lo}")
        return lo

    # --- public API -------------------------------------------------------

    def get_book_info(self, url: str) -> dict:
        book_id, ch_num = self._parse_chapter_url(url)

        # Загружаем страницу (HTTP → браузер)
        soup = self._get_soup_with_browser(url)

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
                title = re.sub(r"\s*-?\s*Chapter\s*\d+.*$", "", title, flags=re.IGNORECASE).strip()

            if not book_id:
                book_id = self._find_book_id_from_soup(soup)

        if not title:
            slug = self._extract_slug(url)
            if slug:
                title = slug.replace("-", " ").title()

        return {
            "title": title or "Без названия",
            "url": url,
            "book_id": book_id,
        }

    def get_chapters_list(self, url: str) -> List[dict]:
        book_id, ch_num = self._parse_chapter_url(url)

        # Загружаем страницу (HTTP → браузер)
        soup = self._get_soup_with_browser(url)

        if not book_id and soup:
            book_id = self._find_book_id_from_soup(soup)

        if not book_id:
            print("mvlempyr: не удалось определить book_id")
            return []

        print(f"mvlempyr: book_id = {book_id}")

        # 1. Попробовать извлечь список глав из HTML (если JS отрендерил)
        if soup:
            chapters = self._extract_chapters_from_rendered_html(soup, book_id)
            if chapters:
                print(f"mvlempyr: извлечено {len(chapters)} глав из HTML")
                return sorted(chapters, key=lambda c: int(c["number"]) if c["number"].isdigit() else 0)

        # 2. Если это страница главы — найти ссылку на новеллу и загрузить её
        if soup and "/chapter/" in url:
            novel_url = self._find_novel_url_from_chapter(soup)
            if novel_url:
                print(f"mvlempyr: загружаю страницу новеллы: {novel_url}")
                novel_soup = self._get_soup_with_browser(novel_url)
                if novel_soup:
                    chapters = self._extract_chapters_from_rendered_html(novel_soup, book_id)
                    if chapters:
                        print(f"mvlempyr: извлечено {len(chapters)} глав со страницы новеллы")
                        return sorted(chapters, key=lambda c: int(c["number"]) if c["number"].isdigit() else 0)

        # 3. Бинарный поиск через HTTP
        print("mvlempyr: пробую HTTP-пробинг...")
        if self._probe_url(f"{self.BASE}/chapter/{book_id}-1"):
            max_ch = self._find_max_chapter_http(book_id, ch_num or 1)
            if max_ch > 0:
                return self._generate_chapter_list(book_id, max_ch)

        # 4. Бинарный поиск через браузер (медленнее, но обходит CloudFlare)
        print("mvlempyr: HTTP недоступен, бинарный поиск через браузер...")
        max_ch = self._find_max_chapter_browser(book_id, ch_num or 1)
        if max_ch > 0:
            return self._generate_chapter_list(book_id, max_ch)

        print(f"mvlempyr: не удалось найти главы для book_id={book_id}")
        return []

    def _find_max_chapter_http(self, book_id: int, known_num: int = 1) -> int:
        """Бинарный поиск через HTTP (быстро, но может не работать при CloudFlare)."""
        hi = max(known_num, 1)
        while hi <= 10000:
            if self._probe_url(f"{self.BASE}/chapter/{book_id}-{hi}"):
                hi *= 2
                time.sleep(0.2)
            else:
                break

        lo = max(hi // 2, 1)
        hi = min(hi, 10000)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            time.sleep(0.2)
            if self._probe_url(f"{self.BASE}/chapter/{book_id}-{mid}"):
                lo = mid
            else:
                hi = mid - 1

        return lo

    def _generate_chapter_list(self, book_id: int, max_ch: int) -> List[dict]:
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

    # --- chapter content --------------------------------------------------

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

        # HTTP → браузер
        soup = self._get_soup_with_browser(chapter_url)
        if not soup:
            return ""

        # div#chapter, .ct-text-block (из скриншота пользователя)
        selectors = [
            "#chapter",
            "#chapter-content",
            ".ct-text-block",
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

        # __NEXT_DATA__
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
