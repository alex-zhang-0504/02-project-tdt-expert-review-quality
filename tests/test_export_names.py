from datetime import date
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from tdt_scoring.export_names import review_export_disposition


class ExportNameTests(unittest.TestCase):
    def test_readable_dated_name_and_safe_filename(self):
        with patch('tdt_scoring.export_names.date') as clock:
            clock.today.return_value = date(2026, 9, 20)
            header = review_export_disposition('经理问卷_虚拟/经理:甲', 'manager-questionnaire.xlsx')
        self.assertIn('filename="manager-questionnaire.xlsx"', header)
        self.assertTrue(header.isascii())
        self.assertIn('经理问卷_虚拟_经理_甲_截止2026年09月20日前的评审记录.xlsx', unquote(header))
