from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal
from uuid import uuid4

from .models import WorkbookAnalysis


CHECKPOINTS: tuple[tuple[str, str], ...] = (
    ("report_acquisition", "获取报告"),
    ("xlsx_acquisition", "获取XLSX"),
    ("workbook_parse", "解析工作簿"),
    ("template_structure", "检查模板结构"),
    ("session_identity", "检查场次身份"),
    ("reviewer_roster", "检查评审名单"),
    ("attendance_signoff", "检查出勤与会签"),
    ("opinions_problems", "检查意见与问题"),
    ("session_uniqueness", "检查场次唯一性"),
    ("fact_bounds", "检查统计事实"),
)
CHECKPOINT_LABELS = dict(CHECKPOINTS)


@dataclass(slots=True)
class ProgressEvent:
    source_name: str
    checkpoint_id: str
    status: Literal["started", "completed", "warning", "error"]
    duration_ms: float = 0.0
    message: str = ""


@dataclass(slots=True)
class ReportProgress:
    source_name: str
    status: str = "queued"
    completed_checkpoints: list[str] = field(default_factory=list)
    checkpoint_durations_ms: dict[str, float] = field(default_factory=dict)
    current_checkpoint: str = ""
    current_checkpoint_label: str = "等待检查"
    message: str = ""

    @property
    def progress_percent(self) -> int:
        return round(len(self.completed_checkpoints) * 100 / len(CHECKPOINTS))


@dataclass(slots=True)
class ImportJob:
    job_id: str
    source_type: str
    status: str = "queued"
    reports: list[ReportProgress] = field(default_factory=list)
    result: WorkbookAnalysis | None = None
    error: str = ""


class ImportJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, ImportJob] = {}
        self._lock = Lock()

    def create(self, source_type: str) -> ImportJob:
        job = ImportJob(job_id=uuid4().hex, source_type=source_type)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def start(self, job_id: str) -> None:
        with self._lock:
            self._get(job_id).status = "running"

    def set_reports(self, job_id: str, source_names: list[str]) -> None:
        with self._lock:
            job = self._get(job_id)
            existing = {report.source_name: report for report in job.reports}
            job.reports = [
                existing.get(name, ReportProgress(source_name=name)) for name in source_names
            ]

    def record(self, job_id: str, event: ProgressEvent) -> None:
        if event.checkpoint_id not in CHECKPOINT_LABELS:
            raise ValueError(f"未知检查节点：{event.checkpoint_id}")
        with self._lock:
            job = self._get(job_id)
            matching_reports = [
                item for item in job.reports if item.source_name == event.source_name
            ]
            report = None
            if event.status != "started":
                report = next(
                    (
                        item
                        for item in matching_reports
                        if item.current_checkpoint == event.checkpoint_id
                        and item.status == "running"
                        and event.checkpoint_id not in item.completed_checkpoints
                    ),
                    None,
                )
            if report is None:
                report = next(
                    (
                        item
                        for item in matching_reports
                        if event.checkpoint_id not in item.completed_checkpoints
                        and item.status != "error"
                    ),
                    None,
                )
            if report is None:
                report = ReportProgress(source_name=event.source_name)
                job.reports.append(report)
            report.current_checkpoint = event.checkpoint_id
            report.current_checkpoint_label = CHECKPOINT_LABELS[event.checkpoint_id]
            report.message = event.message
            if event.status == "started":
                report.status = "running"
                return
            report.checkpoint_durations_ms[event.checkpoint_id] = round(
                max(0.0, event.duration_ms), 3
            )
            if event.status in {"completed", "warning"}:
                if event.checkpoint_id not in report.completed_checkpoints:
                    report.completed_checkpoints.append(event.checkpoint_id)
                report.status = (
                    "completed"
                    if len(report.completed_checkpoints) == len(CHECKPOINTS)
                    else "running"
                )
            else:
                report.status = "error"

    def complete(self, job_id: str, result: WorkbookAnalysis) -> None:
        with self._lock:
            job = self._get(job_id)
            job.result = result
            job.status = "completed"

    def fail(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._get(job_id)
            job.error = message
            job.status = "error"

    def snapshot(self, job_id: str) -> ImportJob:
        with self._lock:
            return deepcopy(self._get(job_id))

    def _get(self, job_id: str) -> ImportJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError("导入任务不存在或本地服务已重启，请重新导入评审表") from exc
