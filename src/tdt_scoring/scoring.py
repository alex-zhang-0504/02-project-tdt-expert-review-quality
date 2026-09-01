from __future__ import annotations

import re
import unicodedata
from math import ceil
from decimal import Decimal, ROUND_HALF_UP

from .models import (
    ExpertProjectScore,
    ExpertSessionScore,
    OPINION_RULE_VERSION,
    OpinionEvidence,
    ProjectProcessScore,
    ReviewSession,
    ScoreItem,
    SignoffRecord,
)
from .questionnaire import QUESTION_IDS, QUESTION_SCORES


ATTENDANCE_SCORES = {
    "正常": ("high", 13),
    "改派（正常）": ("high", 13),
    "缺席未改派": ("low", 0),
    "挂会": ("low", 0),
}

TECHNICAL_OBJECT_KEYWORDS = (
    "方案",
    "模块",
    "接口",
    "参数",
    "指标",
    "KPI",
    "价格",
    "成本",
    "市场",
    "竞品",
    "用户",
    "可行性",
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
    re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|ms|s|dB|℃|元|万|倍)?", re.IGNORECASE),
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
NO_OPINION_VALUES = {
    "",
    "-",
    "—",
    "无",
    "无意见",
    "没有意见",
    "没问题",
    "无问题",
    "同意",
    "赞同",
    "通过",
    "go",
    "gowithrisk",
    "go with risk",
    "redirect",
    "ok",
}
VAGUE_ATTENTION_WORDS = (
    "技术可行性",
    "用户场景",
    "应用场景",
    "竞争对手",
    "可行性",
    "可靠性",
    "兼容性",
    "安全性",
    "注意风险",
    "关注风险",
    "竞品",
    "市场",
    "价格",
    "成本",
    "kpi",
    "指标",
    "风险",
    "场景",
    "质量",
    "进度",
    "性能",
    "功耗",
    "体验",
    "需求",
)
VAGUE_FILLER_WORDS = (
    "需要注意",
    "需注意",
    "注意",
    "需要关注",
    "需关注",
    "关注",
    "留意",
    "重视",
    "考虑",
    "一下",
    "相关",
    "方面",
    "情况",
    "问题",
    "事项",
    "的",
    "和",
    "及",
    "以及",
)
CONCRETE_CONTENT_PATTERN = re.compile(
    r"\d|上涨|下降|增加|减少|高于|低于|超出|不足|异常|不一致|未达标|达标|"
    r"抵消|导致|影响|缺失|冲突|泄漏|时延|超时|断连|失败|偏差|"
    r"建议|要求|补充|验证|确认|优化|调整|修改|测算|分析|对比|测试"
)


def round_one_decimal(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _first_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    return next((keyword for keyword in keywords if keyword.casefold() in text.casefold()), None)


def _compact_opinion(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s，,。.!！?？;；:：、()（）\[\]【】'\"“”‘’]", "", normalized)


def _is_reference_only(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).strip()
    compact = _compact_opinion(normalized)
    if re.fullmatch(r"(?:与|同).{1,24}(?:意见|观点|建议|结论)?(?:相同|一致)", compact):
        return True
    if re.fullmatch(r"同意.{1,24}(?:意见|观点|建议|结论)", compact):
        return True
    if not re.match(r"^(?:参考|参照|详见)", normalized):
        return False
    own_supplement = re.search(
        r"(?:[，,。；;]\s*(?:另|另外|同时|并且|但)?|(?:另|另外|同时|并且|但|本人|我)(?:还|也)?)\s*"
        r"(?:建议|需要|需|应|存在|发现|判断|要求|补充|验证|确认|优化|调整|修改|测算|分析)",
        normalized,
    )
    return own_supplement is None


def _is_vague_attention_only(text: str) -> bool:
    compact = _compact_opinion(text)
    if not compact or CONCRETE_CONTENT_PATTERN.search(compact):
        return False
    residual = compact
    for word in sorted(VAGUE_ATTENTION_WORDS + VAGUE_FILLER_WORDS, key=len, reverse=True):
        residual = residual.replace(word, "")
    return not residual


def _zero_opinion_reason(text: str) -> str | None:
    compact = _compact_opinion(text)
    if compact in NO_OPINION_VALUES:
        return "未给意见"
    if _is_reference_only(text):
        return "只引用他人意见"
    if _is_vague_attention_only(text):
        return "只有泛化提醒"
    return None


def extract_opinion_evidence(text: str, source_cell: str) -> OpinionEvidence:
    normalized = " ".join(text.split()).strip()
    zero_reason = _zero_opinion_reason(normalized)
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
        zero_reason=zero_reason,
        rule_version=OPINION_RULE_VERSION,
    )


def _opinion_score_level(evidence: OpinionEvidence) -> int:
    if evidence.zero_reason:
        return 0
    if (
        evidence.has_technical_object
        and evidence.has_professional_action
        and evidence.has_specific_detail
    ):
        return 2
    return 1


def _best_opinion_evidence(signoff: SignoffRecord) -> OpinionEvidence:
    if not signoff.opinion_sources:
        return extract_opinion_evidence(signoff.basis, signoff.opinion_cell)
    candidates = [
        extract_opinion_evidence(source.text, "、".join(source.cell_references))
        for source in signoff.opinion_sources
    ]
    best = max(candidates, key=_opinion_score_level)
    best.source_texts = [source.text for source in signoff.opinion_sources]
    best.source_cells = list(
        dict.fromkeys(
            cell
            for source in signoff.opinion_sources
            for cell in source.cell_references
        )
    )
    return best


def score_signoff(session: ReviewSession, signoff: SignoffRecord) -> ExpertSessionScore:
    attendance_level, attendance_score = ATTENDANCE_SCORES.get(
        signoff.attendance, ("high", 13) if signoff.attendance else ("low", 0)
    )
    attendance = ScoreItem(
        level=attendance_level,
        score=attendance_score,
        reason=f"参会状况为“{signoff.attendance or '空'}”",
    )

    if signoff.conclusion in {"Go", "Go with Risk", "Redirect"}:
        signoff_item = ScoreItem("high", 25, "已提交有效会签结论")
    else:
        signoff_item = ScoreItem("low", 0, "计分时仍未提交有效会签结论")

    evidence = _best_opinion_evidence(signoff)
    if evidence.zero_reason:
        opinion = ScoreItem("low", 0, f"0分排除：{evidence.zero_reason}")
    elif (
        evidence.has_technical_object
        and evidence.has_professional_action
        and evidence.has_specific_detail
    ):
        opinion = ScoreItem("high", 10, "实质意见包含技术对象、专业动作和具体细节")
    else:
        opinion = ScoreItem("medium", 6, "已识别本人实质意见，三要素未全部明确")

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
) -> list[ExpertProjectScore]:
    project_scores = build_project_scores(sessions)
    grouped: dict[str, list[ExpertProjectScore]] = {}
    for project_score in project_scores:
        grouped.setdefault(project_score.expert_name, []).append(project_score)

    expert_names = sorted(grouped)
    participation_session_ids = {
        expert_name: _participation_session_ids(sessions, expert_name)
        for expert_name in expert_names
    }
    problem_session_ids = {
        expert_name: _problem_session_ids(sessions, expert_name)
        for expert_name in expert_names
    }
    service_eligible_names = {
        name for name, session_ids in participation_session_ids.items()
        if len(session_ids) >= 3
    }
    participation_scores = _dense_top_two_scores(
        {name: len(session_ids) for name, session_ids in participation_session_ids.items()},
        (6, 3),
        service_eligible_names,
    )
    problem_scores = _dense_top_two_scores(
        {name: len(session_ids) for name, session_ids in problem_session_ids.items()},
        (6, 3),
        service_eligible_names,
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
        expected_session_count = len(all_sessions)
        proxy_session_count = sum(bool(session.proxy_name) for session in all_sessions)
        proxy_rate = round_one_decimal(
            proxy_session_count * 100 / expected_session_count
        ) if expected_session_count else 0
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
                participation_session_count=len(participation_session_ids[expert_name]),
                participation_session_ids=participation_session_ids[expert_name],
                participation_score=participation_score,
                problem_session_count=len(problem_session_ids[expert_name]),
                problem_session_ids=problem_session_ids[expert_name],
                problem_score=problem_score,
                annual_service_score=annual_service_score,
                objective_score=round_one_decimal(annual_average + annual_service_score),
                expected_session_count=expected_session_count,
                proxy_session_count=proxy_session_count,
                proxy_rate=proxy_rate,
            )
        )
    return sorted(results, key=lambda item: item.expert_name)



def _expert_attended(session: ReviewSession, expert_name: str) -> bool:
    return any(
        signoff.expert_name == expert_name
        and ATTENDANCE_SCORES.get(
            signoff.attendance,
            ("high", 13) if signoff.attendance else ("low", 0),
        )[1] > 0
        for signoff in session.signoffs
    )


def _participation_session_ids(
    sessions: list[ReviewSession], expert_name: str
) -> list[str]:
    return sorted({
        session.review_id
        for session in sessions
        if _expert_attended(session, expert_name)
    })


def _problem_session_ids(
    sessions: list[ReviewSession], expert_name: str
) -> list[str]:
    return sorted({
        session.review_id
        for session in sessions
        if any(
            problem.description.strip() and expert_name in problem.reviewers
            for problem in session.problems
        )
    })


def _dense_top_two_scores(
    counts: dict[str, int],
    score_levels: tuple[int, int],
    eligible_names: set[str] | None = None,
) -> dict[str, int]:
    eligible = set(counts) if eligible_names is None else eligible_names
    ranked_counts = sorted(
        {count for name, count in counts.items() if name in eligible and count > 0},
        reverse=True,
    )[:2]
    score_by_count = {
        count: score_levels[index] for index, count in enumerate(ranked_counts)
    }
    return {
        name: score_by_count.get(count, 0) if name in eligible else 0
        for name, count in counts.items()
    }


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


def apply_annual_grade_ranking(experts: list[ExpertProjectScore]) -> None:
    completed = [
        expert
        for expert in experts
        if expert.status == "已完成"
        and expert.contribution_score is not None
        and expert.total_score is not None
    ]
    for expert in experts:
        expert.grade = None
    for expert in completed:
        expert.grade = "待排名"
    if not experts or len(completed) != len(experts):
        return

    ranked = sorted(completed, key=lambda expert: expert.total_score or 0, reverse=True)
    band_size = ceil(len(ranked) * 0.15)
    top_cutoff = ranked[band_size - 1].total_score
    bottom_cutoff = ranked[-band_size].total_score
    if top_cutoff == bottom_cutoff:
        for expert in ranked:
            expert.grade = "S" if expert.total_score == 100 else "B"
        return

    for expert in ranked:
        if expert.total_score == 100:
            expert.grade = "S"
            continue
        if expert.total_score is not None and expert.total_score >= top_cutoff:
            expert.grade = "A"
        elif expert.total_score is not None and expert.total_score <= bottom_cutoff:
            expert.grade = "C"
        else:
            expert.grade = "B"


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
    total_score = round_one_decimal(project_score.objective_score + contribution_score)
    return ExpertProjectScore(
        expert_name=project_score.expert_name,
        project_code=project_score.project_code,
        project_name=project_score.project_name,
        sessions=project_score.sessions,
        process_average=project_score.process_average,
        effective_session_count=project_score.effective_session_count,
        project_process_scores=project_score.project_process_scores,
        participation_session_count=project_score.participation_session_count,
        participation_session_ids=project_score.participation_session_ids,
        participation_score=project_score.participation_score,
        problem_session_count=project_score.problem_session_count,
        problem_session_ids=project_score.problem_session_ids,
        problem_score=project_score.problem_score,
        annual_service_score=project_score.annual_service_score,
        objective_score=project_score.objective_score,
        contribution_score=contribution_score,
        professional_reason_tags=normalized_tags,
        professional_reason_note=normalized_note,
        outstanding_contribution_reason=normalized_outstanding_reason,
        total_score=total_score,
        grade="待排名",
        status="已完成",
    )
