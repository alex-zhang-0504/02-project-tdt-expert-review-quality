from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import PRODUCT_VERSION, RELEASE_CHANNEL, __version__
from .build_info import BUILD_ID, PROJECT_ID
from .questionnaire import questionnaire_payload
from .scoring import (
    calculate_contribution,
    normalize_outstanding_contribution_reason,
    normalize_professional_audit,
)
from .service import ScoringService
from .sources.feishu_document import FeishuDocumentSource
from .sources.local_excel import MAX_WORKBOOK_BYTES


WEB_DIR = Path(__file__).resolve().parents[1] / "web"
SERVICE_INSTANCE_ID = uuid4().hex
service = ScoringService()
_feishu_device_code: str | None = None

app = FastAPI(
    title="TDT评审专家打分系统",
    version=__version__,
    docs_url="/api/docs",
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


class FeishuImportRequest(BaseModel):
    url: str = Field(min_length=1)


class FinalizeRequest(BaseModel):
    analysis_id: str = Field(min_length=1)
    project_code: str = Field(min_length=1)
    expert_name: str = Field(min_length=1)
    answers: dict[str, str]
    professional_reason_tags: list[str] = Field(default_factory=list)
    professional_reason_note: str = ""
    outstanding_contribution_reason: str = ""


class ContributionRequest(BaseModel):
    answers: dict[str, str]
    professional_reason_tags: list[str] = Field(default_factory=list)
    professional_reason_note: str = ""
    outstanding_contribution_reason: str = ""


def _encoded(value: object) -> object:
    return jsonable_encoder(asdict(value))


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


@app.get("/api/questionnaire")
def questionnaire() -> dict[str, object]:
    return {"questions": questionnaire_payload()}


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


@app.post("/api/import/feishu")
def import_feishu(payload: FeishuImportRequest) -> object:
    try:
        analysis = service.import_feishu_url(payload.url)
        return _encoded(analysis)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"飞书资源读取失败：{exc}") from exc


@app.post("/api/score/finalize")
def finalize(payload: FinalizeRequest) -> object:
    try:
        result = service.finalize_expert(
            payload.analysis_id,
            payload.project_code,
            payload.expert_name,
            payload.answers,
            payload.professional_reason_tags,
            payload.professional_reason_note,
            payload.outstanding_contribution_reason,
        )
        return _encoded(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/score/contribution")
def contribution(payload: ContributionRequest) -> dict[str, object]:
    try:
        normalized_tags, normalized_note = normalize_professional_audit(
            payload.answers,
            payload.professional_reason_tags,
            payload.professional_reason_note,
        )
        normalized_outstanding_reason = normalize_outstanding_contribution_reason(
            payload.answers, payload.outstanding_contribution_reason
        )
        return {
            "contribution_score": calculate_contribution(payload.answers),
            "max_score": 40,
            "professional_reason_tags": normalized_tags,
            "professional_reason_note": normalized_note,
            "outstanding_contribution_reason": normalized_outstanding_reason,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
