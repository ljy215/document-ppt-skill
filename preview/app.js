(function () {
  "use strict";

  var state = {
    deck: null,
    currentSlide: 0,
    basePath: "./"
  };

  var els = {};

  function $(id) {
    return document.getElementById(id);
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function escapeText(value) {
    return String(value == null ? "" : value);
  }

  function animationClass(animation) {
    var type = animation && animation.type ? animation.type : "none";
    return "anim anim-" + type;
  }

  function animationStyle(animation) {
    var anim = animation || {};
    var duration = Number(anim.duration_ms || 0);
    var delay = Number(anim.delay_ms || 0);
    var order = Number(anim.order || 0);
    var totalDelay = delay + Math.max(0, order - 1) * 120;
    var style = "animation-duration:" + duration + "ms;animation-delay:" + totalDelay + "ms;";
    if (anim.direction === "right") {
      style += "--fly-x:24px;";
    }
    if (anim.direction === "up") {
      style += "--fly-x:0;transform:translateY(24px);";
    }
    if (anim.direction === "down") {
      style += "--fly-x:0;transform:translateY(-24px);";
    }
    return style;
  }

  function validateDeck(deck) {
    if (!deck || typeof deck !== "object") {
      throw new Error("Slide-JSON must be an object.");
    }
    if (deck.schema_version !== "document-ppt.slide.v1") {
      throw new Error("Unsupported schema_version: " + deck.schema_version);
    }
    if (!deck.deck || !Array.isArray(deck.slides) || deck.slides.length === 0) {
      throw new Error("Slide-JSON requires deck metadata and at least one slide.");
    }
  }

  function resolveAssetUrl(url) {
    if (!url) {
      return "";
    }
    if (/^(https?:|data:|blob:)/i.test(url)) {
      return url;
    }
    return new URL(url, state.basePath).toString();
  }

  function applyTheme(deck) {
    var theme = (deck.deck && deck.deck.theme) || {};
    var palette = theme.palette || {};
    document.documentElement.style.setProperty("--slide-bg", palette.background || "#F8FAFC");
    document.documentElement.style.setProperty("--slide-fg", palette.foreground || "#111827");
    document.documentElement.style.setProperty("--slide-accent", palette.accent || "#2563EB");
    document.documentElement.style.setProperty("--accent", palette.accent || "#2563EB");
    document.body.style.fontFamily = theme.font_family || "Microsoft YaHei, Segoe UI, Arial, sans-serif";
  }

  function setDeck(deck, basePath) {
    validateDeck(deck);
    state.deck = deck;
    state.basePath = basePath || state.basePath || "./";
    state.currentSlide = clamp(state.currentSlide, 0, deck.slides.length - 1);
    applyTheme(deck);
    els.jsonEditor.value = JSON.stringify(deck, null, 2);
    render();
  }

  function render() {
    if (!state.deck) {
      return;
    }
    var deck = state.deck;
    var slide = deck.slides[state.currentSlide];
    var metaText = deck.deck.title + " · " + deck.slides.length + " slides";
    els.deckMeta.textContent = metaText;
    els.slideCounter.textContent = state.currentSlide + 1 + " / " + deck.slides.length;
    els.speakerNotes.textContent = slide.speaker_notes || "";
    els.stage.replaceChildren(renderSlide(slide, deck));
  }

  function renderSlide(slide, deck) {
    var theme = deck.deck.theme || {};
    var root = document.createElement("article");
    root.className = "slide layout-" + slide.layout;
    root.dataset.aspect = theme.aspect_ratio || "16:9";

    var title = document.createElement("h2");
    title.className = "slide-title" + (slide.layout === "title" ? " main-title" : "");
    title.textContent = escapeText(slide.title);
    root.appendChild(title);

    if (slide.subtitle) {
      var subtitle = document.createElement("p");
      subtitle.className = "slide-subtitle";
      subtitle.textContent = escapeText(slide.subtitle);
      root.appendChild(subtitle);
    }

    if (slide.bullets && slide.bullets.length) {
      root.appendChild(renderBullets(slide.bullets));
    }

    (slide.visuals || []).forEach(function (visual) {
      root.appendChild(renderVisual(visual));
    });

    return root;
  }

  function renderBullets(bullets) {
    var list = document.createElement("ul");
    list.className = "bullet-list";
    bullets.forEach(function (item) {
      var bullet = document.createElement("li");
      bullet.className = "bullet emphasis-" + (item.emphasis || "normal") + " " + animationClass(item.animation);
      bullet.setAttribute("style", animationStyle(item.animation));
      bullet.textContent = escapeText(item.text);
      list.appendChild(bullet);
    });
    return list;
  }

  function renderVisual(visual) {
    var figure = document.createElement("figure");
    var layout = visual.layout || { x: 0.55, y: 0.25, w: 0.36, h: 0.48 };
    figure.className = "visual " + animationClass(visual.animation);
    figure.setAttribute(
      "style",
      [
        "left:" + layout.x * 100 + "%",
        "top:" + layout.y * 100 + "%",
        "width:" + layout.w * 100 + "%",
        "height:" + layout.h * 100 + "%",
        animationStyle(visual.animation)
      ].join(";")
    );

    var img = document.createElement("img");
    img.alt = visual.caption || visual.asset_id || "slide visual";
    img.src = resolveAssetUrl(visual.asset_url);
    img.addEventListener("error", function () {
      var placeholder = document.createElement("div");
      placeholder.className = "visual-placeholder";
      placeholder.textContent = "Missing asset: " + visual.asset_url;
      img.replaceWith(placeholder);
    });
    figure.appendChild(img);

    if (visual.caption) {
      var caption = document.createElement("figcaption");
      caption.textContent = visual.caption;
      figure.appendChild(caption);
    }
    return figure;
  }

  function loadDeckFromUrl(url) {
    return fetch(url)
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Could not load deck: " + response.status);
        }
        return response.json();
      })
      .then(function (deck) {
        setDeck(deck, deckBasePath(url));
        setStatus("Loaded deck.");
      });
  }

  function deckBasePath(url) {
    if (url === "/api/slide-json/current") {
      return new URL("/deck-assets/", window.location.href).toString();
    }
    return new URL(url, window.location.href).toString();
  }

  function currentDeckUrl() {
    if (window.PREVIEW_DECK_URL) {
      return window.PREVIEW_DECK_URL;
    }
    var params = new URLSearchParams(window.location.search);
    return params.get("deck") || "/api/slide-json/current";
  }

  function setStatus(message) {
    els.updateStatus.textContent = message || "";
  }

  function applyJsonFromEditor() {
    try {
      var nextDeck = JSON.parse(els.jsonEditor.value);
      setDeck(nextDeck, state.basePath);
      setStatus("JSON applied.");
    } catch (error) {
      setStatus(error.message);
    }
  }

  function readUploadedDeck(file) {
    if (!file) {
      return;
    }
    var reader = new FileReader();
    reader.onload = function () {
      try {
        setDeck(JSON.parse(String(reader.result)), window.location.href);
        setStatus("Loaded " + file.name + ".");
      } catch (error) {
        setStatus(error.message);
      }
    };
    reader.readAsText(file, "utf-8");
  }

  function uploadDocument(file) {
    if (!file) {
      return;
    }
    var form = new FormData();
    form.append("document", file);
    setStatus("Uploading document, extracting content, and generating slides...");
    fetch("/api/documents/upload", {
      method: "POST",
      body: form
    })
      .then(function (response) {
        if (!response.ok) {
          return response.text().then(function (text) {
            throw new Error(text || "Upload failed.");
          });
        }
        return response.json();
      })
      .then(function (payload) {
        var baseUrl = new URL(payload.asset_base_url || "/deck-assets/", window.location.href).toString();
        setDeck(payload.slide_json, baseUrl);
        setStatus("Parsed " + payload.filename + " and rendered " + payload.slides + " slides.");
      })
      .catch(function (error) {
        setStatus(error.message);
      });
  }

  function sendPrompt() {
    if (!state.deck) {
      setStatus("Load a deck first.");
      return;
    }
    var prompt = els.chatPrompt.value.trim();
    if (!prompt) {
      setStatus("Enter a revision prompt.");
      return;
    }
    setStatus("Updating...");
    fetch("/api/slide-json/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: prompt, slide_json: state.deck })
    })
      .then(function (response) {
        if (!response.ok) {
          return response.text().then(function (text) {
            throw new Error(text || "Update failed.");
          });
        }
        return response.json();
      })
      .then(function (payload) {
        setDeck(payload.slide_json, state.basePath);
        setStatus("Updated via " + (payload.mode || "backend") + ".");
      })
      .catch(function (error) {
        setStatus(error.message);
      });
  }

  function exportPptx() {
    if (!state.deck) {
      setStatus("Load a deck first.");
      return;
    }
    setStatus("Exporting PPTX...");
    fetch("/api/pptx/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slide_json: state.deck })
    })
      .then(function (response) {
        if (!response.ok) {
          return response.text().then(function (text) {
            throw new Error(text || "Export failed.");
          });
        }
        return response.json();
      })
      .then(function (payload) {
        if (!payload.download_url) {
          throw new Error("Export did not return a download URL.");
        }
        setStatus("PPTX exported: " + payload.filename);
        window.location.href = payload.download_url;
      })
      .catch(function (error) {
        setStatus(error.message);
      });
  }

  function bindEvents() {
    els.prevSlide.addEventListener("click", function () {
      if (!state.deck) {
        return;
      }
      state.currentSlide = clamp(state.currentSlide - 1, 0, state.deck.slides.length - 1);
      render();
    });
    els.nextSlide.addEventListener("click", function () {
      if (!state.deck) {
        return;
      }
      state.currentSlide = clamp(state.currentSlide + 1, 0, state.deck.slides.length - 1);
      render();
    });
    els.applyJson.addEventListener("click", applyJsonFromEditor);
    els.documentFile.addEventListener("change", function (event) {
      uploadDocument(event.target.files[0]);
      event.target.value = "";
    });
    els.deckFile.addEventListener("change", function (event) {
      readUploadedDeck(event.target.files[0]);
    });
    els.sendPrompt.addEventListener("click", sendPrompt);
    els.exportPptx.addEventListener("click", exportPptx);
    document.addEventListener("keydown", function (event) {
      if (event.target.tagName === "TEXTAREA") {
        return;
      }
      if (event.key === "ArrowLeft") {
        els.prevSlide.click();
      }
      if (event.key === "ArrowRight") {
        els.nextSlide.click();
      }
    });
  }

  function init() {
    [
      "deckMeta",
      "slideCounter",
      "prevSlide",
      "nextSlide",
      "documentFile",
      "deckFile",
      "jsonEditor",
      "applyJson",
      "exportPptx",
      "stage",
      "speakerNotes",
      "chatPrompt",
      "sendPrompt",
      "updateStatus"
    ].forEach(function (id) {
      els[id] = $(id);
    });
    bindEvents();
    loadDeckFromUrl(currentDeckUrl()).catch(function () {
      loadDeckFromUrl("./sample_slide_deck.json").catch(function (error) {
        setStatus(error.message);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
