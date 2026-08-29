from __future__ import annotations

import unittest
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from tdt_scoring.excel_reader import parse_date, parse_project, parse_reviewer, read_workbook
from tdt_scoring.scoring import build_project_scores

from tests.workbook_factory import build_v04_workbook, build_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATHS = list(
    (PROJECT_ROOT / "docs").glob("TDT技术项目_TDRX评审报告（模板v0.1）_*.xlsx")
)
if len(TEMPLATE_PATHS) != 1:
    raise RuntimeError("docs目录中必须且只能有一个当前TDRX评审表模板")
TEMPLATE_PATH = TEMPLATE_PATHS[0]


class ExcelReaderTests(unittest.TestCase):
    def test_formal_mode_skips_example_and_empty_sheets(self) -> None:
        sessions, issues = read_workbook(TEMPLATE_PATH)

        self.assertEqual([], sessions)
        issue = next(issue for issue in issues if issue.code == "no_effective_sessions")
        self.assertEqual("error", issue.severity)

    def test_excel_serial_date_is_supported(self) -> None:
        self.assertEqual("2026-03-18", parse_date(46099).isoformat())

    def test_same_expert_is_averaged_across_three_sessions(self) -> None:
        workbook = build_workbook(
            [
                {"stage": "TDR1", "attendance": "正常", "conclusion": "Go"},
                {"stage": "TDR2", "attendance": "缺席未改派", "conclusion": "Go"},
                {"stage": "TDR3", "attendance": "正常", "conclusion": "Go（逾期）"},
            ]
        )
        sessions, _ = read_workbook(workbook)
        score = build_project_scores(sessions)[0]

        self.assertEqual([30, 15, 30], [item.total for item in score.sessions])
        self.assertEqual(3, score.effective_session_count)
        self.assertEqual(25.0, score.process_average)

    def test_project_and_proxy_parsing_use_last_parentheses(self) -> None:
        self.assertEqual(
            ("虚拟项目（子方向）", "P001"), parse_project("虚拟项目（子方向）（P001）")
        )
        self.assertEqual(
            ("虚拟专家甲", "虚拟专家乙", "虚拟专家甲（代理：虚拟专家乙）"),
            parse_reviewer("虚拟专家甲（代理：虚拟专家乙）"),
        )

    def test_malformed_tdr_sheet_is_not_silently_skipped(self) -> None:
        source = build_workbook(
            [{"stage": "TDR1", "attendance": "正常", "conclusion": "Go"}]
        )
        workbook = load_workbook(BytesIO(source))
        workbook["TDR1"]["A15"] = "错误的区块标题"
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()

        sessions, issues = read_workbook(buffer.getvalue())

        self.assertEqual([], sessions)
        self.assertTrue(any(issue.code == "section_structure_missing" for issue in issues))

    def test_v04_title_and_missing_list_drive_session_facts(self) -> None:
        source = build_v04_workbook(
            [
                {
                    "stage": "TDR2",
                    "absent_reviewers": "虚拟专家乙（测试）",
                    "signoffs": [
                        {"role": "射频", "reviewer": "虚拟专家甲", "conclusion": "Go", "opinion": "需关注NTRA线损风险"},
                        {"role": "测试", "reviewer": "虚拟专家乙", "conclusion": "Redirect", "opinion": "测试发现边界场景数据不足，建议补充最差条件验证。"},
                        {"role": "质量", "reviewer": "虚拟专家丙", "conclusion": "-", "opinion": ""},
                    ],
                }
            ],
            project="线损优化（B250001）",
        )

        sessions, issues = read_workbook(source, source_name="virtual-v04.xlsx")

        self.assertFalse([issue for issue in issues if issue.severity == "error"])
        self.assertEqual(1, len(sessions))
        session = sessions[0]
        self.assertEqual(("线损优化", "B250001", "TDR2"), (session.project_name, session.project_code, session.stage))
        self.assertEqual("virtual-v04.xlsx", session.source_name)
        self.assertEqual("正常", session.signoffs[0].attendance)
        self.assertEqual("缺席未改派", session.signoffs[1].attendance)
        self.assertEqual("需关注NTRA线损风险", session.signoffs[0].basis)
        self.assertEqual("D9", session.signoffs[0].opinion_cell)

    def test_v04_dash_counts_as_recorded_reviewer_but_scores_zero(self) -> None:
        source = build_v04_workbook(
            [{"stage": "TDR2", "conclusion": "-"}],
        )

        sessions, issues = read_workbook(source)
        scores = {score.expert_name: score for score in build_project_scores(sessions)}

        self.assertEqual(1, len(sessions))
        self.assertEqual(0, scores["虚拟专家甲"].sessions[0].signoff.score)
        self.assertTrue(any(issue.code == "signoff_not_provided" for issue in issues))
        self.assertFalse(any(issue.code == "effective_signoff_minimum" for issue in issues))

    def test_v04_fewer_than_three_recorded_reviewers_blocks_sheet(self) -> None:
        source = build_v04_workbook(
            [
                {
                    "stage": "TDR2",
                    "signoffs": [
                        {"role": "射频", "reviewer": "虚拟专家甲", "conclusion": "Go"},
                        {"role": "测试", "reviewer": "虚拟专家乙", "conclusion": "-"},
                        {"role": "质量", "reviewer": "虚拟专家丙", "conclusion": ""},
                    ],
                }
            ]
        )

        sessions, issues = read_workbook(source)

        self.assertEqual([], sessions)
        issue = next(issue for issue in issues if issue.code == "effective_signoff_minimum")
        self.assertEqual("error", issue.severity)
        self.assertIn("仅发现2名", issue.message)

    def test_v04_title_accepts_english_parentheses_and_dash_variants(self) -> None:
        source = build_v04_workbook(
            [{"stage": "TDR3", "conclusion": "GO"}],
            project="线损优化(B250001)",
        )
        workbook = load_workbook(BytesIO(source))
        workbook["TDR3评审报告"]["A1"] = "线损优化(B250001)—TDR3"
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()

        sessions, issues = read_workbook(buffer.getvalue())

        self.assertEqual(("线损优化", "B250001", "TDR3"), (sessions[0].project_name, sessions[0].project_code, sessions[0].stage))
        self.assertFalse([issue for issue in issues if issue.code in {"project_name", "project_code", "stage"}])

    def test_v04_footer_notes_are_not_parsed_as_problem_rows(self) -> None:
        source = build_v04_workbook([{"stage": "TDR2"}])
        workbook = load_workbook(BytesIO(source))
        workbook["TDR2评审报告"]["A31"] = "备注说明：评审结果说明"
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()

        sessions, issues = read_workbook(buffer.getvalue())

        self.assertEqual([], sessions[0].problems)
        self.assertFalse(any(issue.code.startswith("problem_") for issue in issues))

    def test_v04_unmatched_absent_reviewer_is_reported_without_guessing(self) -> None:
        source = build_v04_workbook(
            [{"stage": "TDR2", "absent_reviewers": "虚拟专家丁（测试）"}]
        )

        _, issues = read_workbook(source)

        issue = next(issue for issue in issues if issue.code == "absent_reviewer_unmatched")
        self.assertEqual("warning", issue.severity)
        self.assertEqual("B4", issue.cell_reference)

    def test_v04_legacy_combined_stage_is_read_as_tdr2_with_warning(self) -> None:
        source = build_v04_workbook([{"stage": "TDR2"}])
        workbook = load_workbook(BytesIO(source))
        workbook["TDR2评审报告"]["E5"] = "TDR1+TDR2"
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()

        sessions, issues = read_workbook(buffer.getvalue())

        self.assertEqual("TDR2", sessions[0].stage)
        self.assertTrue(any(issue.code == "stage_legacy_combined" for issue in issues))


if __name__ == "__main__":
    unittest.main()
