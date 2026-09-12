from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable
from uuid import uuid4

from .excel_reader import read_workbook
from .models import (
    BatchImportSummary,
    ReportAnalysis,
    ValidationIssue,
    WorkbookAnalysis,
)
from .progress import ProgressEvent
from .scoring import build_facts, refresh, decision_payload
from .sources.feishu_document import FeishuDocumentSource
from .sources.local_excel import LocalExcelSource
from .submission import load_dimension_one_workbook
from .validation import validate_reviewer_name_similarity


class ScoringService:
    def __init__(self, classifier=None) -> None:
        self._analyses: dict[str, WorkbookAnalysis] = {}
        self.classifier = classifier
        from threading import RLock
        self._fact_lock = RLock()

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
            raise KeyError("统计分析不存在或本地服务已重启，请重新导入评审表") from exc

    def confirm_reviewer_names_distinct(
        self,
        analysis_id: str,
        confirmation_key: str,
    ) -> WorkbookAnalysis:
        analysis = self.get_analysis(analysis_id)
        matches = [
            issue
            for issue in analysis.issues
            if issue.code == "reviewer_name_similarity"
            and issue.confirmation_key == confirmation_key
            and issue.requires_confirmation
        ]
        if not matches:
            raise KeyError("未找到需要确认的疑似评审人姓名组")
        confirmed_at = datetime.now(timezone.utc).isoformat()
        for issue in matches:
            issue.severity = "info"
            issue.confirmed_by_user = True
            issue.confirmed_at = confirmed_at
        if not any(issue.severity == "error" for issue in analysis.issues):
            analysis.experts = build_facts(analysis.sessions, decision_payload(analysis.experts))
        return analysis

    def merge_dimension_one_submissions(
        self,
        uploads: list[tuple[bytes, str]],
        *,
        expected_manager_count: int,
        expected_project_count: int | None = None,
    ) -> WorkbookAnalysis:
        if not uploads:
            raise ValueError("请至少选择一份项目经理维度1提交表")
        if expected_manager_count < 1:
            raise ValueError("预计项目经理人数必须大于等于1")
        if expected_project_count is not None and expected_project_count < 1:
            raise ValueError("预计项目数必须大于等于1")

        packages = [
            load_dimension_one_workbook(content, filename)
            for content, filename in uploads
        ]
        issues: list[ValidationIssue] = []
        batch_ids = {package.batch_id for package in packages}
        if len(batch_ids) != 1:
            issues.append(
                ValidationIssue(
                    "submission_batch_mismatch",
                    "提交表的年度批次编号不一致，不能合并",
                    "error",
                    source_name="维度1提交表汇总",
                )
            )

        manager_packages: dict[str, list[str]] = {}
        project_owners: dict[str, list[str]] = {}
        session_sources: dict[tuple[str, str], list[str]] = {}
        sessions = []
        reports = []
        for package in packages:
            manager_packages.setdefault(package.manager_id, []).append(package.filename)
            for project_code in package.project_codes:
                project_owners.setdefault(project_code, []).append(package.manager_id)
            for session in package.sessions:
                session_sources.setdefault(
                    (session.project_code, session.stage), []
                ).append(package.filename)
            sessions.extend(package.sessions)
            issues.extend(package.issues)
            reports.append(
                ReportAnalysis(
                    report_id=uuid4().hex,
                    source_type="manager_submission",
                    source_name=package.filename,
                    session_count=len(package.sessions),
                    expert_count=len(
                        {
                            signoff.expert_name
                            for session in package.sessions
                            for signoff in session.signoffs
                            if signoff.expert_name
                        }
                    ),
                    issues=package.issues,
                )
            )

        duplicate_managers = {
            manager_id: filenames
            for manager_id, filenames in manager_packages.items()
            if len(filenames) > 1
        }
        for manager_id, filenames in sorted(duplicate_managers.items()):
            issues.append(
                ValidationIssue(
                    "submission_manager_duplicate",
                    f"项目经理编号{manager_id}存在多份提交：{'、'.join(filenames)}",
                    "error",
                    source_name="维度1提交表汇总",
                )
            )

        if len(manager_packages) != expected_manager_count:
            issues.append(
                ValidationIssue(
                    "submission_manager_count_mismatch",
                    f"预计{expected_manager_count}位项目经理，实际识别{len(manager_packages)}位",
                    "error",
                    source_name="维度1提交表汇总",
                )
            )

        for project_code, manager_ids in sorted(project_owners.items()):
            unique_manager_ids = sorted(set(manager_ids))
            if len(unique_manager_ids) > 1:
                issues.append(
                    ValidationIssue(
                        "submission_project_owner_conflict",
                        f"项目{project_code}同时出现在项目经理编号{'、'.join(unique_manager_ids)}的提交中",
                        "error",
                        source_name="维度1提交表汇总",
                    )
                )

        for (project_code, stage), filenames in sorted(session_sources.items()):
            if len(filenames) > 1:
                issues.append(
                    ValidationIssue(
                        "submission_stage_duplicate",
                        f"项目{project_code}的{stage}在多份提交表中重复：{'、'.join(filenames)}",
                        "error",
                        source_name="维度1提交表汇总",
                    )
                )

        project_count = len(project_owners)
        if expected_project_count is not None and project_count != expected_project_count:
            issues.append(
                ValidationIssue(
                    "submission_project_count_mismatch",
                    f"预计{expected_project_count}个项目，实际识别{project_count}个",
                    "error",
                    source_name="维度1提交表汇总",
                )
            )

        has_errors = any(issue.severity == "error" for issue in issues)
        decisions = {key: value for package in packages for key, value in package.decisions.items()}
        experts = [] if has_errors else build_facts(sessions, decisions)
        batch_id = next(iter(batch_ids)) if len(batch_ids) == 1 else "批次不一致"
        analysis = WorkbookAnalysis(
            analysis_id=uuid4().hex,
            source_type="dimension_one_merge",
            source_name=f"{batch_id} · {len(packages)}份项目经理提交表",
            sessions=sessions,
            experts=experts,
            issues=issues,
            reports=reports,
        )
        self._analyses[analysis.analysis_id] = analysis
        return analysis

    def select_solution(self, analysis_id: str, opinion_id: str, included: bool) -> WorkbookAnalysis:
        with self._fact_lock:
            analysis = self.get_analysis(analysis_id)
            if any(i.severity == "error" for i in analysis.issues):
                raise ValueError("请先处理报告中的阻断问题")
            opinion = next((o for e in analysis.experts for s in e.sessions for o in s.opinions if o.opinion_id == opinion_id), None)
            if opinion is None:
                raise KeyError("未找到对应意见")
            if opinion.ai_status != "suspected":
                raise ValueError("仅疑似待确认的意见允许选择计入与否")
            if opinion.included is not included:
                opinion.audit.append({"at": datetime.now(timezone.utc).isoformat(), "from": opinion.included, "to": included})
                opinion.included = included
            refresh(analysis.experts)
            return analysis

    def identify_solutions(self, analysis_id: str) -> WorkbookAnalysis:
        with self._fact_lock:
            analysis = self.get_analysis(analysis_id)
            if any(i.severity == "error" for i in analysis.issues):
                raise ValueError("请先处理报告中的阻断问题")
            pending = [o for e in analysis.experts for s in e.sessions for o in s.opinions if o.ai_status == "pending"]
            if not pending:
                return analysis
            if self.classifier is None:
                raise ValueError("尚未配置AI识别服务，意见保持待AI识别；请完成模型接入")
            from .countermeasures import validate_predictions
            predictions = validate_predictions(pending, self.classifier(pending))
            for opinion in pending:
                result = predictions[opinion.opinion_id]
                opinion.ai_status = result["status"]
                opinion.excerpt = result["excerpt"]
                opinion.reason = result["reason"]
                opinion.rule_version = result["rule_version"]
            refresh(analysis.experts)
            analysis.ai_message = "AI识别完成，疑似项默认计入，可在详情中确认"
            return analysis

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
            facts_started = perf_counter()
            if progress and progress_open:
                progress(ProgressEvent(report_name, "fact_bounds", "started"))
            report_experts = build_facts(report_sessions)
            fact_issues = []
            for issue in fact_issues:
                issue.source_name = report_name
            report_issues.extend(fact_issues)
            if progress and progress_open:
                fact_checkpoint_issues = [
                    issue
                    for issue in report_issues
                    if self._issue_checkpoint(issue.code) == "fact_bounds"
                ]
                fact_errors = [
                    issue for issue in fact_checkpoint_issues if issue.severity == "error"
                ]
                fact_warnings = [
                    issue for issue in fact_checkpoint_issues if issue.severity == "warning"
                ]
                progress(
                    ProgressEvent(
                        report_name,
                        "fact_bounds",
                        "error" if fact_errors else "warning" if fact_warnings else "completed",
                        (perf_counter() - facts_started) * 1000,
                        (fact_errors or fact_warnings)[0].message
                        if (fact_errors or fact_warnings)
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
        similarity_issues = validate_reviewer_name_similarity(sessions)
        for issue in similarity_issues:
            for report in reports:
                location_prefix = f"{report.source_name}／"
                if any(
                    location.startswith(location_prefix)
                    for location in issue.related_locations
                ):
                    report.issues.append(issue)
        issues.extend(similarity_issues)
        experts = build_facts(sessions)
        if batch_summary is not None:
            failed_report_count = sum(
                any(
                    issue.severity == "error" and not issue.requires_confirmation
                    for issue in report.issues
                )
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
            "multi_project_first_selected",
            "project_manager",
            "stage",
            "stage_invalid",
        }:
            return "session_identity"
        if code in {
            "effective_signoff_minimum",
            "reviewer_missing",
            "reviewer_duplicate",
            "duplicate_reviewer_merged",
            "duplicate_reviewer_conclusion_conflict",
            "duplicate_reviewer_proxy_conflict",
            "reviewer_name_similarity",
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
        return "fact_bounds"
