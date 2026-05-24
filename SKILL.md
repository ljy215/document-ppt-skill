---
name: toppt
description: Use when the user gives an academic paper file and wants it parsed into multimodal assets, summarized, previewed, edited conversationally, or converted into animated PPTX-ready slide content.
---

# ToPPT

## Overview

Use this skill to analyze a local academic paper, usually a PDF, when the user provides the paper filename or a close name.

The upgraded long-term workflow is:

1. Upload document.
2. Extract text, figures, tables, captions, page coordinates, and asset URLs.
3. Generate a strict Slide-JSON intermediate state instead of direct Markdown.
4. Preview Slide-JSON as animated HTML with pure JavaScript.
5. Apply conversational edits by updating the intermediate JSON.
6. Export a native `.pptx` file with preserved layout and animation intent.

The current implemented foundation is Phase 1: multimodal document parsing and asset extraction.

## Workflow

1. Locate the paper in the current working directory, accepting exact filename, stem, or fuzzy partial matches. If multiple plausible files exist, ask the user to choose.
2. Run `scripts/extract_multimodal_assets.py` on the selected file to extract text, captions, page coordinates, figure/table crops, table CSVs, page previews, and asset mappings:

```bash
python path/to/toppt/scripts/extract_multimodal_assets.py "paper-name.pdf" --output-dir "paper-name_multimodal"
```

3. Read `manifest.json` as the canonical machine-readable output. Use `extracted_text.md` only as a human-friendly inspection aid.
4. Generate strict Slide-JSON from the multimodal manifest:

```bash
python path/to/toppt/scripts/generate_slide_json.py "paper-name_multimodal/manifest.json" --output "paper-name_slide_deck.json"
```

Use `--dry-run` when validating the pipeline without an LLM API key.

5. Create an editable Agent-authored HTML preview bundle:

```bash
python path/to/toppt/scripts/create_agent_preview_bundle.py "paper-name_slide_deck.json" --output-dir "preview_runs/paper-name"
```

When this skill is running inside Codex or Claude Code, the agent must use its own model capability to revise the generated HTML/CSS/JS and Slide-JSON files according to the user's conversational instructions. Do not require the browser page to call an LLM API for design changes. For example, if the user says "改成深色科技风" or "更像论文答辩 PPT", edit `preview_runs/<name>/styles.css`, `app.js`, and/or `slide_deck.json` directly, then verify in the browser.

6. For the legacy Markdown report workflow, `scripts/extract_paper_assets.py` is still available:

```bash
python path/to/toppt/scripts/extract_paper_assets.py "paper-name.pdf" --output-dir "paper-name_assets"
```

7. If the user still asks for a Chinese Markdown reading report, draft it in the current directory. Name it `<paper-stem>_reading-report.md` unless the user asks for another name.
8. Insert local image links using relative paths from the report to the asset folder. Include:
   - A generated paper structure framework diagram, preferably Mermaid.
   - All model/module/architecture figures related to the paper's claimed innovations when the original paper contains them. Use extracted original images if available; otherwise create clean Mermaid reconstructions and clearly label them as reconstructions.
9. Convert relevant extracted CSV tables to Markdown tables and embed them inside the effectiveness-evidence section, next to the explanation that uses them.
10. Verify the report references existing image files and that every major figure/table discussed is aligned with the surrounding claim in the paper.

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
- Phase 3: Pure JavaScript HTML preview renderer plus Agent-authored HTML preview bundles. Conversational style edits are handled by the Codex/Claude Code agent editing generated files, not by requiring a runtime LLM key in the browser.
- Phase 4: PPTX compiler using Python or pure JavaScript. It reads Slide-JSON and exports native `.pptx` slides with layout and animation intent.

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
