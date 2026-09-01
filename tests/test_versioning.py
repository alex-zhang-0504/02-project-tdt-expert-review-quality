from __future__ import annotations

import unittest
from pathlib import Path

from tdt_scoring import PRODUCT_VERSION, RELEASE_CHANNEL, __version__


PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"
INTERNAL_V09_GUIDE = PROJECT_ROOT / "docs" / "2026-08-12-colleague-trial-guide-v0.9.md"
ANNUAL_RULE_V05 = PROJECT_ROOT / "docs" / "tdr-expert-review-quality-assessment-by-year-v0.5.md"
ANNUAL_SPEC_V05 = PROJECT_ROOT / "docs" / "tdrx-review-and-score-data-spec-by-year-v0.5.md"


class VersioningTests(unittest.TestCase):
    def test_product_and_package_versions_are_distinguished(self) -> None:
        self.assertEqual("v0.1", PRODUCT_VERSION)
        self.assertEqual("trial", RELEASE_CHANNEL)
        self.assertEqual("0.1.0", __version__)

    def test_current_trial_version_is_synchronized_in_user_documents(self) -> None:
        readme = README.read_text(encoding="utf-8")
        old_guide = INTERNAL_V09_GUIDE.read_text(encoding="utf-8")

        self.assertIn("试用版 v0.1", readme)
        self.assertIn("年度V0.5", readme)
        self.assertIn("已由产品试用版 v0.1 取代", old_guide)

    def test_annual_v05_rule_and_spec_share_the_48_plus_12_formula(self) -> None:
        rule = ANNUAL_RULE_V05.read_text(encoding="utf-8")
        spec = ANNUAL_SPEC_V05.read_text(encoding="utf-8")

        for text in (rule, spec):
            self.assertIn("0—48", text)
            self.assertIn("0—12", text)
            self.assertIn("0—60", text)
            self.assertIn("有效参评场次", text)
            self.assertIn("场次问题贡献", text)
        self.assertIn("不要求项目已经输出TDR3结果", rule)
        self.assertIn("不生成未完成TDR3提醒", spec)


if __name__ == "__main__":
    unittest.main()
