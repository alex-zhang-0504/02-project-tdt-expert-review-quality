import json
import unittest
import asyncio
from types import SimpleNamespace
from dataclasses import asdict
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

from fastapi import FastAPI
from tdt_scoring.experiment import create_experiment_router, call_deepseek, BASE_URL
from tdt_scoring.models import OpinionFact
from tdt_scoring.service import ScoringService
from tests.workbook_factory import build_v04_workbook


def simulated_call(key, model, opinions):
    return {o.opinion_id: {"status": "suspected", "excerpt": o.text,
            "reason": "仅为模拟连接验收，不代表模型准确率"} for o in opinions}


class LocalClient:
    def __init__(self, app):
        self.app = app

    def post(self, path, headers=None, json=None):
        import json as codec
        content = codec.dumps(json or {}).encode()
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                 "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
                 "query_string": b"", "root_path": "", "server": ("127.0.0.1", 80),
                 "client": ("127.0.0.1", 12345), "headers": [(b"host", b"127.0.0.1"),
                 (b"content-type", b"application/json")] +
                 [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]}
        messages = []
        async def receive():
            return {"type": "http.request", "body": content, "more_body": False}
        async def send(message):
            messages.append(message)
        asyncio.run(self.app(scope, receive, send))
        status = next(m["status"] for m in messages if m["type"] == "http.response.start")
        text = b"".join(m.get("body", b"") for m in messages).decode()
        return SimpleNamespace(status_code=status, text=text, json=lambda: codec.loads(text))


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.service = ScoringService()
        self.caller = MagicMock(side_effect=simulated_call)
        app = FastAPI()
        app.include_router(create_experiment_router(self.service, self.caller))
        self.client = LocalClient(app)
        self.headers = {"X-Experiment-Request": "1"}

    def configure(self):
        response = self.client.post("/api/experiment/settings", headers=self.headers,
            json={"api_key": "fake-test-key-only", "model": "deepseek-v4-flash"})
        self.assertEqual(200, response.status_code)
        self.assertNotIn("fake-test-key-only", response.text)
        self.headers["X-Experiment-Session"] = response.json()["session"]

    def test_default_off_configure_test_disable(self):
        self.assertEqual(409, self.client.post("/api/experiment/test", headers=self.headers).status_code)
        self.configure()
        self.assertEqual(200, self.client.post("/api/experiment/test", headers=self.headers).status_code)
        self.assertEqual("connection-test", self.caller.call_args.args[2][0].opinion_id)
        self.client.post("/api/experiment/disable", headers=self.headers)
        self.assertEqual(409, self.client.post("/api/experiment/test", headers=self.headers).status_code)

    def test_cross_origin_and_missing_header_rejected(self):
        self.assertEqual(403, self.client.post("/api/experiment/test").status_code)
        self.assertEqual(403, self.client.post("/api/experiment/test",
            headers={**self.headers, "Origin": "https://evil.example"}).status_code)

    def test_bad_key_never_echoed(self):
        secret = "sensitive\ninvalid-key"
        response = self.client.post("/api/experiment/settings", headers=self.headers,
            json={"api_key": secret, "model": "deepseek-v4-flash"})
        self.assertEqual(400, response.status_code)
        self.assertNotIn("sensitive", response.text)

    def test_session_isolation_and_expiry(self):
        self.configure()
        self.assertEqual(409, self.client.post("/api/experiment/test",
            headers={"X-Experiment-Request": "1"}).status_code)
        with patch("tdt_scoring.experiment.monotonic", return_value=float("inf")):
            self.assertEqual(409, self.client.post("/api/experiment/test", headers=self.headers).status_code)

    def test_real_preview_requires_consent_and_does_not_mutate(self):
        analysis = self.service.import_local_bytes(build_v04_workbook([
            {"stage": "TDR1", "opinion": "建议增加屏蔽罩。"}]), "虚拟报告.xlsx")
        before = asdict(analysis)
        self.configure()
        response = self.client.post("/api/experiment/preview", headers=self.headers,
            json={"analysis_id": analysis.analysis_id})
        self.assertEqual(400, response.status_code)
        self.caller.assert_not_called()
        response = self.client.post("/api/experiment/preview", headers=self.headers,
            json={"analysis_id": analysis.analysis_id, "confirmed": True})
        self.assertEqual(200, response.status_code)
        self.assertEqual(before, asdict(analysis))

    def test_error_redaction_and_invalid_results(self):
        self.configure()
        self.caller.side_effect = RuntimeError("fake-test-key-only")
        response = self.client.post("/api/experiment/test", headers=self.headers)
        self.assertEqual(422, response.status_code)
        self.assertNotIn("fake-test-key-only", response.text)
        self.caller.side_effect = lambda *args: {}
        self.assertEqual(422, self.client.post("/api/experiment/test", headers=self.headers).status_code)

    def test_network_request_contract(self):
        opinion = OpinionFact("x", "建议增加屏蔽罩。", [], [])
        envelope = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({
            "results": [{"id": "x", "status": "yes", "excerpt": opinion.text, "reason": "具体措施"}]})}}]}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(envelope).encode()
        with patch("tdt_scoring.experiment.build_opener") as opener:
            opener.return_value.open.return_value = response
            result = call_deepseek("fake-test-key-only", "deepseek-v4-flash", [opinion])
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(BASE_URL + "/chat/completions", request.full_url)
            payload = json.loads(request.data)
            self.assertEqual({"type": "json_object"}, payload["response_format"])
            self.assertEqual([{"id": "x", "text": opinion.text}], json.loads(payload["messages"][1]["content"]))
            self.assertEqual("yes", result["x"]["status"])
            self.assertEqual(45, opener.return_value.open.call_args.kwargs["timeout"])

    def test_upstream_unauthorized_redacted(self):
        with patch("tdt_scoring.experiment.build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError(BASE_URL, 401, "fake-test-key-only", {}, None)
            with self.assertRaisesRegex(ValueError, "密钥无效"):
                call_deepseek("fake-test-key-only", "deepseek-v4-flash", [])

    def test_redirect_not_followed(self):
        from tdt_scoring.experiment import NoRedirect
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example"))
