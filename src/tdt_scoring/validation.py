from __future__ import annotations

import re

from .models import ExpertProjectScore, ReviewSession, ValidationIssue


VALID_ATTENDANCE = {
    "正常",
    "部分参加",
    "改派（正常）",
    "改派（部分）",
    "缺席未改派",
    "挂会",
}
VALID_CONCLUSIONS = {"Go", "Go with Risk", "Redirect"}
VALID_STAGES = {"TDR1", "TDR2", "TDR3"}
VALID_PROBLEM_STATUSES = {"open", "closed"}
PROBLEM_NUMBER_PATTERN = re.compile(r"^(?:TDR[123]-)?\d+$", re.IGNORECASE)


def _problem_matches_stage(number: str, stage: str) -> bool:
    prefix = number.split("-", 1)[0].upper()
    normalized_stage = stage.upper()
    if normalized_stage == "TDR1+TDR2":
        return prefix in {"TDR1", "TDR2"}
    return prefix == normalized_stage


def validate_session(session: ReviewSession) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    is_v04 = any(signoff.opinion_cell for signoff in session.signoffs)
    required = {
        "project_name": (session.project_name, "项目名称缺失", "A1" if is_v04 else "B3"),
        "project_code": (session.project_code, "项目编码缺失", "A1" if is_v04 else "B3"),
        "stage": (session.stage, "项目阶段缺失", "E5" if is_v04 else "B4"),
        "meeting_date": (session.meeting_date, "会议日期缺失或格式无法识别", "B5"),
        "meeting_conclusion_missing": (session.meeting_conclusion, "会议评审结论缺失", "E3" if is_v04 else "B7"),
    }
    for code, (value, message, cell_reference) in required.items():
        if not value:
            issues.append(
                ValidationIssue(
                    code=code,
                    message=message,
                    severity="error",
                    sheet_name=session.sheet_name,
                    cell_reference=cell_reference,
                )
            )

    if session.stage and session.stage.upper() not in VALID_STAGES:
        issues.append(
            ValidationIssue(
                "stage_invalid",
                f"项目阶段“{session.stage}”不在允许枚举中",
                "error",
                session.sheet_name,
                cell_reference="E5" if is_v04 else "B4",
            )
        )
    if session.meeting_conclusion and session.meeting_conclusion not in VALID_CONCLUSIONS:
        issues.append(
            ValidationIssue(
                "meeting_conclusion_invalid",
                f"会议评审结论“{session.meeting_conclusion}”不在允许枚举中",
                "error",
                session.sheet_name,
                cell_reference="E3" if is_v04 else "B7",
            )
        )

    signoff_names = {signoff.expert_name for signoff in session.signoffs if signoff.expert_name}
    for absent_reviewer in session.absent_reviewers:
        if absent_reviewer not in signoff_names:
            issues.append(
                ValidationIssue(
                    "absent_reviewer_unmatched",
                    f"缺席评审人“{absent_reviewer}”不在本场会签列表中，请核对姓名",
                    "warning",
                    session.sheet_name,
                    absent_reviewer,
                    cell_reference="B4",
                )
            )
    seen_signoff_names: set[str] = set()
    for signoff in session.signoffs:
        conclusion_column = "C" if signoff.opinion_cell else "D"
        common = {
            "sheet_name": session.sheet_name,
            "expert_name": signoff.expert_name,
            "row_number": signoff.row_number,
        }
        if not signoff.role:
            issues.append(ValidationIssue("role_missing", "评审角色为空", "error", **common, cell_reference=f"A{signoff.row_number}"))
        if not signoff.expert_name:
            issues.append(ValidationIssue("reviewer_missing", "评审人为空", "error", **common, cell_reference=f"B{signoff.row_number}"))
        elif signoff.expert_name in seen_signoff_names:
            issues.append(ValidationIssue("reviewer_duplicate", f"评审人“{signoff.expert_name}”在本场会签列表中重复", "error", **common, cell_reference=f"B{signoff.row_number}"))
        else:
            seen_signoff_names.add(signoff.expert_name)
        if not signoff.attendance:
            issues.append(ValidationIssue("attendance_missing", "参会状况为空", "error", **common, cell_reference=f"C{signoff.row_number}"))
        elif signoff.attendance not in VALID_ATTENDANCE:
            issues.append(
                ValidationIssue(
                    "attendance_invalid",
                    f"参会状况“{signoff.attendance}”不在允许枚举中",
                    "error",
                    **common,
                    cell_reference=f"C{signoff.row_number}",
                )
            )
        if not signoff.conclusion_raw:
            issues.append(ValidationIssue("signoff_missing", "未记录会签结果，按0分记录", "warning", **common, cell_reference=f"{conclusion_column}{signoff.row_number}"))
        elif signoff.conclusion_raw in {"-", "－", "—", "–"}:
            issues.append(
                ValidationIssue(
                    "signoff_not_provided",
                    "技术项目经理已记录评审人未给会签结果；评审记录有效，结果会签按0分记录",
                    "warning",
                    **common,
                    cell_reference=f"{conclusion_column}{signoff.row_number}",
                )
            )
        elif signoff.conclusion not in VALID_CONCLUSIONS:
            issues.append(
                ValidationIssue(
                    "signoff_invalid",
                    f"会签结果“{signoff.conclusion_raw}”无法识别，按0分记录",
                    "warning",
                    **common,
                    cell_reference=f"{conclusion_column}{signoff.row_number}",
                )
            )
        if signoff.attendance.startswith("改派") and not signoff.proxy_name:
            issues.append(ValidationIssue("proxy_missing", "改派记录缺少代理人后缀", "error", **common, cell_reference=f"B{signoff.row_number}"))

    seen_problem_numbers: set[str] = set()
    for problem in session.problems:
        common = {
            "sheet_name": session.sheet_name,
            "row_number": problem.row_number,
        }
        if not problem.number:
            issues.append(ValidationIssue("problem_number_missing", "问题编号为空", "error", **common, cell_reference=f"A{problem.row_number}"))
        elif not PROBLEM_NUMBER_PATTERN.fullmatch(problem.number):
            issues.append(
                ValidationIssue(
                    "problem_number_invalid",
                    f"问题编号“{problem.number}”格式不正确",
                    "warning",
                    **common,
                    cell_reference=f"A{problem.row_number}",
                )
            )
        if problem.number and problem.number in seen_problem_numbers:
            issues.append(
                ValidationIssue(
                    "problem_number_duplicate",
                    f"问题编号“{problem.number}”重复",
                    "error",
                    **common,
                    cell_reference=f"A{problem.row_number}",
                )
            )
        if problem.number:
            seen_problem_numbers.add(problem.number)
        if not problem.reviewers:
            issues.append(ValidationIssue("problem_reviewer_missing", "问题提出人为空", "error", **common, cell_reference=f"B{problem.row_number}"))
        if not problem.description:
            issues.append(ValidationIssue("problem_description_missing", "问题描述为空", "error", **common, cell_reference=f"C{problem.row_number}"))
        if not problem.status:
            issues.append(ValidationIssue("problem_status_missing", "问题状态为空", "error", **common, cell_reference=f"G{problem.row_number}"))
        elif problem.status.casefold() not in VALID_PROBLEM_STATUSES:
            issues.append(ValidationIssue("problem_status_invalid", f"问题状态“{problem.status}”不在open／closed枚举中", "error", **common, cell_reference=f"G{problem.row_number}"))
        for reviewer in problem.reviewers:
            if reviewer not in signoff_names:
                issues.append(
                    ValidationIssue(
                        "reviewer_unmatched",
                        f"问题提出人“{reviewer}”不在本场会签列表中，请确认是非评审专家还是姓名笔误",
                        "warning",
                        session.sheet_name,
                        reviewer,
                        problem.row_number,
                        f"B{problem.row_number}",
                    )
                )

    return issues


def validate_stage_conflicts(sessions: list[ReviewSession]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: dict[tuple[str, str], str] = {}
    for session in sessions:
        key = (session.project_code, session.stage)
        if key in seen:
            issues.append(
                ValidationIssue(
                    "stage_conflict",
                    f"项目{session.project_code}的阶段{session.stage}同时出现在“{seen[key]}”和“{session.sheet_name}”",
                    "error",
                    session.sheet_name,
                    cell_reference="B4",
                )
            )
        else:
            seen[key] = session.sheet_name
    return issues


def validate_problem_number_conflicts(sessions: list[ReviewSession]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: dict[tuple[str, str], tuple[str, str]] = {}
    for session in sessions:
        for problem in session.problems:
            if not problem.number:
                continue
            normalized_number = problem.number.upper()
            number_key = (
                normalized_number
                if "-" in normalized_number
                else f"{session.stage.upper()}:{normalized_number}"
            )
            key = (session.project_code, number_key)
            previous = seen.get(key)
            if previous and previous[0] != problem.description:
                issues.append(
                    ValidationIssue(
                        "problem_number_conflict",
                        f"问题编号“{problem.number}”在“{previous[1]}”与“{session.sheet_name}”对应不同问题描述",
                        "error",
                        session.sheet_name,
                        row_number=problem.row_number,
                        cell_reference=f"A{problem.row_number}",
                    )
                )
            else:
                seen[key] = (problem.description, session.sheet_name)
    return issues


def validate_score_bounds(experts: list[ExpertProjectScore]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for expert in experts:
        for session in expert.sessions:
            if not 0 <= session.total <= 55:
                issues.append(
                    ValidationIssue(
                        "session_score_out_of_range",
                        f"专家“{expert.expert_name}”的场次过程分{session.total}超出0至55",
                        "error",
                        session.sheet_name,
                        expert.expert_name,
                    )
                )
        if expert.effective_session_count != len(expert.sessions):
            issues.append(
                ValidationIssue(
                    "session_count_mismatch",
                    f"专家“{expert.expert_name}”的有效场次数与评分明细数量不一致",
                    "error",
                    expert_name=expert.expert_name,
                )
            )
        if not 0 <= expert.process_average <= 55:
            issues.append(
                ValidationIssue(
                    "project_score_out_of_range",
                    f"专家“{expert.expert_name}”的评审过程表现均分{expert.process_average}超出0至55",
                    "error",
                    expert_name=expert.expert_name,
                )
            )
        if not 0 <= expert.annual_service_score <= 6:
            issues.append(
                ValidationIssue(
                    "service_score_out_of_range",
                    f"专家“{expert.expert_name}”的年度服务贡献分{expert.annual_service_score}超出0至6",
                    "error",
                    expert_name=expert.expert_name,
                )
            )
        if not 0 <= expert.objective_score <= 61:
            issues.append(
                ValidationIssue(
                    "objective_score_out_of_range",
                    f"专家“{expert.expert_name}”的客观分数{expert.objective_score}超出0至61",
                    "error",
                    expert_name=expert.expert_name,
                )
            )
    return issues
