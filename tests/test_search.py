from __future__ import annotations

import unittest

from tdt_scoring.search import expert_name_search_terms


class ExpertSearchTests(unittest.TestCase):
    def test_chinese_name_has_full_pinyin_and_initials(self) -> None:
        self.assertEqual(
            {
                "expert_name_pinyin": "chenyijun",
                "expert_name_initials": "cyj",
            },
            expert_name_search_terms("陈义军"),
        )

    def test_spaces_and_latin_characters_are_normalized(self) -> None:
        self.assertEqual(
            {
                "expert_name_pinyin": "achen",
                "expert_name_initials": "ac",
            },
            expert_name_search_terms(" A 陈 "),
        )


if __name__ == "__main__":
    unittest.main()
