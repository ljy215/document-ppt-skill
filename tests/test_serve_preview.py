from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import serve_preview  # noqa: E402


class PreviewServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.deck = json.loads((ROOT / "preview" / "sample_slide_deck.json").read_text(encoding="utf-8"))

    def test_sample_deck_passes_minimal_validation(self) -> None:
        serve_preview.validate_slide_json(self.deck)

    def test_local_update_preserves_slide_json_shape(self) -> None:
        updated = serve_preview.local_update("压缩第二页文字", self.deck)

        serve_preview.validate_slide_json(updated)
        self.assertEqual("document-ppt.slide.v1", updated["schema_version"])
        self.assertEqual(len(self.deck["slides"]), len(updated["slides"]))
        self.assertIn("压缩第二页文字", updated["slides"][0]["speaker_notes"])


if __name__ == "__main__":
    unittest.main()
