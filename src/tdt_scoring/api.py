from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import PRODUCT_VERSION, RELEASE_CHANNEL, __version__
from .build_info import BUILD_ID, PROJECT_ID
from .progress import ImportJobStore
from .search import expert_name_search_terms
from .service import ScoringService
from .sources.feishu_document import FeishuDocumentSource
from .sources.local_excel import MAX_WORKBOOK_BYTES
from .submission import EXCEL_MEDIA_TYPE, build_dimension_one_workbook
from .subjective import DIMENSIONS, ReviewInput, save_review, build_workbook as build_subjective_workbook
from .score_statistics import build_statistics, build_statistics_workbook


WEB_DIR = Path(__file__).resolve().parents[1] / "web"
SERVICE_INSTANCE_ID = uuid4().hex
service = ScoringService()
import_jobs = ImportJobStore()
import_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tdrx-import")
_feishu_device_code: str | None = None

app = FastAPI(
    title="V0.6四维事实统计版",
    version=__version__,
    docs_url="/api/docs",
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

from .experiment import create_experiment_router
app.include_router(create_experiment_router(service))


class FeishuImportRequest(BaseModel):
    url: str = Field(min_length=1)


class ConfirmReviewerNamesRequest(BaseModel):
    analysis_id: str = Field(min_length=1)
    confirmation_key: str = Field(min_length=1)


class DimensionOneExportRequest(BaseModel):
    analysis_id: str = Field(min_length=1)
    package_kind: Literal["annual_result", "manager_submission"]
    batch_id: str = Field(min_length=1)
    manager_id: str = ""
    manager_name: str = ""
    revision: int = Field(default=1, ge=1)


def _encoded(value: object) -> object:
    encoded = jsonable_encoder(asdict(value))
    if not isinstance(encoded, dict):
        return encoded
    _add_expert_search_terms(encoded)
    for expert in encoded.get("experts", []):
        if isinstance(expert, dict):
            _add_expert_search_terms(expert)
    return encoded


def _add_expert_search_terms(payload: dict[str, object]) -> None:
    expert_name = payload.get("expert_name")
    if isinstance(expert_name, str) and expert_name:
        payload.update(expert_name_search_terms(expert_name))


def _require_feishu_authorization() -> None:
    try:
        status = FeishuDocumentSource.authorization_status()
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if status.get("ready") is not True:
        raise HTTPException(
            status_code=401,
            detail="飞书用户授权未完成，请先点击“授权飞书读取”，在浏览器完成授权后再开始读取",
        )


def _run_feishu_import(job_id: str, url: str) -> None:
    import_jobs.start(job_id)
    try:
        analysis = service.import_feishu_url(
            url,
            progress=lambda event: import_jobs.record(job_id, event),
            on_candidates=lambda names: import_jobs.set_reports(job_id, names),
        )
        import_jobs.complete(job_id, analysis)
    except Exception as exc:
        import_jobs.fail(job_id, str(exc))


def _run_local_import(job_id: str, uploads: list[tuple[bytes, str]]) -> None:
    import_jobs.start(job_id)
    try:
        analysis = service.import_local_files(
            uploads,
            progress=lambda event: import_jobs.record(job_id, event),
        )
        import_jobs.complete(job_id, analysis)
    except Exception as exc:
        import_jobs.fail(job_id, str(exc))


def _job_payload(job_id: str) -> dict[str, object]:
    try:
        job = import_jobs.snapshot(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    reports = []
    for report in job.reports:
        reports.append(
            {
                "source_name": report.source_name,
                "status": report.status,
                "progress_percent": report.progress_percent,
                "current_checkpoint": report.current_checkpoint,
                "current_checkpoint_label": report.current_checkpoint_label,
                "message": report.message,
                "checkpoint_durations_ms": report.checkpoint_durations_ms,
            }
        )
    payload: dict[str, object] = {
        "job_id": job.job_id,
        "source_type": job.source_type,
        "status": job.status,
        "reports": reports,
        "error": job.error,
    }
    if job.result is not None:
        payload["result"] = _encoded(job.result)
    return payload


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(
        html.replace("__BUILD_ID__", BUILD_ID),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": PRODUCT_VERSION,
        "release_channel": RELEASE_CHANNEL,
        "project_id": PROJECT_ID,
        "build_id": BUILD_ID,
        "service_instance_id": SERVICE_INSTANCE_ID,
    }


@app.get("/api/subjective/catalog")
def subjective_catalog() -> object:
    return [{"id": d["id"], "title": d["title"], "options": [
        {k: v for k, v in option.items() if k != "score"} for option in d["options"]]} for d in DIMENSIONS]


@app.get("/api/statistics/scores")
def score_statistics(analysis_id: str = Query(min_length=1), scope_confirmed: bool = False) -> object:
    try:
        with service._fact_lock:
            return build_statistics(service.get_analysis(analysis_id), scope_confirmed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/statistics/scores/export")
def export_score_statistics(analysis_id: str = Query(min_length=1), scope_confirmed: bool = False) -> StreamingResponse:
    try:
        with service._fact_lock:
            content = build_statistics_workbook(service.get_analysis(analysis_id), scope_confirmed)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(BytesIO(content), media_type=EXCEL_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=score-statistics.xlsx", "Cache-Control": "no-store"})


@app.post("/api/subjective/review")
def subjective_review(payload: ReviewInput) -> object:
    try:
        with service._fact_lock:
            return save_review(service.get_analysis(payload.analysis_id), payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/subjective/export")
def export_subjective(analysis_id: str = Query(min_length=1)) -> StreamingResponse:
    try:
        with service._fact_lock:
            content = build_subjective_workbook(service.get_analysis(analysis_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(BytesIO(content), media_type=EXCEL_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=subjective-assessment.xlsx", "Cache-Control": "no-store"})


@app.get("/api/feishu/auth/status")
def feishu_auth_status() -> dict[str, object]:
    try:
        return FeishuDocumentSource.authorization_status()
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/feishu/auth/start")
def feishu_auth_start() -> dict[str, object]:
    global _feishu_device_code
    try:
        authorization = FeishuDocumentSource.start_authorization()
        _feishu_device_code = str(authorization.pop("device_code"))
        return authorization
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/feishu/auth/complete")
def feishu_auth_complete() -> dict[str, object]:
    global _feishu_device_code
    if not _feishu_device_code:
        raise HTTPException(status_code=400, detail="授权会话不存在或已过期，请重新发起授权")
    try:
        status = FeishuDocumentSource.complete_authorization(_feishu_device_code)
        _feishu_device_code = None
        return status
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/import/local")
async def import_local(
    request: Request,
    filename: str = Query(min_length=1),
) -> object:
    try:
        content_length = int(request.headers.get("content-length", "0") or 0)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的Content-Length请求头") from exc
    if content_length > MAX_WORKBOOK_BYTES:
        raise HTTPException(status_code=413, detail="Excel文件超过30MB限制")
    try:
        content = await request.body()
        analysis = service.import_local_bytes(content, filename)
        return _encoded(analysis)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Excel解析失败：{exc}") from exc


@app.post("/api/import/local-batch")
async def import_local_batch(
    files: list[UploadFile] = File(...),
) -> object:
    if not files:
        raise HTTPException(status_code=400, detail="请至少选择一份Excel评审报告")
    uploads: list[tuple[bytes, str]] = []
    for upload in files:
        filename = upload.filename or ""
        if not filename:
            raise HTTPException(status_code=400, detail="存在文件名为空的评审报告")
        content = await upload.read(MAX_WORKBOOK_BYTES + 1)
        uploads.append((content, filename))
    try:
        return _encoded(
            service.import_local_files(uploads)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Excel批量解析失败：{exc}") from exc


@app.post("/api/import/local-batch/start")
async def start_local_batch_import(
    files: list[UploadFile] = File(...),
) -> dict[str, object]:
    if not files:
        raise HTTPException(status_code=400, detail="请至少选择一份Excel评审报告")
    uploads: list[tuple[bytes, str]] = []
    for upload in files:
        filename = upload.filename or ""
        if not filename:
            raise HTTPException(status_code=400, detail="存在文件名为空的评审报告")
        content = await upload.read(MAX_WORKBOOK_BYTES + 1)
        uploads.append((content, filename))
    job = import_jobs.create("local_excel")
    import_jobs.set_reports(job.job_id, [filename for _, filename in uploads])
    import_executor.submit(_run_local_import, job.job_id, uploads)
    return {"job_id": job.job_id, "status": job.status}


@app.post("/api/import/feishu")
def import_feishu(payload: FeishuImportRequest) -> object:
    _require_feishu_authorization()
    try:
        analysis = service.import_feishu_url(payload.url)
        return _encoded(analysis)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"飞书资源读取失败：{exc}") from exc


@app.post("/api/import/feishu/start")
def start_feishu_import(payload: FeishuImportRequest) -> dict[str, object]:
    _require_feishu_authorization()
    try:
        if FeishuDocumentSource.is_folder_url(payload.url):
            FeishuDocumentSource.validate_folder_url(payload.url)
            source_type = "feishu_folder"
        else:
            FeishuDocumentSource.validate_url(payload.url)
            source_type = "feishu_document"
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = import_jobs.create(source_type)
    import_executor.submit(_run_feishu_import, job.job_id, payload.url)
    return {"job_id": job.job_id, "status": job.status}


@app.get("/api/import/jobs/{job_id}")
def import_job_status(job_id: str) -> dict[str, object]:
    return _job_payload(job_id)


@app.post("/api/export/dimension-one")
def export_dimension_one(payload: DimensionOneExportRequest) -> StreamingResponse:
    try:
        analysis = service.get_analysis(payload.analysis_id)
        content = build_dimension_one_workbook(
            analysis,
            package_kind=payload.package_kind,
            batch_id=payload.batch_id,
            manager_id=payload.manager_id,
            manager_name=payload.manager_name,
            revision=payload.revision,
            product_version=PRODUCT_VERSION,
            build_id=BUILD_ID,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.package_kind == "manager_submission":
        filename = f"四维事实提交_{payload.batch_id}_{payload.manager_id}_R{payload.revision:02d}.xlsx"
    else:
        filename = f"四维事实结果_{payload.batch_id}.xlsx"
    disposition = (
        'attachment; filename="dimension-one.xlsx"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return StreamingResponse(
        BytesIO(content),
        media_type=EXCEL_MEDIA_TYPE,
        headers={"Content-Disposition": disposition, "Cache-Control": "no-store"},
    )


@app.post("/api/analysis/confirm-reviewer-names-distinct")
def confirm_reviewer_names_distinct(
    payload: ConfirmReviewerNamesRequest,
) -> object:
    try:
        return _encoded(
            service.confirm_reviewer_names_distinct(
                payload.analysis_id,
                payload.confirmation_key,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc


@app.post("/api/import/dimension-one-submissions")
async def import_dimension_one_submissions(
    files: list[UploadFile] = File(...),
    expected_manager_count: int = Form(..., ge=1),
    expected_project_count: int | None = Form(default=None, ge=1),
) -> object:
    if not files:
        raise HTTPException(status_code=400, detail="请至少选择一份项目经理维度1提交表")
    uploads: list[tuple[bytes, str]] = []
    for upload in files:
        filename = upload.filename or ""
        if not filename:
            raise HTTPException(status_code=400, detail="存在文件名为空的维度1提交表")
        content = await upload.read(MAX_WORKBOOK_BYTES + 1)
        if len(content) > MAX_WORKBOOK_BYTES:
            raise HTTPException(status_code=413, detail=f"“{filename}”超过30MB限制")
        uploads.append((content, filename))
    try:
        return _encoded(
            service.merge_dimension_one_submissions(
                uploads,
                expected_manager_count=expected_manager_count,
                expected_project_count=expected_project_count,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



class SolutionSelectionRequest(BaseModel):
    analysis_id: str = Field(min_length=1)
    opinion_id: str = Field(min_length=1)
    included: bool


class IdentifySolutionsRequest(BaseModel):
    analysis_id: str = Field(min_length=1)


@app.post("/api/facts/solution-selection")
def select_solution(payload: SolutionSelectionRequest) -> object:
    try:
        return _encoded(service.select_solution(payload.analysis_id, payload.opinion_id, payload.included))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/facts/identify-solutions")
def identify_solutions(payload: IdentifySolutionsRequest) -> object:
    try:
        return _encoded(service.identify_solutions(payload.analysis_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
