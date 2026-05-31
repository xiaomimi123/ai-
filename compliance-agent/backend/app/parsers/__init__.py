"""文档解析模块：统一入口 + 策略分发（§3.2）。"""
from app.parsers.base import ParsedDocument, PageBlock
from app.parsers.dispatcher import parse, SUPPORTED_EXTENSIONS

__all__ = ["parse", "ParsedDocument", "PageBlock", "SUPPORTED_EXTENSIONS"]
