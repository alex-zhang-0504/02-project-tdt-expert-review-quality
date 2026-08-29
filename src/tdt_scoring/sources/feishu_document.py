from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


SUPPORTED_HOSTS = ("feishu.cn", "larksuite.com", "doubao.com")
SUPPORTED_PATH_PARTS = ("/sheets/", "/spreadsheets/", "/wiki/")
FOLDER_PATH_PART = "/drive/folder/"
READ_SCOPES = (
    "sheets:spreadsheet:read",
    "docs:document:export",
    "drive:drive:readonly",
    "drive:drive.metadata:readonly",
)


@dataclass(slots=True)
class FeishuWorkbookExport:
    source_name: str
    content: bytes | None
    error: str | None = None


@dataclass(slots=True)
class FeishuFolderExport:
    source_name: str
    discovered_count: int
    candidate_count: int
    excluded_count: int
    excluded_names: list[str]
    workbooks: list[FeishuWorkbookExport]


class FeishuDocumentSource:
    @staticmethod
    def _cli_path() -> str:
        cli = shutil.which("lark-cli")
        if not cli:
            raise RuntimeError("未找到lark-cli，请先安装并初始化飞书命令行工具")
        return cli

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = os.environ.copy()
        environment["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
        environment["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
        return environment

    @staticmethod
    def _run_cli(
        arguments: list[str], *, cwd: str | Path | None = None, timeout: int = 180
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [FeishuDocumentSource._cli_path(), *arguments],
            cwd=cwd,
            env=FeishuDocumentSource._environment(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    @staticmethod
    def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
        value = (result.stdout or "").strip()
        if value:
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                return payload
        return {}

    @staticmethod
    def _error_message(result: subprocess.CompletedProcess[str]) -> str:
        payload = FeishuDocumentSource._payload(result)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            subtype = str(error.get("subtype", ""))
            message = str(error.get("message", "")).strip()
            if subtype in {"token_missing", "token_expired"} or "need_user_authorization" in message:
                return "飞书用户授权缺失或已失效，请先点击“授权飞书读取”"
            hint = str(error.get("hint", ""))
            if "scope" in hint.casefold() or "permission" in subtype.casefold():
                return "飞书只读权限不足，请重新授权表格读取、文档导出和云盘元数据权限"
            if message:
                return message
        detail = (result.stderr or result.stdout).strip()
        return detail.splitlines()[-1] if detail else "飞书命令执行失败"

    @staticmethod
    def validate_url(url: str) -> str:
        value = url.strip()
        parsed = urlparse(value)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme not in {"http", "https"} or not host:
            raise ValueError("请输入完整的飞书云文档URL")
        if not any(host == domain or host.endswith(f".{domain}") for domain in SUPPORTED_HOSTS):
            raise ValueError("URL不是受支持的飞书／Lark云文档地址")
        if not any(part in parsed.path.casefold() for part in SUPPORTED_PATH_PARTS):
            raise ValueError("当前支持飞书电子表格URL，或指向电子表格的Wiki URL")
        return value

    @staticmethod
    def validate_folder_url(url: str) -> str:
        value = url.strip()
        parsed = urlparse(value)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme not in {"http", "https"} or not host:
            raise ValueError("请输入完整的飞书归档文件夹URL")
        if not any(host == domain or host.endswith(f".{domain}") for domain in SUPPORTED_HOSTS):
            raise ValueError("URL不是受支持的飞书／Lark云空间地址")
        if not FeishuDocumentSource.is_folder_url(value):
            raise ValueError("请输入形如/drive/folder/<token>的飞书归档文件夹URL")
        if not FeishuDocumentSource._folder_token(value):
            raise ValueError("飞书归档文件夹URL缺少folder token")
        return value

    @staticmethod
    def is_folder_url(url: str) -> bool:
        return FOLDER_PATH_PART in urlparse(url.strip()).path.casefold()

    @staticmethod
    def _folder_token(url: str) -> str:
        parts = [part for part in urlparse(url).path.split("/") if part]
        lowered = [part.casefold() for part in parts]
        for index in range(len(parts) - 2):
            if lowered[index : index + 2] == ["drive", "folder"]:
                return parts[index + 2]
        return ""

    @staticmethod
    def _spreadsheet_token_from_url(url: str) -> str:
        parts = [part for part in urlparse(url).path.split("/") if part]
        lowered = [part.casefold() for part in parts]
        for marker in ("sheets", "spreadsheets"):
            if marker in lowered:
                index = lowered.index(marker)
                if index + 1 < len(parts):
                    return parts[index + 1]
        return ""

    @staticmethod
    def authorization_status() -> dict[str, object]:
        result = FeishuDocumentSource._run_cli(
            ["auth", "status", "--json", "--verify"], timeout=30
        )
        payload = FeishuDocumentSource._payload(result)
        identities = payload.get("identities", {}) if isinstance(payload, dict) else {}
        user = identities.get("user", {}) if isinstance(identities, dict) else {}
        ready = result.returncode == 0 and isinstance(user, dict) and user.get("status") == "ready"
        return {
            "ready": ready,
            "user_name": user.get("userName") if isinstance(user, dict) else None,
            "message": "飞书用户授权可用" if ready else "尚未完成飞书用户授权",
        }

    @staticmethod
    def start_authorization() -> dict[str, object]:
        result = FeishuDocumentSource._run_cli(
            [
                "auth",
                "login",
                "--scope",
                " ".join(READ_SCOPES),
                "--no-wait",
                "--json",
            ],
            timeout=30,
        )
        payload = FeishuDocumentSource._payload(result)
        if result.returncode != 0 or not payload.get("verification_url"):
            raise RuntimeError(FeishuDocumentSource._error_message(result))
        return {
            "verification_url": payload["verification_url"],
            "device_code": payload["device_code"],
            "expires_in": payload.get("expires_in", 600),
        }

    @staticmethod
    def complete_authorization(device_code: str) -> dict[str, object]:
        result = FeishuDocumentSource._run_cli(
            ["auth", "login", "--device-code", device_code], timeout=610
        )
        if result.returncode != 0:
            raise RuntimeError(FeishuDocumentSource._error_message(result))
        return FeishuDocumentSource.authorization_status()

    @staticmethod
    def export_xlsx(url: str) -> tuple[bytes, str]:
        validated_url = FeishuDocumentSource.validate_url(url)

        with tempfile.TemporaryDirectory(prefix="tdt-scoring-feishu-") as temp_dir:
            output_name = "tdrx-review.xlsx"
            content = FeishuDocumentSource._export_spreadsheet(
                output_name=output_name,
                cwd=temp_dir,
                url=validated_url,
            )
            return content, output_name

    @staticmethod
    def export_folder_xlsx(url: str) -> FeishuFolderExport:
        validated_url = FeishuDocumentSource.validate_folder_url(url)
        folder_token = FeishuDocumentSource._folder_token(validated_url)
        items = FeishuDocumentSource._list_folder_items(folder_token)
        excluded_names: list[str] = []
        candidates: list[tuple[str, str | None, str | None]] = []
        seen_tokens: dict[str, str] = {}

        for item in items:
            name = str(item.get("name") or "未命名飞书资源").strip() or "未命名飞书资源"
            item_type = str(item.get("type") or "").casefold()
            token = ""
            candidate_error: str | None = None
            if item_type == "sheet":
                token = str(item.get("token") or "").strip()
                if not token:
                    candidate_error = "电子表格条目缺少spreadsheet token"
            elif item_type == "shortcut":
                shortcut = item.get("shortcut_info")
                target_type = ""
                if isinstance(shortcut, dict):
                    target_type = str(shortcut.get("target_type") or "").casefold()
                    if target_type == "sheet":
                        token = str(shortcut.get("target_token") or "").strip()
                    elif target_type:
                        excluded_names.append(name)
                        continue
                if not token:
                    token = FeishuDocumentSource._spreadsheet_token_from_url(
                        str(item.get("url") or "")
                    )
                if not token:
                    candidate_error = "快捷方式无法确认其电子表格目标"
            else:
                excluded_names.append(name)
                continue

            if token and token in seen_tokens:
                candidate_error = f"与“{seen_tokens[token]}”重复指向同一飞书工作簿"
                token = ""
            elif token:
                seen_tokens[token] = name
            candidates.append((name, token or None, candidate_error))

        workbooks: list[FeishuWorkbookExport] = []
        with tempfile.TemporaryDirectory(prefix="tdt-scoring-feishu-folder-") as temp_dir:
            for index, (name, token, candidate_error) in enumerate(candidates, start=1):
                if candidate_error or not token:
                    workbooks.append(
                        FeishuWorkbookExport(name, None, candidate_error or "无法解析电子表格目标")
                    )
                    continue
                try:
                    content = FeishuDocumentSource._export_spreadsheet(
                        spreadsheet_token=token,
                        output_name=f"report-{index}.xlsx",
                        cwd=temp_dir,
                    )
                    workbooks.append(FeishuWorkbookExport(name, content))
                except RuntimeError as exc:
                    workbooks.append(FeishuWorkbookExport(name, None, str(exc)))

        return FeishuFolderExport(
            source_name="飞书归档文件夹",
            discovered_count=len(items),
            candidate_count=len(candidates),
            excluded_count=len(excluded_names),
            excluded_names=excluded_names,
            workbooks=workbooks,
        )

    @staticmethod
    def _list_folder_items(folder_token: str) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        page_token = ""
        visited_pages: set[str] = set()
        missing_token_retries = 0
        while True:
            params: dict[str, object] = {"folder_token": folder_token, "page_size": 200}
            if page_token:
                params["page_token"] = page_token
            result = FeishuDocumentSource._run_cli(
                [
                    "drive",
                    "files",
                    "list",
                    "--params",
                    json.dumps(params, ensure_ascii=False, separators=(",", ":")),
                    "--format",
                    "json",
                    "--as",
                    "user",
                ],
                timeout=60,
            )
            if result.returncode != 0:
                raise RuntimeError(FeishuDocumentSource._error_message(result))
            payload = FeishuDocumentSource._payload(result)
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict) or not isinstance(data.get("files"), list):
                raise RuntimeError("飞书文件夹清单返回格式异常，无法确认批次完整性")
            page_key = page_token or "first"
            if page_key not in visited_pages:
                for item in data["files"]:
                    if isinstance(item, dict):
                        items.append(item)
                visited_pages.add(page_key)
            if data.get("has_more") is not True:
                return items
            next_page_token = str(data.get("next_page_token") or "").strip()
            if next_page_token:
                if next_page_token in visited_pages:
                    raise RuntimeError("飞书文件夹分页标记重复，无法确认批次完整性")
                page_token = next_page_token
                missing_token_retries = 0
                continue
            missing_token_retries += 1
            if missing_token_retries >= 3:
                raise RuntimeError("飞书文件夹尚有下一页但未返回分页标记，无法确认批次完整性")

    @staticmethod
    def _export_spreadsheet(
        *,
        output_name: str,
        cwd: str | Path,
        url: str | None = None,
        spreadsheet_token: str | None = None,
    ) -> bytes:
        if bool(url) == bool(spreadsheet_token):
            raise ValueError("飞书表格导出必须且只能指定URL或spreadsheet token之一")
        locator = ["--url", url] if url else ["--spreadsheet-token", spreadsheet_token]
        result = FeishuDocumentSource._run_cli(
            [
                "sheets",
                "+workbook-export",
                *[str(value) for value in locator],
                "--file-extension",
                "xlsx",
                "--output-path",
                f"./{output_name}",
                "--as",
                "user",
            ],
            cwd=cwd,
            timeout=180,
        )
        output_path = Path(cwd, output_name)
        if result.returncode != 0:
            raise RuntimeError(FeishuDocumentSource._error_message(result))
        if not output_path.is_file():
            raise RuntimeError("飞书表格导出完成，但没有生成本地.xlsx文件")
        return output_path.read_bytes()
