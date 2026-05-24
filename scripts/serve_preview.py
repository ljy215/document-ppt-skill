#!/usr/bin/env python3
"""Serve the Phase 3 HTML preview and conversational Slide-JSON update API."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_DIR = ROOT / "preview"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


UPDATE_SYSTEM_PROMPT = """You update a Slide-JSON document according to a user revision prompt.

Rules:
- Return only valid JSON.
- Preserve schema_version document-ppt.slide.v1.
- Preserve slide ids unless the user explicitly requests slide insertions/removals.
- Preserve asset_url values unless they already exist in the input JSON.
- Keep bullet text concise and presentation-ready.
- Every bullet must keep animation and source_refs.
- Do not output Markdown or explanations.
"""


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def validate_slide_json(deck: dict[str, Any]) -> None:
    if deck.get("schema_version") != "document-ppt.slide.v1":
        raise ValueError("schema_version must be document-ppt.slide.v1")
    if not isinstance(deck.get("deck"), dict):
        raise ValueError("deck must be an object")
    slides = deck.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError("slides must be a non-empty array")
    for index, slide in enumerate(slides, start=1):
        if not slide.get("id"):
            slide["id"] = f"slide_{index:02d}"
        if not slide.get("title"):
            raise ValueError(f"{slide.get('id')}: title is required")
        if not isinstance(slide.get("bullets"), list):
            slide["bullets"] = []
        if not isinstance(slide.get("visuals"), list):
            slide["visuals"] = []
        for bullet in slide["bullets"]:
            if not bullet.get("animation"):
                bullet["animation"] = {"type": "fade-in", "order": 1, "duration_ms": 450}
            if not bullet.get("source_refs"):
                bullet["source_refs"] = [{"page": 1, "evidence": "updated by prompt"}]


def local_update(prompt: str, deck: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(deck)
    validate_slide_json(updated)
    first_slide = updated["slides"][0]
    notes = first_slide.get("speaker_notes", "")
    first_slide["speaker_notes"] = (notes + "\n" if notes else "") + "User revision request: " + prompt
    return updated


def call_openai_update(prompt: str, deck: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    base_url = os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL)
    if not api_key or not model:
        raise RuntimeError("OPENAI_API_KEY and OPENAI_MODEL are required for LLM updates")

    body = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": UPDATE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"prompt": prompt, "slide_json": deck},
                    ensure_ascii=False,
                ),
            },
        ],
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed with HTTP {exc.code}: {detail}") from exc

    content = payload["choices"][0]["message"]["content"]
    updated = extract_json_object(content)
    validate_slide_json(updated)
    return updated


class PreviewHandler(BaseHTTPRequestHandler):
    deck_path: Path | None = None

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/slide-json/current":
            self.send_json(self.current_deck())
            return
        if parsed.path.startswith("/deck-assets/"):
            self.serve_deck_asset(parsed.path)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/slide-json/update":
            self.send_error(404)
            return
        try:
            body = self.read_json_body()
            prompt = str(body.get("prompt") or "").strip()
            deck = body.get("slide_json")
            if not prompt:
                raise ValueError("prompt is required")
            if not isinstance(deck, dict):
                raise ValueError("slide_json must be an object")
            validate_slide_json(deck)
            mode = "llm"
            try:
                updated = call_openai_update(prompt, deck)
            except RuntimeError:
                updated = local_update(prompt, deck)
                mode = "local"
            self.send_json({"slide_json": updated, "mode": mode})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        return json.loads(data.decode("utf-8"))

    def current_deck(self) -> dict[str, Any]:
        if self.deck_path and self.deck_path.exists():
            return load_json(self.deck_path)
        return load_json(PREVIEW_DIR / "sample_slide_deck.json")

    def serve_static(self, raw_path: str) -> None:
        relative = "index.html" if raw_path in ("", "/") else raw_path.lstrip("/")
        path = (PREVIEW_DIR / relative).resolve()
        try:
            path.relative_to(PREVIEW_DIR)
        except ValueError:
            self.send_error(403)
            return
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(path.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def serve_deck_asset(self, raw_path: str) -> None:
        if not self.deck_path:
            self.send_error(404)
            return
        relative = raw_path.removeprefix("/deck-assets/")
        asset_root = self.deck_path.parent.resolve()
        path = (asset_root / relative).resolve()
        try:
            path.relative_to(asset_root)
        except ValueError:
            self.send_error(403)
            return
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        content_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".csv": "text/csv; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }.get(path.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--deck", default=None, help="Optional Slide-JSON path to serve as the current deck")
    args = parser.parse_args()

    if args.deck:
        PreviewHandler.deck_path = Path(args.deck).resolve()
        validate_slide_json(load_json(PreviewHandler.deck_path))

    server = ThreadingHTTPServer((args.host, args.port), PreviewHandler)
    print(f"Serving preview at http://{args.host}:{args.port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
