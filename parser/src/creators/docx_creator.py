"""
Модуль для создания DOCX файлов (одна глава = один файл)
"""

import os
import re

from bs4 import BeautifulSoup
from docx import Document

from ..processing import ContentProcessor


class DocxCreator(ContentProcessor):
    """Класс для создания DOCX-файлов (по одному на главу)"""

    @property
    def format_name(self) -> str:
        return "DOCX"

    def create_single_chapter(self, prepared_chapter, novel_info, save_dir, total_volumes):
        """Создание одного .docx файла для одной главы."""
        vol_num = str(prepared_chapter["volume"])
        number = prepared_chapter["number"]
        ch_name = self.parser.decode_html_entities(
            prepared_chapter.get("name", "").strip()
        )

        if total_volumes > 1 and vol_num != "0":
            filename_title = f"Том {vol_num} Глава {number}"
        else:
            filename_title = f"Глава {number}"

        if ch_name:
            filename_title += f" - {ch_name}"

        safe_title = re.sub(r'[\\/*?:"<>|]', "", filename_title)

        doc = Document()

        html_content = prepared_chapter.get("html", "")
        paragraphs = self._html_to_paragraphs(html_content)

        for text in paragraphs:
            if text.strip():
                doc.add_paragraph(text.strip())

        os.makedirs(save_dir, exist_ok=True)
        filepath = os.path.join(save_dir, f"{safe_title}.docx")

        counter = 1
        while os.path.exists(filepath):
            filepath = os.path.join(save_dir, f"{safe_title} ({counter}).docx")
            counter += 1

        doc.save(filepath)
        return filepath

    def _html_to_paragraphs(self, html):
        """Извлечение чистого текста из HTML, разбитого на параграфы."""
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup.find_all(["img", "style", "script"]):
            tag.decompose()

        paragraphs = []
        for p_tag in soup.find_all("p"):
            text = p_tag.get_text(separator=" ").strip()
            if text:
                paragraphs.append(text)

        if not paragraphs:
            text = soup.get_text(separator="\n")
            for line in text.splitlines():
                line = line.strip()
                if line:
                    paragraphs.append(line)

        return paragraphs

    def create(self, novel_info, chapters_data, selected_branch_id=None):
        """Не используется для DOCX — используем create_single_chapter."""
        raise NotImplementedError("Используйте create_single_chapter для DOCX")
