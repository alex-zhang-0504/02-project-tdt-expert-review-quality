from __future__ import annotations

from pathlib import Path


MAX_WORKBOOK_BYTES = 30 * 1024 * 1024


class LocalExcelSource:
    @staticmethod
    def from_bytes(content: bytes, filename: str) -> tuple[bytes, str]:
        if Path(filename).suffix.casefold() != ".xlsx":
            raise ValueError("当前仅支持.xlsx格式的TDRX评审表")
        if not content:
            raise ValueError("上传的Excel文件为空")
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ValueError("Excel文件超过30MB限制")
        if not content.startswith(b"PK"):
            raise ValueError("文件内容不是有效的.xlsx工作簿")
        return content, Path(filename).name
