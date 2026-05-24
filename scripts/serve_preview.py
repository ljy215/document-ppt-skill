#!/usr/bin/env python3
"""Serve the Phase 3 HTML preview and conversational Slide-JSON update API."""

from __future__ import annotations

import argparse
import cgi
import copy
import html
import json
import os
import re
import shutil
import sys
import uuid
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import extract_multimodal_assets
import generate_slide_json


ROOT = Path(__file__).resolve().parents[1]
PREVIEW_DIR = ROOT / "preview"
UPLOAD_ROOT = ROOT / "_preview_uploads"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
ZIP_TEXT_EXTENSIONS = {".docx", ".pptx"}


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


def safe_stem(filename: str) -> str:
    stem = Path(filename).stem or "document"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "document"


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def xml_text(value: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", value).strip())


def extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml_bytes)
    namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespaces):
        parts = [node.text or "" for node in paragraph.findall(".//w:t", namespaces)]
        text = xml_text("".join(parts))
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def extract_pptx_text(path: Path) -> str:
    paragraphs: list[str] = []
    namespaces = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        slide_names = sorted(name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name))
        for slide_index, name in enumerate(slide_names, start=1):
            root = ElementTree.fromstring(archive.read(name))
            parts = [node.text or "" for node in root.findall(".//a:t", namespaces)]
            text = xml_text(" ".join(parts))
            if text:
                paragraphs.append(f"Slide {slide_index}. {text}")
    return "\n".join(paragraphs)


def chunk_text(text: str, size: int = 1400) -> list[str]:
    clean = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not clean:
        return ["No extractable text was found."]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in re.split(r"\n\s*\n", clean):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and current_len + len(paragraph) > size:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(paragraph)
        current_len += len(paragraph)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def build_text_manifest(source_path: Path, manifest_path: Path, text: str) -> dict[str, Any]:
    pages = []
    for index, chunk in enumerate(chunk_text(text), start=1):
        pages.append(
            {
                "page": index,
                "width": 1280,
                "height": 720,
                "image_url": None,
                "text": chunk,
                "blocks": [
                    {
                        "id": f"text_p{index}_001",
                        "page": index,
                        "type": "text",
                        "bbox": [0, 0, 1280, 720],
                        "text": chunk,
                    }
                ],
            }
        )
    manifest = {
        "schema_version": "paper-reader.multimodal.v1",
        "source": {
            "pdf_path": str(source_path),
            "title": source_path.stem,
            "page_count": len(pages),
            "source_type": source_path.suffix.lower().lstrip(".") or "text",
        },
        "pages": pages,
        "captions": [],
        "assets": [],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def extract_document_to_manifest(source_path: Path, manifest_dir: Path) -> Path:
    suffix = source_path.suffix.lower()
    manifest_dir.mkdir(parents=True, exist_ok=True)
    if suffix == ".pdf":
        manifest = extract_multimodal_assets.extract_multimodal(source_path, manifest_dir, zoom=2.0)
        manifest_path = manifest_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest_path
    if suffix in TEXT_EXTENSIONS:
        text = read_text_file(source_path)
    elif suffix == ".docx":
        text = extract_docx_text(source_path)
    elif suffix == ".pptx":
        text = extract_pptx_text(source_path)
    elif suffix == ".json":
        payload = load_json(source_path)
        if payload.get("schema_version") == "document-ppt.slide.v1":
            raise ValueError("slide-json")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        raise ValueError(f"Unsupported document type: {suffix or 'unknown'}")
    manifest_path = manifest_dir / "manifest.json"
    build_text_manifest(source_path, manifest_path, text)
    return manifest_path


def generate_deck_from_manifest(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL"):
        config = generate_slide_json.GenerationConfig(
            model=os.getenv("OPENAI_MODEL"),
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL),
            temperature=0.2,
            max_slides=8,
            dry_run=False,
        )
        prompt_payload = generate_slide_json.build_prompt_payload(manifest, manifest_path, config.max_slides)
        deck = generate_slide_json.call_openai_compatible(prompt_payload, config)
    else:
        deck = local_deck_from_manifest(manifest, manifest_path, max_slides=8)
    errors = generate_slide_json.validate_deck(deck, manifest)
    if errors:
        raise ValueError("Generated Slide-JSON failed validation: " + "; ".join(errors))
    output_path.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    return deck


def local_deck_from_manifest(manifest: dict[str, Any], manifest_path: Path, max_slides: int) -> dict[str, Any]:
    source = manifest.get("source") or {}
    title = source.get("title") or Path(source.get("pdf_path", "")).stem or "Untitled Document"
    pages = manifest.get("pages") or []
    assets = generate_slide_json.select_assets(manifest, limit=6)
    excerpts = [
        generate_slide_json.compact_text(page.get("text") or "", 520)
        for page in pages
        if generate_slide_json.compact_text(page.get("text") or "", 520)
    ]
    summary_bullets = extract_local_bullets("\n".join(excerpts), limit=4)
    if not summary_bullets:
        summary_bullets = ["已完成文档抽取，但可用文本较少。", "可以通过右侧对话继续补充修改要求。"]

    def animation(kind: str, order: int) -> dict[str, Any]:
        return {"type": kind, "order": order, "duration_ms": 450, "delay_ms": 0, "direction": "center"}

    def bullet(text: str, order: int, page: int = 1, kind: str = "fade-in") -> dict[str, Any]:
        return {
            "text": generate_slide_json.compact_text(text, 120),
            "emphasis": "normal",
            "animation": animation(kind, order),
            "source_refs": [{"page": page, "evidence": generate_slide_json.compact_text(text, 80)}],
        }

    visual = first_visual(assets)
    slides = [
        {
            "id": "slide_01",
            "title": title,
            "subtitle": "上传文档自动解析预览",
            "layout": "title",
            "bullets": [bullet("已从上传文件抽取文本、图表与中间态结构。", 1)],
            "visuals": [],
            "speaker_notes": "Local generation was used because no LLM credentials were configured.",
            "transition": "fade",
        },
        {
            "id": "slide_02",
            "title": "文档内容摘要",
            "layout": "visual-right" if visual else "bullets",
            "bullets": [bullet(text, index + 1, min(index + 1, max(1, len(pages)))) for index, text in enumerate(summary_bullets[:4])],
            "visuals": [visual] if visual else [],
            "speaker_notes": "These bullets are derived from extracted document text. Configure OPENAI_API_KEY and OPENAI_MODEL for higher-quality semantic summarization.",
            "transition": "fade",
        },
        {
            "id": "slide_03",
            "title": "后续可编辑方向",
            "layout": "closing",
            "bullets": [
                bullet("右侧对话框会把修改意见和当前 Slide-JSON 发送给后端更新。", 1),
                bullet("下一阶段会把同一份 Slide-JSON 编译为原生 PPTX。", 2),
            ],
            "visuals": [],
            "speaker_notes": "Use the JSON editor for debugging or direct intermediate-state edits.",
            "transition": "fade",
        },
    ]
    return {
        "schema_version": "document-ppt.slide.v1",
        "deck": {
            "title": title,
            "subtitle": "Slide-JSON preview",
            "source_manifest": str(manifest_path),
            "language": "zh-CN",
            "theme": {
                "aspect_ratio": "16:9",
                "font_family": "Microsoft YaHei",
                "palette": {"background": "#F8FAFC", "foreground": "#111827", "accent": "#2563EB"},
            },
        },
        "slides": slides[:max_slides],
    }


def extract_local_bullets(text: str, limit: int) -> list[str]:
    clean = re.sub(r"[#>*_`]+", " ", text)
    parts = re.split(r"(?<=[。！？.!?])\s+|\n+", clean)
    bullets: list[str] = []
    for part in parts:
        sentence = re.sub(r"\s+", " ", part).strip(" -\t\r\n")
        if len(sentence) < 8:
            continue
        bullets.append(sentence)
        if len(bullets) >= limit:
            break
    return bullets


def first_visual(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    for asset in assets:
        if asset.get("url"):
            return {
                "asset_id": asset.get("id") or "asset_01",
                "asset_url": asset["url"],
                "kind": asset.get("kind") or "figure",
                "caption": asset.get("caption") or "",
                "layout": {"x": 0.55, "y": 0.22, "w": 0.36, "h": 0.56},
                "animation": {"type": "zoom-in", "order": 3, "duration_ms": 600, "delay_ms": 0, "direction": "center"},
                "source_refs": [
                    {
                        "page": asset.get("page") or 1,
                        "asset_id": asset.get("id") or "asset_01",
                        "asset_url": asset["url"],
                        "caption": asset.get("caption") or "",
                    }
                ],
            }
    return None


def run_document_pipeline(upload_path: Path, run_dir: Path) -> tuple[dict[str, Any], Path]:
    run_dir.mkdir(parents=True, exist_ok=True)
    if upload_path.suffix.lower() == ".json":
        payload = load_json(upload_path)
        if payload.get("schema_version") == "document-ppt.slide.v1":
            validate_slide_json(payload)
            deck_path = run_dir / "slide_deck.json"
            deck_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload, deck_path
    manifest_dir = run_dir / "manifest"
    manifest_path = extract_document_to_manifest(upload_path, manifest_dir)
    deck_path = run_dir / "slide_deck.json"
    return generate_deck_from_manifest(manifest_path, deck_path), deck_path


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
    current_asset_root: Path | None = None

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
        if parsed.path.startswith("/generated/"):
            self.serve_generated_file(parsed.path)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/documents/upload":
            self.handle_document_upload()
            return
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

    def handle_document_upload(self) -> None:
        try:
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("multipart/form-data"):
                raise ValueError("multipart/form-data is required")
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": content_type,
                },
            )
            field = form["document"] if "document" in form else None
            if field is None or not getattr(field, "filename", ""):
                raise ValueError("document file is required")
            original_name = Path(field.filename).name
            run_id = safe_stem(original_name) + "_" + uuid.uuid4().hex[:10]
            run_dir = (UPLOAD_ROOT / run_id).resolve()
            source_dir = run_dir / "source"
            source_dir.mkdir(parents=True, exist_ok=True)
            upload_path = source_dir / original_name
            with upload_path.open("wb") as output:
                shutil.copyfileobj(field.file, output)

            deck, deck_path = run_document_pipeline(upload_path, run_dir)
            PreviewHandler.deck_path = deck_path
            PreviewHandler.current_asset_root = run_dir / "manifest"
            self.send_json(
                {
                    "filename": original_name,
                    "run_id": run_id,
                    "manifest_url": f"/generated/{run_id}/manifest/manifest.json",
                    "slide_json_url": f"/generated/{run_id}/slide_deck.json",
                    "asset_base_url": f"/generated/{run_id}/manifest/",
                    "slides": len(deck.get("slides", [])),
                    "slide_json": deck,
                }
            )
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
        asset_root = self.current_asset_root or (self.deck_path.parent if self.deck_path else None)
        if not asset_root:
            self.send_error(404)
            return
        relative = raw_path.removeprefix("/deck-assets/")
        asset_root = asset_root.resolve()
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

    def serve_generated_file(self, raw_path: str) -> None:
        relative = raw_path.removeprefix("/generated/")
        path = (UPLOAD_ROOT / relative).resolve()
        try:
            path.relative_to(UPLOAD_ROOT.resolve())
        except ValueError:
            self.send_error(403)
            return
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        content_type = {
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".csv": "text/csv; charset=utf-8",
            ".txt": "text/plain; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
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
