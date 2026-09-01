from __future__ import annotations

import unittest

from tdt_scoring.excel_reader import read_workbook
from tdt_scoring.models import ExpertProjectScore, ExpertSessionScore, OpinionEvidence, ScoreItem
from tdt_scoring.validation import validate_score_bounds

from tests.workbook_factory import build_workbook


class ValidationTests(unittest.TestCase):
    def test_invalid_attendance_and_missing_signoff_are_errors(self) -> None:
        workbook = build_workbook(
            [{"stage": "TDR1", "attendance": "在线", "conclusion": ""}]
        )
        _, issues = read_workbook(workbook)
        codes = {issue.code for issue in issues if issue.severity == "error"}

        self.assertIn("attendance_invalid", codes)
        signoff_issue = next(issue for issue in issues if issue.code == "signoff_missing")
        self.assertEqual("warning", signoff_issue.severity)
        self.assertEqual("D13", signoff_issue.cell_reference)

    def test_proxy_attendance_requires_proxy_suffix(self) -> None:
        workbook = build_workbook(
            [{"stage": "TDR1", "attendance": "改派（正常）", "conclusion": "Go"}]
        )
        _, issues = read_workbook(workbook)

        self.assertTrue(any(issue.code == "proxy_missing" for issue in issues))

    def test_only_scoring_basic_fields_and_enums_are_errors(self) -> None:
        workbook = build_workbook(
            [{
                "stage": "TDR4",
                "attendance": "正常",
                "conclusion": "Go",
                "project": "（VIRTUAL-001）",
                "project_manager": "",
                "meeting_conclusion": "Maybe",
                "role": "",
            }]
        )

        _, issues = read_workbook(workbook)
        codes = {issue.code for issue in issues if issue.severity == "error"}

        self.assertTrue({"project_name", "stage_invalid"} <= codes)
        self.assertNotIn("meeting_conclusion_invalid", codes)
        self.assertNotIn("role_missing", codes)

    def test_problem_required_fields_do_not_control_opinion_scoring(self) -> None:
        workbook = build_workbook(
            [{
                "stage": "TDR1",
                "attendance": "正常",
                "conclusion": "Go with Risk",
                "basis": "有依据",
                "problem": True,
                "problem_description": "",
                "problem_status": "pending",
                "action": "",
                "verification": "",
            }]
        )

        _, issues = read_workbook(workbook)
        by_code = {issue.code: issue for issue in issues}

        self.assertEqual("warning", by_code["problem_description_missing"].severity)
        self.assertNotIn("problem_status_invalid", by_code)
        self.assertNotIn("opinion_elements_missing", by_code)

    def test_duplicate_expert_in_one_session_is_an_error(self) -> None:
        workbook = build_workbook(
            [{
                "stage": "TDR1",
                "attendance": "正常",
                "conclusion": "Go",
                "duplicate_reviewer": True,
            }]
        )

        _, issues = read_workbook(workbook)

        self.assertTrue(any(issue.code == "reviewer_duplicate" for issue in issues))

    def test_problem_number_format_does_not_trigger_quality_issue(self) -> None:
        workbook = build_workbook(
            [
                {
                    "stage": "TDR1",
                    "attendance": "正常",
                    "conclusion": "Go",
                    "problem": True,
                    "problem_number": "TDR1-1",
                    "problem_description": "问题甲",
                },
                {
                    "stage": "TDR2",
                    "attendance": "正常",
                    "conclusion": "Go",
                    "problem": True,
                    "problem_number": "TDR1-1",
                    "problem_description": "另一个问题",
                },
            ]
        )

        _, issues = read_workbook(workbook)

        self.assertFalse(any(issue.code.startswith("problem_number_") for issue in issues))

    def test_simple_problem_numbers_can_restart_in_each_stage(self) -> None:
        workbook = build_workbook(
            [
                {
                    "stage": "TDR1",
                    "attendance": "正常",
                    "conclusion": "Go",
                    "problem": True,
                    "problem_number": "1",
                    "problem_description": "问题甲",
                },
                {
                    "stage": "TDR2",
                    "attendance": "正常",
                    "conclusion": "Go",
                    "problem": True,
                    "problem_number": "1",
                    "problem_description": "问题乙",
                },
            ]
        )

        _, issues = read_workbook(workbook)

        self.assertFalse(any(issue.code == "problem_number_conflict" for issue in issues))

    def test_score_bounds_are_explicitly_validated(self) -> None:
        score_item = ScoreItem("high", 13, "测试")
        session_score = ExpertSessionScore(
            review_id="VIRTUAL-001-TDR1-2026-08-01",
            sheet_name="TDR1",
            project_code="VIRTUAL-001",
            project_name="虚拟项目",
            stage="TDR1",
            expert_name="虚拟专家甲",
            proxy_name=None,
            role="评审主席",
            attendance=score_item,
            signoff=score_item,
            opinion=ScoreItem("high", 11, "越界测试"),
            opinion_evidence=OpinionEvidence("", "", None, None, None),
            total=49,
        )
        project_score = ExpertProjectScore(
            expert_name="虚拟专家甲",
            project_code="VIRTUAL-001",
            project_name="虚拟项目",
            sessions=[session_score],
            process_average=49,
            effective_session_count=1,
        )

        codes = {issue.code for issue in validate_score_bounds([project_score])}

        self.assertEqual(
            {"session_score_out_of_range", "project_score_out_of_range"},
            codes,
        )


if __name__ == "__main__":
    unittest.main()
