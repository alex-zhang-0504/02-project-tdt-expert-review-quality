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
    def test_step_buttons_are_clickable_navigation(self) -> None:
        self.assertIn('step.addEventListener("click"', APP_JS)
        self.assertIn("navigateStep(Number(step.dataset.step))", APP_JS)

    def test_drop_prevents_browser_navigation_and_keeps_multiple_xlsx_files(self) -> None:
        self.assertIn('document.addEventListener("drop"', APP_JS)
        self.assertIn('elements.uploadBox.addEventListener("drop"', APP_JS)
        self.assertIn("event.preventDefault()", APP_JS)
        self.assertIn("useDroppedFiles(event.dataTransfer.files)", APP_JS)
        self.assertIn('elements.file.addEventListener("change"', APP_JS)
        self.assertIn("state.droppedFiles", APP_JS)
        self.assertIn('multiple accept=".xlsx"', INDEX_HTML)
        self.assertIn('formData.append("files", file, file.name)', APP_JS)

    def test_network_failure_has_actionable_message(self) -> None:
        self.assertIn("无法连接本地评分服务", APP_JS)
        self.assertIn("重新双击 start.cmd", APP_JS)
        self.assertIn("重新导入评审表", APP_JS)

    def test_service_health_is_monitored_and_stale_analysis_is_blocked(self) -> None:
        self.assertIn("const SERVICE_HEALTH_INTERVAL_MS = 5000", APP_JS)
        self.assertIn("setInterval(checkServiceHealth, SERVICE_HEALTH_INTERVAL_MS)", APP_JS)
        self.assertIn('health.project_id !== EXPECTED_PROJECT_ID', APP_JS)
        self.assertIn('health.build_id !== EXPECTED_BUILD_ID', APP_JS)
        self.assertIn("service_instance_id", APP_JS)
        self.assertIn("analysisStale", APP_JS)
        self.assertIn("服务已断开", APP_JS)
        self.assertIn("服务已重新启动", APP_JS)
        self.assertIn("!state.serviceAvailable", APP_JS)
        self.assertIn('setServiceStatus(`试用版 ${health.version}`', APP_JS)

    def test_backend_actions_start_disabled_until_health_is_confirmed(self) -> None:
        self.assertIn('id="service-status" role="status" aria-live="polite"', INDEX_HTML)
        self.assertIn('id="import-local" data-service-action="true" disabled', INDEX_HTML)
        self.assertIn('id="import-feishu" data-service-action="true" disabled', INDEX_HTML)
        self.assertIn('id="calculate-total" data-service-action="true" disabled', INDEX_HTML)

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

    def test_quality_gate_has_locations_and_warning_acknowledgement(self) -> None:
        self.assertIn('issue.sheet_name', APP_JS)
        self.assertIn('issue.cell_reference', APP_JS)
        self.assertIn('warningAcknowledged', APP_JS)
        self.assertIn('errors === 0', APP_JS)
        self.assertIn('issue.severity !== "info"', APP_JS)
        self.assertNotIn('"已处理"', APP_JS)

    def test_quality_check_lists_reports_with_backend_progress(self) -> None:
        self.assertNotIn('data-check="', INDEX_HTML)
        self.assertIn('class="report-progress-list"', INDEX_HTML)
        self.assertIn("report.progress_percent", APP_JS)
        self.assertIn("report.current_checkpoint_label", APP_JS)
        self.assertIn("/api/import/jobs/", APP_JS)
        self.assertIn("/api/import/feishu/start", APP_JS)
        self.assertNotIn("finishCheckAnimation", APP_JS)

    def test_quality_check_smoothly_reads_ten_checkpoints_in_three_columns(self) -> None:
        self.assertIn("const IMPORT_PROGRESS_STEP_MS = 120", APP_JS)
        self.assertIn("const IMPORT_CHECKPOINTS = [", APP_JS)
        self.assertIn("waitForProgressPlayback()", APP_JS)
        self.assertIn("updateProgressHeader()", APP_JS)
        self.assertIn('state.importJobStatus === "completed" && playbackComplete', APP_JS)
        self.assertIn('class="report-progress-reader', APP_JS)
        self.assertIn('class="report-progress-segments"', APP_JS)
        self.assertIn("report.display_percent < Math.min(20, report.target_percent)", APP_JS)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", STYLES_CSS)
        self.assertIn("grid-template-columns: repeat(10, minmax(8px, 1fr))", STYLES_CSS)
        self.assertIn("transform: skewX(-24deg)", STYLES_CSS)
        self.assertIn("checkpoint-flash", STYLES_CSS)
        self.assertNotIn("progress-segment-pulse", STYLES_CSS)

    def test_interface_uses_reviewer_wording_and_preserves_full_report_name(self) -> None:
        self.assertNotIn("评审专家", INDEX_HTML)
        self.assertNotIn("评审专家", APP_JS)
        self.assertIn("评审人打分", INDEX_HTML)
        self.assertIn('class="report-progress-name" data-full-name="${escapeHtml(report.source_name)}"', APP_JS)
        self.assertNotIn('title="${escapeHtml(report.source_name)}"', APP_JS)
        self.assertIn("content: attr(data-full-name)", STYLES_CSS)
        self.assertIn(".report-progress-name:hover::after", STYLES_CSS)
        self.assertIn("transition-delay: .45s", STYLES_CSS)
        self.assertIn("background: var(--surface); color: var(--ink)", STYLES_CSS)

    def test_quality_check_can_switch_between_reports(self) -> None:
        self.assertIn('id="report-list"', INDEX_HTML)
        self.assertIn("state.selectedReportIndex", APP_JS)
        self.assertIn("selectReport(index)", APP_JS)
        self.assertIn("analysis.reports", APP_JS)

    def test_dimension_one_shows_extracted_opinion_evidence_and_source(self) -> None:
        self.assertIn("session.opinion_evidence.technical_object", APP_JS)
        self.assertIn("session.opinion_evidence.professional_action", APP_JS)
        self.assertIn("session.opinion_evidence.specific_detail", APP_JS)
        self.assertIn("session.opinion_evidence.source_cell", APP_JS)

    def test_topbar_and_results_follow_confirmed_structure(self) -> None:
        self.assertIn("评审过程表现", INDEX_HTML)
        self.assertNotIn("客观分数考核", INDEX_HTML)
        self.assertIn("主观分数考核", INDEX_HTML)
        self.assertIn('class="module-tabs"', INDEX_HTML)
        self.assertIn('class="expert-slider"', INDEX_HTML)
        self.assertIn('class="results-table"', APP_JS)
        self.assertIn('待完成', APP_JS)
        self.assertIn('expert.participation_project_count', APP_JS)
        self.assertIn('expert.problem_project_count', APP_JS)
        self.assertIn('expert.proxy_session_count', APP_JS)
        self.assertIn('expert.expected_session_count', APP_JS)
        self.assertIn('expert.proxy_rate', APP_JS)
        self.assertIn('客观分数＝评审过程表现', APP_JS)
        self.assertIn('客观分数／60', APP_JS)
        self.assertIn('process_average}／50', APP_JS)
        self.assertIn('participation_score}／6', APP_JS)
        self.assertIn('problem_score}／4', APP_JS)
        self.assertIn("全体专家的客观分数和主观分数均完成后统一生成", APP_JS)

    def test_expert_rail_is_a_fixed_left_column(self) -> None:
        self.assertIn(
            "grid-template-columns: var(--rail-width) minmax(0, 1fr)",
            STYLES_CSS,
        )
        self.assertIn('class="expert-rail-slot"', INDEX_HTML)
        self.assertIn('class="module-label-short">过程</span>', INDEX_HTML)

    def test_all_modules_share_the_full_width_header_container(self) -> None:
        self.assertIn("--content-max-width: 1480px", STYLES_CSS)
        self.assertIn(
            ".head-inner { max-width: var(--content-max-width)",
            STYLES_CSS,
        )
        self.assertIn(
            ".main-content { width: min(var(--content-max-width), calc(100% - 48px))",
            STYLES_CSS,
        )
        self.assertNotIn("width: min(1180px", STYLES_CSS)

    def test_expert_selection_is_limited_to_scoring_modules(self) -> None:
        self.assertIn("return state.activeStep === 3", APP_JS)
        self.assertIn("if (!expertSelectionEnabled()) return", APP_JS)
        self.assertIn("button.disabled = !enabled", APP_JS)
        self.assertIn(".expert-chip:disabled", STYLES_CSS)

    def test_dimension_one_supports_both_workflows_and_numbers_table(self) -> None:
        self.assertIn('id="choose-central"', INDEX_HTML)
        self.assertIn('id="choose-manager"', INDEX_HTML)
        self.assertIn('id="choose-merge"', INDEX_HTML)
        self.assertIn("/api/export/dimension-one", APP_JS)
        self.assertIn("/api/import/dimension-one-submissions", APP_JS)
        self.assertIn('class="dimension-one-table"', APP_JS)
        self.assertIn("background: var(--accent); color: #fff", STYLES_CSS)
        self.assertIn("border-collapse: separate; border-spacing: 0", STYLES_CSS)
        self.assertIn("tbody tr:nth-child(even) td", STYLES_CSS)
        self.assertIn("border-right-color: var(--line-strong)", STYLES_CSS)
        self.assertNotIn("score-high", STYLES_CSS)
        self.assertNotIn("score-medium", STYLES_CSS)
        self.assertNotIn("score-low", STYLES_CSS)

    def test_dimension_one_project_name_has_one_custom_full_name_tip(self) -> None:
        self.assertIn('class="project-name-tooltip" data-full-name=', APP_JS)
        self.assertNotIn('project-name-cell" title=', APP_JS)
        self.assertIn(".project-name-tooltip::after", STYLES_CSS)
        self.assertIn("background: var(--surface); color: var(--ink)", STYLES_CSS)

    def test_questionnaire_registers_score_only_after_submit_succeeds(self) -> None:
        self.assertIn('id="calculate-total" data-service-action="true" disabled>提交</button>', INDEX_HTML)
        self.assertIn('elements.calculate.textContent = "提交"', APP_JS)
        request_index = APP_JS.index('result = await requestJson("/api/score/finalize"')
        health_check_index = APP_JS.index("if (!await checkServiceHealth())")
        register_index = APP_JS.index("state.analysis.experts = result.experts")
        self.assertLess(health_check_index, request_index)
        self.assertLess(request_index, register_index)
        self.assertIn("if (Array.isArray(result.experts))", APP_JS)
        self.assertNotIn('elements.calculate.textContent = state.analysis', APP_JS)

    def test_three_question_audit_fields_are_required_in_special_cases(self) -> None:
        self.assertIn('id="outstanding-contribution-reason"', APP_JS)
        self.assertIn('maxlength="100"', APP_JS)
        self.assertIn('id="professional-reason-note"', APP_JS)
        self.assertIn('name="professional-reason-tag"', APP_JS)
        self.assertIn("function outstandingReasonRequired()", APP_JS)
        self.assertIn("function professionalAuditRequired()", APP_JS)
        self.assertIn("professional_reason_tags", APP_JS)
        self.assertIn("professional_reason_note", APP_JS)
        self.assertIn("outstanding_contribution_reason", APP_JS)

    def test_professional_typical_cases_are_hidden_tooltips(self) -> None:
        self.assertIn("option.reference", APP_JS)
        self.assertIn('class="option-reference"', APP_JS)
        self.assertIn(".option-reference-popover", STYLES_CSS)
        self.assertIn(".option-reference:hover", STYLES_CSS)

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

    def test_readable_typography_is_applied_to_core_controls(self) -> None:
        self.assertNotIn('font-size: 13px', STYLES_CSS)
        self.assertIn('font-size: var(--font-size-supporting); font-weight: var(--font-weight-control)', STYLES_CSS)
        self.assertIn('font-size: 28px; font-weight: var(--font-weight-heading)', STYLES_CSS)
        self.assertIn('min-height: 42px', STYLES_CSS)
        self.assertIn('.report-progress-row { --progress-color: var(--accent); width: 100%', STYLES_CSS)
        self.assertIn('font-size: 18px; font-weight: var(--font-weight-heading)', STYLES_CSS)
        self.assertIn('font-size: var(--font-size-content); font-weight: var(--font-weight-control)', STYLES_CSS)
        self.assertIn('.result-equation small { color: var(--muted); font-size: var(--font-size-supporting); }', STYLES_CSS)

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
