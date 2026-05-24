# Phase 4: PPTX Compilation Engine

## Goal

Compile `document-ppt.slide.v1` Slide-JSON into a native `.pptx` file.

The compiler reads the same intermediate state used by the HTML preview, so the preview and exported deck stay aligned.

## Command

```bash
python scripts/compile_pptx.py slide_deck.json --output deck.pptx
```

## Supported Mapping

- `deck.theme.aspect_ratio` -> PowerPoint page size.
- `deck.theme.palette` -> slide background, foreground, and accent colors.
- `slide.title` and `subtitle` -> native text boxes.
- `slide.bullets` -> native bullet text boxes.
- `visual.asset_url` + normalized layout -> native pictures.
- `speaker_notes` and animation metadata -> speaker notes text.
- `slide.transition` -> basic native slide transition XML when supported by the PowerPoint client.

## Animation Boundary

The current Python backend uses `python-pptx`, which does not expose a stable public API for per-shape entrance animations. To avoid generating corrupt PPTX files, the compiler preserves animation intent in speaker notes and applies slide-level transitions. A later implementation can add direct OOXML timing-tree generation or switch to an engine with a supported animation API.

## Phase Boundary

Phase 4 exports native `.pptx`. It does not perform document extraction or LLM summarization.
