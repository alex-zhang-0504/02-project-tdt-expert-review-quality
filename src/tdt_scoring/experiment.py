"""Opt-in DeepSeek experiment. Credentials and results never enter analysis data."""
from dataclasses import dataclass, field
import json
import secrets
from threading import Lock
from time import monotonic
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

from fastapi import APIRouter, HTTPException, Request as WebRequest
from fastapi.responses import JSONResponse

from .countermeasures import SYSTEM_PROMPT, validate_predictions
from .models import OpinionFact

BASE_URL = "https://api.deepseek.com"
MODELS = ("deepseek-v4-flash", "deepseek-v4-pro")
TTL = 3600


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def call_deepseek(key, model, opinions):
    prompt = SYSTEM_PROMPT.replace("只返回JSON数组", '只返回JSON对象，格式为{"results":[{"id":"原ID","status":"yes/no/suspected","excerpt":"原文","reason":"理由"}]}，results为数组')
    payload = {"model": model, "messages": [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps([{"id": o.opinion_id, "text": o.text} for o in opinions], ensure_ascii=False)},
    ], "response_format": {"type": "json_object"}, "stream": False,
        "thinking": {"type": "disabled"}, "max_tokens": 4096}
    request = Request(BASE_URL + "/chat/completions",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        # Do not forward secrets through redirects or environment-configured proxies.
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=45) as response:
            raw = response.read(262145)
        if len(raw) > 262144:
            raise ValueError()
        envelope = json.loads(raw)
        choice = envelope["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError()
        predictions = json.loads(choice["message"]["content"])["results"]
        result = validate_predictions(opinions, predictions)
        return result
    except HTTPError as exc:
        messages = {401: "密钥无效，请重新配置。", 402: "账户余额不足。",
                    429: "调用过于频繁，请稍后重试。"}
        raise ValueError(messages.get(exc.code, "DeepSeek服务请求失败，请稍后重试。")) from None
    except Exception:
        # Never expose upstream bodies, requests or exception text containing secrets.
        raise ValueError("连接超时、网络不可达或模型结果无效；未修改统计。") from None


@dataclass
class ExperimentSession:
    key: str = field(repr=False)
    model: str
    expires: float
    busy: bool = False


def create_experiment_router(service, caller=call_deepseek):
    router = APIRouter(prefix="/api/experiment")
    sessions = {}
    lock = Lock()

    def guard(request):
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(403, "个人实验仅限本机访问。")
        if request.headers.get("x-experiment-request") != "1":
            raise HTTPException(403, "请从系统个人实验设置操作。")
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "拒绝跨站实验请求。")

    def prune():
        for token in list(sessions):
            if sessions[token].expires <= monotonic() and not sessions[token].busy:
                del sessions[token]

    def current(request):
        token = request.headers.get("x-experiment-session", "")
        prune()
        entry = sessions.get(token)
        if not entry or entry.expires <= monotonic():
            raise HTTPException(409, "实验未开启或已过期，请重新配置。")
        return token, entry

    @router.post("/settings")
    async def settings(request: WebRequest):
        guard(request)
        if len(await request.body()) > 4096:
            raise HTTPException(400, "配置内容过长。")
        try:
            data = await request.json()
            key, model = data["api_key"], data["model"]
            if not isinstance(key, str) or not 8 <= len(key) <= 512 or not key.isascii() or any(c.isspace() for c in key) or model not in MODELS:
                raise ValueError()
        except Exception:
            raise HTTPException(400, "请填写有效密钥并选择支持的模型。") from None
        with lock:
            prune()
            old = request.headers.get("x-experiment-session", "")
            if old in sessions and sessions[old].busy:
                raise HTTPException(409, "调用进行中，请完成后修改配置。")
            if old not in sessions and len(sessions) >= 8:
                raise HTTPException(429, "实验会话过多，请关闭其他会话后重试。")
            sessions.pop(old, None)
            token = secrets.token_urlsafe(32)
            sessions[token] = ExperimentSession(key, model, monotonic() + TTL)
        return JSONResponse({"session": token, "model": model, "expires_in": TTL}, headers={"Cache-Control": "no-store"})

    @router.post("/disable")
    def disable(request: WebRequest):
        guard(request)
        with lock:
            sessions.pop(request.headers.get("x-experiment-session", ""), None)
        return {"message": "已关闭并清除本次实验密钥；已发出的请求无法撤回。"}

    def run(request, opinions):
        guard(request)
        with lock:
            token, entry = current(request)
            if entry.busy:
                raise HTTPException(409, "已有实验请求进行中。")
            entry.busy = True
        try:
            result = caller(entry.key, entry.model, opinions)
            # The network adapter and injected test doubles obey the same contract.
            result = validate_predictions(opinions, [
                {"id": oid, **value} for oid, value in result.items()])
            with lock:
                if sessions.get(token) is not entry or entry.expires <= monotonic():
                    raise HTTPException(409, "实验已关闭或过期，结果已丢弃。")
            return {"model": entry.model, "results": [
                {"text": o.text, **result[o.opinion_id]} for o in opinions],
                "notice": "个人实验结果，未写回主表或导出。"}
        except HTTPException:
            raise
        except ValueError as exc:
            # Only adapter-produced messages are safe; third-party errors are not.
            allowed = {"密钥无效，请重新配置。", "账户余额不足。", "调用过于频繁，请稍后重试。",
                       "DeepSeek服务请求失败，请稍后重试。", "连接超时、网络不可达或模型结果无效；未修改统计。"}
            raise HTTPException(422, str(exc) if str(exc) in allowed else "模型返回无效结果，未修改统计。") from None
        except Exception:
            raise HTTPException(422, "实验调用失败，未修改统计。") from None
        finally:
            with lock:
                entry.busy = False

    @router.post("/test")
    def test(request: WebRequest):
        opinion = OpinionFact("connection-test", "建议增加屏蔽罩，降低射频干扰。", [], [])
        return run(request, [opinion])

    @router.post("/preview")
    async def preview(request: WebRequest):
        guard(request)
        try:
            data = await request.json()
            if data.get("confirmed") is not True:
                raise ValueError()
            analysis = service.get_analysis(data["analysis_id"])
            if any(i.severity == "error" for i in analysis.issues):
                raise ValueError()
            # Bounded, deterministic preview; no names, projects or source cells sent.
            opinions = [o for e in analysis.experts for s in e.sessions for o in s.opinions][:10]
            if not opinions or sum(len(o.text) for o in opinions) > 12000:
                raise ValueError()
        except Exception:
            raise HTTPException(400, "请先读取有效报告并确认外发；最多试验前10条、共12000字。") from None
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(run, request, opinions)

    return router
