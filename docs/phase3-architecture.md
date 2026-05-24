# Phase 3: HTML Preview And Conversational JSON Hot Updates

## Goal

Render uploaded documents as animated HTML previews using pure JavaScript, then support conversational edits by sending the user prompt and current Slide-JSON to a Python backend that returns an updated JSON document.

Phase 3 does not compile PPTX. It proves that ordinary document uploads can be converted into Slide-JSON and drive a live, editable preview.

## Files

```text
preview/
  index.html
  styles.css
  app.js
  sample_slide_deck.json
scripts/
  serve_preview.py
```

## Runtime

Start a local preview server:

```bash
python scripts/serve_preview.py
```

Then open:

```text
http://127.0.0.1:8765/
```

To preview a generated deck, pass it explicitly:

```bash
python scripts/serve_preview.py --deck paper_slide_deck.json
```

The browser upload control accepts:

- `.pdf`
- `.docx`
- `.pptx`
- `.md`
- `.markdown`
- `.txt`
- `.json`

PDF files run through Phase 1 multimodal extraction and Phase 2 Slide-JSON generation. DOCX, PPTX, Markdown, and TXT files use a lightweight Python text extractor before Phase 2 generation. JSON files are treated as Slide-JSON when they already match the schema; otherwise they are converted as text-like structured input.

## Frontend Contract

The frontend is intentionally buildless and TypeScript-free:

- `index.html` defines the app shell.
- `styles.css` defines responsive 16:9 slides and CSS animation classes.
- `app.js` uploads source documents, receives generated Slide-JSON, validates the minimal shape, renders slides, handles navigation, imports JSON files for debugging, edits raw JSON, and sends conversational update requests.

The renderer is data-driven:

1. Read `deck.theme` for colors and font.
2. Render one active slide at a time.
3. Convert bullet animation metadata into CSS classes and delays.
4. Convert visual layout values from normalized coordinates into absolute percentages.
5. Re-render after JSON edits or backend updates.

## Conversational Update Contract

Frontend request:

```http
POST /api/slide-json/update
Content-Type: application/json

{
  "prompt": "把第二页标题改得更学术一点",
  "slide_json": { "...": "current deck" }
}
```

Backend response:

```json
{
  "slide_json": { "...": "updated deck" },
  "mode": "llm"
}
```

If no API key/model is configured, the Python server returns a deterministic local update that records the user prompt in speaker notes. This keeps the preview loop testable offline while preserving the same HTTP contract.

## Document Upload Contract

Frontend request:

```http
POST /api/documents/upload
Content-Type: multipart/form-data

document=<uploaded file>
```

Backend response:

```json
{
  "filename": "paper.pdf",
  "run_id": "paper_ab12cd34ef",
  "manifest_url": "/generated/paper_ab12cd34ef/manifest/manifest.json",
  "slide_json_url": "/generated/paper_ab12cd34ef/slide_deck.json",
  "asset_base_url": "/generated/paper_ab12cd34ef/manifest/",
  "slides": 3,
  "slide_json": { "...": "generated deck" }
}
```

Uploaded files and generated intermediates are stored under `_preview_uploads/`, which is ignored by git.

## Provider Configuration

Normal LLM mode uses an OpenAI-compatible chat completions endpoint:

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_BASE_URL`, defaults to `https://api.openai.com/v1`

## Phase Boundary

Phase 3 owns HTML preview and JSON hot updates only.

Phase 4 will read the same Slide-JSON and compile native `.pptx` output.
