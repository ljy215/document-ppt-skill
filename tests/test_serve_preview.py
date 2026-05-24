from __future__ import annotations

import json
import sys
import tempfile
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

    def test_text_document_pipeline_generates_slide_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "notes.md"
            source.write_text("# Research Notes\n\nThis workflow converts documents into slides.", encoding="utf-8")

            deck, deck_path = serve_preview.run_document_pipeline(source, temp_path / "run")

            serve_preview.validate_slide_json(deck)
            self.assertTrue(deck_path.exists())
            self.assertEqual("notes", deck["deck"]["title"])
            rendered_text = json.dumps(deck, ensure_ascii=False)
            self.assertIn("workflow converts documents into slides", rendered_text)

    def test_slide_json_upload_is_passed_through(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "deck.json"
            source.write_text(json.dumps(self.deck, ensure_ascii=False), encoding="utf-8")

            deck, deck_path = serve_preview.run_document_pipeline(source, temp_path / "run")

            self.assertEqual(self.deck["deck"]["title"], deck["deck"]["title"])
            self.assertTrue(deck_path.exists())


if __name__ == "__main__":
    unittest.main()
