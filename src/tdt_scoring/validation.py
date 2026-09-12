from __future__ import annotations

from hashlib import sha256
import re

from pypinyin import Style, lazy_pinyin

from .models import ReviewSession, ValidationIssue


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
PROBLEM_NUMBER_PATTERN = re.compile(r"^[1-9]\d*$")
CHINESE_PERSON_NAME_PATTERN = re.compile(r"^[\u3400-\u9fff]{2,4}$")
COMMON_COMPOUND_SURNAMES = {
    "欧阳",
    "司马",
    "上官",
    "诸葛",
    "东方",
    "皇甫",
    "尉迟",
    "公孙",
    "慕容",
    "司徒",
    "司空",
    "夏侯",
    "南宫",
    "令狐",
    "长孙",
    "宇文",
}


def _split_chinese_person_name(name: str) -> tuple[str, str] | None:
    normalized = "".join(name.split())
    if not CHINESE_PERSON_NAME_PATTERN.fullmatch(normalized):
        return None
    surname_length = 2 if normalized[:2] in COMMON_COMPOUND_SURNAMES else 1
    given_name = normalized[surname_length:]
    if not given_name:
        return None
    return normalized[:surname_length], given_name


def _pinyin_syllables(text: str) -> tuple[str, ...]:
    return tuple(
        syllable.casefold()
        for syllable in lazy_pinyin(text, style=Style.NORMAL, errors=lambda value: list(value))
    )


def _surname_sound_key(surname: str) -> tuple[str, ...]:
    return tuple(
        syllable[:-1] if syllable.endswith("ng") else syllable
        for syllable in _pinyin_syllables(surname)
    )


def _reviewer_names_sound_similar(left: str, right: str) -> bool:
    left_parts = _split_chinese_person_name(left)
    right_parts = _split_chinese_person_name(right)
    if left_parts is None or right_parts is None:
        return False
    left_surname, left_given = left_parts
    right_surname, right_given = right_parts
    if _pinyin_syllables(left_given) != _pinyin_syllables(right_given):
        return False
    if left_surname == right_surname:
        return True
    left_surname_pinyin = _pinyin_syllables(left_surname)
    right_surname_pinyin = _pinyin_syllables(right_surname)
    return (
        left_surname_pinyin == right_surname_pinyin
        or _surname_sound_key(left_surname) == _surname_sound_key(right_surname)
    )


def validate_reviewer_name_similarity(
    sessions: list[ReviewSession],
) -> list[ValidationIssue]:
    locations_by_name: dict[str, list[str]] = {}
    name_order: list[str] = []
    for session in sessions:
        for signoff in session.signoffs:
            name = "".join(signoff.expert_name.split())
            if not name or _split_chinese_person_name(name) is None:
                continue
            if name not in locations_by_name:
                locations_by_name[name] = []
                name_order.append(name)
            cell = signoff.cell_references.get("reviewer", f"B{signoff.row_number}")
            location = f"{session.source_name}／{session.sheet_name}!{cell}（{name}）"
            if location not in locations_by_name[name]:
                locations_by_name[name].append(location)

    adjacency = {name: set() for name in name_order}
    for index, left in enumerate(name_order):
        for right in name_order[index + 1:]:
            if _reviewer_names_sound_similar(left, right):
                adjacency[left].add(right)
                adjacency[right].add(left)

    issues: list[ValidationIssue] = []
    visited: set[str] = set()
    for first_name in name_order:
        if first_name in visited or not adjacency[first_name]:
            continue
        pending = [first_name]
        component: set[str] = set()
        while pending:
            name = pending.pop()
            if name in component:
                continue
            component.add(name)
            pending.extend(adjacency[name] - component)
        visited.update(component)
        names = [name for name in name_order if name in component]
        locations = [
            location
            for name in names
            for location in locations_by_name[name]
        ]
        confirmation_key = "reviewer-name-similarity:" + sha256(
            "\0".join(sorted(names)).encode("utf-8")
        ).hexdigest()[:16]
        issues.append(
            ValidationIssue(
                code="reviewer_name_similarity",
                message=(
                    f"疑似同一评审人：{'／'.join(names)}。姓名的名字拼音相同，且姓氏相同、同音或近音；"
                    "请核实并统一源报告姓名。若确为不同人员，可确认后分别统计。"
                ),
                severity="error",
                source_name="本批次",
                requires_confirmation=True,
                confirmation_key=confirmation_key,
                related_locations=locations,
            )
        )
    return issues


def validate_session(session: ReviewSession) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    field_reference = session.field_references.get
    required = {
        "project_name": (session.project_name, "项目名称缺失", field_reference("project_identity", "B3")),
        "project_code": (session.project_code, "项目编码缺失", field_reference("project_identity", "B3")),
        "stage": (session.stage, "项目阶段缺失", field_reference("stage", "B4")),
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
                cell_reference=field_reference("stage", "B4"),
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
                    cell_reference=field_reference("absent_reviewers", "B4"),
                )
            )
    seen_signoff_names: set[str] = set()
    for signoff in session.signoffs:
        references = signoff.cell_references
        reviewer_reference = references.get("reviewer", f"B{signoff.row_number}")
        attendance_reference = references.get("attendance", f"C{signoff.row_number}")
        conclusion_reference = references.get("conclusion", f"D{signoff.row_number}")
        common = {
            "sheet_name": session.sheet_name,
            "expert_name": signoff.expert_name,
            "row_number": signoff.row_number,
        }
        if not signoff.expert_name:
            issues.append(ValidationIssue("reviewer_missing", "评审人为空", "error", **common, cell_reference=reviewer_reference))
        elif signoff.expert_name in seen_signoff_names:
            issues.append(ValidationIssue("reviewer_duplicate", f"评审人“{signoff.expert_name}”在本场会签列表中重复", "error", **common, cell_reference=reviewer_reference))
        else:
            seen_signoff_names.add(signoff.expert_name)
        if not signoff.attendance:
            issues.append(ValidationIssue("attendance_missing", "参会状况为空，出勤相关比率暂不计算", "warning", **common, cell_reference=attendance_reference))
        elif signoff.attendance not in VALID_ATTENDANCE:
            issues.append(
                ValidationIssue(
                    "attendance_invalid",
                    f"参会状况“{signoff.attendance}”无法判定，出勤相关比率暂不计算",
                    "warning",
                    **common,
                    cell_reference=attendance_reference,
                )
            )
        if signoff.attendance.startswith("改派") and not signoff.proxy_name:
            issues.append(ValidationIssue("proxy_missing", "改派记录缺少代理人后缀", "error", **common, cell_reference=reviewer_reference))

    for problem in session.problems:
        references = problem.cell_references
        common = {
            "sheet_name": session.sheet_name,
            "row_number": problem.row_number,
        }
        if not problem.reviewers_raw and not problem.reviewers:
            issues.append(ValidationIssue("problem_reviewer_missing", "问题提出人为空；该问题不归属专家、不计入问题贡献", "warning", **common, cell_reference=references.get("reviewers", f"B{problem.row_number}")))
        if not problem.description:
            issues.append(ValidationIssue("problem_description_missing", "问题描述为空；该问题不归属专家、不计入问题贡献", "warning", **common, cell_reference=references.get("description", f"C{problem.row_number}")))

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
                    cell_reference=session.field_references.get("stage", "B4"),
                )
            )
        else:
            seen[key] = session.sheet_name
    return issues
