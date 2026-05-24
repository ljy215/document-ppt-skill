# Agent Preview Brief

Use this brief when the user asks the skill to generate or revise an HTML preview using Codex or Claude Code capability.

## Role

You are the design and implementation agent. Do not ask the browser page to call an LLM. Instead, edit the preview files yourself.

## Inputs

- `manifest.json`
- `slide_deck.json`
- extracted image/table assets
- user's style or content instructions

## Output

An editable static preview bundle:

```text
preview_runs/<name>/
  index.html
  styles.css
  app.js
  slide_deck.json
```

## Revision Examples

- "改成深色科技风": adjust colors, typography, spacing, animation tone, and contrast in `styles.css`.
- "更适合论文答辩": make layout academic, reduce decorative elements, add evidence/source cues.
- "图表更大": adjust visual layout mapping in `app.js` or `slide_deck.json`.
- "精简文字": edit `slide_deck.json` bullets and keep source refs.

## Rules

- Frontend code must be pure JavaScript.
- Do not require an API key for HTML preview generation.
- Do not place all styling decisions in generic presets only; tailor the result to the document and user request.
- Verify with the browser after meaningful visual changes.
