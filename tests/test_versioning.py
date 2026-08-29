from __future__ import annotations

import unittest
from pathlib import Path

from tdt_scoring import PRODUCT_VERSION, RELEASE_CHANNEL, __version__


PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"
INTERNAL_V09_GUIDE = PROJECT_ROOT / "docs" / "2026-08-12-colleague-trial-guide-v0.9.md"


class VersioningTests(unittest.TestCase):
    def test_product_and_package_versions_are_distinguished(self) -> None:
        self.assertEqual("v0.1", PRODUCT_VERSION)
        self.assertEqual("trial", RELEASE_CHANNEL)
        self.assertEqual("0.1.0", __version__)

    def test_current_trial_version_is_synchronized_in_user_documents(self) -> None:
        readme = README.read_text(encoding="utf-8")
        old_guide = INTERNAL_V09_GUIDE.read_text(encoding="utf-8")

        self.assertIn("试用版 v0.1", readme)
        self.assertIn("年度V0.4", readme)
        self.assertIn("已由产品试用版 v0.1 取代", old_guide)


if __name__ == "__main__":
    unittest.main()
