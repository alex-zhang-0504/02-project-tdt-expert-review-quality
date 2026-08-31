from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Callable
from uuid import uuid4

from .excel_reader import read_workbook
from .models import (
    BatchImportSummary,
    ExpertProjectScore,
    ReportAnalysis,
    ValidationIssue,
    WorkbookAnalysis,
)
from .progress import ProgressEvent
from .scoring import (
    apply_annual_grade_ranking,
    build_annual_scores,
    build_project_scores,
    finalize_project_score,
)
from .sources.feishu_document import FeishuDocumentSource
from .sources.local_excel import LocalExcelSource
from .validation import validate_score_bounds


class ScoringService:
    def __init__(self) -> None:
        self._analyses: dict[str, WorkbookAnalysis] = {}

    def import_local_bytes(
        self,
        content: bytes,
        filename: str,
        progress: Callable[[ProgressEvent], None] | None = None,
    ) -> WorkbookAnalysis:
        workbook, source_name = self._prepare_local_input(
            content, filename, progress=progress
        )
        return self._analyze_many(
            [(workbook, source_name, [])],
            source_type="local_excel",
            source_name=source_name,
            progress=progress,
        )

    def import_local_files(
        self,
        files: list[tuple[bytes, str]],
        progress: Callable[[ProgressEvent], None] | None = None,
    ) -> WorkbookAnalysis:
        if not files:
            raise ValueError("请至少选择一份Excel评审报告")
        workbooks: list[tuple[bytes | None, str, list[ValidationIssue]]] = []
        for content, filename in files:
            report_name = Path(filename).name or "未命名报告"
            try:
                workbook, report_name = self._prepare_local_input(
                    content, filename, progress=progress
                )
                workbooks.append((workbook, report_name, []))
            except ValueError as exc:
                message = str(exc)
                if "仅支持.xlsx" in message:
                    code = "file_extension_invalid"
                elif "为空" in message or "30MB" in message:
                    code = "file_limits_invalid"
                else:
                    code = "xlsx_structure_invalid"
                workbooks.append(
                    (
                        None,
                        report_name,
                        [ValidationIssue(code, message, "error", source_name=report_name)],
                    )
                )
        return self._analyze_many(
            workbooks,
            source_type="local_excel",
            source_name=f"{len(workbooks)}份评审报告",
            progress=progress,
        )

    @staticmethod
    def _prepare_local_input(
        content: bytes,
        filename: str,
        *,
        progress: Callable[[ProgressEvent], None] | None,
    ) -> tuple[bytes, str]:
        report_name = Path(filename).name or "未命名报告"
        metadata_started = perf_counter()
        if progress:
            progress(ProgressEvent(report_name, "report_acquisition", "started"))
        try:
            report_name = LocalExcelSource.validate_metadata(content, filename)
        except ValueError as exc:
            if progress:
                progress(
                    ProgressEvent(
                        report_name,
                        "report_acquisition",
                        "error",
                        (perf_counter() - metadata_started) * 1000,
                        str(exc),
                    )
                )
            raise
        if progress:
            progress(
                ProgressEvent(
                    report_name,
                    "report_acquisition",
                    "completed",
                    (perf_counter() - metadata_started) * 1000,
                )
            )
        structure_started = perf_counter()
        if progress:
            progress(ProgressEvent(report_name, "xlsx_acquisition", "started"))
        try:
            LocalExcelSource.validate_xlsx_structure(content)
        except ValueError as exc:
            if progress:
                progress(
                    ProgressEvent(
                        report_name,
                        "xlsx_acquisition",
                        "error",
                        (perf_counter() - structure_started) * 1000,
                        str(exc),
                    )
                )
            raise
        if progress:
            progress(
                ProgressEvent(
                    report_name,
                    "xlsx_acquisition",
                    "completed",
                    (perf_counter() - structure_started) * 1000,
                )
            )
        return content, report_name

    def import_feishu_url(
        self,
        url: str,
        progress: Callable[[ProgressEvent], None] | None = None,
        on_candidates: Callable[[list[str]], None] | None = None,
    ) -> WorkbookAnalysis:
        if FeishuDocumentSource.is_folder_url(url):
            folder = FeishuDocumentSource.export_folder_xlsx(
                url,
                on_candidates=on_candidates,
                on_progress=progress,
            )
            workbooks: list[tuple[bytes | None, str, list[ValidationIssue]]] = []
            for exported in folder.workbooks:
                source_issues = []
                if exported.error:
                    source_issues.append(
                        ValidationIssue(
                            "feishu_report_export_failed",
                            f"飞书候选报告读取失败：{exported.error}",
                            "error",
                            source_name=exported.source_name,
                        )
                    )
                workbooks.append((exported.content, exported.source_name, source_issues))
            return self._analyze_many(
                workbooks,
                source_type="feishu_folder",
                source_name=f"{folder.source_name}（{folder.candidate_count}份候选报告）",
                batch_summary=BatchImportSummary(
                    discovered_count=folder.discovered_count,
                    candidate_count=folder.candidate_count,
                    succeeded_count=0,
                    failed_count=0,
                    excluded_count=folder.excluded_count,
                    complete=False,
                    excluded_names=folder.excluded_names,
                ),
                progress=progress,
            )
        report_name = "tdrx-review.xlsx"
        if on_candidates:
            on_candidates([report_name])
        export_started = perf_counter()
        if progress:
            progress(ProgressEvent(report_name, "report_acquisition", "completed", 0.0))
            progress(ProgressEvent(report_name, "xlsx_acquisition", "started"))
        try:
            workbook, source_name = FeishuDocumentSource.export_xlsx(url)
        except RuntimeError as exc:
            if progress:
                progress(
                    ProgressEvent(
                        report_name,
                        "xlsx_acquisition",
                        "error",
                        (perf_counter() - export_started) * 1000,
                        str(exc),
                    )
                )
            raise
        if progress:
            progress(
                ProgressEvent(
                    report_name,
                    "xlsx_acquisition",
                    "completed",
                    (perf_counter() - export_started) * 1000,
                )
            )
        return self._analyze_many(
            [(workbook, source_name, [])],
            source_type="feishu_document",
            source_name=source_name,
            progress=progress,
        )

    def get_analysis(self, analysis_id: str) -> WorkbookAnalysis:
        try:
            return self._analyses[analysis_id]
        except KeyError as exc:
            raise KeyError("评分分析不存在或本地服务已重启，请重新导入评审表") from exc

    def finalize_expert(
        self,
        analysis_id: str,
        project_code: str,
        expert_name: str,
        answers: dict[str, str],
        professional_reason_tags: list[str] | None = None,
        professional_reason_note: str = "",
        outstanding_contribution_reason: str = "",
    ) -> ExpertProjectScore:
        analysis = self.get_analysis(analysis_id)
        if any(issue.severity == "error" for issue in analysis.issues):
            raise ValueError("评审表仍有错误，请返回读取模块修正后重新导入")
        target = next(
            (
                expert
                for expert in analysis.experts
                if expert.project_code == project_code and expert.expert_name == expert_name
            ),
            None,
        )
        if not target:
            raise KeyError("未找到对应的专家项目记录")
        completed = finalize_project_score(
            target,
            answers,
            professional_reason_tags,
            professional_reason_note,
            outstanding_contribution_reason,
        )
        analysis.experts = [
            completed
            if expert.project_code == project_code and expert.expert_name == expert_name
            else expert
            for expert in analysis.experts
        ]
        apply_annual_grade_ranking(analysis.experts)
        return next(
            expert
            for expert in analysis.experts
            if expert.project_code == project_code and expert.expert_name == expert_name
        )

    def _analyze_many(
        self,
        workbooks: list[tuple[bytes | None, str, list[ValidationIssue]]],
        *,
        source_type: str,
        source_name: str,
        batch_summary: BatchImportSummary | None = None,
        progress: Callable[[ProgressEvent], None] | None = None,
    ) -> WorkbookAnalysis:
        sessions = []
        issues: list[ValidationIssue] = []
        reports: list[ReportAnalysis] = []
        seen_sessions: dict[tuple[str, str], str] = {}
        for workbook, report_name, source_issues in workbooks:
            report_sessions = []
            report_issues = list(source_issues)
            if workbook is not None:
                parse_started = perf_counter()
                if progress:
                    progress(ProgressEvent(report_name, "workbook_parse", "started"))
                try:
                    report_sessions, parsed_issues = read_workbook(
                        workbook,
                        source_name=report_name,
                    )
                    report_issues.extend(parsed_issues)
                    if progress:
                        progress(
                            ProgressEvent(
                                report_name,
                                "workbook_parse",
                                "completed",
                                (perf_counter() - parse_started) * 1000,
                            )
                        )
                except (OSError, ValueError) as exc:
                    report_issues.append(
                        ValidationIssue(
                            "workbook_parse_failed",
                            f"Excel工作簿解析失败：{exc}",
                            "error",
                            source_name=report_name,
                        )
                    )
                    if progress:
                        progress(
                            ProgressEvent(
                                report_name,
                                "workbook_parse",
                                "error",
                                (perf_counter() - parse_started) * 1000,
                                str(exc),
                            )
                        )
            progress_open = workbook is not None and not any(
                issue.code == "workbook_parse_failed" for issue in report_issues
            )
            if progress and progress_open:
                for checkpoint_id in (
                    "template_structure",
                    "session_identity",
                    "reviewer_roster",
                    "attendance_signoff",
                    "opinions_problems",
                ):
                    checkpoint_started = perf_counter()
                    progress(ProgressEvent(report_name, checkpoint_id, "started"))
                    relevant = [
                        issue
                        for issue in report_issues
                        if self._issue_checkpoint(issue.code) == checkpoint_id
                    ]
                    errors = [issue for issue in relevant if issue.severity == "error"]
                    warnings = [issue for issue in relevant if issue.severity == "warning"]
                    status = "error" if errors else "warning" if warnings else "completed"
                    message = (errors or warnings)[0].message if (errors or warnings) else ""
                    progress(
                        ProgressEvent(
                            report_name,
                            checkpoint_id,
                            status,
                            (perf_counter() - checkpoint_started) * 1000,
                            message,
                        )
                    )
                    if errors:
                        progress_open = False
                        break
            for session in report_sessions:
                key = (session.project_code, session.stage)
                previous_source = seen_sessions.get(key)
                if previous_source:
                    report_issues.append(
                        ValidationIssue(
                            "cross_report_stage_duplicate",
                            f"项目{session.project_code}的阶段{session.stage}已存在于“{previous_source}”，请勿重复上传",
                            "error",
                            session.sheet_name,
                            cell_reference="A1",
                            source_name=report_name,
                        )
                    )
                else:
                    seen_sessions[key] = report_name
            duplicate_issues = [
                issue
                for issue in report_issues
                if self._issue_checkpoint(issue.code) == "session_uniqueness"
            ]
            if progress and progress_open:
                unique_started = perf_counter()
                progress(ProgressEvent(report_name, "session_uniqueness", "started"))
                progress(
                    ProgressEvent(
                        report_name,
                        "session_uniqueness",
                        "error" if duplicate_issues else "completed",
                        (perf_counter() - unique_started) * 1000,
                        duplicate_issues[0].message if duplicate_issues else "",
                    )
                )
                if duplicate_issues:
                    progress_open = False
            score_started = perf_counter()
            if progress and progress_open:
                progress(ProgressEvent(report_name, "score_bounds", "started"))
            report_experts = build_project_scores(report_sessions)
            score_issues = validate_score_bounds(report_experts)
            for issue in score_issues:
                issue.source_name = report_name
            report_issues.extend(score_issues)
            if progress and progress_open:
                score_checkpoint_issues = [
                    issue
                    for issue in report_issues
                    if self._issue_checkpoint(issue.code) == "score_bounds"
                ]
                score_errors = [
                    issue for issue in score_checkpoint_issues if issue.severity == "error"
                ]
                score_warnings = [
                    issue for issue in score_checkpoint_issues if issue.severity == "warning"
                ]
                progress(
                    ProgressEvent(
                        report_name,
                        "score_bounds",
                        "error" if score_errors else "warning" if score_warnings else "completed",
                        (perf_counter() - score_started) * 1000,
                        (score_errors or score_warnings)[0].message
                        if (score_errors or score_warnings)
                        else "",
                    )
                )
            sessions.extend(report_sessions)
            issues.extend(report_issues)
            reports.append(
                ReportAnalysis(
                    report_id=uuid4().hex,
                    source_type=source_type,
                    source_name=report_name,
                    session_count=len(report_sessions),
                    expert_count=len(report_experts),
                    issues=report_issues,
                )
            )
        experts = build_annual_scores(sessions)
        issues.extend(validate_score_bounds(experts))
        if batch_summary is not None:
            failed_report_count = sum(
                any(issue.severity == "error" for issue in report.issues)
                for report in reports
            )
            batch_summary.failed_count = failed_report_count
            batch_summary.succeeded_count = max(
                0, batch_summary.candidate_count - failed_report_count
            )
            batch_summary.complete = (
                batch_summary.candidate_count > 0 and failed_report_count == 0
            )
            if batch_summary.candidate_count == 0:
                issues.append(
                    ValidationIssue(
                        "feishu_folder_no_candidates",
                        "飞书归档文件夹第一层没有电子表格候选报告",
                        "error",
                        source_name=source_name,
                    )
                )
            elif failed_report_count:
                issues.append(
                    ValidationIssue(
                        "feishu_folder_batch_incomplete",
                        f"飞书归档批次不完整：{batch_summary.candidate_count}份候选报告中{failed_report_count}份失败，禁止生成完整年度结果",
                        "error",
                        source_name=source_name,
                    )
                )
        analysis = WorkbookAnalysis(
            analysis_id=uuid4().hex,
            source_type=source_type,
            source_name=source_name,
            sessions=sessions,
            experts=experts,
            issues=issues,
            reports=reports,
            batch_summary=batch_summary,
        )
        self._analyses[analysis.analysis_id] = analysis
        return analysis

    @staticmethod
    def _issue_checkpoint(code: str) -> str:
        if code.startswith(("section_", "signoff_header_", "problem_header_")) or code in {
            "basic_field_missing",
            "basic_field_duplicate",
        }:
            return "template_structure"
        if code in {
            "basic_field_value_missing",
            "no_effective_sessions",
            "project_name",
            "project_code",
            "project_identity_invalid",
            "project_manager",
            "stage",
            "stage_invalid",
            "meeting_date",
            "meeting_conclusion_missing",
            "meeting_conclusion_invalid",
        }:
            return "session_identity"
        if code in {
            "effective_signoff_minimum",
            "role_missing",
            "reviewer_missing",
            "reviewer_duplicate",
            "proxy_missing",
        }:
            return "reviewer_roster"
        if code == "absent_with_basis":
            return "opinions_problems"
        if code.startswith(("attendance_", "absent_", "signoff_")):
            return "attendance_signoff"
        if code.startswith(("problem_", "opinion_", "reviewer_unmatched", "basis_")):
            return "opinions_problems"
        if code in {"stage_conflict", "cross_report_stage_duplicate"}:
            return "session_uniqueness"
        return "score_bounds"
