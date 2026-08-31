from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .excel_reader import read_workbook
from .models import (
    BatchImportSummary,
    ExpertProjectScore,
    ReportAnalysis,
    ValidationIssue,
    WorkbookAnalysis,
)
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
    ) -> WorkbookAnalysis:
        workbook, source_name = LocalExcelSource.from_bytes(content, filename)
        return self._analyze_many(
            [(workbook, source_name, [])],
            source_type="local_excel",
            source_name=source_name,
        )

    def import_local_files(
        self,
        files: list[tuple[bytes, str]],
    ) -> WorkbookAnalysis:
        if not files:
            raise ValueError("请至少选择一份Excel评审报告")
        workbooks: list[tuple[bytes | None, str, list[ValidationIssue]]] = []
        for content, filename in files:
            report_name = Path(filename).name or "未命名报告"
            try:
                workbook, report_name = LocalExcelSource.from_bytes(content, filename)
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
        )

    def import_feishu_url(
        self,
        url: str,
    ) -> WorkbookAnalysis:
        if FeishuDocumentSource.is_folder_url(url):
            folder = FeishuDocumentSource.export_folder_xlsx(url)
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
            )
        workbook, source_name = FeishuDocumentSource.export_xlsx(url)
        return self._analyze_many(
            [(workbook, source_name, [])],
            source_type="feishu_document",
            source_name=source_name,
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
    ) -> WorkbookAnalysis:
        sessions = []
        issues: list[ValidationIssue] = []
        reports: list[ReportAnalysis] = []
        seen_sessions: dict[tuple[str, str], str] = {}
        for workbook, report_name, source_issues in workbooks:
            report_sessions = []
            report_issues = list(source_issues)
            if workbook is not None:
                try:
                    report_sessions, parsed_issues = read_workbook(
                        workbook, source_name=report_name
                    )
                    report_issues.extend(parsed_issues)
                except (OSError, ValueError) as exc:
                    report_issues.append(
                        ValidationIssue(
                            "workbook_parse_failed",
                            f"Excel工作簿解析失败：{exc}",
                            "error",
                            source_name=report_name,
                        )
                    )
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
            report_experts = build_project_scores(report_sessions)
            score_issues = validate_score_bounds(report_experts)
            for issue in score_issues:
                issue.source_name = report_name
            report_issues.extend(score_issues)
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
