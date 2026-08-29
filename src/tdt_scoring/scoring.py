from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from .models import (
    ExpertProjectScore,
    ExpertSessionScore,
    OpinionEvidence,
    ProjectProcessScore,
    ReviewSession,
    ScoreItem,
    SignoffRecord,
)
from .questionnaire import QUESTION_IDS, QUESTION_SCORES


ATTENDANCE_SCORES = {
    "正常": ("high", 15),
    "改派（正常）": ("high", 15),
    "缺席未改派": ("low", 0),
    "挂会": ("low", 0),
}

TECHNICAL_OBJECT_KEYWORDS = (
    "方案",
    "模块",
    "接口",
    "参数",
    "指标",
    "线损",
    "范围",
    "场景",
    "数据",
    "测试",
    "性能",
    "功耗",
    "温升",
    "天线",
    "射频",
    "结构",
    "电池",
    "驱动",
    "可靠性",
    "算法",
    "协议",
    "频段",
    "样本",
    "时序",
)
PROFESSIONAL_ACTION_KEYWORDS = (
    "需要",
    "需",
    "应",
    "建议",
    "要求",
    "判断",
    "证明",
    "质疑",
    "关注",
    "提示",
    "风险",
    "问题",
    "验证",
    "补充",
    "确认",
    "存在",
    "发现",
    "可能",
    "影响",
    "优化",
)
SPECIFIC_DETAIL_PATTERNS = (
    re.compile(r"最差|边界|极限|高温|低温|弱网|强干扰|量产|KPI", re.IGNORECASE),
    re.compile(r"数据不足|证据缺口|未覆盖|异常|波动|抵消|导致|影响"),
    re.compile(r"补充.{0,8}(?:数据|验证|测试|证据)"),
    re.compile(r"因为|由于|若|当|条件|连续|阈值|上限|下限"),
)

PROFESSIONAL_REASON_TAGS = {
    "严重技术误判",
    "重大风险遗漏",
    "竞争力误判",
    "其他",
}
AUDIT_NOTE_MAX_LENGTH = 100


def round_one_decimal(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _first_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    return next((keyword for keyword in keywords if keyword.casefold() in text.casefold()), None)


def extract_opinion_evidence(text: str, source_cell: str) -> OpinionEvidence:
    normalized = " ".join(text.split()).strip()
    technical_object = _first_keyword(normalized, TECHNICAL_OBJECT_KEYWORDS)
    if technical_object is None:
        acronym = re.search(r"\b[A-Z][A-Z0-9_-]{1,}\b", normalized)
        technical_object = acronym.group(0) if acronym else None
    professional_action = _first_keyword(normalized, PROFESSIONAL_ACTION_KEYWORDS)
    specific_detail = next(
        (match.group(0) for pattern in SPECIFIC_DETAIL_PATTERNS if (match := pattern.search(normalized))),
        None,
    )
    return OpinionEvidence(
        source_text=normalized,
        source_cell=source_cell,
        technical_object=technical_object,
        professional_action=professional_action,
        specific_detail=specific_detail,
    )


def score_signoff(session: ReviewSession, signoff: SignoffRecord) -> ExpertSessionScore:
    attendance_level, attendance_score = ATTENDANCE_SCORES.get(
        signoff.attendance, ("high", 15) if signoff.attendance else ("low", 0)
    )
    attendance = ScoreItem(
        level=attendance_level,
        score=attendance_score,
        reason=f"参会状况为“{signoff.attendance or '空'}”",
    )

    if signoff.conclusion in {"Go", "Go with Risk", "Redirect"}:
        signoff_item = ScoreItem("high", 15, "已提交有效会签结论")
    else:
        signoff_item = ScoreItem("low", 0, "计分时仍未提交有效会签结论")

    evidence = extract_opinion_evidence(signoff.basis, signoff.opinion_cell)
    if evidence.has_technical_object and evidence.has_professional_action:
        if evidence.has_specific_detail:
            opinion = ScoreItem("high", 25, "意见包含技术对象、专业动作和具体细节")
        else:
            opinion = ScoreItem("medium", 15, "意见包含技术对象和专业动作，具体细节不足")
    else:
        opinion = ScoreItem("low", 0, "未识别到完整的技术对象和专业动作")

    total = attendance.score + signoff_item.score + opinion.score
    return ExpertSessionScore(
        review_id=session.review_id,
        sheet_name=session.sheet_name,
        project_code=session.project_code,
        project_name=session.project_name,
        stage=session.stage,
        expert_name=signoff.expert_name,
        proxy_name=signoff.proxy_name,
        role=signoff.role,
        attendance=attendance,
        signoff=signoff_item,
        opinion=opinion,
        opinion_evidence=evidence,
        total=total,
    )


def build_project_scores(sessions: list[ReviewSession]) -> list[ExpertProjectScore]:
    grouped: dict[tuple[str, str], list[ExpertSessionScore]] = {}
    project_names: dict[str, str] = {}
    for session in sessions:
        project_names[session.project_code] = session.project_name
        for signoff in session.signoffs:
            if not signoff.expert_name:
                continue
            score = score_signoff(session, signoff)
            grouped.setdefault((session.project_code, signoff.expert_name), []).append(score)

    results: list[ExpertProjectScore] = []
    for (project_code, expert_name), scores in grouped.items():
        scores.sort(key=lambda item: (item.stage, item.sheet_name))
        process_average = round_one_decimal(
            sum(item.total for item in scores) / len(scores)
        )
        results.append(
            ExpertProjectScore(
                expert_name=expert_name,
                project_code=project_code,
                project_name=project_names[project_code],
                sessions=scores,
                process_average=process_average,
                effective_session_count=len(scores),
                project_process_scores=[
                    ProjectProcessScore(
                        project_code=project_code,
                        project_name=project_names[project_code],
                        session_count=len(scores),
                        process_average=process_average,
                    )
                ],
                objective_score=process_average,
            )
        )
    return sorted(results, key=lambda item: (item.project_code, item.expert_name))


def build_annual_scores(
    sessions: list[ReviewSession],
    window_start_exclusive: date | None = None,
    window_end_inclusive: date | None = None,
) -> list[ExpertProjectScore]:
    sessions_by_project: dict[str, list[ReviewSession]] = {}
    for session in sessions:
        sessions_by_project.setdefault(session.project_code, []).append(session)
    completed_project_codes = {
        project_code
        for project_code, project_sessions in sessions_by_project.items()
        if any(
            session.stage == "TDR3"
            and _date_in_window(
                session.meeting_date, window_start_exclusive, window_end_inclusive
            )
            for session in project_sessions
        )
    }
    eligible_sessions = [
        session for session in sessions if session.project_code in completed_project_codes
    ]
    project_scores = build_project_scores(eligible_sessions)
    grouped: dict[str, list[ExpertProjectScore]] = {}
    for project_score in project_scores:
        grouped.setdefault(project_score.expert_name, []).append(project_score)

    expert_names = sorted(grouped)
    participation_codes = {
        expert_name: _participation_project_codes(
            sessions_by_project, completed_project_codes, expert_name
        )
        for expert_name in expert_names
    }
    problem_codes = {
        expert_name: _problem_project_codes(
            sessions_by_project, completed_project_codes, expert_name
        )
        for expert_name in expert_names
    }
    participation_scores = _dense_top_three_scores(
        {name: len(codes) for name, codes in participation_codes.items()}
    )
    problem_scores = _dense_top_three_scores(
        {name: len(codes) for name, codes in problem_codes.items()}
    )

    results: list[ExpertProjectScore] = []
    for expert_name, expert_projects in grouped.items():
        expert_projects.sort(key=lambda item: item.project_code)
        annual_average = round_one_decimal(
            sum(item.process_average for item in expert_projects) / len(expert_projects)
        )
        all_sessions = [
            session
            for project in expert_projects
            for session in project.sessions
        ]
        all_sessions.sort(key=lambda item: (item.project_code, item.stage, item.sheet_name))
        codes = "、".join(project.project_code for project in expert_projects)
        project_count = len(expert_projects)
        participation_score = participation_scores[expert_name]
        problem_score = problem_scores[expert_name]
        annual_service_score = participation_score + problem_score
        results.append(
            ExpertProjectScore(
                expert_name=expert_name,
                project_code=codes,
                project_name=(
                    expert_projects[0].project_name
                    if project_count == 1
                    else f"{project_count}个项目年度汇总"
                ),
                sessions=all_sessions,
                process_average=annual_average,
                effective_session_count=len(all_sessions),
                project_process_scores=[
                    project.project_process_scores[0] for project in expert_projects
                ],
                participation_project_count=len(participation_codes[expert_name]),
                participation_project_codes=participation_codes[expert_name],
                participation_score=participation_score,
                problem_project_count=len(problem_codes[expert_name]),
                problem_project_codes=problem_codes[expert_name],
                problem_score=problem_score,
                annual_service_score=annual_service_score,
                objective_score=round_one_decimal(annual_average + annual_service_score),
            )
        )
    return sorted(results, key=lambda item: item.expert_name)


def _date_in_window(
    value: date | None,
    start_exclusive: date | None,
    end_inclusive: date | None,
) -> bool:
    if start_exclusive is None and end_inclusive is None:
        return True
    if start_exclusive is None or end_inclusive is None:
        return False
    if value is None:
        return False
    return start_exclusive < value <= end_inclusive


def _expert_attended(session: ReviewSession, expert_name: str) -> bool:
    return any(
        signoff.expert_name == expert_name
        and ATTENDANCE_SCORES.get(signoff.attendance, ("low", 0))[1] > 0
        for signoff in session.signoffs
    )


def _participation_project_codes(
    sessions_by_project: dict[str, list[ReviewSession]],
    completed_project_codes: set[str],
    expert_name: str,
) -> list[str]:
    result: list[str] = []
    for project_code in sorted(completed_project_codes):
        project_sessions = sessions_by_project[project_code]
        stages = {session.stage for session in project_sessions}
        required_stages = {"TDR1", "TDR3"} if stages == {"TDR1", "TDR2", "TDR3"} else {"TDR3"}
        attended_stages = {
            session.stage
            for session in project_sessions
            if _expert_attended(session, expert_name)
        }
        if required_stages <= attended_stages:
            result.append(project_code)
    return result


def _problem_project_codes(
    sessions_by_project: dict[str, list[ReviewSession]],
    completed_project_codes: set[str],
    expert_name: str,
) -> list[str]:
    return [
        project_code
        for project_code in sorted(completed_project_codes)
        if any(
            problem.description.strip() and expert_name in problem.reviewers
            for session in sessions_by_project[project_code]
            for problem in session.problems
        )
    ]


def _dense_top_three_scores(counts: dict[str, int]) -> dict[str, int]:
    ranked_counts = sorted({count for count in counts.values() if count > 2}, reverse=True)[:3]
    score_by_count = {count: 3 - index for index, count in enumerate(ranked_counts)}
    return {name: score_by_count.get(count, 0) for name, count in counts.items()}


def calculate_contribution(answers: dict[str, str]) -> int:
    missing = [question_id for question_id in QUESTION_IDS if question_id not in answers]
    unknown = [question_id for question_id in answers if question_id not in QUESTION_IDS]
    if missing:
        raise ValueError("以下问卷尚未作答：" + "、".join(missing))
    if unknown:
        raise ValueError("存在未知问卷字段：" + "、".join(unknown))
    invalid = [
        question_id
        for question_id, level in answers.items()
        if level not in QUESTION_SCORES[question_id]
    ]
    if invalid:
        raise ValueError("以下问卷档位无效：" + "、".join(invalid))
    return sum(QUESTION_SCORES[question_id][level] for question_id, level in answers.items())


def normalize_professional_audit(
    answers: dict[str, str], reason_tags: list[str], reason_note: str
) -> tuple[list[str], str | None]:
    if answers.get("professional_judgement_guidance") != "low":
        return [], None
    normalized_tags = list(dict.fromkeys(tag.strip() for tag in reason_tags if tag.strip()))
    invalid_tags = [tag for tag in normalized_tags if tag not in PROFESSIONAL_REASON_TAGS]
    if invalid_tags:
        raise ValueError("专业判断0分原因标签无效：" + "、".join(invalid_tags))
    if not normalized_tags:
        raise ValueError("专业判断与指导为0分时，必须至少选择一个0分原因")
    normalized_note = reason_note.strip()
    if not normalized_note:
        raise ValueError("专业判断与指导为0分时，必须填写0分原因和导致影响")
    if len(normalized_note) > AUDIT_NOTE_MAX_LENGTH:
        raise ValueError("0分原因和导致影响不能超过100字")
    return normalized_tags, normalized_note


def normalize_outstanding_contribution_reason(
    answers: dict[str, str], reason: str
) -> str | None:
    normalized_reason = reason.strip()
    if answers.get("outstanding_contribution") != "high":
        return None
    if not normalized_reason:
        raise ValueError("突出贡献选择10分时，必须填写加分原因")
    if len(normalized_reason) > AUDIT_NOTE_MAX_LENGTH:
        raise ValueError("突出贡献加分原因不能超过100字")
    return normalized_reason


def grade_for(total_score: float) -> str:
    if total_score >= 100:
        return "S"
    if total_score >= 90:
        return "A"
    if total_score >= 75:
        return "B"
    if total_score >= 60:
        return "C"
    return "D"


def finalize_project_score(
    project_score: ExpertProjectScore,
    answers: dict[str, str],
    professional_reason_tags: list[str] | None = None,
    professional_reason_note: str = "",
    outstanding_contribution_reason: str = "",
) -> ExpertProjectScore:
    contribution_score = calculate_contribution(answers)
    normalized_tags, normalized_note = normalize_professional_audit(
        answers, professional_reason_tags or [], professional_reason_note
    )
    normalized_outstanding_reason = normalize_outstanding_contribution_reason(
        answers, outstanding_contribution_reason
    )
    total_score = min(
        100.0,
        round_one_decimal(project_score.objective_score + contribution_score),
    )
    return ExpertProjectScore(
        expert_name=project_score.expert_name,
        project_code=project_score.project_code,
        project_name=project_score.project_name,
        sessions=project_score.sessions,
        process_average=project_score.process_average,
        effective_session_count=project_score.effective_session_count,
        project_process_scores=project_score.project_process_scores,
        participation_project_count=project_score.participation_project_count,
        participation_project_codes=project_score.participation_project_codes,
        participation_score=project_score.participation_score,
        problem_project_count=project_score.problem_project_count,
        problem_project_codes=project_score.problem_project_codes,
        problem_score=project_score.problem_score,
        annual_service_score=project_score.annual_service_score,
        objective_score=project_score.objective_score,
        contribution_score=contribution_score,
        professional_reason_tags=normalized_tags,
        professional_reason_note=normalized_note,
        outstanding_contribution_reason=normalized_outstanding_reason,
        total_score=total_score,
        grade=grade_for(total_score),
        status="已完成",
    )
