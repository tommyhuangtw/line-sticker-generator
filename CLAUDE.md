# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Turns photos into a 12-sticker set formatted to LINE sticker specs, via AI image
generation. Two entry points share the same core: a Flask web UI (`app.py`) and a
CLI (`generate_stickers.py`). User-facing text and docstrings are in Traditional
Chinese.

## Commands

```bash
pip install -r requirements.txt      # install deps
cp .env.example .env                 # then fill in your own API keys

python app.py                        # web UI at http://localhost:8080 (debug=True)

# CLI: generate a full set (pet / dog / kid modes)
python generate_stickers.py --pet --photos <url1> <url2>
python generate_stickers.py --kid --text-only
python generate_stickers.py --pet --phrases "汪汪,肚子餓,想睡覺"

# CLI: crop an already-generated grid image (skip generation)
python crop_stickers.py <grid.png> --remove-bg          # transparent bg (for store upload)
python crop_stickers.py <grid.png> --keep-bg            # keep background
python generate_stickers.py --pet --skip-generate <grid.png>
```

There are no tests, linters, or build steps. `env/` is a committed virtualenv —
ignore it; use your own.

## Architecture

`generate_stickers.py` is the core library; both `app.py` and `crop_stickers.py`
import from it. There is no separate package — it's a flat set of module-level
functions and constant dicts.

**Two-phase pipeline:**
1. **Generate** — build a prompt (`build_prompt`), submit an async task to an image
   provider, poll until a grid image (4 cols × 3 rows = 12 stickers on a green
   screen) is ready.
2. **Crop** (`process_grid_image`) — detect the grid, slice into 12 cells, remove
   the background, fit to LINE dimensions, and emit `main.png` (240×240) and
   `tab.png` (96×74).

**Image providers (KIE AI primary, fal.ai fallback):** Both implement the same
create-task / check-status shape (`create_task_*` / `check_task_status` for KIE;
`fal_*` for fal.ai). `fal_check_task_status` normalizes fal's response into KIE's
`{"state": ..., "resultJson": ...}` format so downstream code is provider-agnostic.
Fallback happens in two places in `app.py`: at submit time (`/api/generate` catches
a KIE `StickerError` and retries on fal) and at poll time (`/api/status` sees KIE
`state == "fail"` and creates a fresh fal task, returning `state: "retry"` with a
`newTaskId` for the frontend to switch to). The chosen provider is persisted in each
task's `metadata.json` so status checks route correctly.

**Cloudinary** (`upload_to_cloudinary` in `app.py`) is required for image-to-image:
the providers need a public image URL, so uploaded photos go to Cloudinary first.
`_optimize_cloudinary_url` rewrites the URL to serve a compressed JPG (≤2048px) —
oversized inputs cause KIE 500s.

**OpenRouter** (`generate_phrases_with_ai`) is optional; used only by `character`
mode to AI-generate the 12 sticker phrases from a personality description.

### Modes and phrases

Four modes — `pet`, `dog`, `kid`, `character` — selected in the UI. Note
`build_prompt` collapses them to three prompt templates: `dog`→`pet`, and only
`character` stays distinct (`prompt_mode` logic in `app.py:220` and `:325`). Default
phrases live in `*_PHRASE_STYLES` dicts (each mode has multiple named styles like
撒嬌/日常實用/傲嬌), aggregated into `ALL_PHRASE_STYLES`. There's also an orthogonal
`AUDIENCES` dict (上班族, 學生, 情侶, 工程師, …) supplying themed phrase sets and a
tone line injected into the prompt. The `PET_PHRASES` / `KID_PHRASES` etc. are
backward-compat aliases pointing at the 撒嬌 style.

### Background removal

`remove_bg_simple` is the most intricate part — a border flood-fill (so interior
shadows are preserved) tuned for the `#00B140` green screen, followed by multi-pass
green-spill removal, enclosed-green-pocket cleanup, edge alpha smoothing, green
despill, and finally `_add_outline` (a dark stroke so white text stays readable on
any chat background). `detect_grid` is hierarchical: it finds row gaps globally,
then detects column gaps per-row independently, so misaligned columns don't get
clipped. Crop and bg-removal run at full resolution; downscaling to LINE size
(`fit_to_line_size`, even dimensions) happens last for quality.

### Output layout

Each generation lives in `output/<task_id>/` containing `metadata.json`,
`grid_raw.png`, `raw/NN.png` (crops before bg removal, kept for iteration),
`stickers/NN.png` (final), `main.png`, `tab.png`. `examples/` holds bundled
read-only example sets shown in the dashboard gallery — `resolve_task_dir` checks
`output/` then falls back to `examples/`, and `is_example` entries always sort last
and can't be deleted/regenerated.

### Frontend

`templates/index.html` is a single ~800-line file (vanilla JS, no build) driving the
whole UI against the `/api/*` JSON routes in `app.py`. It polls `/api/status/<id>`
and handles the `retry` → switch-task flow.

## Conventions

- All errors flow through the `StickerError` exception; API routes catch it and
  return `{"error": ...}` with a 500. Raise `StickerError` (not bare exceptions) for
  user-facing failures.
- HTTP is done with stdlib `urllib.request` throughout (no `requests`), even though
  `requests` is in `requirements.txt`.
- Default grid is 3 rows × 4 cols = 12 stickers; LINE size caps are
  `STICKER_MAX_W/H` (370×320), `MAIN_IMAGE_SIZE` (240×240), `TAB_IMAGE_SIZE` (96×74).
- API keys are read from env at import time (`KIE_API_KEY`, `FAL_API_KEY`, etc.) —
  changing `.env` requires a restart.
