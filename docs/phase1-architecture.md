# Phase 1: Multimodal Document Parsing And Asset Extraction

## Goal

Replace text-only paper parsing with a multimodal extraction layer that keeps text, figures, tables, captions, page coordinates, and local asset URLs aligned in a single manifest.

This phase intentionally stays independent from LLM prompting and PPT generation. Its output is the stable contract consumed by Phase 2.

## Input And Output

Input:

- A local PDF path, exact filename, stem, or fuzzy partial match.

Output directory:

```text
<paper-stem>_multimodal/
  manifest.json
  extracted_text.md
  assets/
    figures/*.png
    tables/*.png
    tables/*.csv
    pages/*.png
```

Core command:

```bash
conda run -n ppt python scripts/extract_multimodal_assets.py "paper.pdf" --output-dir "paper_multimodal"
```

## Manifest Contract

`manifest.json` is designed as the long-lived intermediate source for later phases:

```json
{
  "schema_version": "paper-reader.multimodal.v1",
  "source": {
    "pdf_path": "...",
    "title": "...",
    "page_count": 10
  },
  "pages": [
    {
      "page": 1,
      "width": 595.28,
      "height": 841.89,
      "text": "...",
      "blocks": [
        {
          "id": "text_p1_001",
          "type": "text",
          "bbox": [x0, y0, x1, y1],
          "text": "..."
        }
      ]
    }
  ],
  "captions": [
    {
      "id": "caption_p2_001",
      "kind": "figure",
      "page": 2,
      "bbox": [x0, y0, x1, y1],
      "text": "Fig. 1. Model overview"
    }
  ],
  "assets": [
    {
      "id": "figure_p2_001",
      "kind": "figure",
      "page": 2,
      "bbox": [x0, y0, x1, y1],
      "url": "assets/figures/figure_p2_001.png",
      "caption_id": "caption_p2_001",
      "caption_text": "Fig. 1. Model overview",
      "nearby_text_block_ids": ["text_p2_010"],
      "role_hints": ["model_candidate"]
    }
  ]
}
```

## Extraction Strategy

1. Use PyMuPDF as the primary parser.
   - Extract text lines and image blocks with page coordinates.
   - Render page regions into PNG crops so figures are previewable even when embedded images are fragmented.

2. Use caption-first alignment.
   - Detect figure/table captions with multilingual regex.
   - Associate each asset to the nearest same-page caption of the same kind.
   - Keep distances and coordinates in JSON so later stages can revise alignment.

3. Use pdfplumber as optional table support.
   - Extract table grid data to CSV.
   - Crop the table bbox to PNG for visual preservation.
   - If pdfplumber is unavailable, continue with figures and text.

4. Preserve enough context for LLM summarization.
   - Each asset records nearby text block IDs and nearby text snippets.
   - Model/framework/module captions are tagged with `model_candidate`.

## Phase Boundary

Phase 1 does not call an LLM and does not generate slides. It only produces a reliable multimodal manifest.

Phase 2 will read `manifest.json` and convert it to a strict Slide-JSON document.
