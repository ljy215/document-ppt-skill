#!/usr/bin/env python3
"""Extract text, captions, figure/table crops, and coordinate mappings from a PDF."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Iterable


CAPTION_RE = re.compile(
    r"^\s*((fig(?:ure)?\.?|图)\s*\d+[\w\-\.]*|"
    r"(table|tab\.?|表)\s*\d+[\w\-\.]*)\s*[:：.\-]?\s*(.*)",
    re.IGNORECASE,
)

MODEL_TERMS = re.compile(
    r"(model|architecture|framework|module|overview|pipeline|method|network|"
    r"模型|架构|框架|结构|模块|方法|流程|网络)",
    re.IGNORECASE,
)


@dataclass
class TextBlock:
    id: str
    page: int
    type: str
    bbox: list[float]
    text: str


@dataclass
class Caption:
    id: str
    page: int
    kind: str
    bbox: list[float]
    text: str


@dataclass
class Asset:
    id: str
    kind: str
    page: int
    bbox: list[float]
    url: str
    caption_id: str | None = None
    caption_text: str | None = None
    caption_distance: float | None = None
    nearby_text_block_ids: list[str] = field(default_factory=list)
    nearby_text: list[str] = field(default_factory=list)
    role_hints: list[str] = field(default_factory=list)
    csv_url: str | None = None
    source: str = "pymupdf"


def norm_name(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value).lower()


def find_pdf(name: str, root: Path) -> Path:
    raw = Path(name)
    if raw.exists():
        return raw.resolve()
    if (root / raw).exists():
        return (root / raw).resolve()

    pdfs = [p for p in root.rglob("*.pdf") if p.is_file()]
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found under {root}")

    target = norm_name(raw.stem or raw.name)
    exact = [p for p in pdfs if norm_name(p.name) == norm_name(raw.name) or norm_name(p.stem) == target]
    if len(exact) == 1:
        return exact[0].resolve()
    if len(exact) > 1:
        raise RuntimeError("Multiple exact matches:\n" + "\n".join(str(p) for p in exact))

    partial = [p for p in pdfs if target in norm_name(p.stem) or norm_name(p.stem) in target]
    if len(partial) == 1:
        return partial[0].resolve()
    if len(partial) > 1:
        raise RuntimeError("Multiple partial matches:\n" + "\n".join(str(p) for p in partial[:20]))

    names = {norm_name(p.stem): p for p in pdfs}
    close = get_close_matches(target, list(names), n=5, cutoff=0.55)
    if len(close) == 1:
        return names[close[0]].resolve()
    if close:
        raise RuntimeError("No unique match. Close matches:\n" + "\n".join(str(names[c]) for c in close))
    raise FileNotFoundError(f"Could not find a PDF matching {name!r} under {root}")


def round_bbox(values: Iterable[float]) -> list[float]:
    return [round(float(v), 2) for v in values]


def rect_center(bbox: list[float]) -> tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2


def rect_distance(a: list[float], b: list[float]) -> float:
    ax, ay = rect_center(a)
    bx, by = rect_center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def expanded_bbox(bbox: list[float], page_width: float, page_height: float, pad: float) -> list[float]:
    return [
        max(0.0, bbox[0] - pad),
        max(0.0, bbox[1] - pad),
        min(page_width, bbox[2] + pad),
        min(page_height, bbox[3] + pad),
    ]


def nearest_caption(asset: Asset, captions: list[Caption]) -> None:
    same_page = [c for c in captions if c.page == asset.page and c.kind == asset.kind]
    if not same_page:
        return
    scored = sorted((rect_distance(asset.bbox, c.bbox), c) for c in same_page)
    distance, caption = scored[0]
    asset.caption_id = caption.id
    asset.caption_text = caption.text
    asset.caption_distance = round(distance, 2)
    if MODEL_TERMS.search(caption.text) and "model_candidate" not in asset.role_hints:
        asset.role_hints.append("model_candidate")


def nearby_text(asset: Asset, blocks: list[TextBlock], limit: int = 4) -> None:
    same_page = [b for b in blocks if b.page == asset.page]
    scored = sorted((rect_distance(asset.bbox, b.bbox), b) for b in same_page)
    chosen = [block for _, block in scored[:limit]]
    asset.nearby_text_block_ids = [b.id for b in chosen]
    asset.nearby_text = [b.text for b in chosen]


def render_crop(page: Any, bbox: list[float], output_path: Path, zoom: float) -> None:
    import fitz  # type: ignore

    clip = fitz.Rect(*bbox)
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
    pix.save(str(output_path))


def write_csv(path: Path, rows: list[list[Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def extract_text_and_figures(pdf_path: Path, out_dir: Path, zoom: float) -> tuple[dict[str, Any], list[TextBlock], list[Caption], list[Asset]]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required. Install with: python -m pip install pymupdf") from exc

    doc = fitz.open(str(pdf_path))
    figure_dir = out_dir / "assets" / "figures"
    page_dir = out_dir / "assets" / "pages"
    figure_dir.mkdir(parents=True, exist_ok=True)
    page_dir.mkdir(parents=True, exist_ok=True)

    pages: list[dict[str, Any]] = []
    text_blocks: list[TextBlock] = []
    captions: list[Caption] = []
    assets: list[Asset] = []

    for page_number, page in enumerate(doc, start=1):
        page_rect = page.rect
        page_png = page_dir / f"page_{page_number:03d}.png"
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).save(str(page_png))

        page_text_lines: list[str] = []
        page_blocks: list[dict[str, Any]] = []
        image_bboxes: list[list[float]] = []

        text_dict = page.get_text("dict")
        text_index = 1
        caption_index = 1
        for block in text_dict.get("blocks", []):
            block_type = block.get("type")
            bbox = round_bbox(block.get("bbox", [])) if block.get("bbox") else None
            if block_type == 0:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    line_text = "".join(span.get("text", "") for span in spans).strip()
                    if not line_text:
                        continue
                    line_bbox = round_bbox(line.get("bbox", bbox or []))
                    text_id = f"text_p{page_number}_{text_index:03d}"
                    text_index += 1
                    text_block = TextBlock(text_id, page_number, "text", line_bbox, line_text)
                    text_blocks.append(text_block)
                    page_blocks.append(asdict(text_block))
                    page_text_lines.append(line_text)

                    cap_match = CAPTION_RE.match(line_text)
                    if cap_match:
                        raw_kind = cap_match.group(2) or cap_match.group(3) or ""
                        kind = "table" if raw_kind.lower().startswith(("table", "tab")) or raw_kind == "表" else "figure"
                        captions.append(
                            Caption(
                                id=f"caption_p{page_number}_{caption_index:03d}",
                                page=page_number,
                                kind=kind,
                                bbox=line_bbox,
                                text=line_text,
                            )
                        )
                        caption_index += 1
            elif block_type == 1 and bbox:
                image_bboxes.append(bbox)

        for image_index, bbox in enumerate(image_bboxes, start=1):
            asset_id = f"figure_p{page_number}_{image_index:03d}"
            crop_bbox = expanded_bbox(bbox, page_rect.width, page_rect.height, pad=4)
            png_path = figure_dir / f"{asset_id}.png"
            render_crop(page, crop_bbox, png_path, zoom)
            assets.append(
                Asset(
                    id=asset_id,
                    kind="figure",
                    page=page_number,
                    bbox=crop_bbox,
                    url=str(png_path.relative_to(out_dir)).replace("\\", "/"),
                )
            )

        pages.append(
            {
                "page": page_number,
                "width": round(float(page_rect.width), 2),
                "height": round(float(page_rect.height), 2),
                "image_url": str(page_png.relative_to(out_dir)).replace("\\", "/"),
                "text": "\n".join(page_text_lines),
                "blocks": page_blocks,
            }
        )

    manifest = {
        "schema_version": "paper-reader.multimodal.v1",
        "source": {
            "pdf_path": str(pdf_path),
            "title": doc.metadata.get("title") or pdf_path.stem,
            "page_count": len(doc),
        },
        "pages": pages,
        "captions": [asdict(c) for c in captions],
    }
    return manifest, text_blocks, captions, assets


def extract_tables(pdf_path: Path, out_dir: Path, captions: list[Caption], text_blocks: list[TextBlock], zoom: float) -> list[Asset]:
    try:
        import fitz  # type: ignore
        import pdfplumber  # type: ignore
    except ImportError:
        return []

    table_dir = out_dir / "assets" / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)
    assets: list[Asset] = []

    doc = fitz.open(str(pdf_path))
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_number, plumber_page in enumerate(pdf.pages, start=1):
            try:
                found_tables = plumber_page.find_tables()
            except Exception:
                found_tables = []
            page = doc[page_number - 1]
            for table_index, table_obj in enumerate(found_tables, start=1):
                rows = table_obj.extract() or []
                if not rows:
                    continue
                asset_id = f"table_p{page_number}_{table_index:03d}"
                bbox = round_bbox(table_obj.bbox)
                crop_bbox = expanded_bbox(bbox, page.rect.width, page.rect.height, pad=4)
                png_path = table_dir / f"{asset_id}.png"
                csv_path = table_dir / f"{asset_id}.csv"
                render_crop(page, crop_bbox, png_path, zoom)
                write_csv(csv_path, rows)
                asset = Asset(
                    id=asset_id,
                    kind="table",
                    page=page_number,
                    bbox=crop_bbox,
                    url=str(png_path.relative_to(out_dir)).replace("\\", "/"),
                    csv_url=str(csv_path.relative_to(out_dir)).replace("\\", "/"),
                    source="pdfplumber",
                )
                nearest_caption(asset, captions)
                nearby_text(asset, text_blocks)
                assets.append(asset)
    return assets


def write_extracted_text(manifest: dict[str, Any], assets: list[Asset], out_dir: Path) -> None:
    lines = [
        f"# Extracted Multimodal Text: {manifest['source']['title']}",
        "",
        f"- Source: `{manifest['source']['pdf_path']}`",
        f"- Pages: {manifest['source']['page_count']}",
        "",
        "## Assets",
        "",
    ]
    for asset in assets:
        caption = asset.caption_text or "no caption"
        lines.append(f"- p.{asset.page} `{asset.kind}` `{asset.url}`: {caption}")
    lines.extend(["", "## Page Text", ""])
    for page in manifest.get("pages", []):
        lines.extend([f"### Page {page['page']}", "", page.get("text", ""), ""])
    (out_dir / "extracted_text.md").write_text("\n".join(lines), encoding="utf-8")


def extract_multimodal(pdf_path: Path, out_dir: Path, zoom: float) -> dict[str, Any]:
    manifest, text_blocks, captions, assets = extract_text_and_figures(pdf_path, out_dir, zoom)

    for asset in assets:
        nearest_caption(asset, captions)
        nearby_text(asset, text_blocks)

    table_assets = extract_tables(pdf_path, out_dir, captions, text_blocks, zoom)
    all_assets = assets + table_assets
    manifest["assets"] = [asdict(asset) for asset in all_assets]
    write_extracted_text(manifest, all_assets, out_dir)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper", help="PDF filename, stem, or partial name to search for under --root")
    parser.add_argument("--root", default=".", help="Directory to search. Default: current directory")
    parser.add_argument("--output-dir", default=None, help="Output directory. Default: <pdf-stem>_multimodal")
    parser.add_argument("--zoom", type=float, default=2.0, help="Render zoom for page and asset PNGs")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    pdf_path = find_pdf(args.paper, root)
    out_dir = Path(args.output_dir or f"{pdf_path.stem}_multimodal").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = extract_multimodal(pdf_path, out_dir, args.zoom)
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "source_pdf": str(pdf_path),
                "output_dir": str(out_dir),
                "manifest": str(manifest_path),
                "pages": manifest["source"]["page_count"],
                "assets": len(manifest.get("assets", [])),
                "figures": len([a for a in manifest.get("assets", []) if a.get("kind") == "figure"]),
                "tables": len([a for a in manifest.get("assets", []) if a.get("kind") == "table"]),
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
