from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tdt_scoring.service import ScoringService
from tdt_scoring.progress import CHECKPOINTS, ImportJobStore
from tdt_scoring.sources.feishu_document import FeishuFolderExport, FeishuWorkbookExport

from tests.workbook_factory import build_v04_workbook, build_workbook


class ServiceTests(unittest.TestCase):
    @patch("tdt_scoring.service.FeishuDocumentSource.export_xlsx")
    def test_feishu_import_uses_only_internal_stage_field(
        self, export_xlsx
    ) -> None:
        export_xlsx.return_value = (
            build_v04_workbook([{"stage": "TDR3"}]),
            "tdrx-review.xlsx",
        )

        analysis = ScoringService().import_feishu_url(
            "https://example.feishu.cn/sheets/sheet123"
        )

        self.assertFalse(
            any(issue.code.startswith("filename_stage_") for issue in analysis.issues)
        )

    def test_local_import_does_not_validate_filename_stage(self) -> None:
        analysis = ScoringService().import_local_files(
            [(build_v04_workbook([{"stage": "TDR3"}]), "任意文件名-TDR1+TDR2.xlsx")]
        )

        self.assertEqual("TDR3", analysis.sessions[0].stage)
        self.assertFalse(
            any(issue.code.startswith("filename_stage_") for issue in analysis.issues)
        )

    def test_valid_report_emits_all_real_checkpoints_in_order(self) -> None:
        events = []

        ScoringService().import_local_files(
            [(build_v04_workbook([{"stage": "TDR3"}]), "P001-TDR3.xlsx")],
            progress=events.append,
        )

        completed = [
            event.checkpoint_id
            for event in events
            if event.status in {"completed", "warning"}
        ]
        self.assertEqual([checkpoint_id for checkpoint_id, _ in CHECKPOINTS], completed)
        self.assertTrue(all(event.duration_ms >= 0 for event in events))

    def test_progress_tracks_two_local_reports_with_the_same_filename_separately(self) -> None:
        store = ImportJobStore()
        job = store.create("local_excel")
        store.set_reports(job.job_id, ["同名报告.xlsx", "同名报告.xlsx"])

        ScoringService().import_local_files(
            [
                (build_v04_workbook([{"stage": "TDR1"}], project="项目甲-P001"), "同名报告.xlsx"),
                (build_v04_workbook([{"stage": "TDR2"}], project="项目乙-P002"), "同名报告.xlsx"),
            ],
            progress=lambda event: store.record(job.job_id, event),
        )

        reports = store.snapshot(job.job_id).reports
        self.assertEqual([100, 100], [report.progress_percent for report in reports])

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

    def test_similar_reviewer_names_block_with_all_source_cells_until_confirmed(self) -> None:
        service = ScoringService()
        analysis = service.import_local_files(
            [
                (
                    build_v04_workbook(
                        [{
                            "stage": "TDR3",
                            "signoffs": [
                                {"reviewer": "陈名木", "conclusion": "Go"},
                                {"reviewer": "王志强", "conclusion": "Go"},
                                {"reviewer": "李天宇", "conclusion": "Go"},
                            ],
                        }],
                        project="项目甲-P001",
                    ),
                    "P001.xlsx",
                ),
                (
                    build_v04_workbook(
                        [{
                            "stage": "TDR3",
                            "signoffs": [
                                {"reviewer": "程名木", "conclusion": "Go"},
                                {"reviewer": "赵鹏飞", "conclusion": "Go"},
                                {"reviewer": "周海涛", "conclusion": "Go"},
                            ],
                        }],
                        project="项目乙-P002",
                    ),
                    "P002.xlsx",
                ),
                (
                    build_v04_workbook(
                        [{
                            "stage": "TDR3",
                            "signoffs": [
                                {"reviewer": "程明木", "conclusion": "Go"},
                                {"reviewer": "孙文博", "conclusion": "Go"},
                                {"reviewer": "吴建国", "conclusion": "Go"},
                            ],
                        }],
                        project="项目丙-P003",
                    ),
                    "P003.xlsx",
                ),
            ]
        )

        issue = next(
            issue
            for issue in analysis.issues
            if issue.code == "reviewer_name_similarity"
        )
        self.assertEqual("error", issue.severity)
        self.assertTrue(issue.requires_confirmation)
        self.assertFalse(issue.confirmed_by_user)
        self.assertIn("陈名木／程名木／程明木", issue.message)
        self.assertEqual(
            [
                "P001.xlsx／TDR3评审报告!B9（陈名木）",
                "P002.xlsx／TDR3评审报告!B9（程名木）",
                "P003.xlsx／TDR3评审报告!B9（程明木）",
            ],
            issue.related_locations,
        )
        self.assertTrue(
            all(
                any(
                    report_issue.confirmation_key == issue.confirmation_key
                    for report_issue in report.issues
                )
                for report in analysis.reports
            )
        )

        confirmed = service.confirm_reviewer_names_distinct(
            analysis.analysis_id,
            issue.confirmation_key,
        )
        confirmed_issue = next(
            item
            for item in confirmed.issues
            if item.code == "reviewer_name_similarity"
        )
        self.assertEqual("info", confirmed_issue.severity)
        self.assertTrue(confirmed_issue.confirmed_by_user)
        self.assertTrue(confirmed_issue.confirmed_at)
        self.assertTrue(
            all(
                all(
                    report_issue.severity == "info"
                    for report_issue in report.issues
                    if report_issue.confirmation_key == issue.confirmation_key
                )
                for report in confirmed.reports
            )
        )
        self.assertEqual(
            {"陈名木", "程名木", "程明木"},
            {
                expert.expert_name
                for expert in confirmed.experts
                if expert.expert_name in {"陈名木", "程名木", "程明木"}
            },
        )

    def test_different_given_name_pinyin_does_not_trigger_similarity_confirmation(self) -> None:
        analysis = ScoringService().import_local_files(
            [
                (
                    build_v04_workbook(
                        [{
                            "stage": "TDR3",
                            "signoffs": [
                                {"reviewer": "陈名木", "conclusion": "Go"},
                                {"reviewer": "王志强", "conclusion": "Go"},
                                {"reviewer": "李天宇", "conclusion": "Go"},
                            ],
                        }],
                        project="项目甲-P001",
                    ),
                    "P001.xlsx",
                ),
                (
                    build_v04_workbook(
                        [{
                            "stage": "TDR3",
                            "signoffs": [
                                {"reviewer": "程亮木", "conclusion": "Go"},
                                {"reviewer": "赵鹏飞", "conclusion": "Go"},
                                {"reviewer": "周海涛", "conclusion": "Go"},
                            ],
                        }],
                        project="项目乙-P002",
                    ),
                    "P002.xlsx",
                ),
            ]
        )

        self.assertFalse(
            any(issue.code == "reviewer_name_similarity" for issue in analysis.issues)
        )

if __name__ == "__main__":
    unittest.main()
