from __future__ import annotations

from pathlib import Path


MAX_WORKBOOK_BYTES = 30 * 1024 * 1024


class LocalExcelSource:
    @staticmethod
    def validate_metadata(content: bytes, filename: str) -> str:
        if Path(filename).suffix.casefold() != ".xlsx":
            raise ValueError("当前仅支持.xlsx格式的TDRX评审表")
        if not content:
            raise ValueError("上传的Excel文件为空")
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ValueError("Excel文件超过30MB限制")
        return Path(filename).name

    @staticmethod
    def validate_xlsx_structure(content: bytes) -> None:
        if not content.startswith(b"PK"):
            raise ValueError("文件内容不是有效的.xlsx工作簿")

    @staticmethod
    def from_bytes(content: bytes, filename: str) -> tuple[bytes, str]:
        source_name = LocalExcelSource.validate_metadata(content, filename)
        LocalExcelSource.validate_xlsx_structure(content)
        return content, source_name
