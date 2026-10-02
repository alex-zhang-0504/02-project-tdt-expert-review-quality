from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from io import BytesIO

from openpyxl import load_workbook
from tdt_scoring.scoring_policy import load_policy, parse_policy, effective_policy
from tdt_scoring.score_statistics import build_statistics, build_statistics_workbook
from tests.test_score_statistics import analysis, session


class StagePercentageTests(unittest.TestCase):
    def score(self, stages, receipt):
        facts = {'TDR1': session('TDR1', ('yes',)), 'TDR2': session('TDR2'),
                 'TDR3': session('TDR3', signed=False)}
        value = analysis([facts[s] for s in stages])
        with patch('tdt_scoring.score_statistics.snapshot', return_value=receipt):
            return build_statistics(value, True)['rows'][0]

    def test_all_seven_combinations_and_shared_group(self):
        receipt = load_policy()
        p = receipt['parameters']
        for shared, defaults in [(65, True), (80, False)]:
            p['stage_percentages']['with_second'] = {'TDR1_or_TDR3': shared, 'TDR2': 100-shared}
            expected = {('TDR1',): (100, 0, 0), ('TDR2',): (0, 100, 0), ('TDR3',): (0, 0, 100),
                        ('TDR1', 'TDR2'): (shared, 100-shared, 0), ('TDR2', 'TDR3'): (0, 100-shared, shared),
                        ('TDR1', 'TDR3'): (50, 0, 50), ('TDR1', 'TDR2', 'TDR3'): (40, 20, 40)}
            for stages, weights in expected.items():
                with self.subTest(stages=stages, defaults=defaults):
                    row = self.score(stages, receipt)
                    self.assertEqual(weights, tuple(s['weight'] for s in row['stages'].values()))
                    self.assertAlmostEqual(sum(v*w/100 for v,w in zip((25,15,5), weights)), row['process_total'])

    def test_independent_groups_and_zero_percent_are_valid(self):
        receipt = load_policy()
        receipt['parameters']['stage_percentages']['all'] = {'TDR1': 0, 'TDR2': 100, 'TDR3': 0}
        receipt['parameters']['stage_percentages']['first_third'] = {'TDR1': 70, 'TDR3': 30}
        receipt = parse_policy(json.dumps(receipt['parameters']).encode())
        self.assertEqual(15, self.score(('TDR1', 'TDR2', 'TDR3'), receipt)['process_total'])
        self.assertEqual(19, self.score(('TDR1', 'TDR3'), receipt)['process_total'])
        self.assertEqual(21.5, self.score(('TDR1', 'TDR2'), receipt)['process_total'])

    def test_invalid_group_cannot_be_saved(self):
        original = load_policy()['parameters']
        for bad in [-1, 101, True, '40', float('nan'), 39.99]:
            p = deepcopy(original)
            p['stage_percentages']['all']['TDR1'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_policy(json.dumps(p).encode())
        for change in ('missing', 'single', 'duplicate', 'list'):
            p = deepcopy(original)
            if change == 'missing': del p['stage_percentages']['with_second']
            if change == 'single': p['stage_percentages']['single'] = {'TDR1': 90}
            if change == 'duplicate': p['stage_weights'] = {'TDR1': 4, 'TDR2': 2, 'TDR3': 4}
            if change == 'list': p['stage_percentages']['all'] = ['TDR1', 'TDR2', 'TDR3']
            with self.subTest(change=change), self.assertRaises(ValueError): parse_policy(json.dumps(p).encode())

    def test_legacy_snapshot_read_does_not_mutate_stored_parameters(self):
        old = load_policy()
        del old['parameters']['stage_percentages']
        old['parameters']['stage_weights'] = {'TDR1': 3, 'TDR2': 2, 'TDR3': 5}
        before = deepcopy(old)
        current = effective_policy(old)
        self.assertEqual(before, old)
        self.assertEqual({'TDR1': 30, 'TDR2': 20, 'TDR3': 50}, current['parameters']['stage_percentages']['all'])
        self.assertEqual({'TDR1': 37.5, 'TDR3': 62.5}, current['parameters']['stage_percentages']['first_third'])
        self.assertEqual(65, current['parameters']['stage_percentages']['with_second']['TDR1_or_TDR3'])
        self.assertEqual(old['parameters']['participation'], current['parameters']['participation'])

    def test_export_uses_same_combination_result(self):
        value = analysis([session('TDR1', ('yes',)), session('TDR2')])
        data = build_statistics(value, True)
        self.assertEqual(21.5, data['rows'][0]['process_total'])
        book = load_workbook(BytesIO(build_statistics_workbook(value, True)), data_only=True)
        stage_rows = list(book.worksheets[1].values)
        self.assertTrue(any(65 in row and 'TDR1' in row for row in stage_rows))
        self.assertTrue(any(35 in row and 'TDR2' in row for row in stage_rows))
