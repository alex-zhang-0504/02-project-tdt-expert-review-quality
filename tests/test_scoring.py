from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from tdt_scoring.excel_reader import read_workbook
from tdt_scoring.scoring import (
    build_annual_scores,
    build_project_scores,
    _dense_top_three_scores,
    calculate_contribution,
    finalize_project_score,
    grade_for,
)

from tests.workbook_factory import build_v04_workbook, build_workbook


FIXTURE = Path(__file__).parent / "fixtures" / "virtual-expert-three-sessions.json"


class ScoringTests(unittest.TestCase):
    def test_annual_process_score_weights_projects_not_sessions(self) -> None:
        detailed = "需确认NTRA线损范围。最差场景下可能抵消性能提升，建议补充边界数据。"
        project_a, _ = read_workbook(
            build_v04_workbook(
                [
                    {"stage": "TDR1", "opinion": detailed},
                    {"stage": "TDR2", "opinion": detailed},
                    {"stage": "TDR3", "opinion": detailed},
                ],
                project="项目甲（P001）",
            )
        )
        project_b, _ = read_workbook(
            build_v04_workbook(
                [
                    {
                        "stage": "TDR3",
                        "absent_reviewers": "虚拟专家甲",
                        "conclusion": "-",
                        "opinion": "",
                    }
                ],
                project="项目乙（P002）",
            )
        )

        annual = next(
            item
            for item in build_annual_scores(project_a + project_b)
            if item.expert_name == "虚拟专家甲"
        )

        self.assertEqual(27.5, annual.process_average)
        self.assertEqual(4, annual.effective_session_count)
        self.assertEqual([55.0, 0.0], [item.process_average for item in annual.project_process_scores])

    def test_v04_signoff_and_opinion_are_scored_independently(self) -> None:
        workbook = build_v04_workbook(
            [
                {
                    "stage": "TDR2",
                    "signoffs": [
                        {"role": "射频", "reviewer": "虚拟专家甲", "conclusion": "Go", "opinion": ""},
                        {"role": "天线", "reviewer": "虚拟专家乙", "conclusion": "Go", "opinion": "需关注NTRA线损风险"},
                        {"role": "测试", "reviewer": "虚拟专家丙", "conclusion": "Redirect", "opinion": "需确认NTRA线损范围。最差场景下可能抵消性能提升并影响量产价值KPI，建议补充边界数据。"},
                    ],
                }
            ]
        )
        sessions, _ = read_workbook(workbook)
        scores = {score.expert_name: score for score in build_project_scores(sessions)}

        self.assertEqual((15, 0, 30), (scores["虚拟专家甲"].sessions[0].signoff.score, scores["虚拟专家甲"].sessions[0].opinion.score, scores["虚拟专家甲"].sessions[0].total))
        self.assertEqual((15, 15, 45), (scores["虚拟专家乙"].sessions[0].signoff.score, scores["虚拟专家乙"].sessions[0].opinion.score, scores["虚拟专家乙"].sessions[0].total))
        self.assertEqual((15, 25, 55), (scores["虚拟专家丙"].sessions[0].signoff.score, scores["虚拟专家丙"].sessions[0].opinion.score, scores["虚拟专家丙"].sessions[0].total))
        self.assertTrue(scores["虚拟专家丙"].sessions[0].opinion_evidence.has_technical_object)
        self.assertTrue(scores["虚拟专家丙"].sessions[0].opinion_evidence.has_professional_action)
        self.assertTrue(scores["虚拟专家丙"].sessions[0].opinion_evidence.has_specific_detail)
    def test_complete_risk_opinion_scores_high(self) -> None:
        workbook = build_workbook(
            [
                {
                    "stage": "TDR1",
                    "attendance": "正常",
                    "conclusion": "Go with Risk",
                    "basis": "需确认NTRA线损范围。最差场景下可能抵消性能提升并影响量产价值KPI，建议补充边界数据。",
                    "problem": "yes",
                    "action": "有改善措施",
                    "verification": "有验证方式和通过条件",
                }
            ]
        )
        sessions, _ = read_workbook(workbook)
        score = build_project_scores(sessions)[0].sessions[0]

        self.assertEqual(55, score.total)
        self.assertEqual(25, score.opinion.score)

    def test_partial_risk_opinion_scores_medium(self) -> None:
        workbook = build_workbook(
            [
                {
                    "stage": "TDR1",
                    "attendance": "正常",
                    "conclusion": "Redirect",
                    "basis": "需关注NTRA线损风险",
                    "problem": "yes",
                    "action": "有改善措施",
                    "verification": "",
                }
            ]
        )
        sessions, _ = read_workbook(workbook)
        score = build_project_scores(sessions)[0].sessions[0]

        self.assertEqual(45, score.total)
        self.assertEqual(15, score.opinion.score)

    def test_questionnaire_and_total_match_fixture(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        workbook = build_workbook(
            [
                {"stage": "TDR1", "attendance": "正常", "conclusion": "Go"},
                {"stage": "TDR2", "attendance": "缺席未改派", "conclusion": "Go"},
                {"stage": "TDR3", "attendance": "正常", "conclusion": "Go（逾期）"},
            ]
        )
        sessions, _ = read_workbook(workbook)
        project_score = build_project_scores(sessions)[0]
        completed = finalize_project_score(
            project_score, fixture["contribution_answers"]
        )

        self.assertEqual(fixture["expected_process_average"], project_score.process_average)
        self.assertEqual(
            fixture["expected_contribution_score"],
            calculate_contribution(fixture["contribution_answers"]),
        )
        self.assertEqual(fixture["expected_total_score"], completed.total_score)
        self.assertEqual(fixture["expected_grade"], completed.grade)

    def test_questionnaire_requires_all_three_answers(self) -> None:
        with self.assertRaisesRegex(ValueError, "尚未作答"):
            calculate_contribution({"fulfillment_collaboration": "high"})

    def test_bonus_contribution_levels_require_a_case_within_100_chars(self) -> None:
        workbook = build_workbook(
            [{"stage": "TDR1", "attendance": "正常", "conclusion": "Go"}]
        )
        sessions, _ = read_workbook(workbook)
        project_score = build_project_scores(sessions)[0]
        answers = {
            "fulfillment_collaboration": "high",
            "professional_judgement_guidance": "high",
            "outstanding_contribution": "high",
        }

        with self.assertRaisesRegex(ValueError, "必须填写.*加分原因"):
            finalize_project_score(project_score, answers, outstanding_contribution_reason="   ")
        with self.assertRaisesRegex(ValueError, "加分原因不能超过100字"):
            finalize_project_score(
                project_score,
                answers,
                outstanding_contribution_reason="案" * 101,
            )

        completed = finalize_project_score(
            project_score,
            answers,
            outstanding_contribution_reason="  协助项目组定位热失控根因并推动验证闭环。  ",
        )
        self.assertEqual(
            "协助项目组定位热失控根因并推动验证闭环。",
            completed.outstanding_contribution_reason,
        )

    def test_general_opinion_and_middle_dimension_two_reach_seventy_points(self) -> None:
        workbook = build_workbook(
            [
                {
                    "stage": "TDR1",
                    "attendance": "部分参加",
                    "conclusion": "Redirect（逾期）",
                    "basis": "需关注NTRA线损风险",
                    "problem": "yes",
                    "action": "有改善措施",
                    "verification": "",
                }
            ]
        )
        sessions, _ = read_workbook(workbook)
        project_score = build_project_scores(sessions)[0]
        completed = finalize_project_score(
            project_score,
            {
                "fulfillment_collaboration": "medium",
                "professional_judgement_guidance": "medium",
                "outstanding_contribution": "low",
            },
        )

        self.assertEqual(45, project_score.process_average)
        self.assertEqual(20, completed.contribution_score)
        self.assertEqual(65, completed.total_score)
        self.assertEqual("C", completed.grade)

    def test_professional_zero_requires_reason_tags_and_note(self) -> None:
        project_score = build_project_scores(
            read_workbook(
                build_workbook([{"stage": "TDR1", "attendance": "正常", "conclusion": "Go"}])
            )[0]
        )[0]
        answers = {
            "fulfillment_collaboration": "high",
            "professional_judgement_guidance": "low",
            "outstanding_contribution": "low",
        }

        with self.assertRaisesRegex(ValueError, "至少选择一个0分原因"):
            finalize_project_score(project_score, answers)
        with self.assertRaisesRegex(ValueError, "0分原因和导致影响"):
            finalize_project_score(
                project_score,
                answers,
                professional_reason_tags=["严重技术误判"],
            )
        completed = finalize_project_score(
            project_score,
            answers,
            professional_reason_tags=["严重技术误判", "重大风险遗漏"],
            professional_reason_note="TDR3遗漏关键失效风险，导致节点未通过。",
        )
        self.assertEqual(["严重技术误判", "重大风险遗漏"], completed.professional_reason_tags)
        self.assertEqual("TDR3遗漏关键失效风险，导致节点未通过。", completed.professional_reason_note)

    def test_one_hundred_is_the_exclusive_s_grade(self) -> None:
        self.assertEqual("S", grade_for(100))
        self.assertEqual("A", grade_for(99.9))
        self.assertEqual("A", grade_for(90))

    def test_service_ranking_uses_three_distinct_counts_and_requires_three_projects(self) -> None:
        scores = _dense_top_three_scores(
            {"甲": 8, "乙": 8, "丙": 6, "丁": 5, "戊": 2}
        )

        self.assertEqual({"甲": 3, "乙": 3, "丙": 2, "丁": 1, "戊": 0}, scores)

    def test_service_contribution_deduplicates_projects_and_adds_to_objective_score(self) -> None:
        sessions = []
        for index in range(1, 4):
            workbook = build_v04_workbook(
                [
                    {
                        "stage": "TDR3",
                        "opinion": "接口时序存在风险，建议补充高温场景验证。",
                        "problems": [
                            {"number": "1", "reviewer": "虚拟专家甲", "description": "问题一", "status": "open"},
                            {"number": "2", "reviewer": "虚拟专家甲", "description": "问题二", "status": "closed"},
                        ],
                    }
                ],
                project=f"项目{index}（P00{index}）",
            )
            sessions.extend(read_workbook(workbook)[0])

        annual = next(
            item for item in build_annual_scores(sessions) if item.expert_name == "虚拟专家甲"
        )

        self.assertEqual(3, annual.participation_project_count)
        self.assertEqual(3, annual.problem_project_count)
        self.assertEqual(3, annual.participation_score)
        self.assertEqual(3, annual.problem_score)
        self.assertEqual(6, annual.annual_service_score)
        self.assertEqual(61.0, annual.objective_score)
        completed = finalize_project_score(
            annual,
            {
                "fulfillment_collaboration": "high",
                "professional_judgement_guidance": "high",
                "outstanding_contribution": "high",
            },
            outstanding_contribution_reason="识别关键风险并推动项目完成验证闭环。",
        )
        self.assertEqual(100.0, completed.total_score)

    def test_three_stage_participation_requires_tdr1_and_tdr3_attendance(self) -> None:
        workbook = build_v04_workbook(
            [
                {
                    "stage": "TDR1",
                    "absent_reviewers": "虚拟专家乙",
                    "signoffs": [
                        {"reviewer": "虚拟专家甲", "conclusion": "Go"},
                        {"reviewer": "虚拟专家乙", "conclusion": "Go"},
                        {"reviewer": "虚拟专家丙", "conclusion": "-"},
                    ],
                },
                {
                    "stage": "TDR2",
                    "signoffs": [
                        {"reviewer": "虚拟专家甲", "conclusion": "Go"},
                        {"reviewer": "虚拟专家乙", "conclusion": "Go"},
                        {"reviewer": "虚拟专家丙", "conclusion": "-"},
                    ],
                },
                {
                    "stage": "TDR3",
                    "signoffs": [
                        {"reviewer": "虚拟专家甲", "conclusion": "Go"},
                        {"reviewer": "虚拟专家乙", "conclusion": "Go"},
                        {"reviewer": "虚拟专家丙", "conclusion": "-"},
                    ],
                },
            ]
        )

        annual = {item.expert_name: item for item in build_annual_scores(read_workbook(workbook)[0])}

        self.assertEqual(1, annual["虚拟专家甲"].participation_project_count)
        self.assertEqual(0, annual["虚拟专家乙"].participation_project_count)

    def test_assessment_window_is_start_exclusive_and_end_inclusive(self) -> None:
        sessions = []
        for code, meeting_date in (
            ("P001", date(2025, 1, 1)),
            ("P002", date(2025, 1, 2)),
            ("P003", date(2025, 12, 31)),
            ("P004", date(2026, 1, 1)),
        ):
            workbook = build_v04_workbook(
                [{"stage": "TDR3", "meeting_date": meeting_date}],
                project=f"项目{code}（{code}）",
            )
            sessions.extend(read_workbook(workbook)[0])

        annual = build_annual_scores(
            sessions,
            window_start_exclusive=date(2025, 1, 1),
            window_end_inclusive=date(2025, 12, 31),
        )[0]

        self.assertEqual(["P002", "P003"], [item.project_code for item in annual.project_process_scores])


if __name__ == "__main__":
    unittest.main()
