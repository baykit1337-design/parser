"""
Модуль для автоматического перевода названий глав EN -> RU
"""

import re


def is_english(text):
    """Проверяет, содержит ли текст преимущественно латинские символы."""
    if not text or not text.strip():
        return False
    latin_chars = sum(1 for c in text if c.isalpha() and ord(c) < 128)
    all_alpha = sum(1 for c in text if c.isalpha())
    if all_alpha == 0:
        return False
    return latin_chars / all_alpha > 0.7


def translate_title(text):
    """Переводит название главы с английского на русский.
    Если перевод не удался — возвращает оригинал.
    """
    if not text or not text.strip():
        return text

    if not is_english(text):
        return text

    try:
        from deep_translator import GoogleTranslator
        result = GoogleTranslator(source="en", target="ru").translate(text)
        if result:
            return result
    except Exception:
        pass

    return text
