from .assessment import selected_experts, require_selected
"""Session-owned, incremental AI analysis. No credentials or report data on disk."""
from dataclasses import asdict
import sqlite3
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .countermeasures import validate_predictions
from .ai_policy import load_policy, using_policy
from .scoring import refresh


def install_ai_routes(router, service, caller, sessions, lock, guard, current,
                      error_messages, ttl, encode=asdict):
    jobs = {}

    def snapshot(job):
        with service._fact_lock:
            analysis = service.get_analysis(job["analysis_id"])
            result = {k: job[k] for k in ("id", "analysis_id", "status", "total", "completed", "failed", "suspected", "message", "mode")}
            result["remaining"] = job["total"] - job["completed"] - job["failed"]
            result["policy"] = job["policy"]["receipt"]
            result["analysis"] = jsonable_encoder(encode(analysis))
            return result

    def active(job, entry):
        return not job["stop"].is_set() and sessions.get(job["owner"]) is entry

    def safe_error(exc):
        return str(exc) if str(exc) in error_messages.values() else "模型返回无效结果，本条未写入，请重试。"

    def execute(job, entry, opinions):
        try:
            for opinion in opinions:
                error = ""
                fatal = False
                for attempt in range(2):
                    with lock:
                        if not active(job, entry):
                            return
                    try:
                        with using_policy(job["policy"]):
                            raw = caller(entry.key, entry.model, [opinion])
                        result = validate_predictions([opinion], [{"id": oid, **value} for oid, value in raw.items()])[opinion.opinion_id]
                        error = ""
                        break
                    except Exception as exc:
                        error = safe_error(exc)
                        fatal = error in [error_messages[c] for c in (400, 401, 402, 422)]
                        if fatal or attempt == 1 or job["stop"].wait(1):
                            break
                with lock:
                    if sessions.get(job["owner"]) is not entry:
                        return
                    with service.edit_analysis(job['analysis_id']) as analysis:
                        # Re-resolve references after another edit was rolled back.
                        opinion = next(o for e in analysis.experts for s in e.sessions for o in s.opinions if o.opinion_id == opinion.opinion_id)
                        if error:
                            if opinion.ai_status == 'pending':
                                opinion.reason = "识别失败：" + error
                        else:
                            opinion.ai_status = result["status"]
                            opinion.excerpt = result["excerpt"]
                            opinion.reason = result["reason"]
                            receipt = job["policy"]["receipt"]
                            opinion.rule_version = "countermeasure-policy-v" + receipt["version"] + "/sha256:" + receipt["sha256"] + "/" + entry.model
                        refresh(analysis.experts)
                    if error:
                        job['failed'] += 1
                    else:
                        job['completed'] += 1
                        job['completed_ids'].add(opinion.opinion_id)
                        job['suspected'] += result['status'] == 'suspected'
                    if fatal:
                        job["message"] = error + " 已停止后续调用，未完成意见保持待识别。"
                        break
            with lock:
                job["status"] = "partial" if job["failed"] else "completed"
        except Exception:
            with lock:
                job["status"] = "partial"
                job["message"] = "分析任务中断，已保存成功结果，请重试未完成意见。"
        finally:
            with lock:
                if not active(job, entry):
                    job["status"] = "cancelled"
                    job["message"] = "已停止，成功结果已保留，未完成意见可继续识别。"
                    if job['completed'] == job['total']:
                        job['status'] = 'completed'
                        job['message'] = '全部意见已完成识别。'
                entry.busy = False
                entry.expires = monotonic() + ttl
                with service._fact_lock:
                    analysis = service.get_analysis(job["analysis_id"])
                    total = sum(e.overall["opinions"] for e in selected_experts(analysis))
                    pending = sum(e.overall["pending"] for e in selected_experts(analysis))
                    analysis.ai_message = (f"本批次{total - pending}／{total}条已识别；本次共{job['total']}条，成功{job['completed']}条（疑似{job['suspected']}条），"
                                           f"失败{job['failed']}条，剩余{job['total'] - job['completed'] - job['failed']}条。"
                                           + job["message"])
                    try:
                        service.persist(analysis)
                    except (OSError, ValueError, sqlite3.Error):
                        job['status'] = 'partial'
                        job['message'] = '本机保存失败，请检查存储空间并重新打开考核；未成功写入的结果不能视为已保存。'
                    finally:
                        service._active_ai = max(0, getattr(service, '_active_ai', 1) - 1)

    @router.post("/jobs")
    async def start(request: Request):
        guard(request)
        try:
            data = await request.json()
            if data.get("confirmed") is not True:
                raise ValueError()
            analysis = service.get_analysis(data["analysis_id"])
            if any(i.severity == "error" for i in analysis.issues):
                raise ValueError()
        except Exception:
            raise HTTPException(400, "请先读取有效报告，并确认向DeepSeek发送意见文本。") from None
        try:
            require_selected(analysis)
            policy = load_policy()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if data.get("policy_hash") and data["policy_hash"] != policy["receipt"]["sha256"]:
            raise HTTPException(409, "判定配置已变更，请重新打开分析窗口核对规则版本。")
        with lock:
            token, entry = current(request)
            for job in jobs.values():
                if job["analysis_id"] == analysis.analysis_id and job["status"] in {"running", "stopping"}:
                    if job["owner"] != token:
                        raise HTTPException(409, "该报告已有AI分析任务，请等待完成。")
                    return JSONResponse(snapshot(job), headers={"Cache-Control": "no-store"})
            if entry.busy or not entry.verified:
                raise HTTPException(409, "请先完成AI连接验证，或等待当前调用结束。")
            mode = data.get('mode', 'pending')
            if mode not in {'pending', 'all', 'resume'}:
                raise HTTPException(400, '识别范围无效')
            completed_ids = set()
            with service._fact_lock:
                all_opinions = [o for e in selected_experts(analysis) for s in e.sessions for o in s.opinions]
                if mode == 'resume':
                    previous = jobs.get(data.get('resume_id'))
                    if not previous or previous['owner'] != token or previous['analysis_id'] != analysis.analysis_id:
                        raise HTTPException(409, '未找到本会话可继续的任务，请重新识别')
                    targets = previous['target_ids']
                    completed_ids = set(previous['completed_ids'])
                else:
                    targets = {o.opinion_id for o in all_opinions if mode == 'all' or o.ai_status == 'pending'}
                opinions = [o for o in all_opinions if o.opinion_id in targets - completed_ids]
            if not opinions:
                raise HTTPException(409, "全部意见已有识别结果，无需重复调用。")
            policy["roles"] = {}
            for expert in selected_experts(analysis):
                for session in expert.sessions:
                    roles = sorted({signoff.role for source in analysis.sessions
                                    if source.project_code == session.project_code and source.stage == session.stage
                                    and source.source_name == session.source_name
                                    for signoff in source.signoffs if signoff.expert_name == expert.expert_name})
                    for opinion in session.opinions:
                        policy["roles"][opinion.opinion_id] = roles
            # Keep only the latest finished task for this analysis and session.
            for oid in list(jobs):
                old = jobs[oid]
                if old["status"] not in {"running", "stopping"} and old['analysis_id'] == analysis.analysis_id and (old["owner"] == token or old["owner"] not in sessions):
                    del jobs[oid]
            job = dict(id=uuid4().hex, owner=token, analysis_id=analysis.analysis_id,
                       status="running", total=len(targets), completed=len(completed_ids), failed=0,
                       suspected=sum(o.ai_status == 'suspected' for o in all_opinions if o.opinion_id in completed_ids),
                       message="", stop=Event(), policy=policy, mode=mode,
                       target_ids=targets, completed_ids=completed_ids)
            jobs[job["id"]] = job
            entry.busy = True
            service._active_ai = getattr(service, '_active_ai', 0) + 1
            analysis.ai_message = "AI逐条分析进行中，成功结果实时保存。"
            Thread(target=execute, args=(job, entry, opinions), daemon=True).start()
            return JSONResponse(snapshot(job), headers={"Cache-Control": "no-store"})

    def owned(request, job_id):
        guard(request)
        job = jobs.get(job_id)
        if not job or job["owner"] != request.headers.get("x-experiment-session", ""):
            raise HTTPException(404, "未找到当前会话的分析任务。")
        return job

    @router.post("/jobs/{job_id}")
    def status(request: Request, job_id: str):
        with lock:
            return JSONResponse(snapshot(owned(request, job_id)), headers={"Cache-Control": "no-store"})

    @router.post("/jobs/{job_id}/cancel")
    def cancel(request: Request, job_id: str):
        with lock:
            job = owned(request, job_id)
            if job["status"] in {"running", "stopping"}:
                job["stop"].set()
                job['status'] = 'stopping'
            return JSONResponse(snapshot(job), headers={"Cache-Control": "no-store"})
