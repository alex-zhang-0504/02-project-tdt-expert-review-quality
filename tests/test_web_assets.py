from __future__ import annotations

import unittest
from pathlib import Path


APP_JS = (Path(__file__).resolve().parents[1] / "src" / "web" / "app.js").read_text(
    encoding="utf-8"
)
INDEX_HTML = (Path(__file__).resolve().parents[1] / "src" / "web" / "index.html").read_text(
    encoding="utf-8"
)
STYLES_CSS = (Path(__file__).resolve().parents[1] / "src" / "web" / "styles.css").read_text(
    encoding="utf-8"
)


class WebAssetTests(unittest.TestCase):
    def test_drop_prevents_browser_navigation_and_keeps_multiple_xlsx_files(self) -> None:
        self.assertIn('document.addEventListener("drop"', APP_JS)
        self.assertIn('elements.uploadBox.addEventListener("drop"', APP_JS)
        self.assertIn("event.preventDefault()", APP_JS)
        self.assertIn("useDroppedFiles(event.dataTransfer.files)", APP_JS)
        self.assertIn('elements.file.addEventListener("change"', APP_JS)
        self.assertIn("state.droppedFiles", APP_JS)
        self.assertIn('multiple accept=".xlsx"', INDEX_HTML)
        self.assertIn('formData.append("files", file, file.name)', APP_JS)

    def test_import_only_exposes_upload_and_single_feishu_folder_url(self) -> None:
        self.assertNotIn("local-path", INDEX_HTML)
        self.assertNotIn("include-examples", INDEX_HTML)
        self.assertIn("飞书归档文件夹URL", INDEX_HTML)
        self.assertIn("只读取第一层", INDEX_HTML)
        self.assertEqual(1, INDEX_HTML.count('id="feishu-url"'))

    def test_feishu_folder_batch_summary_blocks_incomplete_results(self) -> None:
        self.assertIn('id="batch-summary"', INDEX_HTML)
        self.assertIn("飞书批次不完整，禁止生成完整年度结果", APP_JS)
        self.assertIn("summary.failed_count", APP_JS)
        self.assertIn("aggregate.errors > 0", APP_JS)

    def test_similar_reviewer_names_require_a_dedicated_confirmation(self) -> None:
        self.assertIn("reviewer_name_similarity", APP_JS)
        self.assertIn("确认均为不同人员", APP_JS)
        self.assertIn("issue.related_locations", APP_JS)
        self.assertIn("${index + 1}．${escapeHtml(location)}", APP_JS)
        self.assertIn(".issue-related-locations span { display: block; }", STYLES_CSS)
        self.assertIn("/api/analysis/confirm-reviewer-names-distinct", APP_JS)
        self.assertIn("confirmation_key", APP_JS)

    def test_quality_check_can_switch_between_reports(self) -> None:
        self.assertIn('id="report-list"', INDEX_HTML)
        self.assertIn("state.selectedReportIndex", APP_JS)
        self.assertIn("selectReport(index)", APP_JS)
        self.assertIn("analysis.reports", APP_JS)

    def test_dimension_one_reviewer_search_supports_three_fuzzy_modes(self) -> None:
        self.assertIn('placeholder="姓名／全拼／首字母"', INDEX_HTML)
        self.assertIn("function isSearchSubsequence", APP_JS)
        self.assertIn("function reviewerMatchesSearch", APP_JS)
        self.assertIn("expert.expert_name_pinyin", APP_JS)
        self.assertIn("expert.expert_name_initials", APP_JS)
        self.assertIn("reviewerMatchesSearch", APP_JS)

    def test_numbers_visual_tokens_are_used(self) -> None:
        self.assertIn('--accent: #0a9bf5', STYLES_CSS)
        self.assertIn('"Aptos", "Segoe UI"', STYLES_CSS)
        self.assertIn('--font-size-micro: 12px', STYLES_CSS)
        self.assertIn('--font-size-supporting: 14px', STYLES_CSS)
        self.assertIn('--font-size-body: 15px', STYLES_CSS)
        self.assertIn('--font-size-content: 16px', STYLES_CSS)
        self.assertIn('--font-weight-body: 400', STYLES_CSS)
        self.assertIn('--font-weight-control: 600', STYLES_CSS)
        self.assertIn('--font-weight-heading: 700', STYLES_CSS)

    def test_siyuan_signature_matches_project_01(self) -> None:
        self.assertIn(
            '<div class="copyright-mark" aria-hidden="true">Designed by Siyuan for TRD</div>',
            INDEX_HTML,
        )
        self.assertIn("position: fixed; right: 16px; bottom: 6px; z-index: 30", STYLES_CSS)
        self.assertIn("color: var(--muted); font-size: var(--font-size-micro); line-height: 1.2; opacity: .62", STYLES_CSS)
        self.assertIn("pointer-events: none; user-select: none", STYLES_CSS)

    def test_quality_check_does_not_render_internal_checkpoint_catalog(self) -> None:
        self.assertIn("正在逐份检查", APP_JS)
        self.assertIn("正在枚举飞书归档文件夹", APP_JS)
        self.assertNotIn("检查标准区块与基础字段", INDEX_HTML)
        self.assertNotIn("读取标题中的项目名称", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
