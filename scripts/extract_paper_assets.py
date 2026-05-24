#!/usr/bin/env python3
"""Extract text, sections, figures, tables, and caption alignment from a paper PDF."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import Any


CAPTION_RE = re.compile(
    r"^\s*((fig(?:ure)?\.?|图)\s*\d+[\w\-\.]*|"
    r"(table|tab\.?|表)\s*\d+[\w\-\.]*)\s*[:：.\-]?\s*(.*)",
    re.IGNORECASE,
)

SECTION_RE = re.compile(
    r"^\s*((?:\d+(?:\.\d+){0,3}|[IVX]{1,6})[\s.、-]+)?"
    r"(abstract|introduction|related work|background|method|methodology|approach|"
    r"model|experiments?|results?|evaluation|discussion|conclusion|limitations?|"
    r"摘要|引言|相关工作|背景|方法|模型|实验|结果|评估|讨论|结论|局限)\b.*$",
    re.IGNORECASE,
)

MODEL_TERMS = re.compile(
    r"(model|architecture|framework|module|overview|pipeline|method|network|"
    r"模型|架构|框架|结构|模块|方法|流程|网络)",
    re.IGNORECASE,
)


@dataclass
class Caption:
    page: int
    text: str
    kind: str
    bbox: list[float] | None = None


@dataclass
class Figure:
    id: str
    page: int
    path: str
    bbox: list[float] | None
    width: int | None
    height: int | None
    nearest_caption: str | None = None
    caption_distance: float | None = None
    is_model_candidate: bool = False


@dataclass
class Table:
    id: str
    page: int
    path: str
    bbox: list[float] | None
    rows: int
    cols: int
    nearest_caption: str | None = None
    caption_distance: float | None = None


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


def rect_distance(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b:
        return None
    ax = (a[0] + a[2]) / 2
    ay = (a[1] + a[3]) / 2
    bx = (b[0] + b[2]) / 2
    by = (b[1] + b[3]) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def nearest_caption(page: int, bbox: list[float] | None, kind: str, captions: list[Caption]) -> tuple[str | None, float | None]:
    same_page = [c for c in captions if c.page == page and c.kind == kind]
    if not same_page:
        return None, None
    scored = [(rect_distance(bbox, c.bbox), c) for c in same_page]
    scored = [(d if d is not None else 999999.0, c) for d, c in scored]
    scored.sort(key=lambda item: item[0])
    return scored[0][1].text, round(scored[0][0], 2)


def write_csv(path: Path, rows: list[list[Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def extract_with_pymupdf(pdf_path: Path, out_dir: Path) -> dict[str, Any]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required. Install with: python -m pip install pymupdf") from exc

    doc = fitz.open(str(pdf_path))
    figure_dir = out_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)

    pages: list[dict[str, Any]] = []
    captions: list[Caption] = []
    figures: list[Figure] = []
    sections: list[dict[str, Any]] = []

    for page_index, page in enumerate(doc, start=1):
        text_dict = page.get_text("dict")
        page_lines: list[str] = []
        image_blocks: list[dict[str, Any]] = []

        for block in text_dict.get("blocks", []):
            block_type = block.get("type")
            bbox = [round(float(v), 2) for v in block.get("bbox", [])] if block.get("bbox") else None
            if block_type == 0:
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    line_text = "".join(span.get("text", "") for span in spans).strip()
                    if not line_text:
                        continue
                    page_lines.append(line_text)
                    cap_match = CAPTION_RE.match(line_text)
                    if cap_match:
                        raw_kind = cap_match.group(2) or cap_match.group(3) or ""
                        kind = "table" if raw_kind.lower().startswith(("table", "tab")) or raw_kind == "表" else "figure"
                        line_bbox = [round(float(v), 2) for v in line.get("bbox", bbox or [])] if line.get("bbox") or bbox else None
                        captions.append(Caption(page_index, line_text, kind, line_bbox))
                    if SECTION_RE.match(line_text) and len(line_text) <= 140:
                        sections.append({"page": page_index, "title": line_text})
            elif block_type == 1:
                image_blocks.append(block)

        for image_index, block in enumerate(image_blocks, start=1):
            image_bytes = block.get("image")
            ext = block.get("ext") or "png"
            bbox = [round(float(v), 2) for v in block.get("bbox", [])] if block.get("bbox") else None
            fig_id = f"fig_p{page_index}_{image_index}"
            path = figure_dir / f"{fig_id}.{ext}"
            if image_bytes:
                path.write_bytes(image_bytes)
            cap, dist = nearest_caption(page_index, bbox, "figure", captions)
            figures.append(
                Figure(
                    id=fig_id,
                    page=page_index,
                    path=str(path.relative_to(out_dir)),
                    bbox=bbox,
                    width=block.get("width"),
                    height=block.get("height"),
                    nearest_caption=cap,
                    caption_distance=dist,
                    is_model_candidate=bool(cap and MODEL_TERMS.search(cap)),
                )
            )

        pages.append({"page": page_index, "text": "\n".join(page_lines)})

    for fig in figures:
        cap, dist = nearest_caption(fig.page, fig.bbox, "figure", captions)
        fig.nearest_caption = fig.nearest_caption or cap
        fig.caption_distance = fig.caption_distance if fig.caption_distance is not None else dist
        fig.is_model_candidate = fig.is_model_candidate or bool(fig.nearest_caption and MODEL_TERMS.search(fig.nearest_caption))

    return {
        "metadata": {
            "source_pdf": str(pdf_path),
            "page_count": len(doc),
            "title": doc.metadata.get("title") or pdf_path.stem,
        },
        "pages": pages,
        "sections": sections,
        "captions": [asdict(c) for c in captions],
        "figures": [asdict(f) for f in figures],
    }


def extract_tables(pdf_path: Path, out_dir: Path, captions: list[Caption]) -> list[Table]:
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return []

    table_dir = out_dir / "tables"
    table_dir.mkdir(parents=True, exist_ok=True)
    tables: list[Table] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            try:
                found_tables = page.find_tables()
            except Exception:
                found_tables = []
            for table_index, table_obj in enumerate(found_tables, start=1):
                rows = table_obj.extract() or []
                if not rows:
                    continue
                table_id = f"table_p{page_index}_{table_index}"
                path = table_dir / f"{table_id}.csv"
                write_csv(path, rows)
                bbox = [round(float(v), 2) for v in table_obj.bbox] if table_obj.bbox else None
                cap, dist = nearest_caption(page_index, bbox, "table", captions)
                col_count = max((len(r) for r in rows), default=0)
                tables.append(
                    Table(
                        id=table_id,
                        page=page_index,
                        path=str(path.relative_to(out_dir)),
                        bbox=bbox,
                        rows=len(rows),
                        cols=col_count,
                        nearest_caption=cap,
                        caption_distance=dist,
                    )
                )
    return tables


def write_markdown(data: dict[str, Any], out_dir: Path) -> None:
    lines = [
        f"# Extracted Text: {data['metadata']['title']}",
        "",
        f"- Source: `{data['metadata']['source_pdf']}`",
        f"- Pages: {data['metadata']['page_count']}",
        "",
        "## Section Candidates",
        "",
    ]
    for sec in data.get("sections", []):
        lines.append(f"- p.{sec['page']}: {sec['title']}")
    lines.extend(["", "## Figure Candidates", ""])
    for fig in data.get("figures", []):
        mark = " model-candidate" if fig.get("is_model_candidate") else ""
        lines.append(f"- p.{fig['page']} `{fig['path']}`{mark}: {fig.get('nearest_caption') or 'no caption'}")
    lines.extend(["", "## Table Candidates", ""])
    for table in data.get("tables", []):
        lines.append(f"- p.{table['page']} `{table['path']}`: {table.get('nearest_caption') or 'no caption'}")
    lines.extend(["", "## Page Text", ""])
    for page in data.get("pages", []):
        lines.extend([f"### Page {page['page']}", "", page["text"], ""])
    (out_dir / "extracted_text.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper", help="PDF filename, stem, or partial name to search for under --root")
    parser.add_argument("--root", default=".", help="Directory to search. Default: current directory")
    parser.add_argument("--output-dir", default=None, help="Output directory. Default: <pdf-stem>_assets")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    pdf_path = find_pdf(args.paper, root)
    out_dir = Path(args.output_dir or f"{pdf_path.stem}_assets").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    data = extract_with_pymupdf(pdf_path, out_dir)
    captions = [Caption(**c) for c in data.get("captions", [])]
    data["tables"] = [asdict(t) for t in extract_tables(pdf_path, out_dir, captions)]
    write_markdown(data, out_dir)
    (out_dir / "paper_extraction.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "source_pdf": str(pdf_path),
        "output_dir": str(out_dir),
        "pages": data["metadata"]["page_count"],
        "figures": len(data.get("figures", [])),
        "tables": len(data.get("tables", [])),
        "model_candidates": [f["path"] for f in data.get("figures", []) if f.get("is_model_candidate")],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
