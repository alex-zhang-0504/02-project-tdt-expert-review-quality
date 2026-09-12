from __future__ import annotations

import unittest

from tdt_scoring.excel_reader import read_workbook

from tests.workbook_factory import build_workbook


class ValidationTests(unittest.TestCase):
    def test_invalid_attendance_and_missing_signoff_are_errors(self) -> None:
        workbook = build_workbook(
            [{"stage": "TDR1", "attendance": "在线", "conclusion": ""}]
        )
        _, issues = read_workbook(workbook)
        codes = {issue.code for issue in issues}

        self.assertIn("attendance_invalid", codes)
        self.assertNotIn("signoff_missing", codes)

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

if __name__ == "__main__":
    unittest.main()
