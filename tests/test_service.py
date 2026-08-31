from __future__ import annotations

import unittest
from unittest.mock import patch

from tdt_scoring.service import ScoringService
from tdt_scoring.sources.feishu_document import FeishuFolderExport, FeishuWorkbookExport

from tests.workbook_factory import build_v04_workbook, build_workbook


class ServiceTests(unittest.TestCase):
    @patch("tdt_scoring.service.FeishuDocumentSource.export_folder_xlsx")
    def test_feishu_folder_failure_keeps_successes_visible_and_blocks_batch(
        self, export_folder
    ) -> None:
        export_folder.return_value = FeishuFolderExport(
            source_name="飞书归档文件夹",
            discovered_count=3,
            candidate_count=2,
            excluded_count=1,
            excluded_names=["归档说明"],
            workbooks=[
                FeishuWorkbookExport(
                    "P001.xlsx",
                    build_v04_workbook([{"stage": "TDR3"}], project="项目甲-P001"),
                ),
                FeishuWorkbookExport("P002.xlsx", None, "没有下载权限"),
            ],
        )

        analysis = ScoringService().import_feishu_url(
            "https://example.feishu.cn/drive/folder/fld123"
        )

        self.assertEqual("feishu_folder", analysis.source_type)
        self.assertEqual(2, len(analysis.reports))
        self.assertEqual(1, analysis.batch_summary.succeeded_count)
        self.assertEqual(1, analysis.batch_summary.failed_count)
        self.assertFalse(analysis.batch_summary.complete)
        self.assertIn(
            "feishu_report_export_failed",
            [issue.code for issue in analysis.reports[1].issues],
        )
        self.assertIn(
            "feishu_folder_batch_incomplete",
            [issue.code for issue in analysis.issues],
        )

    @patch("tdt_scoring.service.FeishuDocumentSource.export_folder_xlsx")
    def test_feishu_folder_without_candidates_is_incomplete(self, export_folder) -> None:
        export_folder.return_value = FeishuFolderExport(
            source_name="飞书归档文件夹",
            discovered_count=1,
            candidate_count=0,
            excluded_count=1,
            excluded_names=["子文件夹"],
            workbooks=[],
        )

        analysis = ScoringService().import_feishu_url(
            "https://example.feishu.cn/drive/folder/fld123"
        )

        self.assertFalse(analysis.batch_summary.complete)
        self.assertEqual(0, analysis.batch_summary.succeeded_count)
        self.assertIn(
            "feishu_folder_no_candidates",
            [issue.code for issue in analysis.issues],
        )

    def test_batch_import_keeps_per_report_quality_results(self) -> None:
        service = ScoringService()
        analysis = service.import_local_files(
            [
                (build_v04_workbook([{"stage": "TDR1", "opinion": "需关注线损风险"}], project="项目甲-P001"), "P001.xlsx"),
                (build_v04_workbook([{"stage": "TDR2", "opinion": "接口时序存在风险，建议补充高温场景验证。"}], project="项目乙-P002"), "P002.xlsx"),
            ]
        )

        self.assertEqual("2份评审报告", analysis.source_name)
        self.assertEqual(2, len(analysis.reports))
        self.assertEqual(["P001.xlsx", "P002.xlsx"], [report.source_name for report in analysis.reports])
        self.assertEqual([1, 1], [report.session_count for report in analysis.reports])
        self.assertTrue(all(issue.source_name == report.source_name for report in analysis.reports for issue in report.issues))

    def test_batch_import_keeps_a_broken_report_as_its_own_error_card(self) -> None:
        service = ScoringService()
        analysis = service.import_local_files(
            [
                (build_v04_workbook([{"stage": "TDR1"}]), "valid.xlsx"),
                (b"not-an-xlsx", "broken.xlsx"),
            ]
        )

        self.assertEqual(2, len(analysis.reports))
        broken = analysis.reports[1]
        self.assertEqual("broken.xlsx", broken.source_name)
        self.assertEqual("xlsx_structure_invalid", broken.issues[0].code)
        self.assertEqual("error", broken.issues[0].severity)

    def test_batch_import_rejects_the_same_project_stage_twice(self) -> None:
        workbook = build_v04_workbook(
            [{"stage": "TDR1"}], project="项目甲-P001"
        )

        analysis = ScoringService().import_local_files(
            [(workbook, "first.xlsx"), (workbook, "second.xlsx")]
        )

        duplicate = next(
            issue
            for issue in analysis.reports[1].issues
            if issue.code == "cross_report_stage_duplicate"
        )
        self.assertEqual("cross_report_stage_duplicate", duplicate.code)
        self.assertEqual("error", duplicate.severity)
    def test_import_and_finalize_are_backend_owned(self) -> None:
        workbook = build_workbook(
            [
                {"stage": "TDR1", "attendance": "正常", "conclusion": "Go"},
                {"stage": "TDR2", "attendance": "正常", "conclusion": "Go"},
                {"stage": "TDR3", "attendance": "正常", "conclusion": "Go"},
            ]
        )
        service = ScoringService()
        analysis = service.import_local_bytes(workbook, "virtual.xlsx")
        completed = service.finalize_expert(
            analysis.analysis_id,
            "VIRTUAL-001",
            "虚拟专家甲",
            {
                "fulfillment_collaboration": "high",
                "professional_judgement_guidance": "medium",
                "outstanding_contribution": "low",
            },
        )

        self.assertEqual(24, completed.contribution_score)
        self.assertEqual(64.0, completed.total_score)
        self.assertEqual("B", completed.grade)
        self.assertEqual("已完成", completed.status)
        self.assertIsNone(completed.outstanding_contribution_reason)

    def test_validation_errors_block_final_scoring(self) -> None:
        workbook = build_workbook(
            [{"stage": "TDR1", "attendance": "未知状态", "conclusion": "Go"}]
        )
        service = ScoringService()
        analysis = service.import_local_bytes(workbook, "invalid.xlsx")

        with self.assertRaisesRegex(ValueError, "仍有错误"):
            service.finalize_expert(
                analysis.analysis_id,
                "VIRTUAL-001",
                "虚拟专家甲",
                {
                    "fulfillment_collaboration": "high",
                    "professional_judgement_guidance": "high",
                    "outstanding_contribution": "high",
                },
            )

    def test_bonus_case_is_required_before_result_registration(self) -> None:
        service = ScoringService()
        analysis = service.import_local_bytes(
            build_workbook(
                [{"stage": "TDR3", "attendance": "正常", "conclusion": "Go"}]
            ),
            "virtual.xlsx",
        )
        answers = {
            "fulfillment_collaboration": "high",
            "professional_judgement_guidance": "high",
            "outstanding_contribution": "high",
        }

        with self.assertRaisesRegex(ValueError, "必须填写.*加分原因"):
            service.finalize_expert(
                analysis.analysis_id,
                "VIRTUAL-001",
                "虚拟专家甲",
                answers,
                outstanding_contribution_reason="",
            )
        self.assertEqual("待问卷作答", analysis.experts[0].status)

        completed = service.finalize_expert(
            analysis.analysis_id,
            "VIRTUAL-001",
            "虚拟专家甲",
            answers,
            outstanding_contribution_reason="避免关键物料在量产阶段出现批量失效。",
        )
        self.assertEqual(
            "避免关键物料在量产阶段出现批量失效。",
            completed.outstanding_contribution_reason,
        )
        self.assertEqual("已完成", analysis.experts[0].status)


if __name__ == "__main__":
    unittest.main()
