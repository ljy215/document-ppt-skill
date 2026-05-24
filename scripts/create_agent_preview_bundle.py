#!/usr/bin/env python3
"""Create an agent-authored HTML-PPT preview bundle from Slide-JSON."""

from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_slide_json(deck: dict[str, Any]) -> None:
    if deck.get("schema_version") != "document-ppt.slide.v1":
        raise ValueError("schema_version must be document-ppt.slide.v1")
    if not isinstance(deck.get("slides"), list) or not deck["slides"]:
        raise ValueError("slides must be a non-empty array")


def text(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def resolve_asset(deck_path: Path, deck: dict[str, Any], asset_url: str) -> Path:
    raw = Path(asset_url)
    if raw.is_absolute():
        return raw
    source_manifest = deck.get("deck", {}).get("source_manifest")
    if source_manifest:
        manifest_path = Path(source_manifest)
        if not manifest_path.is_absolute():
            manifest_path = (deck_path.parent / manifest_path).resolve()
        if manifest_path.name == "manifest.json":
            manifest_path = manifest_path.parent
        candidate = manifest_path / raw
        if candidate.exists():
            return candidate
    return (deck_path.parent / raw).resolve()


def copy_visual_assets(deck_path: Path, deck: dict[str, Any], output_dir: Path) -> None:
    copied: set[str] = set()
    for slide in deck.get("slides", []):
        for visual in slide.get("visuals", []):
            asset_url = visual.get("asset_url")
            if not asset_url or asset_url in copied or "://" in asset_url or asset_url.startswith("data:"):
                continue
            source = resolve_asset(deck_path, deck, asset_url)
            if not source.exists():
                continue
            destination = output_dir / asset_url
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            copied.add(asset_url)


def animation_attrs(item: dict[str, Any]) -> str:
    animation = item.get("animation") or {}
    return (
        f' data-anim="{text(animation.get("type", "fade-in"))}"'
        f' style="--order:{int(animation.get("order") or 1)};'
        f'--duration:{int(animation.get("duration_ms") or 450)}ms;'
        f'--delay:{int(animation.get("delay_ms") or 0)}ms;"'
    )


def render_visual(visual: dict[str, Any]) -> str:
    layout = visual.get("layout") or {"x": 0.55, "y": 0.24, "w": 0.36, "h": 0.48}
    animation = visual.get("animation") or {}
    style = (
        f"left:{float(layout.get('x', 0.55)) * 100:.3f}%;"
        f"top:{float(layout.get('y', 0.24)) * 100:.3f}%;"
        f"width:{float(layout.get('w', 0.36)) * 100:.3f}%;"
        f"height:{float(layout.get('h', 0.48)) * 100:.3f}%;"
        f"--order:{int(animation.get('order') or 1)};"
        f"--duration:{int(animation.get('duration_ms') or 450)}ms;"
        f"--delay:{int(animation.get('delay_ms') or 0)}ms;"
    )
    caption = visual.get("caption") or ""
    return f"""
      <figure class="visual" data-anim="{text(animation.get("type", "zoom-in"))}" style="{style}">
        <img src="{text(visual.get("asset_url"))}" alt="{text(caption or visual.get("asset_id") or "visual")}">
        <figcaption>{text(caption)}</figcaption>
      </figure>"""


def render_slide(slide: dict[str, Any], index: int) -> str:
    subtitle = f'<p class="slide-subtitle">{text(slide.get("subtitle"))}</p>' if slide.get("subtitle") else ""
    bullets = "\n".join(
        f'<li class="bullet emphasis-{text(bullet.get("emphasis", "normal"))}"{animation_attrs(bullet)}>{text(bullet.get("text"))}</li>'
        for bullet in slide.get("bullets", [])
    )
    bullet_block = f'<ul class="bullet-list">{bullets}</ul>' if bullets else ""
    visuals = "\n".join(render_visual(visual) for visual in slide.get("visuals", []))
    notes = text(slide.get("speaker_notes", ""))
    return f"""
    <section class="slide layout-{text(slide.get("layout", "bullets"))}" data-slide="{index}" data-notes="{notes}">
      <div class="slide-index">{index + 1:02d}</div>
      <h2 class="slide-title">{text(slide.get("title"))}</h2>
      {subtitle}
      {bullet_block}
      {visuals}
    </section>"""


def write_index(output_dir: Path, deck: dict[str, Any]) -> None:
    deck_json = json.dumps(deck, ensure_ascii=False)
    title = text(deck.get("deck", {}).get("title") or "ToPPT")
    slides = "\n".join(render_slide(slide, index) for index, slide in enumerate(deck["slides"]))
    html_text = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <link rel="stylesheet" href="./styles.css">
  </head>
  <body>
    <script>window.TOPPT_DECK = {deck_json};</script>
    <main class="deck-shell">
      <aside class="deck-toolbar">
        <div class="brand">
          <span class="brand-mark">P</span>
          <div>
            <h1>{title}</h1>
            <p id="deckStatus">Ready</p>
          </div>
        </div>
        <div class="nav-row">
          <button id="prevSlide" type="button" title="Previous slide">&larr;</button>
          <span id="slideCounter">1 / {len(deck["slides"])}</span>
          <button id="nextSlide" type="button" title="Next slide">&rarr;</button>
        </div>
        <button id="overviewToggle" type="button">Overview</button>
        <button id="themeToggle" type="button">Theme</button>
        <button id="presenterToggle" type="button">Presenter</button>
        <button id="exportPptx" class="primary-action" type="button">Export PPTX</button>
      </aside>
      <section id="deckStage" class="deck-stage">
        {slides}
      </section>
      <aside class="agent-panel">
        <label for="chatPrompt">Codex Revision</label>
        <textarea id="chatPrompt" placeholder="例如：改成深色科技风；第 3 页图放大；整体更像答辩 PPT"></textarea>
        <button id="sendPrompt" class="primary-action" type="button">Send To Codex</button>
        <p id="agentStatus">Your message will be queued for Codex to edit this HTML deck.</p>
        <details>
          <summary>Slide-JSON</summary>
          <textarea id="jsonEditor" spellcheck="false"></textarea>
        </details>
      </aside>
    </main>
    <script src="./app.js"></script>
  </body>
</html>
"""
    (output_dir / "index.html").write_text(html_text, encoding="utf-8")


def write_styles(output_dir: Path, deck: dict[str, Any]) -> None:
    palette = ((deck.get("deck") or {}).get("theme") or {}).get("palette") or {}
    bg = palette.get("background", "#F8FAFC")
    fg = palette.get("foreground", "#111827")
    accent = palette.get("accent", "#0F766E")
    css = f""":root {{
  --app-bg: #e8edf3;
  --panel-bg: #ffffff;
  --panel-border: #d5dce8;
  --muted: #64748b;
  --slide-bg: {bg};
  --slide-fg: {fg};
  --accent: {accent};
  --stage-pad: 16px;
}}

* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  min-height: 100vh;
  font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
  background: var(--app-bg);
  color: #111827;
}}
button, textarea {{ font: inherit; }}
button {{
  min-height: 36px;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  background: #fff;
  color: #111827;
  cursor: pointer;
}}
.primary-action {{
  border-color: var(--accent);
  background: var(--accent);
  color: #fff;
  font-weight: 700;
}}
.deck-shell {{
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr) 300px;
  gap: 14px;
  min-height: 100vh;
  padding: var(--stage-pad);
}}
.deck-toolbar, .agent-panel {{
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: var(--panel-bg);
}}
.brand {{ display: flex; gap: 10px; align-items: center; }}
.brand-mark {{
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
  font-weight: 800;
}}
.brand h1 {{ margin: 0; font-size: 15px; line-height: 1.2; }}
.brand p, #agentStatus {{ margin: 3px 0 0; color: var(--muted); font-size: 12px; line-height: 1.45; }}
.nav-row {{ display: grid; grid-template-columns: 38px 1fr 38px; gap: 8px; align-items: center; }}
.nav-row span {{ text-align: center; color: var(--muted); font-size: 13px; }}
.deck-stage {{
  display: grid;
  place-items: center;
  min-width: 0;
  min-height: 0;
}}
.slide {{
  position: relative;
  display: none;
  width: min(100%, calc((100vh - 32px) * 16 / 9));
  aspect-ratio: 16 / 9;
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.16);
  border-radius: 8px;
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--accent) 10%, transparent), transparent 42%),
    var(--slide-bg);
  color: var(--slide-fg);
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.18);
}}
.slide.active {{ display: block; }}
.slide-index {{
  position: absolute;
  right: 4%;
  top: 4%;
  color: color-mix(in srgb, var(--slide-fg) 38%, transparent);
  font-size: 13px;
  font-weight: 700;
}}
.slide-title {{
  position: absolute;
  left: 7%;
  top: 8%;
  right: 7%;
  margin: 0;
  font-size: 34px;
  line-height: 1.16;
  letter-spacing: 0;
}}
.layout-title .slide-title {{ top: 28%; font-size: 44px; right: 10%; }}
.slide-subtitle {{
  position: absolute;
  left: 7%;
  top: 41%;
  right: 8%;
  margin: 0;
  color: color-mix(in srgb, var(--slide-fg) 68%, transparent);
  font-size: 18px;
  line-height: 1.4;
}}
.bullet-list {{
  position: absolute;
  left: 7%;
  top: 25%;
  width: 48%;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 11px;
  list-style: none;
}}
.layout-bullets .bullet-list, .layout-closing .bullet-list {{
  width: 82%;
}}
.layout-visual-left .bullet-list {{
  left: 55%;
  width: 38%;
}}
.bullet {{
  position: relative;
  padding-left: 1.05em;
  font-size: 20px;
  line-height: 1.42;
}}
.bullet::before {{
  content: "";
  position: absolute;
  left: 0;
  top: 0.58em;
  width: 0.42em;
  height: 0.42em;
  border-radius: 50%;
  background: var(--accent);
}}
.emphasis-strong {{ font-weight: 800; }}
.emphasis-risk::before {{ background: #dc2626; }}
.emphasis-evidence::before {{ background: #059669; }}
.visual {{
  position: absolute;
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  gap: 6px;
  margin: 0;
}}
.visual img {{
  width: 100%;
  height: 100%;
  min-height: 0;
  object-fit: contain;
  border: 1px solid rgba(148, 163, 184, 0.45);
  border-radius: 6px;
  background: #fff;
}}
.visual figcaption {{
  color: color-mix(in srgb, var(--slide-fg) 64%, transparent);
  font-size: 11px;
  line-height: 1.25;
}}
[data-anim] {{
  opacity: 0;
  animation-duration: var(--duration, 450ms);
  animation-delay: calc(var(--delay, 0ms) + (var(--order, 1) - 1) * 115ms);
  animation-fill-mode: both;
}}
.active [data-anim="fade-in"] {{ animation-name: fadeIn; }}
.active [data-anim="fly-in"] {{ animation-name: flyIn; }}
.active [data-anim="zoom-in"] {{ animation-name: zoomIn; }}
.active [data-anim="wipe"] {{ animation-name: wipeIn; }}
@keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
@keyframes flyIn {{ from {{ opacity: 0; transform: translateX(24px); }} to {{ opacity: 1; transform: translateX(0); }} }}
@keyframes zoomIn {{ from {{ opacity: 0; transform: scale(0.94); }} to {{ opacity: 1; transform: scale(1); }} }}
@keyframes wipeIn {{ from {{ opacity: 0; clip-path: inset(0 100% 0 0); }} to {{ opacity: 1; clip-path: inset(0 0 0 0); }} }}
.overview .deck-stage {{
  align-content: start;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
  overflow: auto;
}}
.overview .slide {{
  display: block;
  width: 100%;
  box-shadow: none;
  cursor: pointer;
}}
.agent-panel textarea {{
  min-height: 150px;
  resize: vertical;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  padding: 10px;
}}
#jsonEditor {{
  width: 100%;
  min-height: 240px;
  font-family: Consolas, "Courier New", monospace;
  font-size: 12px;
}}
body.theme-dark {{
  --app-bg: #060914;
  --panel-bg: #101827;
  --panel-border: #243244;
  --slide-bg: #08111f;
  --slide-fg: #e5edf7;
  --accent: #38bdf8;
  color: #e5edf7;
}}
body.theme-warm {{
  --app-bg: #f3f4f6;
  --slide-bg: #fffaf0;
  --slide-fg: #1f2937;
  --accent: #b45309;
}}
@media (max-width: 1100px) {{
  .deck-shell {{ grid-template-columns: 1fr; }}
  .slide {{ width: 100%; }}
  .slide-title {{ font-size: 28px; }}
  .layout-title .slide-title {{ font-size: 34px; }}
  .bullet {{ font-size: 17px; }}
}}
"""
    (output_dir / "styles.css").write_text(css, encoding="utf-8")


def write_app(output_dir: Path) -> None:
    js = """(function () {
  "use strict";

  var deck = window.TOPPT_DECK;
  var slides = Array.prototype.slice.call(document.querySelectorAll(".slide"));
  var index = 0;
  var overview = false;
  var themes = ["", "theme-dark", "theme-warm"];
  var themeIndex = 0;
  var els = {
    counter: document.getElementById("slideCounter"),
    status: document.getElementById("deckStatus"),
    agentStatus: document.getElementById("agentStatus"),
    prompt: document.getElementById("chatPrompt"),
    jsonEditor: document.getElementById("jsonEditor")
  };

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function showSlide(next) {
    index = clamp(next, 0, slides.length - 1);
    slides.forEach(function (slide, slideIndex) {
      slide.classList.toggle("active", slideIndex === index);
    });
    els.counter.textContent = index + 1 + " / " + slides.length;
    els.status.textContent = "Slide " + (index + 1);
  }

  function setOverview(enabled) {
    overview = enabled;
    document.body.classList.toggle("overview", overview);
    if (!overview) {
      showSlide(index);
    }
  }

  function cycleTheme() {
    document.body.classList.remove.apply(document.body.classList, themes.filter(Boolean));
    themeIndex = (themeIndex + 1) % themes.length;
    if (themes[themeIndex]) {
      document.body.classList.add(themes[themeIndex]);
    }
  }

  function openPresenter() {
    var slide = slides[index];
    var notes = slide ? slide.dataset.notes || "" : "";
    var popup = window.open("", "toppt-presenter", "width=640,height=520");
    if (!popup) {
      els.status.textContent = "Presenter window was blocked.";
      return;
    }
    popup.document.write("<!doctype html><title>Presenter Notes</title><body style='font-family:Segoe UI,Arial,sans-serif;padding:24px;line-height:1.55'><h1>Slide " + (index + 1) + "</h1><p>" + notes + "</p></body>");
    popup.document.close();
  }

  function queueForCodex() {
    var prompt = els.prompt.value.trim();
    if (!prompt) {
      els.agentStatus.textContent = "Enter a revision request first.";
      return;
    }
    els.agentStatus.textContent = "Sending request to Codex queue...";
    fetch("/api/slide-json/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: prompt, slide_json: deck })
    })
      .then(function (response) {
        if (!response.ok) {
          return response.text().then(function (text) { throw new Error(text || "Request failed."); });
        }
        return response.json();
      })
      .then(function (payload) {
        var request = payload.agent_request || {};
        els.agentStatus.textContent = "Queued for Codex: " + (request.request_id || "latest request");
      })
      .catch(function (error) {
        els.agentStatus.textContent = error.message;
      });
  }

  function exportPptx() {
    els.status.textContent = "Exporting PPTX...";
    fetch("/api/pptx/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slide_json: deck })
    })
      .then(function (response) {
        if (!response.ok) {
          return response.text().then(function (text) { throw new Error(text || "Export failed."); });
        }
        return response.json();
      })
      .then(function (payload) {
        els.status.textContent = "PPTX exported.";
        window.location.href = payload.download_url;
      })
      .catch(function (error) {
        els.status.textContent = error.message;
      });
  }

  document.getElementById("prevSlide").addEventListener("click", function () { showSlide(index - 1); });
  document.getElementById("nextSlide").addEventListener("click", function () { showSlide(index + 1); });
  document.getElementById("overviewToggle").addEventListener("click", function () { setOverview(!overview); });
  document.getElementById("themeToggle").addEventListener("click", cycleTheme);
  document.getElementById("presenterToggle").addEventListener("click", openPresenter);
  document.getElementById("sendPrompt").addEventListener("click", queueForCodex);
  document.getElementById("exportPptx").addEventListener("click", exportPptx);
  slides.forEach(function (slide, slideIndex) {
    slide.addEventListener("click", function () {
      if (overview) {
        setOverview(false);
        showSlide(slideIndex);
      }
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.target.tagName === "TEXTAREA") {
      return;
    }
    if (event.key === "ArrowRight" || event.key === " ") showSlide(index + 1);
    if (event.key === "ArrowLeft") showSlide(index - 1);
    if (event.key.toLowerCase() === "o") setOverview(!overview);
    if (event.key.toLowerCase() === "t") cycleTheme();
    if (event.key.toLowerCase() === "p") openPresenter();
  });

  els.jsonEditor.value = JSON.stringify(deck, null, 2);
  showSlide(0);
})();
"""
    (output_dir / "app.js").write_text(js, encoding="utf-8")


def write_agent_notes(output_dir: Path, deck_path: Path) -> None:
    notes = f"""# Agent Preview Bundle

Source Slide-JSON:

```text
{deck_path}
```

This bundle is an agent-authored HTML-PPT deck, inspired by html-ppt-skill style workflows.

- `index.html` contains concrete slide DOM generated from Slide-JSON.
- `styles.css` controls theme tokens, slide layouts, and animations.
- `app.js` controls navigation, overview, presenter mode, Codex request queueing, and PPTX export.
- `slide_deck.json` remains the export contract for offline PPTX generation.

When the user sends a right-panel request, read `_preview_uploads/agent_requests/latest.json`, update this bundle, then refresh the browser.
"""
    (output_dir / "AGENT_NOTES.md").write_text(notes, encoding="utf-8")


def create_bundle(deck_path: Path, output_dir: Path) -> dict[str, Any]:
    deck = load_json(deck_path)
    validate_slide_json(deck)
    output_dir.mkdir(parents=True, exist_ok=True)
    copy_visual_assets(deck_path, deck, output_dir)
    write_index(output_dir, deck)
    write_styles(output_dir, deck)
    write_app(output_dir)
    shutil.copy2(deck_path, output_dir / "slide_deck.json")
    write_agent_notes(output_dir, deck_path)
    return {
        "output_dir": str(output_dir),
        "entry": str(output_dir / "index.html"),
        "deck": str(output_dir / "slide_deck.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slide_json", help="Path to document-ppt.slide.v1 JSON")
    parser.add_argument("--output-dir", required=True, help="Directory for the editable preview bundle")
    args = parser.parse_args()

    result = create_bundle(Path(args.slide_json).resolve(), Path(args.output_dir).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
