# Agent HTML Preview Workflow

## Intent

The browser preview is useful for runtime inspection, but it should not be treated as the AI design engine.

When this skill is running inside Codex or Claude Code, the agent itself should spend its normal model budget to create and revise the HTML preview files. The local web page does not need `OPENAI_API_KEY` for design edits.

## Workflow

1. Extract the source document into `manifest.json`.
2. Generate or draft `slide_deck.json`.
3. Create an editable HTML preview bundle:

```bash
python scripts/create_agent_preview_bundle.py slide_deck.json --output-dir preview_runs/paper_preview
```

4. The agent reads the generated files and modifies them directly according to the user's style request:
   - `preview_runs/paper_preview/index.html`
   - `preview_runs/paper_preview/styles.css`
   - `preview_runs/paper_preview/app.js`
   - `preview_runs/paper_preview/slide_deck.json`

5. For follow-up requests such as "改成深色科技风", "更像答辩 PPT", "减少文字、突出图表", or "改成绿色清新风格", the agent edits these files again and verifies the result in the browser.

## Boundary

The in-page chat box is only a runtime API client. It cannot automatically use Codex or Claude Code quota by itself.

Conversational design edits should happen in the Codex/Claude Code chat. The agent then updates the generated HTML/CSS/JS preview artifacts.

## Quality Requirements

- Use plain JavaScript only.
- Keep the generated bundle static and portable.
- Preserve Slide-JSON as the source of content truth.
- Use extracted figures and tables when they exist.
- After style edits, verify the HTML preview in the browser.
