"""
RanobeLIB API - модуль для скачивания новелл с сайта RanobeLIB
"""

from .api import RanobeLibAPI
from .auth import RanobeLibAuth
from .branches import get_branch_info_for_display, get_formatted_branches_with_teams
from .creators import DocxCreator, EpubCreator, Fb2Creator, HtmlCreator, TxtCreator
from .img import ImageHandler
from .parser import RanobeLibParser
from .processing import ContentProcessor
from .scrapers import detect_site, SITE_RANOBELIB, SITE_WEBNOVEL, SITE_MVLEMPYR
from .settings import Settings, settings
from .translate import translate_title

__version__ = "0.4"

__all__ = [
    "ContentProcessor",
    "detect_site",
    "DocxCreator",
    "EpubCreator",
    "Fb2Creator",
    "get_branch_info_for_display",
    "get_formatted_branches_with_teams",
    "HtmlCreator",
    "ImageHandler",
    "RanobeLibAPI",
    "RanobeLibAuth",
    "RanobeLibParser",
    "Settings",
    "settings",
    "SITE_MVLEMPYR",
    "SITE_RANOBELIB",
    "SITE_WEBNOVEL",
    "translate_title",
    "TxtCreator",
] 