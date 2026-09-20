import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tdt_scoring import report_owner as owner
from tdt_scoring.service import ScoringService
from tdt_scoring.submission import build_dimension_one_workbook, load_dimension_one_workbook
from tests.workbook_factory import build_v04_workbook


def response(data):
    return subprocess.CompletedProcess([], 0, json.dumps({'ok': True, 'data': data}), '')


class OwnerTests(unittest.TestCase):
    def test_original_owner_not_last_editor_and_identity_dedup(self):
        def cli(args, **kwargs):
            if args[0] == 'drive':
                return response({'metas': [dict(doc_token=t, owner_id='ou_manager', latest_modify_user='ou_editor') for t in ['a', 'b']]})
            self.assertEqual('ou_manager', args[args.index('--user-ids') + 1])
            return response({'users': [{'open_id': 'ou_manager', 'localized_name': '虚拟经理甲'}]})
        with patch('tdt_scoring.sources.feishu_document.FeishuDocumentSource._run_cli', side_effect=cli) as calls:
            result = owner.read_owners(['a', 'b', 'a'])
        self.assertEqual(2, calls.call_count)
        self.assertEqual('ou_manager', result['a']['owner_id'])
        self.assertEqual('虚拟经理甲', result['a']['name'])
        self.assertEqual('resolved', result['b']['status'])
        self.assertEqual(64, len(result['a']['policy']['sha256']))

    def test_missing_owner_and_name_never_fallback(self):
        with patch('tdt_scoring.sources.feishu_document.FeishuDocumentSource._run_cli', side_effect=[
            response({'metas': [{'doc_token': 'a', 'latest_modify_user': 'ou_editor'}, {'doc_token': 'b', 'owner_id': 'ou_manager'}]}),
            response({'users': []})]):
            result = owner.read_owners(['a', 'b'])
        self.assertEqual('unresolved', result['a']['status'])
        self.assertEqual('', result['a']['owner_id'])
        self.assertEqual('name_unresolved', result['b']['status'])

    def test_bad_policy_blocks_lookup(self):
        with patch.object(owner, 'POLICY_PATH', Path('missing-owner-policy.json')), patch('tdt_scoring.sources.feishu_document.FeishuDocumentSource._run_cli') as call:
            result = owner.read_owners(['a'])
        call.assert_not_called()
        self.assertIsNone(result['a']['policy'])
        self.assertIn('配置', result['a']['error'])

    def test_timeout_explicit(self):
        with patch('tdt_scoring.sources.feishu_document.FeishuDocumentSource._run_cli', side_effect=subprocess.TimeoutExpired('test', 60)):
            result = owner.read_owner_url('https://example.feishu.cn/sheets/a')
        self.assertEqual('unresolved', result['status'])
        self.assertIn('超时', result['error'])

    def test_service_and_export_roundtrip(self):
        identity = dict(source_token='a', owner_id='ou_manager', name='虚拟经理甲', status='resolved', error='', policy=owner.load_policy())
        content = build_v04_workbook([{'stage': 'TDR1'}])
        with patch('tdt_scoring.service.FeishuDocumentSource.export_xlsx', return_value=(content, 'report.xlsx')), patch('tdt_scoring.service.read_owner_url', return_value=identity):
            analysis = ScoringService().import_feishu_url('https://example.feishu.cn/sheets/a')
        self.assertEqual(identity, analysis.reports[0].manager_identity)
        self.assertEqual('虚拟经理甲', analysis.sessions[0].project_manager)
        workbook = build_dimension_one_workbook(analysis, package_kind='manager_submission', manager_id='ou_manager', manager_name='虚拟经理甲', batch_id='test', product_version='test', build_id='test')
        loaded = load_dimension_one_workbook(workbook, 'test.xlsx')
        self.assertEqual(identity, loaded.sessions[0].manager_identity)
