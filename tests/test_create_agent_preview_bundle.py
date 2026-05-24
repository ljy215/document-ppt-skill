from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import create_agent_preview_bundle  # noqa: E402


class AgentPreviewBundleTests(unittest.TestCase):
    def test_create_bundle_writes_static_preview_files(self) -> None:
        deck_path = ROOT / "tests" / "fixtures" / "minimal_slide_deck.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "preview"

            result = create_agent_preview_bundle.create_bundle(deck_path, output_dir)

            self.assertTrue((output_dir / "index.html").exists())
            self.assertTrue((output_dir / "styles.css").exists())
            self.assertTrue((output_dir / "app.js").exists())
            self.assertTrue((output_dir / "slide_deck.json").exists())
            self.assertTrue((output_dir / "AGENT_NOTES.md").exists())
            self.assertIn("index.html", result["entry"])
            html = (output_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("window.PREVIEW_DECK_URL", html)
            deck = json.loads((output_dir / "slide_deck.json").read_text(encoding="utf-8"))
            self.assertEqual("document-ppt.slide.v1", deck["schema_version"])


if __name__ == "__main__":
    unittest.main()
