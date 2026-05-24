# Phase 2: LLM Prompting And Slide-JSON Generation

## Goal

Convert the Phase 1 multimodal `manifest.json` into a strict Slide-JSON intermediate state. The LLM must not directly output Markdown, HTML, or PPTX.

Phase 2 is the contract layer between document understanding and rendering/export. Frontend preview and PPTX compilation should both consume the same Slide-JSON.

## Inputs And Outputs

Input:

```text
<paper-stem>_multimodal/manifest.json
```

Output:

```text
<paper-stem>_slide_deck.json
```

Command:

```bash
python scripts/generate_slide_json.py "<paper-stem>_multimodal/manifest.json" --output "<paper-stem>_slide_deck.json"
```

Offline structure test:

```bash
conda run -n ppt python scripts/generate_slide_json.py "<paper-stem>_multimodal/manifest.json" --output draft_slide_deck.json --dry-run
```

Recommended runtime:

```bash
conda env create -f environment.yml
conda run -n ppt python scripts/extract_multimodal_assets.py "paper.pdf" --output-dir "paper_multimodal"
conda run -n ppt python scripts/generate_slide_json.py "paper_multimodal/manifest.json" --output "paper_slide_deck.json" --dry-run
```

## Slide-JSON Contract

The canonical schema is:

```text
schemas/slide-json.schema.json
```

The deck contains:

- Paper metadata.
- Theme and layout defaults.
- A slide list.
- Each slide contains title, concise bullet items, optional visual assets, speaker notes, and animation intent.
- Each bullet has its own `animation` field.
- Visual assets must reference URLs from Phase 1 `manifest.json`.

## LLM Boundary

The prompt builder sends compact evidence, not the full PDF text:

- Page-level text excerpts.
- Figure/table captions.
- Nearby text snippets for each asset.
- Role hints such as `model_candidate`.
- Source page and asset URL for traceability.

The LLM is instructed to return only valid JSON that matches the schema. The Python layer then:

1. Extracts the JSON payload.
2. Validates required structure.
3. Checks asset URL references against the manifest.
4. Writes the normalized Slide-JSON file.

## Provider Strategy

The generator is provider-light:

- `--dry-run` creates deterministic skeleton slides without calling a model.
- Normal mode calls an OpenAI-compatible chat completions endpoint using only Python standard library HTTP code.
- API configuration is provided by environment variables or CLI flags:
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `OPENAI_MODEL`

This keeps Phase 2 usable with OpenAI-compatible gateways while avoiding a hard dependency on a Python SDK.

## Phase Boundary

Phase 2 does not render HTML and does not export PPTX. It only creates and validates Slide-JSON.

Phase 3 will load the Slide-JSON in a pure JavaScript renderer and apply conversational JSON patches.
