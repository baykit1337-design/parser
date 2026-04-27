"""
Скрапер для mvlempyr.io (My Virtual Library Empire).

URL-паттерны:
- Книга:  https://www.mvlempyr.io/novel/{slug}
- Глава:  https://www.mvlempyr.io/chapter/{book_id}-{chapter_number}

Сайт защищён CloudFlare — HTTP не проходят.
Используем Chrome пользователя (DrissionPage).

Список глав загружается JS сайта из WordPress API
(chap.heliosarchive.online). Мы открываем одну вкладку,
ждём пока JS отработает, триггерим загрузку оглавления
и парсим результат из DOM.
"""

import json
import re
import time
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, HAS_DRISSION


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
        m = re.search(r"/chapter/(\d+)-(\d+)", url)
        if m:
            return int(m.group(1)), int(m.group(2))
        return None, None

    @staticmethod
    def _extract_slug(url: str) -> Optional[str]:
        m = re.search(r"/novel/([a-z0-9\-]+)", url, re.IGNORECASE)
        return m.group(1) if m else None

    def _find_book_id_from_soup(self, soup: BeautifulSoup) -> Optional[int]:
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            m = re.search(r"/chapter/(\d+)-\d+", href)
            if m:
                return int(m.group(1))
        for script in soup.find_all("script"):
            text = script.string or script.get_text() or ""
            m = re.search(r"/chapter/(\d{3,})-\d+", text)
            if m:
                return int(m.group(1))
        return None

    # --- browser tab management -------------------------------------------

    def _open_tab(self, url: str):
        page = self._get_browser_page()
        if not page:
            return None
        try:
            tab = page.new_tab(url)
            return tab
        except Exception as e:
            print(f"mvlempyr: не удалось открыть вкладку: {e}")
            return None

    def _close_tab(self, tab):
        if tab:
            try:
                tab.close()
            except Exception:
                pass

    def _wait_page_ready(self, tab, max_wait: int = 90) -> bool:
        """Ждёт пока страница загрузится (CloudFlare + начальный рендер).

        Для медленного интернета: до max_wait секунд.
        Возвращает True если страница загружена.
        """
        checks = max_wait // 3
        last_len = 0
        stable = 0

        for i in range(checks):
            time.sleep(3)
            try:
                html = tab.html or ""
            except Exception:
                continue

            if self._is_cloudflare_challenge(html):
                print(f"  CloudFlare challenge... ({i * 3}s)")
                stable = 0
                last_len = len(html)
                continue

            cur_len = len(html)
            if cur_len > 2000:
                if abs(cur_len - last_len) < 200:
                    stable += 1
                    if stable >= 2:
                        return True
                else:
                    stable = 0
                last_len = cur_len

        return last_len > 2000

    # --- book info --------------------------------------------------------

    def get_book_info(self, url: str) -> dict:
        book_id, ch_num = self._parse_chapter_url(url)

        tab = self._open_tab(url)
        if not tab:
            slug = self._extract_slug(url)
            return {
                "title": slug.replace("-", " ").title() if slug else "Без названия",
                "url": url,
                "book_id": book_id,
            }

        title = None
        try:
            print(f"mvlempyr: загружаю страницу для info...")
            self._wait_page_ready(tab, max_wait=60)
            html = tab.html or ""
            soup = BeautifulSoup(html, "html.parser")

            for sel in ("h1", ".NovelName", ".novel-title", ".entry-title", "title"):
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
        finally:
            self._close_tab(tab)

        if not title:
            slug = self._extract_slug(url)
            if slug:
                title = slug.replace("-", " ").title()

        return {
            "title": title or "Без названия",
            "url": url,
            "book_id": book_id,
        }

    # --- chapters list ----------------------------------------------------

    def get_chapters_list(self, url: str) -> List[dict]:
        book_id, ch_num = self._parse_chapter_url(url)

        if not HAS_DRISSION:
            print(
                "\n[!] mvlempyr.io требует браузер для загрузки.\n"
                "    Установите DrissionPage:\n"
                "    pip install DrissionPage\n"
            )
            return []

        # Если URL — страница новеллы (/novel/...), нужно сначала найти
        # URL главы, т.к. JS оглавления работает только на /chapter/
        chapter_url = url
        if "/chapter/" not in url:
            chapter_url = self._find_chapter_url_from_novel(url, book_id)
            if not chapter_url:
                print("mvlempyr: не удалось найти ссылку на главу со страницы новеллы")
                return []

        # Открываем страницу главы
        print(f"mvlempyr: открываю страницу главы...")
        tab = self._open_tab(chapter_url)
        if not tab:
            return []

        try:
            # 1. Ждём загрузки страницы
            print(f"mvlempyr: жду загрузку страницы (медленный интернет — терпение)...")
            if not self._wait_page_ready(tab, max_wait=90):
                print("mvlempyr: страница не загрузилась за 90 секунд")
                return []

            # Извлекаем book_id из HTML если ещё нет
            if not book_id:
                try:
                    html = tab.html or ""
                    soup = BeautifulSoup(html, "html.parser")
                    book_id = self._find_book_id_from_soup(soup)
                except Exception:
                    pass
            if not book_id:
                book_id, _ = self._parse_chapter_url(chapter_url)
            if not book_id:
                print("mvlempyr: не удалось определить book_id")
                return []

            print(f"mvlempyr: book_id = {book_id}")

            # 2. Ждём пока JS сайта установит window.tagId и window.totalChapters
            tag_id = None
            total_chapters = 0
            print("mvlempyr: жду инициализацию JS сайта (tagId, totalChapters)...")

            for i in range(40):  # до 120 сек
                time.sleep(3)
                try:
                    tag_id = tab.run_js("return window.tagId || null")
                    total_chapters = tab.run_js("return window.totalChapters || 0")
                except Exception:
                    continue

                if tag_id and total_chapters and int(total_chapters) > 0:
                    print(f"mvlempyr: tagId={tag_id}, totalChapters={total_chapters}")
                    break

                if i > 0 and i % 10 == 0:
                    print(f"  ещё жду... ({i * 3}s)")
            else:
                print(f"mvlempyr: JS не инициализировался (tagId={tag_id}, total={total_chapters})")
                # Фолбэк — попробуем из HTML
                return self._fallback_chapters_from_html(tab, book_id)

            # 3. Триггерим загрузку оглавления
            print("mvlempyr: триггерю загрузку оглавления...")
            try:
                tab.run_js(
                    "if(window.refreshChapterListPanelIfNeeded) "
                    "window.refreshChapterListPanelIfNeeded();"
                    "else document.querySelector('.slide-in-button')?.click();"
                )
            except Exception as e:
                print(f"mvlempyr: ошибка при триггере: {e}")
                try:
                    tab.run_js("document.querySelector('.slide-in-button')?.click()")
                except Exception:
                    pass

            # 4. Ждём пока #content заполнится .chapter-item элементами
            print("mvlempyr: жду загрузку списка глав...")
            loaded_count = 0
            for i in range(40):  # до 120 сек
                time.sleep(3)
                try:
                    count = tab.run_js(
                        "return document.querySelectorAll('#content .chapter-item').length"
                    )
                except Exception:
                    continue

                if count and int(count) > 0:
                    if int(count) == loaded_count and loaded_count > 0:
                        # Стабилизировалось — все главы загружены
                        print(f"mvlempyr: загружено {count} глав в оглавление")
                        break
                    loaded_count = int(count)
                    if i > 0 and i % 5 == 0:
                        print(f"  загружается... {loaded_count} глав ({i * 3}s)")
                elif i > 0 and i % 10 == 0:
                    print(f"  ещё жду... ({i * 3}s)")
            else:
                if loaded_count > 0:
                    print(f"mvlempyr: загружено {loaded_count} глав (таймаут, но данные есть)")
                else:
                    print("mvlempyr: главы не загрузились в #content")
                    return self._fallback_chapters_from_html(tab, book_id)

            # 5. Извлекаем данные глав через JS (быстрее чем парсить HTML)
            chapters = self._extract_chapters_from_dom(tab, book_id)
            if chapters:
                print(f"mvlempyr: извлечено {len(chapters)} глав")
                return chapters

            print("mvlempyr: не удалось извлечь главы из DOM")
            return self._fallback_chapters_from_html(tab, book_id)

        finally:
            self._close_tab(tab)

    def _find_chapter_url_from_novel(self, novel_url: str, book_id: Optional[int]) -> Optional[str]:
        """Загружает страницу новеллы и ищет ссылку на первую главу."""
        tab = self._open_tab(novel_url)
        if not tab:
            return None

        try:
            print("mvlempyr: загружаю страницу новеллы для поиска главы...")
            self._wait_page_ready(tab, max_wait=60)
            html = tab.html or ""
            soup = BeautifulSoup(html, "html.parser")

            for a in soup.select("a[href]"):
                href = a.get("href", "")
                if "/chapter/" in href:
                    return urljoin(self.BASE, href)

            # Попробуем найти book_id и сконструировать URL
            if not book_id:
                book_id = self._find_book_id_from_soup(soup)
            if book_id:
                return f"{self.BASE}/chapter/{book_id}-1"

            return None
        finally:
            self._close_tab(tab)

    def _extract_chapters_from_dom(self, tab, book_id: int) -> List[dict]:
        """Извлекает список глав напрямую из DOM через JS."""
        try:
            data_json = tab.run_js("""
                var items = document.querySelectorAll('#content .chapter-item');
                var result = [];
                items.forEach(function(item, idx) {
                    var h1 = item.querySelector('h1');
                    var dateSpan = item.querySelector('.chapter-date');
                    result.push({
                        href: item.getAttribute('href') || '',
                        name: h1 ? h1.textContent.trim() : item.textContent.trim(),
                        index: item.dataset.listingIndex || String(idx),
                        date: dateSpan ? dateSpan.textContent.trim() : ''
                    });
                });
                return JSON.stringify(result);
            """)
        except Exception as e:
            print(f"mvlempyr: ошибка извлечения из DOM: {e}")
            return []

        if not data_json:
            return []

        try:
            items = json.loads(data_json)
        except Exception:
            return []

        chapters = []
        for item in items:
            href = item.get("href", "")
            name = item.get("name", "")
            idx = item.get("index", str(len(chapters)))

            # Убираем "123. " из начала названия
            clean_name = re.sub(r"^\d+\.\s*", "", name).strip()

            full_url = urljoin(self.BASE, href) if href else ""
            m = re.search(r"/chapter/\d+-(\d+)", href)
            ch_num = m.group(1) if m else str(int(idx) + 1)

            chapters.append({
                "number": ch_num,
                "name": clean_name or f"Chapter {ch_num}",
                "url": full_url,
                "volume": "1",
            })

        return chapters

    def _fallback_chapters_from_html(self, tab, book_id: int) -> List[dict]:
        """Фолбэк: парсим что есть в HTML."""
        try:
            html = tab.html or ""
        except Exception:
            return []

        if not html or len(html) < 500:
            return []

        soup = BeautifulSoup(html, "html.parser")
        chapters = []
        seen = set()

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

        if chapters:
            chapters.sort(key=lambda c: int(c["number"]) if c["number"].isdigit() else 0)
            print(f"mvlempyr: фолбэк — извлечено {len(chapters)} глав из HTML ссылок")

        return chapters

    # --- chapter content --------------------------------------------------

    def get_chapter_text(self, chapter_url: str) -> str:
        time.sleep(0.5)

        tab = self._open_tab(chapter_url)
        if not tab:
            return ""

        try:
            # Ждём загрузки страницы
            if not self._wait_page_ready(tab, max_wait=90):
                print(f"mvlempyr: страница не загрузилась: {chapter_url}")
                return ""

            # Ждём появления реального контента (не "LOADING")
            text = self._wait_for_chapter_content(tab, max_wait=60)
            return text
        finally:
            self._close_tab(tab)

    def _wait_for_chapter_content(self, tab, max_wait: int = 60) -> str:
        """Ждёт пока текст главы реально появится в DOM.

        Проверяет #chapter-content .ct-text-block на наличие
        текстовых параграфов. Не закрывает вкладку — caller управляет.
        """
        checks = max_wait // 3
        best_text = ""

        for i in range(checks):
            time.sleep(3)

            try:
                result = tab.run_js("""
                    var selectors = [
                        '#chapter-content .ct-text-block',
                        '#chapter-content',
                        '#chapter',
                        '.chapter-content',
                        '.entry-content',
                        'article',
                        'main'
                    ];
                    for (var s = 0; s < selectors.length; s++) {
                        var node = document.querySelector(selectors[s]);
                        if (!node) continue;
                        var ps = node.querySelectorAll('p');
                        var texts = [];
                        for (var j = 0; j < ps.length; j++) {
                            var t = ps[j].textContent.trim();
                            if (t.length > 1) texts.push(t);
                        }
                        if (texts.length > 0) {
                            return JSON.stringify({
                                selector: selectors[s],
                                count: texts.length,
                                totalLen: texts.join('').length,
                                text: texts.join('\\n')
                            });
                        }
                    }
                    return null;
                """)
            except Exception:
                continue

            if not result:
                if i > 0 and i % 5 == 0:
                    print(f"  контент ещё не загружен... ({i * 3}s)")
                continue

            try:
                data = json.loads(result)
            except Exception:
                continue

            text = data.get("text", "")
            total_len = data.get("totalLen", 0)
            count = data.get("count", 0)

            # Проверяем что это реальный контент, а не заглушка
            if total_len < 50 or count < 2:
                continue

            # Проверяем что это не "Loading..." текст
            if "loading" in text.lower()[:100]:
                continue

            # Контент есть и он реальный
            if len(text) >= len(best_text):
                best_text = text

            # Ждём ещё один цикл чтобы убедиться что контент стабилен
            if best_text and i > 0:
                time.sleep(3)
                try:
                    result2 = tab.run_js("""
                        var node = document.querySelector('#chapter-content .ct-text-block')
                                || document.querySelector('#chapter-content')
                                || document.querySelector('#chapter');
                        if (!node) return '0';
                        return String(node.textContent.length);
                    """)
                    new_len = int(result2 or "0")
                    if abs(new_len - total_len) < 50:
                        return best_text
                except Exception:
                    return best_text

        return best_text
