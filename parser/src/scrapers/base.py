"""
Базовый класс для скраперов сторонних сайтов
"""

import time
import requests
from bs4 import BeautifulSoup


class BaseScraper:
    """Базовый скрапер с общей логикой HTTP-запросов и парсинга."""

    def __init__(self):
        self.session = requests.Session()
        self._setup_headers()

    def _setup_headers(self):
        """Настройка заголовков — переопределяется в подклассах."""
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        })

    def _get_soup(self, url, retries=3, delay=2):
        """Загружает страницу и возвращает BeautifulSoup объект."""
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                return BeautifulSoup(response.text, "html.parser")
            except requests.exceptions.RequestException as e:
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))
                else:
                    print(f"Ошибка загрузки {url}: {e}")
                    return None

    def get_book_info(self, url):
        """Получение информации о книге. Переопределяется в подклассах."""
        raise NotImplementedError

    def get_chapters_list(self, url):
        """Получение списка глав. Переопределяется в подклассах."""
        raise NotImplementedError

    def get_chapter_text(self, chapter_url):
        """Получение текста одной главы. Переопределяется в подклассах."""
        raise NotImplementedError
