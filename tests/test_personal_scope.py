from copy import deepcopy
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from tests.test_workspace import WorkspaceTests
from tdt_scoring.score_statistics import build_statistics
from tdt_scoring.service import ScoringService
from tdt_scoring.models import OpinionFact, ValidationIssue
from tdt_scoring.storage import Connection


class PersonalScopeTests(unittest.TestCase):
    setUp = WorkspaceTests.setUp
    encode = staticmethod(WorkspaceTests.encode)
    request = WorkspaceTests.request

    def test_scope_is_report_specific_and_does_not_mutate_full_scores(self):
        # Deliberately give another owner's report the same project code.
        first = self.analysis.sessions[0]
        for session in self.analysis.sessions:
            session.project_code = first.project_code
        for expert in self.analysis.experts:
            for session in expert.sessions:
                session.project_code = first.project_code
                if session.source_name == 'a.xlsx':
                    session.attended = False
        original = deepcopy(asdict(self.analysis))
        scores = build_statistics(self.analysis)
        view = self.workspace.visible(self.analysis, self.manager)
        self.assertTrue(view.experts)
        self.assertTrue(all(s.source_name == 'a.xlsx' for e in view.experts for s in e.sessions))
        self.assertTrue(any(not s.attended for e in view.experts for s in e.sessions))
        self.assertEqual(original, asdict(self.analysis))
        self.assertEqual(scores, build_statistics(self.analysis))

    def test_own_decision_saved_foreign_write_rejected_and_learning_retained(self):
        for expert in self.analysis.experts:
            for session in expert.sessions:
                if not session.opinions:
                    session.opinions.append(OpinionFact('virtual-'+expert.expert_name+'-'+session.source_name+'-'+session.stage, '虚拟对策建议', [], []))
                for opinion in session.opinions:
                    opinion.ai_status = 'no'
        own = next(o for e in self.analysis.experts if e.expert_name == self.name for s in e.sessions if s.source_name == 'a.xlsx' for o in s.opinions)
        foreign = next(o for e in self.analysis.experts if e.expert_name == self.name for s in e.sessions if s.source_name == 'b.xlsx' for o in s.opinions)
        data = dict(analysis_id=self.id, opinion_id=foreign.opinion_id, included=True)
        self.assertEqual(403, self.request('/api/workspace/solution-selection', data, 'POST', 'a')[0])
        self.assertIsNone(foreign.included)
        data['opinion_id'] = own.opinion_id
        self.assertEqual(200, self.request('/api/workspace/solution-selection', data, 'POST', 'a')[0])
        self.assertTrue(own.included)
        path = Path(self.temp.name) / 'countermeasure-corrections.jsonl'
        record = json.loads(path.read_text(encoding='utf-8').splitlines()[-1])
        self.assertEqual('correction', record['kind'])
        self.assertEqual('a', record['actor']['employee_id'])
        self.assertEqual('no', record['automatic_status'])
        data['included'] = False
        self.assertEqual(200, self.request('/api/workspace/solution-selection', data, 'POST', 'a')[0])
        self.assertEqual(2, len(path.read_text(encoding='utf-8').splitlines()))
        loaded = ScoringService(store=self.store).get_analysis(self.id)
        self.assertFalse(next(o for e in loaded.experts for s in e.sessions for o in s.opinions if o.opinion_id == own.opinion_id).included)

    def test_anonymous_session_has_no_directory_and_name_login(self):
        session = self.request('/api/workspace/session', user='')[1]
        self.assertEqual([], session['users'])
        self.assertTrue(session['has_accounts'])
        self.assertEqual(200, self.request('/api/workspace/login', {'name': self.manager['name']}, 'POST', '')[0])
        self.assertEqual(400, self.request('/api/workspace/login', {'name': '不存在的人员'}, 'POST', '')[0])
        self.assertEqual(403, self.request('/api/statistics/scores', user='a')[0])

    def test_failed_report_progress_survives_restart_and_legacy_reconstruction(self):
        report = self.analysis.reports[0]
        report.issues = [ValidationIssue('reviewer_missing', '虚拟名单错误', 'error')]
        report.scan_progress = {'percent': 50, 'label': '检查评审名单'}
        self.service.persist(self.analysis)
        reopened = ScoringService(store=self.store).get_analysis(self.id)
        self.assertEqual(50, reopened.reports[0].scan_progress['percent'])
        reopened.reports[0].scan_progress = {}
        reopened.reports[0].session_count = 1
        ScoringService.restore_report_progress(reopened)
        self.assertEqual(50, reopened.reports[0].scan_progress['percent'])
        reopened.reports[0].scan_progress = {}
        reopened.reports[0].session_count = 0
        ScoringService.restore_report_progress(reopened)
        self.assertIsNone(reopened.reports[0].scan_progress['percent'])

    def test_learning_write_failure_rolls_back_decision_and_database(self):
        opinion = OpinionFact('virtual-write-failure', '虚拟意见', [], [], ai_status='no')
        next(s for e in self.analysis.experts for s in e.sessions if s.source_name == 'a.xlsx').opinions.append(opinion)
        self.service.persist(self.analysis)
        with patch.object(self.store, 'write_corrections', side_effect=OSError('virtual disk failure')):
            with self.assertRaises(OSError):
                self.workspace.select_solution(self.id, opinion.opinion_id, True, self.manager)
        saved = ScoringService(store=self.store).get_analysis(self.id)
        self.assertIsNone(next(o for e in saved.experts for s in e.sessions for o in s.opinions if o.opinion_id == opinion.opinion_id).included)

    def test_daily_rotation_preserves_previous_when_new_backup_fails(self):
        folder = Path(self.temp.name) / 'backups'
        today = folder / ('daily-' + date.today().isoformat() + '.sqlite3')
        old = folder / 'daily-2000-01-01.sqlite3'
        old.write_bytes(today.read_bytes())
        with self.store.connect():
            pass
        self.assertEqual([today.name], [p.name for p in folder.glob('daily-*.sqlite3')])
        old.write_bytes(today.read_bytes())
        today.unlink()
        with patch('tdt_scoring.storage.os.replace', side_effect=OSError('virtual write failure')):
            with self.assertRaises(OSError):
                self.store.connect()
        self.assertTrue(old.exists())
        with self.store.connect():
            pass
        self.assertFalse(old.exists())
        with sqlite3.connect(today, factory=Connection) as db:
            self.assertEqual('ok', db.execute('PRAGMA integrity_check').fetchone()[0])
