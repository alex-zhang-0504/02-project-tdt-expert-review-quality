from __future__ import annotations

import asyncio
import unittest
from io import BytesIO

from fastapi import HTTPException
from starlette.datastructures import UploadFile
from unittest.mock import patch

from tdt_scoring.api import (
    ContributionRequest,
    FinalizeRequest,
    app,
    contribution,
    finalize,
    health,
    FeishuImportRequest,
    import_local_batch,
    index,
    service,
    start_feishu_import,
)
from tdt_scoring import PRODUCT_VERSION, RELEASE_CHANNEL, __version__
from tdt_scoring.build_info import BUILD_ID, PROJECT_ID
from tests.workbook_factory import build_v04_workbook


class ApiTests(unittest.TestCase):
    def test_health_identifies_the_loaded_source_build(self) -> None:
        result = health()

        self.assertEqual("ok", result["status"])
        self.assertEqual(PROJECT_ID, result["project_id"])
        self.assertEqual(BUILD_ID, result["build_id"])
        self.assertTrue(result["service_instance_id"])
        self.assertEqual("v0.1", PRODUCT_VERSION)
        self.assertEqual("trial", RELEASE_CHANNEL)
        self.assertEqual(PRODUCT_VERSION, result["version"])
        self.assertEqual(RELEASE_CHANNEL, result["release_channel"])
        self.assertEqual(__version__, app.version)

    def test_removed_local_path_and_demo_mode_are_not_exposed(self) -> None:
        paths = {route.path for route in app.routes}

        self.assertNotIn("/api/import/path", paths)

    def test_multiple_file_import_route_is_exposed(self) -> None:
        paths = {route.path for route in app.routes}

        self.assertIn("/api/import/local-batch", paths)
        self.assertIn("/api/import/local-batch/start", paths)
        self.assertIn("/api/import/feishu/start", paths)
        self.assertIn("/api/import/jobs/{job_id}", paths)

    @patch("tdt_scoring.api.FeishuDocumentSource.authorization_status")
    def test_feishu_import_job_is_blocked_until_user_authorization_is_ready(
        self, authorization_status
    ) -> None:
        authorization_status.return_value = {"ready": False}

        with self.assertRaises(HTTPException) as context:
            start_feishu_import(
                FeishuImportRequest(
                    url="https://example.feishu.cn/drive/folder/fld123"
                )
            )

        self.assertEqual(401, context.exception.status_code)
        self.assertIn("授权未完成", context.exception.detail)

    @patch("tdt_scoring.api.import_executor.submit")
    @patch("tdt_scoring.api.FeishuDocumentSource.authorization_status")
    def test_authorized_feishu_folder_starts_one_background_batch_job(
        self, authorization_status, submit
    ) -> None:
        authorization_status.return_value = {"ready": True}

        result = start_feishu_import(
            FeishuImportRequest(
                url="https://example.feishu.cn/drive/folder/fld123"
            )
        )

        self.assertTrue(result["job_id"])
        self.assertEqual("queued", result["status"])
        submit.assert_called_once()

    def test_multiple_file_import_accepts_two_workbooks(self) -> None:
        first = build_v04_workbook([{"stage": "TDR1"}], project="项目甲（P001）")
        second = build_v04_workbook([{"stage": "TDR2"}], project="项目乙（P002）")

        payload = asyncio.run(
            import_local_batch(
                [
                    UploadFile(BytesIO(first), filename="P001.xlsx"),
                    UploadFile(BytesIO(second), filename="P002.xlsx"),
                ]
            )
        )

        self.assertEqual("2份评审报告", payload["source_name"])
        self.assertEqual(["P001.xlsx", "P002.xlsx"], [report["source_name"] for report in payload["reports"]])

    def test_index_busts_cached_assets_with_current_build(self) -> None:
        response = index()
        html = response.body.decode("utf-8")

        self.assertIn(f"/static/styles.css?build={BUILD_ID}", html)
        self.assertIn(f"/static/app.js?build={BUILD_ID}", html)
        self.assertNotIn("__BUILD_ID__", html)
        self.assertEqual("no-store", response.headers["cache-control"])

    def test_contribution_can_be_scored_without_process_analysis(self) -> None:
        result = contribution(
            ContributionRequest(
                answers={
                    "fulfillment_collaboration": "medium",
                    "professional_judgement_guidance": "medium",
                    "outstanding_contribution": "high",
                },
                outstanding_contribution_reason="识别关键风险并推动项目完成验证闭环。",
            )
        )

        self.assertEqual(30, result["contribution_score"])
        self.assertEqual(
            "识别关键风险并推动项目完成验证闭环。",
            result["outstanding_contribution_reason"],
        )

    def test_contribution_api_rejects_bonus_level_without_case(self) -> None:
        with self.assertRaises(HTTPException) as context:
            contribution(
                ContributionRequest(
                    answers={
                        "fulfillment_collaboration": "high",
                        "professional_judgement_guidance": "medium",
                        "outstanding_contribution": "high",
                    },
                    outstanding_contribution_reason=" ",
                )
            )
        self.assertEqual(400, context.exception.status_code)
        self.assertIn("必须填写", context.exception.detail)

    def test_finalize_returns_the_refreshed_annual_expert_cohort(self) -> None:
        analysis = service.import_local_bytes(
            build_v04_workbook([{"stage": "TDR3"}]),
            "ranking-api.xlsx",
        )
        result = None
        for expert in analysis.experts:
            result = finalize(
                FinalizeRequest(
                    analysis_id=analysis.analysis_id,
                    project_code=expert.project_code,
                    expert_name=expert.expert_name,
                    answers={
                        "fulfillment_collaboration": "high",
                        "professional_judgement_guidance": "medium",
                        "outstanding_contribution": "low",
                    },
                )
            )

        self.assertIsNotNone(result)
        self.assertEqual(3, len(result["experts"]))
        self.assertTrue(all(expert["status"] == "已完成" for expert in result["experts"]))
        self.assertNotIn("待排名", [expert["grade"] for expert in result["experts"]])


if __name__ == "__main__":
    unittest.main()
