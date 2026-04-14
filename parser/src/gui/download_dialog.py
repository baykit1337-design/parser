"""
Диалог для отображения процесса загрузки глав и создания книг (.docx)
"""

import os
import re
import shutil
import time
from typing import Any, Dict, List

from PyQt6.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from ..api import OperationCancelledError, RanobeLibAPI
from ..creators.docx_creator import DocxCreator
from ..img import ImageHandler
from ..parser import RanobeLibParser
from ..processing import ContentProcessor
from ..settings import USER_DATA_DIR
from ..translate import translate_title


class DownloadWorker(QThread):
    """Рабочий поток для скачивания глав и создания DOCX файлов (RanobeLIB)"""

    progress_update = pyqtSignal(str, int)
    chapter_download = pyqtSignal(int, int)
    time_update = pyqtSignal(float, float)
    format_progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(
        self,
        novel_info: Dict[str, Any],
        selected_chapters: List[Dict[str, Any]],
        selected_formats: List[str],
        api: RanobeLibAPI,
        parser: RanobeLibParser,
        image_handler: ImageHandler,
        save_dir: str,
        options: Dict[str, bool],
    ):
        super().__init__()
        self.novel_info = novel_info
        self.selected_chapters = selected_chapters
        self.selected_formats = selected_formats
        self.api = api
        self.parser = parser
        self.image_handler = image_handler
        self.save_dir = save_dir
        self.options = options
        self.is_cancelled = False
        self._temp_dir = ""

        self.start_time = 0
        self.created_files = []

    def cancel(self):
        if not self.is_cancelled:
            self.progress_update.emit("Отмена процесса...", 0)
            self.is_cancelled = True
            self.api.cancel_pending_requests()

    def run(self):
        self.start_time = time.time()
        self.image_handler.reset()

        novel_id = self.novel_info.get("id")
        self._temp_dir = os.path.join(USER_DATA_DIR, "temp", f"images_{novel_id}")

        should_emit_finish = True
        try:
            os.makedirs(self._temp_dir, exist_ok=True)
            self._download_and_save_chapters()
        except OperationCancelledError:
            should_emit_finish = True
            self.is_cancelled = True
        except Exception as e:
            should_emit_finish = False
            if not self.is_cancelled:
                self.error.emit(str(e))
        finally:
            self._cleanup_temp_files()
            if should_emit_finish:
                self.finished.emit(self.created_files)

    def _download_and_save_chapters(self):
        """Скачивание глав и сохранение каждой как отдельный .docx"""
        total_chapters = len(self.selected_chapters)
        self.progress_update.emit("Подготовка к загрузке глав...", 0)

        processor = ContentProcessor(self.api, self.parser, self.image_handler)
        processor.update_settings()
        processor.download_cover_enabled = self.options.get("download_cover", processor.download_cover_enabled)
        processor.download_images_enabled = self.options.get("download_images", processor.download_images_enabled)
        processor.group_by_volumes = self.options.get("group_by_volumes", processor.group_by_volumes)
        processor.add_translator = self.options.get("add_translator", processor.add_translator)

        docx_creator = DocxCreator(self.api, self.parser, self.image_handler)
        total_volumes = docx_creator.get_total_volume_count(self.novel_info)

        for i, chapter_data in enumerate(self.selected_chapters):
            if self.is_cancelled:
                return

            chapter_info = chapter_data["chapter"]
            branch_ids = chapter_data["branch_ids"]
            branch_id = branch_ids[0] if branch_ids else "0"
            branch_info = next(
                (
                    b
                    for b in chapter_info.get("branches", [])
                    if str(b.get("branch_id", "0")) == str(branch_id)
                ),
                {"branch_id": branch_id},
            )

            self.chapter_download.emit(i + 1, total_chapters)
            chapter_title = f"Глава {chapter_info.get('number', '?')}"
            if chapter_info.get("name"):
                chapter_title += f" - {chapter_info.get('name')}"

            self.progress_update.emit(
                f"Загрузка {chapter_title}...", int(100 * (i / total_chapters))
            )

            prepared_chapter = processor._process_single_chapter(
                {"chapter": chapter_info, "branch": branch_info},
                self.novel_info,
                self._temp_dir,
                total_chapters - (i + 1),
            )

            # Перевод названия главы EN -> RU
            ch_name = prepared_chapter.get("name", "")
            if ch_name:
                prepared_chapter["name"] = translate_title(ch_name)

            try:
                filepath = docx_creator.create_single_chapter(
                    prepared_chapter, self.novel_info, self.save_dir, total_volumes
                )
                self.created_files.append(filepath)
                self.progress_update.emit(
                    f"Сохранен: {os.path.basename(filepath)}", int(100 * ((i + 1) / total_chapters))
                )
            except Exception as e:
                self.progress_update.emit(f"Ошибка сохранения главы: {e}", 0)

            elapsed_time = time.time() - self.start_time
            chapters_done = i + 1
            remaining_time = -1.0
            if chapters_done > 0:
                avg_time = elapsed_time / chapters_done
                remaining_time = avg_time * (total_chapters - chapters_done)
            self.time_update.emit(elapsed_time, remaining_time)

        self.progress_update.emit("Все главы загружены и сохранены", 100)

    def _cleanup_temp_files(self):
        if not self._temp_dir or not os.path.exists(self._temp_dir):
            return
        self.progress_update.emit("Очистка временных файлов...", 0)
        try:
            shutil.rmtree(self._temp_dir)
        except Exception as e:
            self.progress_update.emit(f"Не удалось удалить временные файлы: {e}", 0)

        novel_id = self.novel_info.get("id")
        cache_key = (novel_id, None)
        ContentProcessor._global_cache.pop(cache_key, None)


class ExternalDownloadWorker(QThread):
    """Рабочий поток для скачивания глав с внешних сайтов (webnovel, mvlempyr)"""

    progress_update = pyqtSignal(str, int)
    chapter_download = pyqtSignal(int, int)
    time_update = pyqtSignal(float, float)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, book_info, chapters, site_type, save_dir):
        super().__init__()
        self.book_info = book_info
        self.chapters = chapters
        self.site_type = site_type
        self.save_dir = save_dir
        self.is_cancelled = False
        self.start_time = 0
        self.created_files = []

    def cancel(self):
        if not self.is_cancelled:
            self.progress_update.emit("Отмена процесса...", 0)
            self.is_cancelled = True

    def run(self):
        self.start_time = time.time()
        try:
            self._download_chapters()
        except Exception as e:
            if not self.is_cancelled:
                self.error.emit(str(e))
        finally:
            self.finished.emit(self.created_files)

    def _download_chapters(self):
        from ..scrapers.site_detector import SITE_WEBNOVEL, SITE_MVLEMPYR

        if self.site_type == SITE_WEBNOVEL:
            from ..scrapers.webnovel import WebnovelScraper
            scraper = WebnovelScraper()
        else:
            from ..scrapers.mvlempyr import MvlempyrScraper
            scraper = MvlempyrScraper()

        total = len(self.chapters)
        os.makedirs(self.save_dir, exist_ok=True)

        for i, chapter in enumerate(self.chapters):
            if self.is_cancelled:
                return

            self.chapter_download.emit(i + 1, total)
            ch_number = chapter.get("number", str(i + 1))
            ch_name = chapter.get("name", "")
            ch_url = chapter.get("url", "")
            vol = chapter.get("volume", "1")

            self.progress_update.emit(
                f"Загрузка Глава {ch_number} — {ch_name}...",
                int(100 * (i / total))
            )

            try:
                text = scraper.get_chapter_text(ch_url)
            except Exception as e:
                self.progress_update.emit(f"Ошибка загрузки главы {ch_number}: {e}", 0)
                continue

            if not text or not text.strip():
                self.progress_update.emit(f"Глава {ch_number}: пустой текст, пропуск", 0)
                continue

            # Перевод названия EN -> RU
            if ch_name:
                ch_name = translate_title(ch_name)

            filename_title = f"Глава {ch_number}"
            if ch_name:
                filename_title += f" - {ch_name}"

            safe_title = re.sub(r'[\\/*?:"<>|]', "", filename_title)

            try:
                from docx import Document
                doc = Document()
                for line in text.split("\n"):
                    line = line.strip()
                    if line:
                        doc.add_paragraph(line)

                filepath = os.path.join(self.save_dir, f"{safe_title}.docx")
                counter = 1
                while os.path.exists(filepath):
                    filepath = os.path.join(self.save_dir, f"{safe_title} ({counter}).docx")
                    counter += 1

                doc.save(filepath)
                self.created_files.append(filepath)
                self.progress_update.emit(
                    f"Сохранен: {os.path.basename(filepath)}",
                    int(100 * ((i + 1) / total))
                )
            except Exception as e:
                self.progress_update.emit(f"Ошибка сохранения главы {ch_number}: {e}", 0)

            elapsed_time = time.time() - self.start_time
            chapters_done = i + 1
            remaining = -1.0
            if chapters_done > 0:
                avg = elapsed_time / chapters_done
                remaining = avg * (total - chapters_done)
            self.time_update.emit(elapsed_time, remaining)

        self.progress_update.emit("Все главы загружены и сохранены", 100)


class DownloadDialog(QDialog):
    """Диалог для отображения прогресса загрузки (RanobeLIB)"""

    def __init__(
        self,
        novel_info: Dict[str, Any],
        selected_chapters: List[Dict[str, Any]],
        selected_formats: List[str],
        api: RanobeLibAPI,
        parser: RanobeLibParser,
        image_handler: ImageHandler,
        save_dir: str,
        options: Dict[str, bool],
        parent=None,
    ):
        super().__init__(parent)
        self.novel_info = novel_info
        self.selected_chapters = selected_chapters
        self.selected_formats = selected_formats
        self.api = api
        self.parser = parser
        self.image_handler = image_handler
        self.save_dir = save_dir
        self.options = options

        self.download_worker = None
        self.created_files = []
        self._close_requested = False

        self._setup_ui()
        self._start_download()

    def _setup_ui(self):
        self.setWindowTitle("Загрузка и создание DOCX")
        self.setMinimumWidth(600)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)

        chapters_group = QGroupBox("Прогресс загрузки глав")
        chapters_layout = QVBoxLayout(chapters_group)

        self.chapters_progress = QProgressBar()
        self.chapters_progress.setMinimum(0)
        self.chapters_progress.setMaximum(len(self.selected_chapters))
        self.chapters_progress.setValue(0)
        chapters_layout.addWidget(self.chapters_progress)

        self.chapters_label = QLabel("0 из 0 глав загружено")
        chapters_layout.addWidget(self.chapters_label)

        time_layout = QHBoxLayout()
        self.elapsed_time_label = QLabel("Прошло: 00:00")
        self.remaining_time_label = QLabel("Осталось: вычисление...")
        time_layout.addWidget(self.elapsed_time_label)
        time_layout.addStretch()
        time_layout.addWidget(self.remaining_time_label)
        chapters_layout.addLayout(time_layout)

        layout.addWidget(chapters_group)

        log_group = QGroupBox("Лог операций")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(150)
        log_layout.addWidget(self.log_text)

        layout.addWidget(log_group)

        buttons_layout = QHBoxLayout()

        self.open_folder_button = QPushButton("Открыть папку")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_folder)
        buttons_layout.addWidget(self.open_folder_button)

        self.close_button = QPushButton("Отмена")
        self.close_button.setObjectName("stopButton")
        self.close_button.clicked.connect(self._cancel_download)
        buttons_layout.addWidget(self.close_button)

        layout.addLayout(buttons_layout)

    def _start_download(self):
        title = self.novel_info.get("rus_name") or self.novel_info.get("eng_name", "Новелла")
        self.log_text.append(f"<b>Начало загрузки новеллы: {title}</b>")
        self.log_text.append(f"Выбрано глав: {len(self.selected_chapters)}")
        self.log_text.append(f"Формат: DOCX (одна глава = один файл)")
        self.log_text.append("─" * 50)

        self.download_worker = DownloadWorker(
            self.novel_info,
            self.selected_chapters,
            self.selected_formats,
            self.api,
            self.parser,
            self.image_handler,
            self.save_dir,
            self.options,
        )

        self.download_worker.progress_update.connect(self._on_progress_update)
        self.download_worker.chapter_download.connect(self._on_chapter_download)
        self.download_worker.time_update.connect(self._on_time_update)
        self.download_worker.finished.connect(self._on_download_finished)
        self.download_worker.error.connect(self._on_download_error)

        self.download_worker.start()

    def _cancel_download(self):
        if self.download_worker and self.download_worker.isRunning():
            self.close_button.setEnabled(False)
            self.log_text.append("<b>Отмена операции...</b>")
            self.download_worker.cancel()

    def closeEvent(self, event):
        if self.download_worker and self.download_worker.isRunning():
            self._close_requested = True
            self._cancel_download()
            event.accept()
        else:
            event.accept()

    def _format_time(self, seconds: float) -> str:
        if seconds < 0:
            return "вычисление..."
        seconds = int(seconds)
        minutes = seconds // 60
        seconds %= 60
        return f"{minutes:02d}:{seconds:02d}"

    def _on_progress_update(self, message: str, progress: int):
        self.log_text.append(message)

    def _on_chapter_download(self, current: int, total: int):
        self.chapters_progress.setValue(current)
        self.chapters_label.setText(f"{current} из {total} глав загружено")

    def _on_time_update(self, elapsed: float, remaining: float):
        self.elapsed_time_label.setText(f"Прошло: {self._format_time(elapsed)}")
        self.remaining_time_label.setText(f"Осталось: ~{self._format_time(remaining)}")

    def _on_download_finished(self, created_files: List[str]):
        self.created_files = created_files

        self.log_text.append("─" * 50)
        if self.download_worker and self.download_worker.is_cancelled:
            self.log_text.append("<b>Загрузка отменена</b>")
        else:
            self.log_text.append("<b>Загрузка завершена</b>")

        if self.download_worker:
            elapsed = time.time() - self.download_worker.start_time
            self.elapsed_time_label.setText(f"Прошло: {self._format_time(elapsed)}")
            self.remaining_time_label.setText("Осталось: 00:00")

        if created_files:
            self.log_text.append(f"<b>Создано файлов: {len(created_files)}</b>")
            self.open_folder_button.setEnabled(True)

        self.close_button.setText("Закрыть")
        self.close_button.setObjectName("")
        self.close_button.setEnabled(True)
        try:
            self.close_button.clicked.disconnect(self._cancel_download)
        except TypeError:
            pass
        self.close_button.clicked.connect(self.accept)

        if self._close_requested:
            self.accept()

    def _open_folder(self):
        if os.path.isdir(self.save_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(self.save_dir)))

    def _on_download_error(self, error_message: str):
        self.log_text.append(f"<span style='color: #ff3050;'><b>Ошибка:</b> {error_message}</span>")

        if self.download_worker:
            elapsed = time.time() - self.download_worker.start_time
            self.elapsed_time_label.setText(f"Прошло: {self._format_time(elapsed)}")
            self.remaining_time_label.setText("Осталось: --:--")

        self.close_button.setText("Закрыть")
        self.close_button.setEnabled(True)
        try:
            self.close_button.clicked.disconnect(self._cancel_download)
        except TypeError:
            pass
        self.close_button.clicked.connect(self.accept)

        if self._close_requested:
            self.accept()


class ExternalDownloadDialog(QDialog):
    """Диалог для загрузки глав с внешних сайтов (webnovel, mvlempyr)"""

    def __init__(self, book_info, chapters, site_type, save_dir, parent=None):
        super().__init__(parent)
        self.book_info = book_info
        self.chapters = chapters
        self.site_type = site_type
        self.save_dir = save_dir

        self.download_worker = None
        self.created_files = []
        self._close_requested = False

        self._setup_ui()
        self._start_download()

    def _setup_ui(self):
        site_name = "WebNovel" if self.site_type == "webnovel" else "MvlEmpyr"
        self.setWindowTitle(f"Загрузка с {site_name}")
        self.setMinimumWidth(600)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)

        chapters_group = QGroupBox("Прогресс загрузки глав")
        chapters_layout = QVBoxLayout(chapters_group)

        self.chapters_progress = QProgressBar()
        self.chapters_progress.setMinimum(0)
        self.chapters_progress.setMaximum(len(self.chapters))
        self.chapters_progress.setValue(0)
        chapters_layout.addWidget(self.chapters_progress)

        self.chapters_label = QLabel("0 из 0 глав загружено")
        chapters_layout.addWidget(self.chapters_label)

        time_layout = QHBoxLayout()
        self.elapsed_time_label = QLabel("Прошло: 00:00")
        self.remaining_time_label = QLabel("Осталось: вычисление...")
        time_layout.addWidget(self.elapsed_time_label)
        time_layout.addStretch()
        time_layout.addWidget(self.remaining_time_label)
        chapters_layout.addLayout(time_layout)

        layout.addWidget(chapters_group)

        log_group = QGroupBox("Лог операций")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(150)
        log_layout.addWidget(self.log_text)

        layout.addWidget(log_group)

        buttons_layout = QHBoxLayout()

        self.open_folder_button = QPushButton("Открыть папку")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_folder)
        buttons_layout.addWidget(self.open_folder_button)

        self.close_button = QPushButton("Отмена")
        self.close_button.setObjectName("stopButton")
        self.close_button.clicked.connect(self._cancel_download)
        buttons_layout.addWidget(self.close_button)

        layout.addLayout(buttons_layout)

    def _start_download(self):
        title = self.book_info.get("title", "Новелла")
        self.log_text.append(f"<b>Начало загрузки: {title}</b>")
        self.log_text.append(f"Глав к загрузке: {len(self.chapters)}")
        self.log_text.append(f"Формат: DOCX (одна глава = один файл)")
        self.log_text.append("─" * 50)

        self.download_worker = ExternalDownloadWorker(
            self.book_info, self.chapters, self.site_type, self.save_dir
        )

        self.download_worker.progress_update.connect(self._on_progress_update)
        self.download_worker.chapter_download.connect(self._on_chapter_download)
        self.download_worker.time_update.connect(self._on_time_update)
        self.download_worker.finished.connect(self._on_download_finished)
        self.download_worker.error.connect(self._on_download_error)

        self.download_worker.start()

    def _cancel_download(self):
        if self.download_worker and self.download_worker.isRunning():
            self.close_button.setEnabled(False)
            self.log_text.append("<b>Отмена операции...</b>")
            self.download_worker.cancel()

    def closeEvent(self, event):
        if self.download_worker and self.download_worker.isRunning():
            self._close_requested = True
            self._cancel_download()
            event.accept()
        else:
            event.accept()

    def _format_time(self, seconds: float) -> str:
        if seconds < 0:
            return "вычисление..."
        seconds = int(seconds)
        minutes = seconds // 60
        seconds %= 60
        return f"{minutes:02d}:{seconds:02d}"

    def _on_progress_update(self, message: str, progress: int):
        self.log_text.append(message)

    def _on_chapter_download(self, current: int, total: int):
        self.chapters_progress.setValue(current)
        self.chapters_label.setText(f"{current} из {total} глав загружено")

    def _on_time_update(self, elapsed: float, remaining: float):
        self.elapsed_time_label.setText(f"Прошло: {self._format_time(elapsed)}")
        self.remaining_time_label.setText(f"Осталось: ~{self._format_time(remaining)}")

    def _on_download_finished(self, created_files: List[str]):
        self.created_files = created_files

        self.log_text.append("─" * 50)
        if self.download_worker and self.download_worker.is_cancelled:
            self.log_text.append("<b>Загрузка отменена</b>")
        else:
            self.log_text.append("<b>Загрузка завершена</b>")

        if self.download_worker:
            elapsed = time.time() - self.download_worker.start_time
            self.elapsed_time_label.setText(f"Прошло: {self._format_time(elapsed)}")
            self.remaining_time_label.setText("Осталось: 00:00")

        if created_files:
            self.log_text.append(f"<b>Создано файлов: {len(created_files)}</b>")
            self.open_folder_button.setEnabled(True)

        self.close_button.setText("Закрыть")
        self.close_button.setObjectName("")
        self.close_button.setEnabled(True)
        try:
            self.close_button.clicked.disconnect(self._cancel_download)
        except TypeError:
            pass
        self.close_button.clicked.connect(self.accept)

        if self._close_requested:
            self.accept()

    def _open_folder(self):
        if os.path.isdir(self.save_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(self.save_dir)))

    def _on_download_error(self, error_message: str):
        self.log_text.append(f"<span style='color: #ff3050;'><b>Ошибка:</b> {error_message}</span>")

        if self.download_worker:
            elapsed = time.time() - self.download_worker.start_time
            self.elapsed_time_label.setText(f"Прошло: {self._format_time(elapsed)}")
            self.remaining_time_label.setText("Осталось: --:--")

        self.close_button.setText("Закрыть")
        self.close_button.setEnabled(True)
        try:
            self.close_button.clicked.disconnect(self._cancel_download)
        except TypeError:
            pass
        self.close_button.clicked.connect(self.accept)

        if self._close_requested:
            self.accept()
