from __future__ import annotations

import unittest
from pathlib import Path
from zipfile import ZipFile

from tdt_scoring.excel_reader import read_workbook
from tdt_scoring.scoring import build_project_scores


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "docs" / "TDT技术项目_TDRX评审报告（模板v0.1）_2026-08-11.xlsx"
TRAINING_WORKBOOK = (
    PROJECT_ROOT / "data" / "2026-08-11-virtual-tdrx-review-training-v0.1.xlsx"
)


class VirtualTrainingWorkbookTests(unittest.TestCase):
    def test_training_workbook_is_parseable_and_scores_expected_sessions(self) -> None:
        sessions, issues = read_workbook(TRAINING_WORKBOOK)
        scores = {score.expert_name: score for score in build_project_scores(sessions)}

        self.assertFalse(any(issue.severity == "error" for issue in issues))
        self.assertTrue(issues)
        self.assertTrue(all(issue.code == "signoff_invalid" for issue in issues))
        self.assertEqual(["TDR1", "TDR2", "TDR3"], [session.stage for session in sessions])
        self.assertEqual(33, sum(len(session.signoffs) for session in sessions))
        self.assertEqual(6, sum(len(session.problems) for session in sessions))
        self.assertEqual(11, len(scores))
        self.assertEqual([50, 50, 40], [item.total for item in scores["高腾飞"].sessions])
        self.assertEqual(46.7, scores["高腾飞"].process_average)
        self.assertEqual([0, 0, 40], [item.total for item in scores["高大宇"].sessions])
        self.assertEqual(13.3, scores["高大宇"].process_average)

    def test_training_workbook_only_changes_three_target_worksheets(self) -> None:
        with ZipFile(TEMPLATE) as template, ZipFile(TRAINING_WORKBOOK) as training:
            self.assertEqual(template.namelist(), training.namelist())
            changed = {
                name
                for name in template.namelist()
                if template.read(name) != training.read(name)
            }

        self.assertEqual(
            {
                "xl/worksheets/sheet7.xml",
                "xl/worksheets/sheet8.xml",
                "xl/worksheets/sheet9.xml",
            },
            changed,
        )


if __name__ == "__main__":
    unittest.main()
