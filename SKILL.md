---
name: toppt
description: Use when the user gives an academic paper file and wants it parsed into multimodal assets, summarized, previewed, edited conversationally, or converted into animated PPTX-ready slide content.
---

# ToPPT

## Overview

Use this skill whenever the user provides a local academic paper or document path and asks to generate PPT, parse the file, preview it, revise it, or perform another operation related to turning the file into slides.

The default workflow is now an end-to-end preview-first PPT workflow:

1. Upload document.
2. Extract text, figures, tables, captions, page coordinates, and asset URLs.
3. Generate a strict Slide-JSON intermediate state instead of direct Markdown.
4. Generate and serve an animated HTML preview with pure JavaScript.
5. Let the user revise the deck in the web page through the right-side conversation box.
6. Export the current front-end Slide-JSON state to a native `.pptx` from the web page.

When the user says something like `帮我根据 "E:\paper-reader\xxx.pdf" 生成ppt`, do not jump straight to a final `.pptx`. Run the parsing and preview server first, give the user the preview URL, and let the user review or revise the deck in the browser before exporting.

## Workflow

1. Locate the document from the provided path, filename, stem, or fuzzy partial match. If multiple plausible files exist, ask the user to choose.
2. Start the preview server with the project Python environment, preferably the `ppt` conda environment:

```bash
conda run -n ppt python scripts/serve_preview.py --host 127.0.0.1 --port 8765
```

If the user provided a specific Slide-JSON file, pass it with `--deck`.

3. Open or provide the preview URL:

```text
http://127.0.0.1:8765/
```

4. In the preview page, upload the source document. The page accepts `.pdf`, `.docx`, `.pptx`, `.md`, `.markdown`, `.txt`, and `.json`. Uploading must automatically trigger parsing, Slide-JSON generation, and HTML preview rendering.
5. For PDFs, the server runs `scripts/extract_multimodal_assets.py` internally to extract text, captions, page coordinates, figure/table crops, table CSVs, page previews, and asset mappings:

```bash
python path/to/toppt/scripts/extract_multimodal_assets.py "paper-name.pdf" --output-dir "paper-name_multimodal"
```

6. Generate strict Slide-JSON from the manifest:

```bash
python path/to/toppt/scripts/generate_slide_json.py "paper-name_multimodal/manifest.json" --output "paper-name_slide_deck.json"
```

Use `--dry-run` when validating the pipeline without an LLM API key.

7. Let the user revise inside the preview page:
   - The right-side chat box sends the user prompt plus the current Slide-JSON to the backend.
   - If LLM credentials are configured, the backend updates the Slide-JSON through the LLM.
   - If credentials are not configured, the backend keeps a local fallback update and the agent may still edit the Slide-JSON or preview assets directly when asked.
   - The preview must hot-update from the returned Slide-JSON.
8. Let the user click `Export PPTX` in the preview page. The page sends the current front-end Slide-JSON to `/api/pptx/export`; the backend compiles it with `scripts/compile_pptx.py` and returns a downloadable `.pptx`.
9. For static/offline preview bundles, use:

```bash
python path/to/toppt/scripts/create_agent_preview_bundle.py "paper-name_slide_deck.json" --output-dir "preview_runs/paper-name"
```

10. If the user asks for style changes such as "改成深色科技风" or "更像论文答辩 PPT", prefer the browser conversation flow first. If the requested change requires renderer/CSS behavior that the backend JSON update cannot express, edit `preview/styles.css`, `preview/app.js`, or the generated preview bundle directly and verify in the browser.

11. For the legacy Markdown report workflow, `scripts/extract_paper_assets.py` is still available:

```bash
python path/to/toppt/scripts/extract_paper_assets.py "paper-name.pdf" --output-dir "paper-name_assets"
```

12. If the user still asks for a Chinese Markdown reading report, draft it in the current directory. Name it `<paper-stem>_reading-report.md` unless the user asks for another name.
13. Insert local image links using relative paths from the report to the asset folder. Include:
   - A generated paper structure framework diagram, preferably Mermaid.
   - All model/module/architecture figures related to the paper's claimed innovations when the original paper contains them. Use extracted original images if available; otherwise create clean Mermaid reconstructions and clearly label them as reconstructions.
14. Convert relevant extracted CSV tables to Markdown tables and embed them inside the effectiveness-evidence section, next to the explanation that uses them.
15. Verify the report references existing image files and that every major figure/table discussed is aligned with the surrounding claim in the paper.

## Extraction Notes

- Prefer the bundled multimodal extractor before ad hoc PDF parsing. It records page numbers, bounding boxes, captions, rendered asset crops, page previews, and nearest figure/table relationships.
- If `PyMuPDF` or `pdfplumber` is unavailable, install or use the existing PDF skill/tooling. Do not fabricate figure/table details from memory.
- For scanned PDFs, perform OCR only if the local environment supports it; otherwise explain the limitation and rely on visible figures plus any extractable metadata.
- When choosing innovation model/module diagrams, search captions and nearby text for terms such as `model`, `architecture`, `framework`, `module`, `overview`, `pipeline`, `method`, `network`, and equivalent Chinese terms for model, framework, structure, module, method, process, and network.
- When a module or figure is based on prior work, mark it as not original and cite the paper reference id used by the authors, for example `non-original, cited by authors as [35]`. Determine this from nearby method text, captions, and reference mentions. If unclear, write `source unclear in the paper` rather than guessing.
- When inserting experiment tables, prefer extracted CSV files from `assets/tables/`. If extraction merged columns poorly, reconstruct the table from the PDF text, keeping the original table number, caption, page, metrics, and values.

## Phase Roadmap

- Phase 1: Python multimodal extraction engine using PyMuPDF and optional pdfplumber. Output `manifest.json`.
- Phase 2: Python LLM orchestration that converts `manifest.json` into strict Slide-JSON. The LLM must not directly output Markdown. The schema lives at `schemas/slide-json.schema.json`.
- Phase 3: Pure JavaScript HTML preview renderer plus a backend upload/update API. The preview page is the main place where the user reviews and requests conversational revisions.
- Phase 4: PPTX compiler using Python `python-pptx`. The preview page sends the current Slide-JSON to the backend export API, which writes a native `.pptx` with layout, figures, theme colors, slide transitions, and animation intent preserved in speaker notes.

## Report Requirements

Write the report in Chinese and include these sections:

1. Paper narrative: explain the problem setup, motivation, baseline limitations, proposed method, experiments, and conclusion as a coherent story.
2. Key innovations: list concrete innovations and distinguish claimed novelty from implementation detail.
3. Paper structure framework diagram: include a Mermaid diagram showing the paper's rhetorical and technical structure.
4. How the authors narrate improvements/innovations: analyze how the authors frame gaps, introduce improvements, name modules, and connect design choices to problems.
5. How the authors prove effectiveness: summarize experiments, ablations, metrics, datasets, qualitative evidence, complexity analysis, and comparisons. Insert the paper's relevant experiment tables in this section, especially attention comparisons, small-object layer tests, lightweight module tests, ablations, scale/generalization tests, and model comparisons.
6. Innovations: list the author's model and all module figures related to the innovation. For each item, include the extracted figure, page/caption context, what role it plays in the paper, whether it appears to be original to the paper, and if not original, which reference id the authors cite.
7. Summary and thesis inspiration: discuss logical gaps, assumptions, missing experiments, risks of overclaiming, inspiration for the user's master's thesis, and concrete directions for improvement.

## Quality Bar

- Tie every important claim to page numbers, section names, figures, tables, or experiment names from the extraction.
- Keep figure/table discussion near the corresponding narrative claim; avoid dumping all images at the end.
- Do not omit experiment tables that support the effectiveness argument; if a table is too large, include the most relevant rows and say it is an excerpt.
- Do not list only one architecture figure when the paper contains multiple innovation-related module diagrams. Enumerate them and mark borrowed/non-original modules with cited references.
- Be explicit about uncertainty: mark ambiguous captions, unclear OCR, missing baselines, or inferred module boundaries.
- The final report should help the user understand both "what the paper did" and "how the paper persuaded the reader."
