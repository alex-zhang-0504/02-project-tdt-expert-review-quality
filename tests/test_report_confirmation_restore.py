from copy import deepcopy
from tempfile import TemporaryDirectory
import unittest

from tests.test_assessment import sample
from tdt_scoring.models import ValidationIssue
from tdt_scoring.service import ScoringService
from tdt_scoring.storage import WorkspaceStore


class ReportConfirmationRestoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = WorkspaceStore(self.folder.name)
        self.analysis = sample()
        self.issue = ValidationIssue('reviewer_name_similarity', '虚拟姓名组待确认', 'error',
                                     requires_confirmation=True, confirmation_key='virtual-group')
        self.analysis.issues = [self.issue]
        for report in self.analysis.reports:
            report.issues = [deepcopy(self.issue)]
            report.scan_progress = {'percent': 100, 'label': '检查统计事实'}

    def assert_confirmed(self, analysis):
        for report in analysis.reports:
            issue = next(i for i in report.issues if i.confirmation_key == 'virtual-group')
            self.assertEqual('info', issue.severity)
            self.assertTrue(issue.confirmed_by_user)
            self.assertEqual(analysis.issues[0].confirmed_at, issue.confirmed_at)
            self.assertEqual(100, report.scan_progress['percent'])

    def test_confirm_after_storage_roundtrip_updates_report_copies_and_survives_restart(self):
        self.store.save(self.analysis, 0)
        service = ScoringService(store=self.store)
        confirmed = service.confirm_reviewer_names_distinct(self.analysis.analysis_id, 'virtual-group')
        self.assert_confirmed(confirmed)
        self.assert_confirmed(ScoringService(store=self.store).get_analysis(self.analysis.analysis_id))

    def test_legacy_confirmed_summary_restores_rows_without_hiding_other_errors(self):
        self.issue.severity = 'info'
        self.issue.confirmed_by_user = True
        self.issue.confirmed_at = '2026-09-29T00:00:00+00:00'
        other = ValidationIssue('unresolved_virtual_error', '另一项尚未解决的错误', 'error')
        self.analysis.issues.append(other)
        self.analysis.reports[1].issues.append(deepcopy(other))
        self.store.save(self.analysis, 0)
        restored = ScoringService(store=self.store).get_analysis(self.analysis.analysis_id)
        self.assert_confirmed(restored)
        self.assertFalse(any(i.severity == 'error' for i in restored.reports[0].issues))
        self.assertTrue(any(i.severity == 'error' for i in restored.reports[1].issues))

    def test_unconfirmed_summary_does_not_clear_report_errors(self):
        self.store.save(self.analysis, 0)
        restored = ScoringService(store=self.store).get_analysis(self.analysis.analysis_id)
        self.assertTrue(all(r.issues[0].severity == 'error' for r in restored.reports))
