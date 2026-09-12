import unittest
from pathlib import Path
from tdt_scoring import PRODUCT_VERSION, __version__
from tdt_scoring.api import app
from tdt_scoring.submission import RULE_VERSION


class VersioningTests(unittest.TestCase):
    def test_v06_has_no_legacy_scoring_endpoints(self):
        self.assertEqual("v0.6", PRODUCT_VERSION)
        self.assertEqual("0.6.0", __version__)
        self.assertEqual("facts-v0.6", RULE_VERSION)
        paths = set(app.openapi()["paths"])
        self.assertFalse(any(p.startswith("/api/score") for p in paths))
        self.assertNotIn("/api/questionnaire", paths)

    def test_current_docs_point_to_statistics(self):
        root = Path(__file__).resolve().parents[1]
        for filename in ("README.md", "AGENTS.md", "CONTEXT.md", "ROADMAP.md"):
            self.assertIn("V0.6", (root / filename).read_text(encoding="utf-8"))
