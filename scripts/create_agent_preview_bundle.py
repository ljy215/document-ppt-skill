#!/usr/bin/env python3
"""Create an editable static HTML preview bundle from Slide-JSON."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_DIR = ROOT / "preview"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_slide_json(deck: dict[str, Any]) -> None:
    if deck.get("schema_version") != "document-ppt.slide.v1":
        raise ValueError("schema_version must be document-ppt.slide.v1")
    if not isinstance(deck.get("slides"), list) or not deck["slides"]:
        raise ValueError("slides must be a non-empty array")


def copy_runtime(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("index.html", "styles.css", "app.js"):
        shutil.copy2(PREVIEW_DIR / filename, output_dir / filename)


def rewrite_index_for_static(output_dir: Path) -> None:
    path = output_dir / "index.html"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '<input id="documentFile" type="file" accept=".pdf,.docx,.pptx,.md,.markdown,.txt,.json,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation,text/markdown,text/plain,application/json">',
        '<input id="documentFile" type="file" accept=".json" disabled>',
    )
    text = text.replace(
        '<script src="./app.js"></script>',
        '<script>window.PREVIEW_DECK_URL = "./slide_deck.json";</script>\n    <script src="./app.js"></script>',
    )
    path.write_text(text, encoding="utf-8")


def write_agent_notes(output_dir: Path, deck_path: Path) -> None:
    notes = f"""# Agent Preview Bundle

Source Slide-JSON:

```text
{deck_path}
```

Edit this bundle directly when the user asks for style or content changes.

- Use `slide_deck.json` for content edits.
- Use `styles.css` for visual style changes.
- Use `app.js` for rendering behavior changes.
- Keep frontend logic in pure JavaScript.
"""
    (output_dir / "AGENT_NOTES.md").write_text(notes, encoding="utf-8")


def create_bundle(deck_path: Path, output_dir: Path) -> dict[str, Any]:
    deck = load_json(deck_path)
    validate_slide_json(deck)
    copy_runtime(output_dir)
    rewrite_index_for_static(output_dir)
    shutil.copy2(deck_path, output_dir / "slide_deck.json")
    write_agent_notes(output_dir, deck_path)
    return {
        "output_dir": str(output_dir),
        "entry": str(output_dir / "index.html"),
        "deck": str(output_dir / "slide_deck.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slide_json", help="Path to document-ppt.slide.v1 JSON")
    parser.add_argument("--output-dir", required=True, help="Directory for the editable preview bundle")
    args = parser.parse_args()

    result = create_bundle(Path(args.slide_json).resolve(), Path(args.output_dir).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
