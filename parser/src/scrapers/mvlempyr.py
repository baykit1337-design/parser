"""
Скрапер для mvlempyr.io
"""

import re
import time
from urllib.parse import urlparse, urljoin

from .base import BaseScraper


class MvlempyrScraper(BaseScraper):
    """Скрапер для сайта mvlempyr.io"""

    def _setup_headers(self):
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

    def _get_base_url(self, url):
        """Извлекает базовый URL сайта."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.hostname}"

    def get_book_info(self, url):
        """Получение информации о книге с mvlempyr.io"""
        soup = self._get_soup(url)
        if not soup:
            return {"title": "Без названия", "url": url}

        title_tag = soup.find("h1") or soup.find("h2")
        title = title_tag.get_text(strip=True) if title_tag else "Без названия"

        return {
            "title": title,
            "url": url,
        }

    def get_chapters_list(self, url):
        """Получение списка глав с mvlempyr.io"""
        soup = self._get_soup(url)
        if not soup:
            return []

        base_url = self._get_base_url(url)
        chapters = []

        toc_link = soup.find("a", string=re.compile(r"оглавление|table of contents|chapters", re.I))
        if toc_link and toc_link.get("href"):
            toc_url = urljoin(base_url, toc_link["href"])
            toc_soup = self._get_soup(toc_url)
            if toc_soup:
                soup = toc_soup

        chapter_links = soup.select("a[href]")

        seen_urls = set()
        chapter_candidates = []
        for link in chapter_links:
            href = link.get("href", "")
            text = link.get_text(strip=True)
            if not href or not text:
                continue

            full_url = urljoin(base_url, href)

            is_chapter = bool(
                re.search(r'chapter|глава|ch[\-_\.]?\d', text + href, re.IGNORECASE)
            )

            if not is_chapter:
                continue
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            chapter_candidates.append({"text": text, "url": full_url})

        for i, candidate in enumerate(chapter_candidates):
            name = candidate["text"]
            ch_match = re.search(r'(?:chapter|глава|ch)[\s.\-_]*(\d+)', name, re.IGNORECASE)
            ch_number = ch_match.group(1) if ch_match else str(i + 1)

            ch_name = re.sub(
                r'^(?:chapter|глава|ch)[\s.\-_]*\d+[\s.\-:]*',
                '', name, flags=re.IGNORECASE
            ).strip()

            chapters.append({
                "number": ch_number,
                "name": ch_name or name,
                "url": candidate["url"],
                "volume": "1",
            })

        return chapters

    def get_chapter_text(self, chapter_url):
        """Получение текста главы с mvlempyr.io"""
        time.sleep(0.5)
        soup = self._get_soup(chapter_url)
        if not soup:
            return ""

        content_selectors = [
            ".chapter-content",
            ".entry-content",
            ".post-content",
            ".text-content",
            ".reading-content",
            "article .content",
            "article",
            ".chapter-body",
            "#chapter-content",
            "main",
        ]

        content_div = None
        for selector in content_selectors:
            content_div = soup.select_one(selector)
            if content_div:
                break

        if not content_div:
            return ""

        for tag in content_div.find_all(["script", "style", "img", "noscript", "iframe", "nav"]):
            tag.decompose()

        for ad in content_div.find_all(class_=re.compile(r"ad|banner|promo|nav|footer|header", re.I)):
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
