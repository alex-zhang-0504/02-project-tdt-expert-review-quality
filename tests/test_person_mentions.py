import unittest
from tdt_scoring.excel_reader import parse_reviewer, split_reviewers, split_absent_reviewers
from tdt_scoring.service import ScoringService
from tests.workbook_factory import build_v04_workbook, build_workbook

class PersonMentionTests(unittest.TestCase):
    def test_names_and_proxy(self):
        self.assertEqual(('虚拟甲', '虚拟乙', '@虚拟甲（＠虚拟乙）'), parse_reviewer('@虚拟甲（＠虚拟乙）'))
        self.assertEqual(['虚拟甲', '虚拟乙'], split_reviewers('@虚拟甲、＠ 虚拟乙'))
        self.assertEqual(['虚拟甲'], split_absent_reviewers('@虚拟甲'))
        self.assertEqual('a@example.com', parse_reviewer('a@example.com')[0])

    def test_cross_stage_same_identity_and_opinion(self):
        a=ScoringService().import_local_bytes(build_v04_workbook([
            {'stage':'TDR1','reviewer':'@虚拟专家甲','opinion':'建议增加验证。'},
            {'stage':'TDR2','reviewer':'虚拟专家甲','problems':[{'number':'1','reviewer':'＠虚拟专家甲','description':'明确的风险待验证'}]}
        ]),'virtual.xlsx')
        e=next(e for e in a.experts if e.expert_name=='虚拟专家甲')
        self.assertEqual(2,e.overall['expected'])
        self.assertEqual(2,e.overall['opinions'])
        self.assertFalse(any(e.expert_name.startswith(('@','＠')) for e in a.experts))

    def test_absent_plain_roster_mentioned(self):
        a=ScoringService().import_local_bytes(build_v04_workbook([
            {'stage':'TDR1','reviewer':'@虚拟专家甲','conclusion':'-','absent_reviewers':'虚拟专家甲'}
        ]),'virtual.xlsx')
        e=next(e for e in a.experts if e.expert_name=='虚拟专家甲')
        self.assertEqual(0,e.overall['attended'])

    def test_legacy_manager_and_opinion(self):
        a=ScoringService().import_local_bytes(build_workbook([
            {'stage':'TDR1','attendance':'正常','conclusion':'Go','reviewer':'@虚拟专家甲','project_manager':'＠虚拟经理','problem':True,'problem_reviewer':'虚拟专家甲'}
        ]),'virtual.xlsx')
        self.assertEqual('虚拟经理',a.sessions[0].project_manager)
        self.assertEqual('虚拟专家甲',a.experts[0].expert_name)

    def test_valid_signoff_overrides_absence_without_warning(self):
        for conclusion in ['Go', 'Go with Risk', 'Redirect']:
            with self.subTest(conclusion=conclusion):
                a=ScoringService().import_local_bytes(build_v04_workbook([
                    {'stage':'TDR1','reviewer':'@虚拟专家甲','conclusion':conclusion,'absent_reviewers':'虚拟专家甲'}
                ]),'virtual.xlsx')
                e=next(e for e in a.experts if e.expert_name=='虚拟专家甲')
                self.assertEqual(1,e.overall['attended'])
                self.assertEqual(1,e.overall['signed'])
                issue=next(i for i in a.issues if i.code=='absent_with_valid_signoff')
                self.assertEqual('info',issue.severity)
                self.assertIn('无需修改报告',issue.message)
                self.assertFalse(any(i.severity in ['warning','error'] for i in a.issues))
