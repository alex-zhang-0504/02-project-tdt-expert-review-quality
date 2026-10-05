from __future__ import annotations

import unittest
import json
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tdt_scoring.report_owner import read_owner_url
from tdt_scoring.sources.feishu_document import FeishuDocumentSource
from tdt_scoring.sources.local_excel import LocalExcelSource


class SourceTests(unittest.TestCase):
    def setUp(self):
        mock = patch('tdt_scoring.report_owner.read_owners', side_effect=lambda tokens: {t: {} for t in tokens})
        mock.start()
        self.addCleanup(mock.stop)

    def test_feishu_sheet_and_wiki_urls_are_supported(self) -> None:
        urls = (
            "https://example.feishu.cn/sheets/abc123",
            "https://example.larksuite.com/wiki/abc123",
            "https://doubao.com/spreadsheets/abc123",
        )

        self.assertEqual(list(urls), [FeishuDocumentSource.validate_url(url) for url in urls])

    def test_non_spreadsheet_feishu_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "电子表格"):
            FeishuDocumentSource.validate_url("https://example.feishu.cn/docx/abc123")

    def test_feishu_folder_url_is_supported_as_its_own_input_type(self) -> None:
        url = "https://example.feishu.cn/drive/folder/fld123?from=copylink"

        self.assertEqual(url, FeishuDocumentSource.validate_folder_url(url))
        self.assertTrue(FeishuDocumentSource.is_folder_url(url))
        self.assertEqual("fld123", FeishuDocumentSource._folder_token(url))

    @patch.object(FeishuDocumentSource, "_run_cli")
    def test_folder_listing_manually_follows_pagination(self, run_cli) -> None:
        run_cli.side_effect = [
            CompletedProcess(
                [],
                0,
                stdout=json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "files": [{"name": "A", "type": "sheet", "token": "s1"}],
                            "has_more": True,
                            "next_page_token": "next-1",
                        },
                    }
                ),
                stderr="",
            ),
            CompletedProcess(
                [],
                0,
                stdout=json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "files": [{"name": "B", "type": "sheet", "token": "s2"}],
                            "has_more": False,
                        },
                    }
                ),
                stderr="",
            ),
        ]

        items = FeishuDocumentSource._list_folder_items("fld123")

        self.assertEqual(["A", "B"], [item["name"] for item in items])
        second_params = json.loads(run_cli.call_args_list[1].args[0][4])
        self.assertEqual("next-1", second_params["page_token"])

    @patch.object(FeishuDocumentSource, "_export_spreadsheet")
    @patch.object(FeishuDocumentSource, "_list_folder_items")
    def test_folder_export_resolves_sheets_shortcuts_and_blocks_duplicates(
        self, list_items, export_spreadsheet
    ) -> None:
        list_items.return_value = [
            {"name": "直接表格", "type": "sheet", "token": "s1"},
            {
                "name": "快捷方式",
                "type": "shortcut",
                "shortcut_info": {"target_type": "sheet", "target_token": "s2"},
            },
            {
                "name": "URL回退",
                "type": "shortcut",
                "url": "https://example.feishu.cn/sheets/s3",
            },
            {"name": "说明文档", "type": "docx", "token": "d1"},
            {"name": "子文件夹", "type": "folder", "token": "f1"},
            {
                "name": "重复快捷方式",
                "type": "shortcut",
                "shortcut_info": {"target_type": "sheet", "target_token": "s1"},
            },
        ]
        export_spreadsheet.side_effect = [b"one", b"two", b"three"]

        result = FeishuDocumentSource.export_folder_xlsx(
            "https://example.feishu.cn/drive/folder/fld123"
        )

        self.assertEqual(6, result.discovered_count)
        self.assertEqual(4, result.candidate_count)
        self.assertEqual(2, result.excluded_count)
        self.assertEqual(["说明文档", "子文件夹"], result.excluded_names)
        self.assertEqual([b"one", b"two", b"three", None], [item.content for item in result.workbooks])
        self.assertIn("重复指向", result.workbooks[-1].error)
        self.assertEqual(3, export_spreadsheet.call_count)

    @patch.object(FeishuDocumentSource, "_export_spreadsheet", return_value=b"xlsx")
    @patch.object(FeishuDocumentSource, "_list_folder_items")
    def test_folder_export_emits_real_candidate_and_export_progress(
        self, list_items, _export_spreadsheet
    ) -> None:
        list_items.return_value = [
            {"name": "报告A", "type": "sheet", "token": "s1"},
        ]
        candidates = []
        events = []

        FeishuDocumentSource.export_folder_xlsx(
            "https://example.feishu.cn/drive/folder/fld123",
            on_candidates=candidates.extend,
            on_progress=events.append,
        )

        self.assertEqual(["报告A"], candidates)
        self.assertEqual(
            [
                ("report_acquisition", "completed"),
                ("xlsx_acquisition", "started"),
                ("xlsx_acquisition", "completed"),
            ],
            [(event.checkpoint_id, event.status) for event in events],
        )
        self.assertGreaterEqual(events[-1].duration_ms, 0)

    def test_cli_error_json_on_stderr_is_reported_instead_of_closing_brace(self) -> None:
        result = CompletedProcess(
            [],
            1,
            stdout="",
            stderr=(
                "token refresh notice\n"
                "{\n"
                '  "error": {"subtype": "token_missing", "message": "need_user_authorization"}\n'
                "}\n"
            ),
        )

        message = FeishuDocumentSource._error_message(result)

        self.assertIn("授权缺失", message)
        self.assertNotEqual("}", message)

    @patch("tdt_scoring.sources.feishu_document.subprocess.run")
    @patch("tdt_scoring.sources.feishu_document.shutil.which", return_value="lark-cli.cmd")
    def test_lark_cli_output_is_decoded_as_utf8(self, _which, run) -> None:
        run.return_value = CompletedProcess([], 0, stdout='{"ok": true}', stderr="")

        FeishuDocumentSource._run_cli(["auth", "status"])

        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    @patch("tdt_scoring.sources.feishu_document.subprocess.run")
    @patch("tdt_scoring.sources.feishu_document.shutil.which", return_value=r"C:\npm\lark-cli.CMD")
    def test_cmd_shim_rejects_shell_metacharacters_before_running(self, _which, run) -> None:
        for value in ("https://example.feishu.cn/sheets/abc?x=1&calc", "a|b", "a>b", "a<b", "a^b", "%PATH%", "a\nb"):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "特殊字符"):
                FeishuDocumentSource._run_cli(["sheets", "+workbook-export", "--url", value])
        run.assert_not_called()

    @patch.object(FeishuDocumentSource, "_run_cli")
    def test_spreadsheet_export_passes_only_scheme_host_and_path(self, run_cli) -> None:
        run_cli.return_value = CompletedProcess([], 0, stdout="", stderr="")
        with TemporaryDirectory() as folder:
            Path(folder, "r.xlsx").write_bytes(b"xlsx")
            FeishuDocumentSource._export_spreadsheet(
                output_name="r.xlsx", cwd=folder,
                url="https://example.feishu.cn/wiki/abc123?from=copylink&sheet=s1#top")
        arguments = run_cli.call_args.args[0]
        self.assertEqual("https://example.feishu.cn/wiki/abc123", arguments[arguments.index("--url") + 1])

    def test_owner_lookup_passes_only_scheme_host_and_path(self) -> None:
        with patch("tdt_scoring.report_owner.request", return_value=({}, "")) as request:
            read_owner_url("https://example.feishu.cn/wiki/abc123?from=copylink&sheet=s1")
        arguments = request.call_args.args[0]
        self.assertEqual("https://example.feishu.cn/wiki/abc123", arguments[arguments.index("--url") + 1])

    def test_local_source_rejects_non_xlsx_content(self) -> None:
        with self.assertRaisesRegex(ValueError, "有效"):
            LocalExcelSource.from_bytes(b"not-a-workbook", "review.xlsx")


if __name__ == "__main__":
    unittest.main()
