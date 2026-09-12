from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal


Severity = Literal["error", "warning", "info"]
Level = Literal["high", "medium", "low"]
OPINION_RULE_VERSION = "countermeasure-v0.6"


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: Severity = "warning"
    sheet_name: str | None = None
    expert_name: str | None = None
    row_number: int | None = None
    cell_reference: str | None = None
    source_name: str | None = None
    requires_confirmation: bool = False
    confirmation_key: str | None = None
    confirmed_by_user: bool = False
    confirmed_at: str | None = None
    related_locations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OpinionSource:
    text: str
    cell_references: list[str] = field(default_factory=list)
    raw_texts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProblemRecord:
    number: str
    reviewers: list[str]
    description: str
    action: str
    verification: str
    progress: str
    status: str
    row_number: int
    cell_references: dict[str, str] = field(default_factory=dict)
    reviewers_raw: list[str] = field(default_factory=list)
    unmatched_reviewers: list[str] = field(default_factory=list)
    status_raw: str = ""
    source_number: str = ""
    item_index: int | None = None


@dataclass(slots=True)
class SignoffRecord:
    role: str
    reviewer_raw: str
    expert_name: str
    proxy_name: str | None
    attendance: str
    conclusion_raw: str
    conclusion: str
    overdue: bool
    basis: str
    row_number: int
    opinion_cell: str = ""
    cell_references: dict[str, str] = field(default_factory=dict)
    opinion_sources: list[OpinionSource] = field(default_factory=list)


@dataclass(slots=True)
class ReviewSession:
    sheet_name: str
    project_name: str
    project_code: str
    stage: str
    meeting_date: date | None
    project_manager: str
    meeting_conclusion: str
    meeting_opinion: str
    source_name: str = ""
    absent_reviewers_raw: str = ""
    absent_reviewers: list[str] = field(default_factory=list)
    signoffs: list[SignoffRecord] = field(default_factory=list)
    problems: list[ProblemRecord] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    field_references: dict[str, str] = field(default_factory=dict)
    parser_profile: str = "legacy"

    @property
    def review_id(self) -> str:
        return f"{self.project_code}-{self.stage}"


@dataclass(slots=True)
class OpinionFact:
    opinion_id: str
    text: str
    cells: list[str]
    raw_texts: list[str]
    ai_status: str = "pending"
    excerpt: str = ""
    reason: str = ""
    rule_version: str = ""
    included: bool | None = None
    audit: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class SessionFact:
    review_id: str
    project_code: str
    project_name: str
    stage: str
    sheet_name: str
    source_name: str
    attendance: str
    attended: bool | None
    signoff: str
    signed: bool
    proxy_name: str | None
    opinions: list[OpinionFact]
    cells: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ExpertFacts:
    expert_name: str
    sessions: list[SessionFact]
    stages: dict[str, dict]
    overall: dict


@dataclass(slots=True)
class BatchImportSummary:
    discovered_count: int
    candidate_count: int
    succeeded_count: int
    failed_count: int
    excluded_count: int
    complete: bool
    excluded_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkbookAnalysis:
    analysis_id: str
    source_type: str
    source_name: str
    sessions: list[ReviewSession]
    experts: list[ExpertFacts]
    issues: list[ValidationIssue]
    reports: list[ReportAnalysis] = field(default_factory=list)
    batch_summary: BatchImportSummary | None = None
    rule_version: str = "facts-v0.6"
    ai_message: str = ""
    subjective_reviews: dict[str, dict] = field(default_factory=dict)


@dataclass(slots=True)
class ReportAnalysis:
    report_id: str
    source_type: str
    source_name: str
    session_count: int
    expert_count: int
    issues: list[ValidationIssue]
