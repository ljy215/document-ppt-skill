from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_slide_json  # noqa: E402


class SlideJsonGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest_path = ROOT / "tests" / "fixtures" / "minimal_manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def test_dry_run_deck_is_valid_against_internal_contract(self) -> None:
        deck = generate_slide_json.dry_run_deck(self.manifest, self.manifest_path, max_slides=8)

        errors = generate_slide_json.validate_deck(deck, self.manifest)

        self.assertEqual([], errors)
        self.assertEqual("document-ppt.slide.v1", deck["schema_version"])
        self.assertEqual(3, len(deck["slides"]))
        self.assertEqual("slide_01", deck["slides"][0]["id"])

    def test_prompt_payload_uses_only_manifest_asset_urls(self) -> None:
        payload = generate_slide_json.build_prompt_payload(self.manifest, self.manifest_path, max_slides=8)
        known_urls = generate_slide_json.manifest_asset_urls(self.manifest)

        for asset in payload["assets"]:
            self.assertIn(asset["url"], known_urls)

    def test_cli_writes_dry_run_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "slide_deck.json"
            exit_code = generate_slide_json.main_with_args(
                [
                    str(self.manifest_path),
                    "--output",
                    str(output_path),
                    "--dry-run",
                ]
            )

            self.assertEqual(0, exit_code)
            deck = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual([], generate_slide_json.validate_deck(deck, self.manifest))


if __name__ == "__main__":
    unittest.main()
