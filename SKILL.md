---
name: paper-reader
description: Use when the user gives the name of an academic paper file in the current directory and wants the paper read, including text, structure, figures, tables, captions, innovations, evidence, logic gaps, thesis inspiration, and a Chinese Markdown reading report with extracted diagrams.
---

# Paper Reader

## Overview

Use this skill to analyze a local academic paper, usually a PDF, when the user provides the paper filename or a close name. The goal is a Chinese Markdown reading report that preserves the paper's narrative, structure, figure/table context, innovation claims, evidence chain, and implications for the user's master's thesis work.

## Workflow

1. Locate the paper in the current working directory, accepting exact filename, stem, or fuzzy partial matches. If multiple plausible files exist, ask the user to choose.
2. Run `scripts/extract_paper_assets.py` on the selected file to extract text, section candidates, figures, tables, captions, and page-coordinate metadata:

```bash
python path/to/paper-reader/scripts/extract_paper_assets.py "paper-name.pdf" --output-dir "paper-name_assets"
```

3. Read `paper_extraction.json` for structure and figure/table alignment. Read `extracted_text.md` for the paper body. Inspect extracted images in `figures/` when selecting diagrams for the report.
4. Draft a Markdown report in the current directory. Name it `<paper-stem>_reading-report.md` unless the user asks for another name.
5. Insert local image links using relative paths from the report to the asset folder. Include:
   - A generated paper structure framework diagram, preferably Mermaid.
   - All model/module/architecture figures related to the paper's claimed innovations when the original paper contains them. Use extracted original images if available; otherwise create clean Mermaid reconstructions and clearly label them as reconstructions.
6. Convert relevant extracted CSV tables to Markdown tables and embed them inside the effectiveness-evidence section, next to the explanation that uses them.
7. Verify the report references existing image files and that every major figure/table discussed is aligned with the surrounding claim in the paper.

## Extraction Notes

- Prefer the bundled extractor before ad hoc PDF parsing. It records page numbers, bounding boxes, captions, and nearest figure/table relationships.
- If `PyMuPDF` or `pdfplumber` is unavailable, install or use the existing PDF skill/tooling. Do not fabricate figure/table details from memory.
- For scanned PDFs, perform OCR only if the local environment supports it; otherwise explain the limitation and rely on visible figures plus any extractable metadata.
- When choosing innovation model/module diagrams, search captions and nearby text for terms such as `model`, `architecture`, `framework`, `module`, `overview`, `pipeline`, `method`, `network`, and equivalent Chinese terms for model, framework, structure, module, method, process, and network.
- When a module or figure is based on prior work, mark it as not original and cite the paper reference id used by the authors, for example `non-original, cited by authors as [35]`. Determine this from nearby method text, captions, and reference mentions. If unclear, write `source unclear in the paper` rather than guessing.
- When inserting experiment tables, prefer extracted CSV files from `tables/`. If extraction merged columns poorly, reconstruct the table from the PDF text, keeping the original table number, caption, page, metrics, and values.

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
