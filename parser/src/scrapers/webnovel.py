"""
Скрапер для webnovel.com
"""

import re
import time
from urllib.parse import urlparse, urljoin

from .base import BaseScraper


class WebnovelScraper(BaseScraper):
    """Скрапер для сайта webnovel.com"""

    def _setup_headers(self):
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.webnovel.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        })

    def _extract_book_id(self, url):
        """Извлекает ID книги из URL webnovel."""
        match = re.search(r'/book/(\d+)', url)
        if match:
            return match.group(1)
        path = urlparse(url).path
        parts = path.strip("/").split("/")
        for part in parts:
            if part.isdigit() and len(part) > 8:
                return part
        return None

    def get_book_info(self, url):
        """Получение информации о книге с webnovel.com"""
        soup = self._get_soup(url)
        if not soup:
            return {"title": "Без названия", "url": url}

        title_tag = soup.find("h1") or soup.find("h2")
        title = title_tag.get_text(strip=True) if title_tag else "Без названия"

        return {
            "title": title,
            "url": url,
            "book_id": self._extract_book_id(url),
        }

    def get_chapters_list(self, url):
        """Получение списка глав с webnovel.com"""
        book_id = self._extract_book_id(url)
        if not book_id:
            print("Не удалось определить ID книги в URL webnovel")
            return []

        catalog_url = f"https://www.webnovel.com/book/{book_id}/catalog"
        soup = self._get_soup(catalog_url)
        if not soup:
            soup = self._get_soup(url)
        if not soup:
            return []

        chapters = []
        chapter_links = soup.select("a[href*='/book/'][href*='/chapter/']")
        if not chapter_links:
            chapter_links = soup.select(".chapter-item a, .catalog-item a, li a[href*='chapter']")

        seen_urls = set()
        for i, link in enumerate(chapter_links):
            href = link.get("href", "")
            if not href:
                continue
            full_url = urljoin("https://www.webnovel.com", href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            name = link.get_text(strip=True)
            ch_match = re.search(r'chapter\s*(\d+)', name, re.IGNORECASE)
            ch_number = ch_match.group(1) if ch_match else str(i + 1)

            ch_name = re.sub(r'^chapter\s*\d+\s*[-:.]?\s*', '', name, flags=re.IGNORECASE).strip()

            chapters.append({
                "number": ch_number,
                "name": ch_name or name,
                "url": full_url,
                "volume": "1",
            })

        return chapters

    def get_chapter_text(self, chapter_url):
        """Получение текста главы с webnovel.com"""
        time.sleep(1)
        soup = self._get_soup(chapter_url)
        if not soup:
            return ""

        content_selectors = [
            ".cha-words",
            ".cha-content",
            ".chapter-content",
            ".read-content",
            "[class*='chapter'] [class*='content']",
            ".j_contentWrap",
            "article",
        ]

        content_div = None
        for selector in content_selectors:
            content_div = soup.select_one(selector)
            if content_div:
                break

        if not content_div:
            main = soup.find("main") or soup.find("div", {"id": "chapter-container"})
            if main:
                content_div = main

        if not content_div:
            return ""

        for tag in content_div.find_all(["script", "style", "img", "noscript", "iframe"]):
            tag.decompose()

        for ad in content_div.find_all(class_=re.compile(r"ad|banner|promo|piracy", re.I)):
            ad.decompose()

        paragraphs = []
        for p in content_div.find_all("p"):
            text = p.get_text(strip=True)
            if text and len(text) > 1:
                paragraphs.append(text)

        if not paragraphs:
            text = content_div.get_text(separator="\n")
            for line in text.splitlines():
                line = line.strip()
                if line and len(line) > 1:
                    paragraphs.append(line)

        return "\n".join(paragraphs)
