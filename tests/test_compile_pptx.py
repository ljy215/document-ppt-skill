from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import compile_pptx  # noqa: E402


class CompilePptxTests(unittest.TestCase):
    def test_compile_minimal_slide_json_to_pptx(self) -> None:
        deck_path = ROOT / "tests" / "fixtures" / "minimal_slide_deck.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "deck.pptx"

            result = compile_pptx.compile_pptx(deck_path, output_path)

            self.assertEqual(3, result["slides"])
            self.assertTrue(output_path.exists())
            with zipfile.ZipFile(output_path) as archive:
                slide_files = [name for name in archive.namelist() if name.startswith("ppt/slides/slide")]
            self.assertGreaterEqual(len(slide_files), 3)


if __name__ == "__main__":
    unittest.main()
