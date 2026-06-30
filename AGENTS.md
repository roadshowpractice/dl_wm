# AGENTS.md — dl_wm

Documentation for AI coding agents (Claude Code, Codex, Cursor, etc.) working in this repo.

---

## What this project does

dl_wm downloads social media video (YouTube, Instagram, Facebook) and runs a
post-processing pipeline: watermarking, transcription, subtitle burn, clip extraction,
and final film assembly.

Primary entry point: `python bin/call_router.py "<url>"` routes a URL through the
full workflow. Each stage can also be run independently.

---

## Directory layout

    bin/            Entry-point scripts — run directly, never imported as a module
    conf/           JSON config files (app_config.json, config.json) — no secrets committed
    downloaders/    Per-vendor download logic (youtube.py, instagram.py, facebook.py)
    igp/            Instagram graph probe utilities (separate from main downloader)
    lib/            Shared library modules — NOT an installable package (no __init__.py)
    pipeline/       Staged clip pipeline: extract -> intro -> build_manifest -> render
    tests/          All pytest tests live here
    fonts/          Bundled fonts for watermark and intro card rendering
    examples/       Example manifests for reference
    inputs/         Input JSONL/JSON clip definitions
    outputs/        Runtime output (gitignored)
    metadata/       Downloaded metadata cache (gitignored)
    logs/           Runtime logs (gitignored)

---

## Setup

    conda env create -f environment.yml
    conda activate dl_wm

---

## Running tests

    pytest tests/

Tests use monkeypatching and tmp_path fixtures. No network calls, no real downloads,
no file I/O outside tmp_path.

---

## Architecture and data flow

A URL enters the system and moves through these stages:

### 1. URL -> vendor detection   (lib/vendor_router.py)

    detect_vendor()            maps hostname/path to "youtube", "instagram", or "facebook"
    extract_vendor_id()        pulls the platform-native media ID from the URL
    canonicalize_vendor_url()  normalizes YouTube shorts/mobile URLs to watch?v= form
    metadata_filename()        derives the canonical metadata filename: vendor__id.json

vendor_router.py is pure functions with no I/O or side effects.

### 2. Vendor + ID -> download   (downloaders/<vendor>.py)

Each downloader is independent. YouTube uses yt-dlp with a strategy chain declared
in conf/app_config.json under "youtube_download.strategies". Strategies are data,
not code — the downloader iterates them in order and stops on first success.

YouTube-specific retry/repair behavior:
- web_cookie_file strategy: tries a saved cookie file; on bot-detection error,
  regenerates the cookie via browser extraction, then retries once.
- android_fallback strategy: bypasses cookie entirely via extractor_arg.
- The full attempt chain is recorded in the return dict under "attempts".

Cookie file paths come from conf/ and are gitignored. Never commit them.

### 3. Download -> metadata file   (metadata/)

Raw yt-dlp or API metadata is written to metadata/raw/<vendor>__<id>.json, then
compacted by lib/metadata_compactor.py into a leaner record at metadata/<vendor>__<id>.json.
An index is maintained at metadata/index.jsonl.

### 4. Metadata -> watermarked video   (lib/watermarker2.py)

Burns a source label onto the video using ffmpeg and the bundled Inter fonts.
Label format: "Uploader | Date | Title" (long titles are truncated safely).
Output lands in outputs/<datestamp>/.

### 5. Watermarked video -> transcription   (bin/transcribe_media.py, optional)

Calls the transcription service configured under "transcription" in conf/app_config.json.
Writes a .txt transcript and optionally a .whisper.json with word-level timestamps
beside the video file.

### 6. Whisper JSON -> clip JSONL   (bin/clip_from_whisper.py)

Slices clip definitions from word-level timestamps. Writes clips.jsonl with
repo-root-relative paths. When word timestamps are unavailable, falls back to
native transcript segments. The old equal-time shortening path (short_srt.py) is
disabled because it produced synthetic timings.

### 7. Clip JSONL -> staged pipeline   (pipeline/)

Four intentionally separate stages so outputs can be inspected or edited between steps:

    pipeline/extract.py         cuts raw clips from the watermarked video
    pipeline/intro.py           prepends per-clip title cards (uses fonts/)
    pipeline/build_manifest.py  assembles final_manifest.json  <-- human review point
    pipeline/render.py          concatenates clips into final_film.mp4

Do not auto-skip the build_manifest stage. It is a deliberate human checkpoint.

---

## Module relationships

    lib/vendor_router.py        pure URL-parsing functions; no I/O; imported widely
    lib/teton_utils.py          loads conf/app_config.json and conf/config.json;
                                also contains legacy download helpers (download_video,
                                extract_metadata) that predate the downloaders/ package
    lib/watermarker2.py         ffmpeg wrapper for watermark burn
    lib/metadata_compactor.py   trims raw yt-dlp metadata to a compact record
    lib/downloader5.py          low-level download helpers
    lib/caller_lib.py           shared argv/logging/task-update machinery for bin/call_*.py
    lib/tasks_lib.py            task queue and default task loading from conf/default_tasks.json
    lib/transcription_caller.py calls external transcription API; also owns update_task_for_media
    lib/utilities1.py           general utilities

    downloaders/youtube.py      imports lib/vendor_router, lib/teton_utils,
                                lib/metadata_compactor
    downloaders/instagram.py    imports lib/vendor_router, downloaders/cookies.py
    downloaders/facebook.py     imports lib/vendor_router, downloaders/cookies.py
    downloaders/cookies.py      cookie file loading shared by instagram and facebook

    pipeline/                   self-contained; reads/writes files, does not import lib/

Note: lib/ modules are imported without a package prefix (e.g. "from teton_utils import ...")
because bin/ and lib/ scripts run with lib/ on sys.path. This is why lib/ has no __init__.py.

---

## Config files

    conf/config.json        platform-specific output directories (Linux vs macOS keys)
                            loaded by lib/teton_utils.load_config()

    conf/app_config.json    app-level settings: download strategies, transcription
                            service, metadata paths, logging, subtitle burn options
                            loaded by lib/teton_utils.load_app_config()
                            (env vars and ~ are expanded automatically)

Always load config through teton_utils — do not open these files directly in new code.

---

## Key conventions

- vendor_router.py is the single source of truth for URL->vendor mapping.
  Do not duplicate vendor detection logic anywhere else.

- Download strategies are declared as data in app_config.json, not as if-branches
  in downloader code. Add a new strategy to the config; do not add code branches.

- All tests belong in tests/. Four test_*.py files exist in lib/ from before this
  rule was established — do not add more there.

- outputs/, metadata/, and logs/ are runtime directories. Never assume their
  contents exist or are committed.

- conf/*.cookies.txt files are secrets. They are gitignored. Never commit them.

---

## What to understand before touching

    lib/watermarker2.py         ffmpeg filter chain is tuned; visual regressions are silent
    downloaders/youtube.py      strategy/retry/repair chain has ordering dependencies;
                                read the tests in tests/test_youtube_downloader.py first
    pipeline/build_manifest.py  output is a human review checkpoint; do not skip it
    conf/app_config.json        download strategies, cookie paths, and transcription
                                config are tightly coupled to downloader behavior
