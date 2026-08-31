from __future__ import annotations

import json
import unittest
from pathlib import Path

from tdt_scoring.excel_reader import read_workbook
from tdt_scoring.models import ExpertProjectScore
from tdt_scoring.scoring import (
    apply_annual_grade_ranking,
    build_annual_scores,
    build_project_scores,
    _dense_top_two_scores,
    calculate_contribution,
    finalize_project_score,
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
                project="项目甲-P001",
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
                project="项目乙-P002",
            )
        )

        annual = next(
            item
            for item in build_annual_scores(project_a + project_b)
            if item.expert_name == "虚拟专家甲"
        )

        self.assertEqual(25.0, annual.process_average)
        self.assertEqual(4, annual.effective_session_count)
        self.assertEqual([50.0, 0.0], [item.process_average for item in annual.project_process_scores])

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

        self.assertEqual((25, 0, 40), (scores["虚拟专家甲"].sessions[0].signoff.score, scores["虚拟专家甲"].sessions[0].opinion.score, scores["虚拟专家甲"].sessions[0].total))
        self.assertEqual((25, 6, 46), (scores["虚拟专家乙"].sessions[0].signoff.score, scores["虚拟专家乙"].sessions[0].opinion.score, scores["虚拟专家乙"].sessions[0].total))
        self.assertEqual((25, 10, 50), (scores["虚拟专家丙"].sessions[0].signoff.score, scores["虚拟专家丙"].sessions[0].opinion.score, scores["虚拟专家丙"].sessions[0].total))
        self.assertTrue(scores["虚拟专家丙"].sessions[0].opinion_evidence.has_technical_object)
        self.assertTrue(scores["虚拟专家丙"].sessions[0].opinion_evidence.has_professional_action)
        self.assertTrue(scores["虚拟专家丙"].sessions[0].opinion_evidence.has_specific_detail)

    def test_annual_proxy_facts_only_report_count_and_rate(self) -> None:
        signoffs_with_proxy = [
            {"role": "射频", "reviewer": "虚拟专家甲（虚拟专家丁）", "conclusion": "Go"},
            {"role": "天线", "reviewer": "虚拟专家乙", "conclusion": "Go"},
            {"role": "测试", "reviewer": "虚拟专家丙", "conclusion": "Go"},
        ]
        direct_signoffs = [
            {"role": "射频", "reviewer": "虚拟专家甲", "conclusion": "Go"},
            {"role": "天线", "reviewer": "虚拟专家乙", "conclusion": "Go"},
            {"role": "测试", "reviewer": "虚拟专家丙", "conclusion": "Go"},
        ]
        workbook = build_v04_workbook(
            [
                {"stage": "TDR1", "signoffs": signoffs_with_proxy},
                {"stage": "TDR2", "signoffs": signoffs_with_proxy},
                {"stage": "TDR3", "signoffs": direct_signoffs},
            ],
            project="虚拟项目-P001",
        )

        annual = {
            item.expert_name: item
            for item in build_annual_scores(read_workbook(workbook)[0])
        }["虚拟专家甲"]

        self.assertEqual(3, annual.expected_session_count)
        self.assertEqual(2, annual.proxy_session_count)
        self.assertEqual(66.7, annual.proxy_rate)
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

        self.assertEqual(50, score.total)
        self.assertEqual(10, score.opinion.score)

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

        self.assertEqual(46, score.total)
        self.assertEqual(6, score.opinion.score)

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

        self.assertEqual(46, project_score.process_average)
        self.assertEqual(20, completed.contribution_score)
        self.assertEqual(66, completed.total_score)
        self.assertEqual("待排名", completed.grade)

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

    def test_annual_grade_ranking_uses_fifteen_seventy_fifteen_bands(self) -> None:
        experts = [
            ExpertProjectScore(
                expert_name=f"专家{index:02d}",
                project_code="年度汇总",
                project_name="年度汇总",
                sessions=[],
                process_average=0,
                effective_session_count=0,
                contribution_score=0,
                total_score=float(101 - index),
                status="已完成",
            )
            for index in range(1, 21)
        ]

        apply_annual_grade_ranking(experts)

        grades = [expert.grade for expert in experts]
        self.assertEqual("S", grades[0])
        self.assertEqual(["A", "A"], grades[1:3])
        self.assertEqual(["B"] * 14, grades[3:17])
        self.assertEqual(["C"] * 3, grades[17:])

    def test_annual_grade_ranking_waits_for_every_expert_and_keeps_boundary_ties(self) -> None:
        experts = [
            ExpertProjectScore(
                expert_name=f"专家{index}",
                project_code="年度汇总",
                project_name="年度汇总",
                sessions=[],
                process_average=0,
                effective_session_count=0,
                contribution_score=0 if score is not None else None,
                total_score=score,
                status="已完成" if score is not None else "待问卷作答",
            )
            for index, score in enumerate((95.0, 95.0, 80.0, None), start=1)
        ]

        apply_annual_grade_ranking(experts)
        self.assertEqual(["待排名", "待排名", "待排名", None], [item.grade for item in experts])

        experts[-1].contribution_score = 0
        experts[-1].total_score = 70.0
        experts[-1].status = "已完成"
        apply_annual_grade_ranking(experts)
        self.assertEqual(["A", "A", "B", "C"], [item.grade for item in experts])

    def test_annual_grade_ranking_does_not_publish_s_before_both_dimensions_finish_for_all(self) -> None:
        experts = [
            ExpertProjectScore(
                expert_name="专家甲",
                project_code="年度汇总",
                project_name="年度汇总",
                sessions=[],
                process_average=60,
                effective_session_count=1,
                objective_score=60,
                contribution_score=40,
                total_score=100,
                status="已完成",
            ),
            ExpertProjectScore(
                expert_name="专家乙",
                project_code="年度汇总",
                project_name="年度汇总",
                sessions=[],
                process_average=50,
                effective_session_count=1,
                objective_score=50,
                contribution_score=None,
                total_score=None,
                status="待问卷作答",
            ),
        ]

        apply_annual_grade_ranking(experts)

        self.assertEqual("待排名", experts[0].grade)
        self.assertIsNone(experts[1].grade)

    def test_service_ranking_uses_two_distinct_counts_and_requires_three_projects(self) -> None:
        counts = {"甲": 8, "乙": 8, "丙": 6, "丁": 5, "戊": 2}

        self.assertEqual(
            {"甲": 6, "乙": 6, "丙": 3, "丁": 0, "戊": 0},
            _dense_top_two_scores(counts, (6, 3)),
        )
        self.assertEqual(
            {"甲": 4, "乙": 4, "丙": 2, "丁": 0, "戊": 0},
            _dense_top_two_scores(counts, (4, 2)),
        )

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
                project=f"项目{index}-P00{index}",
            )
            sessions.extend(read_workbook(workbook)[0])

        annual = next(
            item for item in build_annual_scores(sessions) if item.expert_name == "虚拟专家甲"
        )

        self.assertEqual(3, annual.participation_project_count)
        self.assertEqual(3, annual.problem_project_count)
        self.assertEqual(6, annual.participation_score)
        self.assertEqual(4, annual.problem_score)
        self.assertEqual(10, annual.annual_service_score)
        self.assertEqual(60.0, annual.objective_score)
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
        self.assertEqual(1, annual["虚拟专家乙"].participation_project_count)

    def test_v04_c_column_problem_can_supply_and_deduplicate_opinion(self) -> None:
        detailed = "需确认NTRA线损范围。最差场景下可能抵消性能提升，建议补充边界数据。"
        workbook = build_v04_workbook(
            [{
                "stage": "TDR2",
                "opinion": f"1．{detailed}",
                "problems": [{
                    "number": "1",
                    "reviewer": "虚拟专家甲",
                    "description": detailed,
                    "status": "open",
                }],
            }]
        )

        sessions, _ = read_workbook(workbook)
        score = next(
            item for item in build_project_scores(sessions)
            if item.expert_name == "虚拟专家甲"
        ).sessions[0]

        self.assertEqual(10, score.opinion.score)
        self.assertEqual(1, len(sessions[0].signoffs[0].opinion_sources))
        self.assertEqual(["D9", "C26"], score.opinion_evidence.source_cells)

    def test_v04_c_column_only_opinion_is_scored(self) -> None:
        detailed = "需确认NTRA线损范围。最差场景下可能抵消性能提升，建议补充边界数据。"
        workbook = build_v04_workbook(
            [{
                "stage": "TDR2",
                "problems": [{
                    "number": "1",
                    "reviewer": "虚拟专家甲",
                    "description": detailed,
                    "status": "open",
                }],
            }]
        )

        sessions, _ = read_workbook(workbook)
        score = next(
            item for item in build_project_scores(sessions)
            if item.expert_name == "虚拟专家甲"
        ).sessions[0]

        self.assertEqual(10, score.opinion.score)
        self.assertEqual(["C26"], score.opinion_evidence.source_cells)

    def test_v04_distinct_opinions_do_not_merge_elements_across_candidates(self) -> None:
        workbook = build_v04_workbook(
            [{
                "stage": "TDR2",
                "opinion": "NTRA线损范围\n建议补充验证",
            }]
        )

        sessions, _ = read_workbook(workbook)
        score = next(
            item for item in build_project_scores(sessions)
            if item.expert_name == "虚拟专家甲"
        ).sessions[0]

        self.assertEqual(0, score.opinion.score)
        self.assertEqual(2, len(sessions[0].signoffs[0].opinion_sources))

    def test_one_workbook_three_sheets_equals_three_single_sheet_workbooks(self) -> None:
        rows = [
            {"stage": "TDR1", "opinion": "需关注NTRA线损风险"},
            {"stage": "TDR2", "opinion": "需确认NTRA线损范围，建议补充边界数据"},
            {"stage": "TDR3", "opinion": "需确认NTRA线损范围。最差场景可能影响量产，建议补充边界数据。"},
        ]
        combined_sessions = read_workbook(
            build_v04_workbook(rows, project="虚拟项目-P001")
        )[0]
        separate_sessions = []
        for row in rows:
            separate_sessions.extend(
                read_workbook(
                    build_v04_workbook([row], project="虚拟项目-P001")
                )[0]
            )

        combined = build_annual_scores(combined_sessions)
        separate = build_annual_scores(separate_sessions)

        self.assertEqual(combined, separate)

if __name__ == "__main__":
    unittest.main()
