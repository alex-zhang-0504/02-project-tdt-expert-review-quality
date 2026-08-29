from __future__ import annotations

import io
import re
from datetime import date, datetime
from pathlib import Path
from typing import BinaryIO

from openpyxl import load_workbook
from openpyxl.utils.datetime import CALENDAR_WINDOWS_1900, from_excel
from openpyxl.worksheet.worksheet import Worksheet

from .models import ProblemRecord, ReviewSession, SignoffRecord, ValidationIssue
from .validation import (
    PROBLEM_NUMBER_PATTERN,
    VALID_CONCLUSIONS,
    validate_problem_number_conflicts,
    validate_session,
    validate_stage_conflicts,
)


SECTION_BASIC = "评审会基本信息列表"
SECTION_SIGNOFF = "评审结论和会签列表"
SECTION_PROBLEMS = "评审问题&建议汇总表"
SECTION_PROBLEMS_V04 = "评审问题汇总表"
SECTION_TITLES = (SECTION_BASIC, SECTION_SIGNOFF, SECTION_PROBLEMS)
SIGNOFF_HEADERS = ("评审角色", "评审人", "参会状况", "会签结果", "评审依据")
PROBLEM_HEADERS = (
    "序号",
    "评审人",
    "问题描述",
    "建议改善措施",
    "验证方式与通过条件",
    "进展",
    "问题状态",
)

PROJECT_CODE_PATTERN = re.compile(r"[（(]([^（）()]*)[）)]")
PROXY_PATTERN = re.compile(r"^(.*?)[（(]\s*代理\s*[:：]\s*(.*?)[）)]\s*$")
REPORT_TITLE_PATTERN = re.compile(r"^(?P<project>.+?)[\-－—–]\s*(?P<stage>TDR[123])$", re.IGNORECASE)
ABSENT_ROLE_PATTERN = re.compile(r"^(.*?)[（(][^（）()]+[）)]$")
RECORDED_NO_CONCLUSION_MARKERS = {"-", "－", "—", "–"}


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ")
    return " ".join(text.split()).strip()


def normalize_parentheses(value: object) -> str:
    return normalize_text(value).translate(str.maketrans({"(": "（", ")": "）", ":": "："}))


def canonical_attendance(value: object) -> str:
    return normalize_parentheses(value)


def canonical_conclusion(value: object) -> tuple[str, bool]:
    raw = normalize_parentheses(value)
    overdue = raw.endswith("（逾期）")
    base = raw[: -len("（逾期）")].strip() if overdue else raw
    aliases = {
        "go": "Go",
        "go with risk": "Go with Risk",
        "redirect": "Redirect",
        "tbd": "TBD",
    }
    return aliases.get(base.casefold(), base), overdue


def canonical_meeting_conclusion(value: object) -> str:
    raw = normalize_parentheses(value)
    aliases = {
        "go": "Go",
        "go with risk": "Go with Risk",
        "redirect": "Redirect",
        "tbd": "TBD",
    }
    return aliases.get(raw.casefold(), raw)


def parse_reviewer(value: object) -> tuple[str, str | None, str]:
    raw = normalize_text(value)
    match = PROXY_PATTERN.match(raw)
    if not match:
        return raw, None, raw
    expert_name = normalize_text(match.group(1))
    proxy_name = normalize_text(match.group(2))
    return expert_name, proxy_name or None, raw


def split_reviewers(value: object) -> list[str]:
    text = normalize_text(value)
    if not text:
        return []
    return [
        reviewer.strip()
        for reviewer in re.split(r"[、，,]", text)
        if reviewer.strip()
    ]


def split_absent_reviewers(value: object) -> list[str]:
    text = normalize_text(value)
    if not text or text.casefold() in {"无", "-", "none"}:
        return []
    reviewers: list[str] = []
    for item in re.split(r"[、，,；;／/\n]", str(value)):
        normalized = normalize_text(item)
        if not normalized:
            continue
        match = ABSENT_ROLE_PATTERN.match(normalized)
        reviewers.append(normalize_text(match.group(1)) if match else normalized)
    return reviewers


def parse_project(value: object) -> tuple[str, str]:
    text = normalize_text(value)
    matches = list(PROJECT_CODE_PATTERN.finditer(text))
    if not matches:
        return text, ""
    match = matches[-1]
    project_code = normalize_text(match.group(1))
    project_name = normalize_text(text[: match.start()] + text[match.end() :])
    return project_name, project_code


def parse_report_title(value: object) -> tuple[str, str, str] | None:
    text = normalize_parentheses(value)
    if not text or text.startswith("填写规则"):
        return None
    match = REPORT_TITLE_PATTERN.match(text)
    if not match:
        return None
    project_name, project_code = parse_project(match.group("project"))
    return project_name, project_code, match.group("stage").upper()


def parse_date(value: object, *, epoch: datetime = CALENDAR_WINDOWS_1900) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = from_excel(value, epoch=epoch)
        except (TypeError, ValueError, OverflowError):
            return None
        return parsed.date() if isinstance(parsed, datetime) else parsed
    text = normalize_text(value)
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _find_section_rows(ws: Worksheet) -> dict[str, int]:
    sections: dict[str, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            value = normalize_text(cell.value)
            aliases = {
                SECTION_BASIC: SECTION_BASIC,
                SECTION_SIGNOFF: SECTION_SIGNOFF,
                SECTION_PROBLEMS: SECTION_PROBLEMS,
                SECTION_PROBLEMS_V04: SECTION_PROBLEMS,
            }
            canonical = aliases.get(value)
            if canonical and canonical not in sections:
                sections[canonical] = cell.row
    return sections


def _next_header_row(
    ws: Worksheet, start_row: int, required_labels: tuple[str, ...]
) -> int | None:
    for row_number in range(start_row + 1, min(start_row + 7, ws.max_row) + 1):
        row_text = [normalize_text(ws.cell(row_number, column).value) for column in range(1, ws.max_column + 1)]
        if all(any(label in cell for cell in row_text) for label in required_labels):
            return row_number
    return None


def _header_map(ws: Worksheet, row_number: int) -> dict[str, int]:
    return {
        normalize_text(ws.cell(row_number, column).value): column
        for column in range(1, ws.max_column + 1)
        if normalize_text(ws.cell(row_number, column).value)
    }


def _find_column(headers: dict[str, int], label: str) -> int | None:
    for header, column in headers.items():
        if header == label or label in header:
            return column
    return None


def _basic_info(ws: Worksheet, start_row: int, end_row: int) -> dict[str, object]:
    labels = {
        "技术项目+编号",
        "项目阶段",
        "会议日期",
        "技术项目经理",
        "评审结论",
        "评审意见",
    }
    result: dict[str, object] = {}
    for row_number in range(start_row + 1, end_row):
        for column in range(1, ws.max_column + 1):
            label = normalize_text(ws.cell(row_number, column).value)
            if label not in labels:
                continue
            value: object = None
            for value_column in range(column + 1, ws.max_column + 1):
                candidate = ws.cell(row_number, value_column).value
                if normalize_text(candidate):
                    value = candidate
                    break
            result[label] = value
    return result


def _parse_signoffs(
    ws: Worksheet, header_row: int, end_row: int
) -> list[SignoffRecord]:
    headers = _header_map(ws, header_row)
    columns = {
        "role": _find_column(headers, "评审角色"),
        "reviewer": _find_column(headers, "评审人"),
        "attendance": _find_column(headers, "参会状况"),
        "conclusion": _find_column(headers, "会签结果"),
        "basis": _find_column(headers, "评审依据"),
    }
    if any(column is None for column in columns.values()):
        return []

    signoffs: list[SignoffRecord] = []
    for row_number in range(header_row + 1, end_row):
        role = normalize_text(ws.cell(row_number, columns["role"]).value)
        reviewer_value = ws.cell(row_number, columns["reviewer"]).value
        reviewer = normalize_text(reviewer_value)
        if role.startswith("↓") or reviewer.startswith("↓"):
            continue
        attendance = canonical_attendance(ws.cell(row_number, columns["attendance"]).value)
        conclusion_raw = normalize_text(ws.cell(row_number, columns["conclusion"]).value)
        basis = normalize_text(ws.cell(row_number, columns["basis"]).value)
        if not reviewer and not any((attendance, conclusion_raw, basis)):
            continue
        expert_name, proxy_name, reviewer_raw = parse_reviewer(reviewer_value)
        conclusion, overdue = canonical_conclusion(conclusion_raw)
        signoffs.append(
            SignoffRecord(
                role=role,
                reviewer_raw=reviewer_raw,
                expert_name=expert_name,
                proxy_name=proxy_name,
                attendance=attendance,
                conclusion_raw=conclusion_raw,
                conclusion=conclusion,
                overdue=overdue,
                basis=basis,
                row_number=row_number,
            )
        )
    return signoffs


def _parse_problems(ws: Worksheet, header_row: int) -> list[ProblemRecord]:
    headers = _header_map(ws, header_row)
    columns = {
        "number": _find_column(headers, "序号"),
        "reviewers": _find_column(headers, "评审人"),
        "description": _find_column(headers, "问题描述"),
        "action": _find_column(headers, "建议改善措施"),
        "verification": _find_column(headers, "验证方式与通过条件"),
        "progress": _find_column(headers, "进展"),
        "status": _find_column(headers, "问题状态"),
    }
    if any(column is None for column in columns.values()):
        return []

    problems: list[ProblemRecord] = []
    started = False
    for row_number in range(header_row + 1, ws.max_row + 1):
        number = normalize_text(ws.cell(row_number, columns["number"]).value)
        known_values = {
            key: normalize_text(ws.cell(row_number, column).value)
            for key, column in columns.items()
        }
        if not any(known_values.values()):
            if started:
                break
            continue
        if number.startswith("↓"):
            continue
        other_values = [
            known_values[key]
            for key in ("reviewers", "description", "action", "verification", "progress", "status")
        ]
        if not number and not any(other_values):
            if started:
                break
            continue
        if number and not PROBLEM_NUMBER_PATTERN.fullmatch(number) and not any(other_values):
            continue
        started = True
        problems.append(
            ProblemRecord(
                number=number,
                reviewers=split_reviewers(known_values["reviewers"]),
                description=known_values["description"],
                action=known_values["action"],
                verification=known_values["verification"],
                progress=known_values["progress"],
                status=known_values["status"],
                row_number=row_number,
            )
        )
    return problems


def _parse_sheet(ws: Worksheet, sections: dict[str, int]) -> ReviewSession | None:
    signoff_header = _next_header_row(
        ws, sections[SECTION_SIGNOFF], ("评审角色", "评审人", "参会状况", "会签结果")
    )
    problem_header = _next_header_row(
        ws, sections[SECTION_PROBLEMS], ("序号", "评审人", "问题描述")
    )
    if signoff_header is None or problem_header is None:
        return None

    info = _basic_info(ws, sections[SECTION_BASIC], sections[SECTION_SIGNOFF])
    stage = normalize_text(info.get("项目阶段"))
    if not stage:
        return None
    signoffs = _parse_signoffs(ws, signoff_header, sections[SECTION_PROBLEMS])
    if not signoffs:
        return None
    project_name, project_code = parse_project(info.get("技术项目+编号"))
    session = ReviewSession(
        sheet_name=ws.title,
        project_name=project_name,
        project_code=project_code,
        stage=stage,
        meeting_date=parse_date(info.get("会议日期"), epoch=ws.parent.epoch),
        project_manager=normalize_text(info.get("技术项目经理")),
        meeting_conclusion=canonical_meeting_conclusion(info.get("评审结论")),
        meeting_opinion=normalize_text(info.get("评审意见")),
        signoffs=signoffs,
        problems=_parse_problems(ws, problem_header),
    )
    session.issues.extend(validate_session(session))
    return session


def _find_labeled_value(ws: Worksheet, label: str, *, max_row: int = 6) -> object:
    for row_number in range(1, min(max_row, ws.max_row) + 1):
        for column in range(1, min(7, ws.max_column) + 1):
            if normalize_text(ws.cell(row_number, column).value) != label:
                continue
            for value_column in range(column + 1, min(7, ws.max_column) + 1):
                value = ws.cell(row_number, value_column).value
                if normalize_text(value):
                    return value
    return None


def _parse_v04_signoffs(
    ws: Worksheet,
    header_row: int,
    end_row: int,
    absent_reviewers: list[str],
) -> list[SignoffRecord]:
    headers = _header_map(ws, header_row)
    columns = {
        "role": _find_column(headers, "评审角色"),
        "reviewer": _find_column(headers, "评审人姓名") or _find_column(headers, "评审人"),
        "conclusion": _find_column(headers, "会签结果"),
        "opinion": _find_column(headers, "评审意见"),
    }
    if any(column is None for column in columns.values()):
        return []

    signoffs: list[SignoffRecord] = []
    for row_number in range(header_row + 1, end_row):
        role = normalize_text(ws.cell(row_number, columns["role"]).value)
        reviewer_value = ws.cell(row_number, columns["reviewer"]).value
        reviewer = normalize_text(reviewer_value)
        conclusion_raw = normalize_text(ws.cell(row_number, columns["conclusion"]).value)
        opinion = normalize_text(ws.cell(row_number, columns["opinion"]).value)
        if role.startswith("↓") or reviewer.startswith("填写"):
            continue
        if not reviewer and not any((role, conclusion_raw, opinion)):
            continue
        expert_name, proxy_name, reviewer_raw = parse_reviewer(reviewer_value)
        conclusion, overdue = canonical_conclusion(conclusion_raw)
        if conclusion == "-":
            conclusion = ""
        signoffs.append(
            SignoffRecord(
                role=role,
                reviewer_raw=reviewer_raw,
                expert_name=expert_name,
                proxy_name=proxy_name,
                attendance="缺席未改派" if expert_name in absent_reviewers else "正常",
                conclusion_raw=conclusion_raw,
                conclusion=conclusion,
                overdue=overdue,
                basis=opinion if opinion != "-" else "",
                row_number=row_number,
                opinion_cell=f"D{row_number}",
            )
        )
    return signoffs


def _parse_v04_problems(ws: Worksheet, header_row: int) -> list[ProblemRecord]:
    headers = _header_map(ws, header_row)
    columns = {
        "number": _find_column(headers, "序号"),
        "reviewers": _find_column(headers, "评审人"),
        "description": _find_column(headers, "问题描述"),
        "action": _find_column(headers, "是否要修正"),
        "verification": _find_column(headers, "问题等级"),
        "progress": _find_column(headers, "反馈/修改说明"),
        "status": _find_column(headers, "问题状态"),
    }
    if any(column is None for column in columns.values()):
        return []
    problems: list[ProblemRecord] = []
    for row_number in range(header_row + 1, min(ws.max_row, header_row + 7) + 1):
        values = {
            key: normalize_text(ws.cell(row_number, column).value)
            for key, column in columns.items()
        }
        if values["number"].startswith("备注说明"):
            break
        if values["number"].startswith("↓") or values["reviewers"].startswith("填写"):
            continue
        if not any(values.values()):
            continue
        problems.append(
            ProblemRecord(
                number=values["number"],
                reviewers=split_reviewers(values["reviewers"]),
                description=values["description"],
                action=values["action"],
                verification=values["verification"],
                progress=values["progress"],
                status=values["status"],
                row_number=row_number,
            )
        )
    return problems


def _parse_v04_sheet(
    ws: Worksheet,
    sections: dict[str, int],
    *,
    source_name: str,
) -> tuple[ReviewSession | None, ValidationIssue | None]:
    title = parse_report_title(ws["A1"].value)
    if not title or SECTION_SIGNOFF not in sections or SECTION_PROBLEMS not in sections:
        return None, ValidationIssue(
            "section_structure_missing",
            "最新版评审报告缺少会签或问题区块表头",
            "error",
            ws.title,
            source_name=source_name,
        )
    signoff_header = _next_header_row(
        ws, sections[SECTION_SIGNOFF], ("评审角色", "评审人", "会签结果", "评审意见")
    )
    problem_header = _next_header_row(
        ws, sections[SECTION_PROBLEMS], ("序号", "评审人", "问题描述")
    )
    if signoff_header is None or problem_header is None:
        return None, ValidationIssue(
            "section_structure_missing",
            "最新版评审报告缺少会签或问题区块表头",
            "error",
            ws.title,
            source_name=source_name,
        )
    project_name, project_code, title_stage = title
    raw_stage = normalize_text(_find_labeled_value(ws, "评审阶段")) or title_stage
    stage = raw_stage
    if raw_stage.upper() == "TDR1+TDR2":
        stage = "TDR2"
    absent_reviewers = split_absent_reviewers(
        _find_labeled_value(ws, "缺席人姓名和角色")
        or _find_labeled_value(ws, "缺席评审人姓名")
    )
    signoffs = _parse_v04_signoffs(
        ws, signoff_header, sections[SECTION_PROBLEMS], absent_reviewers
    )
    meeting_date = parse_date(_find_labeled_value(ws, "TDR会议日期"), epoch=ws.parent.epoch)
    meeting_conclusion = canonical_meeting_conclusion(_find_labeled_value(ws, "评审结论"))
    meeting_opinion = normalize_text(_find_labeled_value(ws, "评审意见"))
    problems = _parse_v04_problems(ws, problem_header)
    recorded_reviewer_names = {
        signoff.expert_name
        for signoff in signoffs
        if signoff.expert_name
        and (
            signoff.conclusion in VALID_CONCLUSIONS
            or signoff.conclusion_raw in RECORDED_NO_CONCLUSION_MARKERS
        )
    }
    has_formal_facts = bool(
        meeting_date
        or meeting_conclusion
        or meeting_opinion
        or problems
        or recorded_reviewer_names
    )
    if len(recorded_reviewer_names) < 3:
        if not has_formal_facts:
            return None, None
        return None, ValidationIssue(
            "effective_signoff_minimum",
            (
                f"正式TDR Sheet仅发现{len(recorded_reviewer_names)}名不同评审人的已记录会签结果；"
                "至少需要3名，允许值为Go／Go with Risk／Redirect／-"
            ),
            "error",
            ws.title,
            source_name=source_name,
        )
    session = ReviewSession(
        sheet_name=ws.title,
        project_name=project_name,
        project_code=project_code,
        stage=stage,
        meeting_date=meeting_date,
        project_manager="",
        meeting_conclusion=meeting_conclusion,
        meeting_opinion=meeting_opinion,
        source_name=source_name,
        absent_reviewers=absent_reviewers,
        signoffs=signoffs,
        problems=problems,
    )
    if stage != title_stage:
        session.issues.append(
            ValidationIssue(
                "stage_title_conflict",
                f"标题阶段“{title_stage}”与第一区块阶段“{stage}”不一致",
                "error",
                ws.title,
                cell_reference="A1/E5",
                source_name=source_name,
            )
        )
    if raw_stage.upper() == "TDR1+TDR2":
        session.issues.append(
            ValidationIssue(
                "stage_legacy_combined",
                "旧阶段值“TDR1+TDR2”已按TDR2读取，请在源表中改为TDR2",
                "warning",
                ws.title,
                cell_reference="E5",
                source_name=source_name,
            )
        )
    session.issues.extend(validate_session(session))
    return session, None


def read_workbook(
    source: str | Path | bytes | BinaryIO,
    *,
    source_name: str = "",
) -> tuple[list[ReviewSession], list[ValidationIssue]]:
    workbook_source: str | Path | BinaryIO
    if isinstance(source, bytes):
        workbook_source = io.BytesIO(source)
    else:
        workbook_source = source

    workbook = load_workbook(
        workbook_source,
        read_only=False,
        data_only=True,
        keep_links=True,
    )
    sessions: list[ReviewSession] = []
    structure_issues: list[ValidationIssue] = []
    try:
        for ws in workbook.worksheets:
            if "示例" in ws.title:
                continue
            sections = _find_section_rows(ws)
            if parse_report_title(ws["A1"].value):
                session, parse_issue = _parse_v04_sheet(
                    ws, sections, source_name=source_name
                )
                if session:
                    sessions.append(session)
                elif parse_issue:
                    structure_issues.append(parse_issue)
                continue
            is_tdr_candidate = ws.title.upper().startswith("TDR") or bool(sections)
            if not all(title in sections for title in SECTION_TITLES):
                if is_tdr_candidate:
                    missing = [title for title in SECTION_TITLES if title not in sections]
                    structure_issues.append(
                        ValidationIssue(
                            "section_structure_missing",
                            "缺少业务区块：" + "、".join(missing),
                            "error",
                            ws.title,
                        )
                    )
                continue
            signoff_header = _next_header_row(
                ws, sections[SECTION_SIGNOFF], SIGNOFF_HEADERS[:4]
            )
            problem_header = _next_header_row(
                ws, sections[SECTION_PROBLEMS], PROBLEM_HEADERS[:3]
            )
            if signoff_header is None:
                structure_issues.append(
                    ValidationIssue("signoff_header_missing", "未找到会签列表表头", "error", ws.title)
                )
            else:
                headers = _header_map(ws, signoff_header)
                missing = [label for label in SIGNOFF_HEADERS if _find_column(headers, label) is None]
                if missing:
                    structure_issues.append(
                        ValidationIssue(
                            "signoff_header_missing",
                            "会签列表缺少列：" + "、".join(missing),
                            "error",
                            ws.title,
                            cell_reference=f"A{signoff_header}",
                        )
                    )
            if problem_header is None:
                structure_issues.append(
                    ValidationIssue("problem_header_missing", "未找到问题汇总表表头", "error", ws.title)
                )
            else:
                headers = _header_map(ws, problem_header)
                missing = [label for label in PROBLEM_HEADERS if _find_column(headers, label) is None]
                if missing:
                    structure_issues.append(
                        ValidationIssue(
                            "problem_header_missing",
                            "问题汇总表缺少列：" + "、".join(missing),
                            "error",
                            ws.title,
                            cell_reference=f"A{problem_header}",
                        )
                    )
            if signoff_header is None or problem_header is None or any(
                issue.sheet_name == ws.title
                and issue.code in {"signoff_header_missing", "problem_header_missing"}
                for issue in structure_issues
            ):
                continue
            session = _parse_sheet(ws, sections)
            if session:
                session.source_name = source_name
                sessions.append(session)
    finally:
        workbook.close()

    issues = structure_issues + [issue for session in sessions for issue in session.issues]
    issues.extend(validate_stage_conflicts(sessions))
    issues.extend(validate_problem_number_conflicts(sessions))
    if not sessions:
        issues.append(
            ValidationIssue(
                code="no_effective_sessions",
                message="未发现可计分的正式TDR场次；示例表和无正式评审事实的空白占位Sheet已跳过",
                severity="error",
            )
        )
    for issue in issues:
        if issue.source_name is None:
            issue.source_name = source_name
    return sessions, issues
