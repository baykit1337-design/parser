"""
Виджет с настройками для скачивания и переименования файлов
"""

import base64
import glob
import os
import re
import shutil
from typing import Any, Dict, List

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..settings import settings


class SettingsWidget(QWidget):
    """Виджет с настройками для скачивания"""

    settings_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.format_checkboxes = {}
        self.option_checkboxes = {}
        self._setup_ui()
        self._load_settings()
        self._connect_signals()

    def _setup_ui(self):
        """Настройка интерфейса виджета"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 10, 0, 0)

        settings_title_label = QLabel("Настройки")
        font = settings_title_label.font()
        font.setBold(True)
        settings_title_label.setFont(font)
        main_layout.addWidget(settings_title_label)

        content_frame = QFrame()
        content_frame.setObjectName("contentFrame")
        settings_layout = QVBoxLayout(content_frame)

        self.option_checkboxes["download_cover"] = QCheckBox("Скачивать обложку")
        self.option_checkboxes["download_cover"].setChecked(True)
        self.option_checkboxes["download_cover"].setToolTip("Включает скачивание обложки новеллы")
        settings_layout.addWidget(self.option_checkboxes["download_cover"])

        self.option_checkboxes["download_images"] = QCheckBox("Скачивать изображения из глав")
        self.option_checkboxes["download_images"].setChecked(True)
        self.option_checkboxes["download_images"].setToolTip(
            "Включает скачивание изображений из глав"
        )
        settings_layout.addWidget(self.option_checkboxes["download_images"])

        self.option_checkboxes["compress_images"] = QCheckBox("Сжимать изображения")
        self.option_checkboxes["compress_images"].setChecked(True)
        self.option_checkboxes["compress_images"].setToolTip(
            "Ограничение высоты/ширины изображений до 800px"
        )
        settings_layout.addWidget(self.option_checkboxes["compress_images"])

        self.option_checkboxes["add_translator"] = QCheckBox("Добавлять данные о переводчике")
        self.option_checkboxes["add_translator"].setChecked(False)
        self.option_checkboxes["add_translator"].setToolTip(
            "Добавляет строку с переводчиком после названия главы"
        )
        settings_layout.addWidget(self.option_checkboxes["add_translator"])

        self.option_checkboxes["group_by_volumes"] = QCheckBox("Группировать главы по томам")
        self.option_checkboxes["group_by_volumes"].setChecked(True)
        self.option_checkboxes["group_by_volumes"].setToolTip(
            "Группировка по томам вместо указания тома в названии главы"
        )
        settings_layout.addWidget(self.option_checkboxes["group_by_volumes"])

        settings_layout.setSpacing(3)

        format_label = QLabel("Формат: DOCX (одна глава = один файл)")
        format_label.setStyleSheet("margin-top: 5px; color: #0070ff;")
        settings_layout.addWidget(format_label)

        path_label = QLabel("Каталог для сохранения:")
        path_label.setStyleSheet("margin-top: 5px;")
        settings_layout.addWidget(path_label)

        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setText(os.path.abspath("downloads"))
        self.path_edit.setReadOnly(True)
        path_layout.addWidget(self.path_edit)

        self.browse_button = QPushButton("...")
        self.browse_button.setFixedWidth(30)
        self.browse_button.setToolTip("Выбрать каталог")
        self.browse_button.clicked.connect(self._browse_directory)
        path_layout.addWidget(self.browse_button)

        settings_layout.addLayout(path_layout)
        main_layout.addWidget(content_frame)

        self.download_button = QPushButton(" Скачать")
        self.download_button.setMinimumHeight(40)
        self.download_button.setObjectName("downloadButton")

        base64_icon = "PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHdpZHRoPScyNCcgaGVpZ2h0PScyNCcgdmlld0JveD0nMCAwIDI0IDI0Jz48ZyBmaWxsPScjZmZmZmZmJyBmaWxsLXJ1bGU9J2V2ZW5vZGQnIGNsaXAtcnVsZT0nZXZlbm9kZCc+PHBhdGggZD0nTTEzIDExLjE1VjRhMSAxIDAgMSAwLTIgMHY3LjE1TDguNzggOC4zNzRhMSAxIDAgMSAwLTEuNTYgMS4yNWw0IDVhMSAxIDAgMCAwIDEuNTYgMGw0LTVhMSAxIDAgMSAwLTEuNTYtMS4yNXonLz48cGF0aCBkPSdNOS42NTcgMTUuODc0TDcuMzU4IDEzSDVhMiAyIDAgMCAwLTIgMnY0YTIgMiAwIDAgMCAyIDJoMTRhMiAyIDAgMCAwIDItMnYtNGEyIDIgMCAwIDAtMi0yaC0yLjM1OGwtMi4zIDIuODc0YTMgMyAwIDAgMS00LjY4NSAwTTE3IDE2YTEgMSAwIDEgMCAwIDJoLjAxYTEgMSAwIDEgMCAwLTJ6Jy8+PC9nPjwvc3ZnPg=="
        pixmap = QPixmap()
        pixmap.loadFromData(base64.b64decode(base64_icon))
        icon = QIcon(pixmap)
        self.download_button.setIcon(icon)

        main_layout.addWidget(self.download_button)

        # --- Секция переименования файлов ---
        rename_title_label = QLabel("Переименование файлов")
        rename_title_label.setStyleSheet("margin-top: 10px;")
        font2 = rename_title_label.font()
        font2.setBold(True)
        rename_title_label.setFont(font2)
        main_layout.addWidget(rename_title_label)

        rename_frame = QFrame()
        rename_frame.setObjectName("renameFrame")
        rename_layout = QVBoxLayout(rename_frame)

        src_label = QLabel("Папка-источник:")
        rename_layout.addWidget(src_label)

        src_path_layout = QHBoxLayout()
        self.rename_src_edit = QLineEdit()
        self.rename_src_edit.setReadOnly(True)
        self.rename_src_edit.setPlaceholderText("Выберите папку с .docx файлами")
        src_path_layout.addWidget(self.rename_src_edit)

        self.rename_src_button = QPushButton("...")
        self.rename_src_button.setFixedWidth(30)
        self.rename_src_button.setToolTip("Выбрать папку-источник")
        self.rename_src_button.clicked.connect(self._browse_rename_src)
        src_path_layout.addWidget(self.rename_src_button)
        rename_layout.addLayout(src_path_layout)

        dst_label = QLabel("Папка-назначение:")
        rename_layout.addWidget(dst_label)

        dst_path_layout = QHBoxLayout()
        self.rename_dst_edit = QLineEdit()
        self.rename_dst_edit.setReadOnly(True)
        self.rename_dst_edit.setPlaceholderText("Выберите папку для результата")
        dst_path_layout.addWidget(self.rename_dst_edit)

        self.rename_dst_button = QPushButton("...")
        self.rename_dst_button.setFixedWidth(30)
        self.rename_dst_button.setToolTip("Выбрать папку-назначение")
        self.rename_dst_button.clicked.connect(self._browse_rename_dst)
        dst_path_layout.addWidget(self.rename_dst_button)
        rename_layout.addLayout(dst_path_layout)

        rename_buttons_layout = QHBoxLayout()

        self.preview_rename_button = QPushButton("Превью")
        self.preview_rename_button.setObjectName("previewRenameButton")
        self.preview_rename_button.setToolTip("Показать как будут выглядеть имена до/после")
        self.preview_rename_button.clicked.connect(self._preview_rename)
        rename_buttons_layout.addWidget(self.preview_rename_button)

        self.rename_button = QPushButton("Переименовать")
        self.rename_button.setObjectName("renameButton")
        self.rename_button.setToolTip("Копировать файлы с удалением 'Том N' из имени")
        self.rename_button.clicked.connect(self._do_rename)
        rename_buttons_layout.addWidget(self.rename_button)

        rename_layout.addLayout(rename_buttons_layout)

        self.rename_log = QTextEdit()
        self.rename_log.setReadOnly(True)
        self.rename_log.setMaximumHeight(120)
        self.rename_log.setPlaceholderText("Лог переименования...")
        rename_layout.addWidget(self.rename_log)

        main_layout.addWidget(rename_frame)
        main_layout.addStretch()

    def _load_settings(self):
        """Загрузка настроек из модуля settings"""
        for key, checkbox in self.option_checkboxes.items():
            checkbox.setChecked(settings.get(key))

        self.path_edit.setText(settings.get("save_directory"))

    def _connect_signals(self):
        """Подключение сигналов к слотам"""
        for key, checkbox in self.option_checkboxes.items():
            checkbox.stateChanged.connect(lambda state, k=key: self._save_option(k, bool(state)))

        self.path_edit.textChanged.connect(lambda text: self._save_option("save_directory", text))

    def _save_option(self, key: str, value: Any):
        """Сохранение отдельной настройки"""
        settings.set(key, value)
        self.settings_changed.emit()

    def _browse_directory(self):
        """Открывает диалог выбора директории для сохранения файлов"""
        directory = QFileDialog.getExistingDirectory(
            self, "Выберите каталог для сохранения", self.path_edit.text()
        )
        if directory:
            self.path_edit.setText(os.path.normpath(directory))

    def _browse_rename_src(self):
        """Выбор папки-источника для переименования"""
        directory = QFileDialog.getExistingDirectory(
            self, "Выберите папку-источник", self.rename_src_edit.text() or ""
        )
        if directory:
            self.rename_src_edit.setText(os.path.normpath(directory))

    def _browse_rename_dst(self):
        """Выбор папки-назначения для переименования"""
        directory = QFileDialog.getExistingDirectory(
            self, "Выберите папку-назначение", self.rename_dst_edit.text() or ""
        )
        if directory:
            self.rename_dst_edit.setText(os.path.normpath(directory))

    @staticmethod
    def _remove_volume_prefix(filename):
        """Убирает 'Том N ' из имени файла."""
        return re.sub(r'^Том\s+\d+\s+', '', filename)

    def _get_docx_files(self):
        """Возвращает список .docx файлов из папки-источника."""
        src_dir = self.rename_src_edit.text()
        if not src_dir or not os.path.isdir(src_dir):
            return []
        return sorted(glob.glob(os.path.join(src_dir, "*.docx")))

    def _preview_rename(self):
        """Показывает превью переименования в логе."""
        self.rename_log.clear()
        files = self._get_docx_files()
        if not files:
            self.rename_log.append("Нет .docx файлов в папке-источнике")
            return

        self.rename_log.append(f"<b>Найдено файлов: {len(files)}</b>")
        self.rename_log.append("")
        for filepath in files:
            old_name = os.path.basename(filepath)
            new_name = self._remove_volume_prefix(old_name)
            if old_name != new_name:
                self.rename_log.append(f"{old_name}  →  <b>{new_name}</b>")
            else:
                self.rename_log.append(f"{old_name}  (без изменений)")

    def _do_rename(self):
        """Копирует .docx файлы в папку-назначение, убирая 'Том N' из имени."""
        self.rename_log.clear()
        src_dir = self.rename_src_edit.text()
        dst_dir = self.rename_dst_edit.text()

        if not src_dir or not os.path.isdir(src_dir):
            self.rename_log.append("<span style='color: #ff0040;'>Укажите папку-источник</span>")
            return
        if not dst_dir:
            self.rename_log.append("<span style='color: #ff0040;'>Укажите папку-назначение</span>")
            return

        files = self._get_docx_files()
        if not files:
            self.rename_log.append("Нет .docx файлов в папке-источнике")
            return

        os.makedirs(dst_dir, exist_ok=True)
        count = 0
        for filepath in files:
            old_name = os.path.basename(filepath)
            new_name = self._remove_volume_prefix(old_name)
            dst_path = os.path.join(dst_dir, new_name)
            try:
                shutil.copy2(filepath, dst_path)
                count += 1
            except Exception as e:
                self.rename_log.append(
                    f"<span style='color: #ff0040;'>Ошибка: {old_name} — {e}</span>"
                )

        self.rename_log.append(f"<b>Скопировано файлов: {count} из {len(files)}</b>")

    def get_selected_formats(self) -> List[str]:
        """Возвращает список выбранных форматов (только DOCX)"""
        return ["DOCX"]

    def get_save_directory(self) -> str:
        """Возвращает выбранный каталог для сохранения"""
        return self.path_edit.text()

    def set_save_directory(self, directory: str):
        """Устанавливает каталог для сохранения"""
        self.path_edit.setText(os.path.normpath(directory))

    def get_options(self) -> Dict[str, bool]:
        """Возвращает словарь с настройками опций"""
        return {key: checkbox.isChecked() for key, checkbox in self.option_checkboxes.items()}

    def get_focus_chain(self) -> List[QWidget]:
        """Возвращает виджеты настроек в порядке табуляции."""
        chain: List[QWidget] = []

        for key in ["download_cover", "download_images", "compress_images", "add_translator", "group_by_volumes"]:
            checkbox = self.option_checkboxes.get(key)
            if checkbox is not None:
                chain.append(checkbox)

        chain.append(self.path_edit)
        chain.append(self.browse_button)
        chain.append(self.download_button)
        chain.append(self.rename_src_edit)
        chain.append(self.rename_src_button)
        chain.append(self.rename_dst_edit)
        chain.append(self.rename_dst_button)
        chain.append(self.preview_rename_button)
        chain.append(self.rename_button)
        return chain
