from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal


Severity = Literal["error", "warning", "info"]
Level = Literal["high", "medium", "low"]
OPINION_RULE_VERSION = "v0.4-opinion-exclusion-20260901"


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
class ScoreItem:
    level: Level
    score: int
    reason: str


@dataclass(slots=True)
class OpinionEvidence:
    source_text: str
    source_cell: str
    technical_object: str | None
    professional_action: str | None
    specific_detail: str | None
    zero_reason: str | None = None
    rule_version: str = OPINION_RULE_VERSION
    source_texts: list[str] = field(default_factory=list)
    source_cells: list[str] = field(default_factory=list)

    @property
    def has_technical_object(self) -> bool:
        return self.technical_object is not None

    @property
    def has_professional_action(self) -> bool:
        return self.professional_action is not None

    @property
    def has_specific_detail(self) -> bool:
        return self.specific_detail is not None


@dataclass(slots=True)
class ExpertSessionScore:
    review_id: str
    sheet_name: str
    project_code: str
    project_name: str
    stage: str
    expert_name: str
    proxy_name: str | None
    role: str
    attendance: ScoreItem
    signoff: ScoreItem
    opinion: ScoreItem
    opinion_evidence: OpinionEvidence
    total: int


@dataclass(slots=True)
class ExpertProjectScore:
    expert_name: str
    project_code: str
    project_name: str
    sessions: list[ExpertSessionScore]
    process_average: float
    effective_session_count: int
    project_process_scores: list[ProjectProcessScore] = field(default_factory=list)
    participation_session_count: int = 0
    participation_session_ids: list[str] = field(default_factory=list)
    participation_score: int = 0
    problem_session_count: int = 0
    problem_session_ids: list[str] = field(default_factory=list)
    problem_score: int = 0
    annual_service_score: int = 0
    objective_score: float = 0
    expected_session_count: int = 0
    proxy_session_count: int = 0
    proxy_rate: float = 0
    contribution_score: int | None = None
    professional_reason_tags: list[str] = field(default_factory=list)
    professional_reason_note: str | None = None
    outstanding_contribution_reason: str | None = None
    total_score: float | None = None
    grade: str | None = None
    status: str = "待问卷作答"


@dataclass(slots=True)
class ProjectProcessScore:
    project_code: str
    project_name: str
    session_count: int
    process_average: float


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
    experts: list[ExpertProjectScore]
    issues: list[ValidationIssue]
    reports: list[ReportAnalysis] = field(default_factory=list)
    batch_summary: BatchImportSummary | None = None


@dataclass(slots=True)
class ReportAnalysis:
    report_id: str
    source_type: str
    source_name: str
    session_count: int
    expert_count: int
    issues: list[ValidationIssue]
