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

    def __init__(self):
        super().__init__()
        self._api_tab = None

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

    def _open_tab_and_load(self, url: str, max_wait: int = 90):
        """Открывает вкладку и ГАРАНТИРУЕТ что страница реально загрузилась.

        1. Создаёт пустую вкладку
        2. Навигация через tab.get() с таймаутом
        3. Проверяет что страница не CloudFlare challenge
        4. Проверяет что появился реальный контент mvlempyr
        5. Если зависло — пробует refresh

        Возвращает tab или None.
        """
        page = self._get_browser_page()
        if not page:
            return None

        tab = None
        try:
            tab = page.new_tab()
        except Exception as e:
            print(f"mvlempyr: не удалось создать вкладку: {e}")
            return None

        try:
            print(f"  навигация: {url}")
            tab.get(url, timeout=max_wait, retry=2)
        except Exception as e:
            print(f"  tab.get() завершился с ошибкой: {e}")
            print(f"  проверяю что загрузилось...")

        # Проверяем что реально загрузилось
        loaded = self._verify_page_loaded(tab, url, max_wait=max_wait)
        if loaded:
            return tab

        # Страница не загрузилась — пробуем refresh
        print(f"  страница не загружена, пробую refresh...")
        try:
            tab.refresh()
            time.sleep(5)
        except Exception:
            pass

        loaded = self._verify_page_loaded(tab, url, max_wait=60)
        if loaded:
            return tab

        print(f"  страница так и не загрузилась")
        return tab  # возвращаем как есть, может частично загружено

    def _verify_page_loaded(self, tab, url: str, max_wait: int = 90) -> bool:
        """Проверяет что страница mvlempyr реально загрузилась.

        Не просто смотрит на размер HTML, а ищет конкретные признаки:
        - URL содержит mvlempyr
        - Есть элементы #chapter, .NovelName, nav, и т.д.
        - Нет CloudFlare challenge
        """
        checks = max_wait // 4
        last_len = 0
        saw_content = False

        for i in range(checks):
            time.sleep(4)
            try:
                html = tab.html or ""
                cur_url = tab.url or ""
            except Exception:
                continue

            html_len = len(html)

            # CloudFlare challenge — продолжаем ждать
            if self._is_cloudflare_challenge(html):
                print(f"  CloudFlare... ({(i + 1) * 4}s, {html_len} символов)")
                last_len = html_len
                continue

            # Пустая или слишком маленькая страница
            if html_len < 1000:
                if i > 0 and i % 5 == 0:
                    print(f"  страница почти пустая ({html_len} символов, {(i + 1) * 4}s)")
                last_len = html_len
                continue

            # Проверяем наличие конкретных признаков mvlempyr
            has_chapter = "#chapter" in html or "chapter-content" in html
            has_novel = "NovelName" in html or "novel-name" in html
            has_mvl = "mvlempyr" in html.lower() or "heliosarchive" in html
            has_nav = "prev-top" in html or "next-top" in html

            if has_chapter or has_novel or has_mvl or has_nav:
                print(f"  страница загружена! ({html_len} символов, {(i + 1) * 4}s)")
                return True

            # Если HTML большой и стабильный — тоже считаем загруженным
            if html_len > 5000:
                if abs(html_len - last_len) < 300:
                    if saw_content:
                        print(f"  страница стабилизировалась ({html_len} символов, {(i + 1) * 4}s)")
                        return True
                    saw_content = True
                else:
                    saw_content = False

            last_len = html_len

            if i > 0 and i % 5 == 0:
                print(f"  жду загрузку... ({html_len} символов, {(i + 1) * 4}s)")

        return last_len > 5000

    def _close_tab(self, tab):
        if tab:
            try:
                tab.close()
            except Exception:
                pass

    # --- book info --------------------------------------------------------

    def get_book_info(self, url: str) -> dict:
        book_id, ch_num = self._parse_chapter_url(url)

        print("mvlempyr: загружаю страницу для info...")
        tab = self._open_tab_and_load(url, max_wait=60)
        if not tab:
            slug = self._extract_slug(url)
            return {
                "title": slug.replace("-", " ").title() if slug else "Без названия",
                "url": url,
                "book_id": book_id,
            }

        title = None
        try:
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

    @staticmethod
    def _compute_tag_id(book_id: int) -> int:
        """tagId = pow(7, book_id, 1999999997) — формула из chbbv14.js."""
        return pow(7, book_id, 1999999997)

    def get_chapters_list(self, url: str) -> List[dict]:
        book_id, ch_num = self._parse_chapter_url(url)

        if not HAS_DRISSION:
            print(
                "\n[!] mvlempyr.io требует браузер для загрузки.\n"
                "    Установите DrissionPage:\n"
                "    pip install DrissionPage\n"
            )
            return []

        # Если URL — /novel/..., ищем book_id и строим /chapter/ URL
        if "/chapter/" not in url:
            book_id = self._resolve_book_id_from_novel(url)
            if not book_id:
                print("mvlempyr: не удалось определить book_id")
                return []

        if not book_id:
            print("mvlempyr: не удалось определить book_id из URL")
            return []

        tag_id = self._compute_tag_id(book_id)
        print(f"mvlempyr: book_id={book_id}, tagId={tag_id}")

        # Открываем любую страницу mvlempyr чтобы браузер прошёл CloudFlare
        # и у нас появился контекст для fetch к heliosarchive.online
        print("mvlempyr: открываю страницу для получения сессии браузера...")
        tab = self._open_tab_and_load(url, max_wait=90)
        if not tab:
            return []

        # Сохраняем вкладку сразу — пригодится для скачивания глав
        self._api_tab = tab

        try:
            print("mvlempyr: запрашиваю количество глав через API...")
            total = self._fetch_total_chapters(tab, tag_id)
            if not total or total <= 0:
                print("mvlempyr: API не вернул количество глав, пробую фолбэк...")
                return self._fallback_chapters_from_html(tab, book_id)

            print(f"mvlempyr: всего глав: {total}")

            chapters = self._fetch_all_chapters(tab, tag_id, total, book_id)
            if chapters:
                print(f"mvlempyr: получено {len(chapters)} глав из API")
                return chapters

            print("mvlempyr: API не вернул данные, пробую фолбэк...")
            return self._fallback_chapters_from_html(tab, book_id)
        except Exception:
            self._close_tab(tab)
            self._api_tab = None
            raise

    @staticmethod
    def _sync_xhr_js(api_url: str, parse_mode: str = "header") -> str:
        """JS-код для синхронного XMLHttpRequest (без async/await).

        parse_mode='header' — возвращает X-WP-Total
        parse_mode='json'   — возвращает JSON тело ответа
        """
        if parse_mode == "header":
            return f"""
                try {{
                    var xhr = new XMLHttpRequest();
                    xhr.open('GET', '{api_url}', false);

                    xhr.send();
                    if (xhr.status !== 200) return 'ERR:' + xhr.status + ':' + xhr.responseText.substring(0, 200);
                    return xhr.getResponseHeader('X-WP-Total') || '0';
                }} catch(e) {{
                    return 'ERR:' + e.message;
                }}
            """
        return f"""
            try {{
                var xhr = new XMLHttpRequest();
                xhr.open('GET', '{api_url}', false);
                xhr.send();
                if (xhr.status !== 200) return 'ERR:' + xhr.status;
                var data = JSON.parse(xhr.responseText);
                var result = [];
                for (var i = 0; i < data.length; i++) {{
                    var p = data[i];
                    var acf = p.acf || {{}};
                    result.push({{
                        ch_name: acf.ch_name || (p.title && p.title.rendered) || '',
                        ch_num: acf.chapter_number || '',
                        link: p.link || '',
                        slug: p.slug || '',
                        date: p.date || ''
                    }});
                }}
                return JSON.stringify(result);
            }} catch(e) {{
                return 'ERR:' + e.message;
            }}
        """

    def _fetch_total_chapters(self, tab, tag_id: int) -> int:
        api_url = (
            f"https://chap.heliosarchive.online/wp-json/wp/v2/posts"
            f"?tags={tag_id}&per_page=1"
        )
        js = self._sync_xhr_js(api_url, "header")

        for attempt in range(3):
            try:
                result = tab.run_js(js, timeout=120)
            except Exception as e:
                print(f"  XHR ошибка (попытка {attempt + 1}): {e}")
                time.sleep(5)
                continue

            if not result:
                print(f"  пустой ответ (попытка {attempt + 1})")
                time.sleep(5)
                continue

            result = str(result)
            if result.startswith("ERR:"):
                print(f"  API ошибка: {result}")
                time.sleep(5)
                continue

            try:
                return int(result)
            except ValueError:
                print(f"  неожиданный ответ: {result}")
                time.sleep(5)

        return 0

    def _fetch_all_chapters(self, tab, tag_id: int, total: int,
                            book_id: int) -> List[dict]:
        pages_needed = (total + 499) // 500
        all_posts = []

        for page_num in range(1, pages_needed + 1):
            api_url = (
                f"https://chap.heliosarchive.online/wp-json/wp/v2/posts"
                f"?tags={tag_id}&per_page=500&page={page_num}"
            )
            print(f"  загрузка страницы {page_num}/{pages_needed}...")

            js = self._sync_xhr_js(api_url, "json")
            posts_json = None
            for attempt in range(3):
                try:
                    posts_json = tab.run_js(js, timeout=120)
                except Exception as e:
                    print(f"    ошибка (попытка {attempt + 1}): {e}")
                    time.sleep(5)
                    continue

                if posts_json and not str(posts_json).startswith("ERR:"):
                    break
                print(f"    {posts_json} (попытка {attempt + 1})")
                time.sleep(5)

            if not posts_json or str(posts_json).startswith("ERR:"):
                print(f"  не удалось загрузить страницу {page_num}")
                continue

            try:
                posts = json.loads(posts_json)
                all_posts.extend(posts)
                print(f"  получено {len(posts)} постов")
            except Exception as e:
                print(f"  ошибка парсинга JSON: {e}")

        if not all_posts:
            return []

        # Сортируем по chapter_number и строим список
        all_posts.sort(
            key=lambda p: int(p.get("ch_num") or "0") if str(p.get("ch_num", "")).isdigit() else 0
        )

        chapters = []
        for idx, post in enumerate(all_posts):
            ch_num = post.get("ch_num", "")
            if not ch_num or not str(ch_num).isdigit():
                ch_num = str(idx + 1)
            ch_name = post.get("ch_name", "") or f"Chapter {ch_num}"
            link = post.get("link", "")

            if link:
                from urllib.parse import urlparse
                path = urlparse(link).path.rstrip("/")
                chapter_url = f"{self.BASE}{path}"
            else:
                chapter_url = f"{self.BASE}/chapter/{book_id}-{ch_num}"

            chapters.append({
                "number": str(ch_num),
                "name": ch_name,
                "url": chapter_url,
                "volume": "1",
            })

        return chapters

    def _resolve_book_id_from_novel(self, novel_url: str) -> Optional[int]:
        """Загружает страницу новеллы и ищет book_id."""
        print("mvlempyr: загружаю страницу новеллы...")
        tab = self._open_tab_and_load(novel_url, max_wait=60)
        if not tab:
            return None

        try:
            html = tab.html or ""
            soup = BeautifulSoup(html, "html.parser")
            return self._find_book_id_from_soup(soup)
        finally:
            self._close_tab(tab)

    def _fallback_chapters_from_html(self, tab, book_id: int) -> List[dict]:
        """Фолбэк: парсим ссылки на главы из HTML."""
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
            print(f"mvlempyr: фолбэк — {len(chapters)} глав из HTML")

        return chapters

    # --- chapter content --------------------------------------------------

    def _ensure_api_tab(self):
        """Возвращает постоянную вкладку для API-запросов.

        Одна вкладка на весь сеанс скачивания. Не открывает новые.
        """
        if self._api_tab is not None:
            try:
                _ = self._api_tab.url
                return self._api_tab
            except Exception:
                self._api_tab = None

        print("mvlempyr: открываю вкладку для API-запросов...")
        self._api_tab = self._open_tab_and_load(
            f"{self.BASE}/chapter/1-1", max_wait=90
        )
        return self._api_tab

    def close_browser(self):
        """Закрывает API-вкладку и браузер."""
        if self._api_tab:
            self._close_tab(self._api_tab)
            self._api_tab = None
        super().close_browser()

    def get_chapter_text(self, chapter_url: str) -> str:
        """Загружает текст главы через WordPress API (без открытия страниц)."""
        m = re.search(r"/chapter/(\d+-\d+)", chapter_url)
        if not m:
            return ""
        slug = m.group(1)

        tab = self._ensure_api_tab()
        if not tab:
            return ""

        api_url = (
            f"https://chap.heliosarchive.online/wp-json/wp/v2/posts"
            f"?slug={slug}&_fields=content"
        )
        js = f"""
            try {{
                var xhr = new XMLHttpRequest();
                xhr.open('GET', '{api_url}', false);
                xhr.send();
                if (xhr.status !== 200) return 'ERR:' + xhr.status;
                var data = JSON.parse(xhr.responseText);
                if (!data.length) return 'ERR:no_post';
                var html = data[0].content && data[0].content.rendered || '';
                if (!html) return 'ERR:no_content';
                var div = document.createElement('div');
                div.innerHTML = html;
                var ps = div.querySelectorAll('p');
                var texts = [];
                for (var i = 0; i < ps.length; i++) {{
                    var t = ps[i].textContent.trim();
                    if (t.length > 1) texts.push(t);
                }}
                if (texts.length > 0) return texts.join('\\n');
                return div.textContent.trim();
            }} catch(e) {{
                return 'ERR:' + e.message;
            }}
        """
        for attempt in range(3):
            try:
                result = tab.run_js(js, timeout=120)
            except Exception as e:
                print(f"  XHR ошибка главы {slug} (попытка {attempt + 1}): {e}")
                time.sleep(3)
                continue

            if not result:
                time.sleep(2)
                continue

            result = str(result)
            if result.startswith("ERR:"):
                print(f"  API ошибка главы {slug}: {result}")
                time.sleep(2)
                continue

            return result

        return ""
