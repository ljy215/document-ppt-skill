#!/usr/bin/env python3
"""Generate strict Slide-JSON from a Phase 1 multimodal manifest."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "document-ppt.slide.v1"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


SYSTEM_PROMPT = """You convert multimodal academic-paper extraction data into strict Slide-JSON.

Rules:
- Return only valid JSON. Do not include Markdown fences or commentary.
- The JSON must match schema_version document-ppt.slide.v1.
- Keep bullet points concise and presentation-ready.
- Every important claim must cite page/source_refs.
- Use only asset_url values provided in the input evidence.
- Each bullet must include an animation object.
- Prefer fade-in for normal bullets, fly-in for contrasts, zoom-in for key figures, and appear for metadata.
- Do not invent figures, tables, metrics, datasets, or claims.
"""


@dataclass
class GenerationConfig:
    model: str | None
    api_key: str | None
    base_url: str
    temperature: float
    max_slides: int
    dry_run: bool


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_text(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def manifest_asset_urls(manifest: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for asset in manifest.get("assets", []):
        if asset.get("url"):
            urls.add(asset["url"])
        if asset.get("csv_url"):
            urls.add(asset["csv_url"])
    return urls


def select_assets(manifest: dict[str, Any], limit: int = 14) -> list[dict[str, Any]]:
    def score(asset: dict[str, Any]) -> tuple[int, int, str]:
        role_hints = asset.get("role_hints") or []
        role_score = 0
        if "model_candidate" in role_hints:
            role_score -= 20
        if asset.get("kind") == "table":
            role_score -= 8
        if asset.get("caption_text"):
            role_score -= 4
        return role_score, int(asset.get("page") or 9999), asset.get("id") or ""

    assets = sorted(manifest.get("assets", []), key=score)
    selected = []
    for asset in assets[:limit]:
        selected.append(
            {
                "id": asset.get("id"),
                "kind": asset.get("kind"),
                "page": asset.get("page"),
                "url": asset.get("url"),
                "csv_url": asset.get("csv_url"),
                "caption": compact_text(asset.get("caption_text") or "", 240),
                "role_hints": asset.get("role_hints") or [],
                "nearby_text": [compact_text(text, 220) for text in (asset.get("nearby_text") or [])[:3]],
            }
        )
    return selected


def select_page_excerpts(manifest: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    pages = manifest.get("pages", [])
    excerpts = []
    for page in pages[:limit]:
        excerpts.append(
            {
                "page": page.get("page"),
                "text_excerpt": compact_text(page.get("text") or "", 1200),
            }
        )
    return excerpts


def build_prompt_payload(manifest: dict[str, Any], manifest_path: Path, max_slides: int) -> dict[str, Any]:
    source = manifest.get("source") or manifest.get("metadata") or {}
    return {
        "task": "Create a presentation Slide-JSON from the paper extraction manifest.",
        "constraints": {
            "schema_version": SCHEMA_VERSION,
            "max_slides": max_slides,
            "language": "zh-CN",
            "style": "academic, concise, evidence-grounded",
        },
        "source": {
            "title": source.get("title") or Path(source.get("pdf_path", "")).stem or "Untitled Paper",
            "manifest_path": str(manifest_path),
            "page_count": source.get("page_count"),
        },
        "required_slide_flow": [
            "研究背景与问题",
            "核心方法或系统框架",
            "关键创新点",
            "实验设计与证据",
            "局限与可改进方向",
        ],
        "page_excerpts": select_page_excerpts(manifest),
        "assets": select_assets(manifest),
    }


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


def call_openai_compatible(prompt_payload: dict[str, Any], config: GenerationConfig) -> dict[str, Any]:
    if not config.api_key:
        raise RuntimeError("OPENAI_API_KEY or --api-key is required unless --dry-run is used")
    if not config.model:
        raise RuntimeError("OPENAI_MODEL or --model is required unless --dry-run is used")

    endpoint = config.base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": config.model,
        "temperature": config.temperature,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
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
    return extract_json_object(content)


def dry_run_deck(manifest: dict[str, Any], manifest_path: Path, max_slides: int) -> dict[str, Any]:
    source = manifest.get("source") or {}
    title = source.get("title") or Path(source.get("pdf_path", "")).stem or "Untitled Paper"
    assets = select_assets(manifest, limit=6)
    first_visual = assets[0] if assets else None

    def bullet(text: str, order: int, page: int = 1, evidence: str = "") -> dict[str, Any]:
        return {
            "text": text,
            "emphasis": "normal",
            "animation": {"type": "fade-in", "order": order, "duration_ms": 450, "delay_ms": 0, "direction": "center"},
            "source_refs": [{"page": page, "evidence": evidence}],
        }

    visuals = []
    if first_visual and first_visual.get("url"):
        visuals.append(
            {
                "asset_id": first_visual["id"],
                "asset_url": first_visual["url"],
                "kind": first_visual["kind"],
                "caption": first_visual.get("caption") or "",
                "layout": {"x": 0.54, "y": 0.22, "w": 0.38, "h": 0.56},
                "animation": {"type": "zoom-in", "order": 3, "duration_ms": 600, "delay_ms": 0, "direction": "center"},
                "source_refs": [
                    {
                        "page": first_visual.get("page") or 1,
                        "asset_id": first_visual["id"],
                        "asset_url": first_visual["url"],
                        "caption": first_visual.get("caption") or "",
                    }
                ],
            }
        )

    slides = [
        {
            "id": "slide_01",
            "title": title,
            "subtitle": "论文内容自动结构化草稿",
            "layout": "title",
            "bullets": [bullet("从多模态解析结果生成，可继续交给 LLM 精修。", 1)],
            "visuals": [],
            "speaker_notes": "Dry-run deck for validating the Slide-JSON pipeline.",
            "transition": "fade",
        },
        {
            "id": "slide_02",
            "title": "研究问题与方法线索",
            "layout": "visual-right" if visuals else "bullets",
            "bullets": [
                bullet("围绕论文摘要、引言与方法页提炼问题定义。", 1),
                bullet("优先保留模型图、框架图和关键实验表。", 2),
                bullet("每条要点保留页码或图表来源，便于后续追溯。", 3),
            ],
            "visuals": visuals,
            "speaker_notes": "Replace this dry-run content with LLM-generated claims in normal mode.",
            "transition": "fade",
        },
        {
            "id": "slide_03",
            "title": "后续编辑方向",
            "layout": "closing",
            "bullets": [
                bullet("Phase 3 将用纯 JavaScript 根据该 JSON 生成 HTML 预览。", 1),
                bullet("对话式修改只更新 JSON，不直接改 HTML 或 PPTX。", 2),
            ],
            "visuals": [],
            "speaker_notes": "This slide documents the intended pipeline boundary.",
            "transition": "fade",
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "deck": {
            "title": title,
            "subtitle": "Slide-JSON draft",
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


def validate_deck(deck: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if deck.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(deck.get("deck"), dict):
        errors.append("deck must be an object")
    slides = deck.get("slides")
    if not isinstance(slides, list) or not slides:
        errors.append("slides must be a non-empty array")
        return errors

    known_urls = manifest_asset_urls(manifest)
    seen_ids: set[str] = set()
    for index, slide in enumerate(slides, start=1):
        expected_id = f"slide_{index:02d}"
        slide_id = slide.get("id")
        if slide_id in seen_ids:
            errors.append(f"duplicate slide id: {slide_id}")
        seen_ids.add(slide_id)
        if not re.match(r"^slide_[0-9]{2}$", str(slide_id)):
            errors.append(f"invalid slide id: {slide_id}")
        if slide_id != expected_id:
            errors.append(f"slide id should be sequential: expected {expected_id}, got {slide_id}")
        if not slide.get("title"):
            errors.append(f"{slide_id}: missing title")
        for bullet_index, item in enumerate(slide.get("bullets") or [], start=1):
            if not item.get("text"):
                errors.append(f"{slide_id}: bullet {bullet_index} missing text")
            animation = item.get("animation") or {}
            if not animation.get("type"):
                errors.append(f"{slide_id}: bullet {bullet_index} missing animation.type")
        for visual in slide.get("visuals") or []:
            asset_url = visual.get("asset_url")
            if asset_url not in known_urls:
                errors.append(f"{slide_id}: unknown visual asset_url {asset_url!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="Path to Phase 1 manifest.json")
    parser.add_argument("--output", default=None, help="Output Slide-JSON path")
    parser.add_argument("--schema", default="schemas/slide-json.schema.json", help="Schema path for documentation/reference")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL"), help="OpenAI-compatible model name")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY"), help="API key. Defaults to OPENAI_API_KEY")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL), help="OpenAI-compatible base URL")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-slides", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true", help="Generate a deterministic skeleton without calling an LLM")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    manifest = load_json(manifest_path)
    output_path = Path(args.output or manifest_path.with_name("slide_deck.json")).resolve()

    config = GenerationConfig(
        model=args.model,
        api_key=args.api_key,
        base_url=args.base_url,
        temperature=args.temperature,
        max_slides=args.max_slides,
        dry_run=args.dry_run,
    )

    if config.dry_run:
        deck = dry_run_deck(manifest, manifest_path, config.max_slides)
    else:
        prompt_payload = build_prompt_payload(manifest, manifest_path, config.max_slides)
        deck = call_openai_compatible(prompt_payload, config)

    errors = validate_deck(deck, manifest)
    if errors:
        raise RuntimeError("Slide-JSON validation failed:\n" + "\n".join(f"- {error}" for error in errors))

    output_path.write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output_path),
                "slides": len(deck.get("slides", [])),
                "schema": str(Path(args.schema).resolve()),
                "dry_run": config.dry_run,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
