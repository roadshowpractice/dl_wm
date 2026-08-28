# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup and commands

```bash
# create/update the conda env (Python 3.10, ffmpeg, torch/cpu, deno, yt-dlp, moviepy, whisper via setup_env.sh)
conda env create -f environment.yml      # first time
conda env update -f environment.yml --prune   # refresh
conda activate dl_wm                     # or: cad  (alias set up by setup_env.sh / README)

# full env setup including whisper (which environment.yml intentionally omits)
./setup_env.sh

# sanity-check the environment (imports, writable outputs/metadata dirs, ffmpeg on PATH)
python bin/doctor.py
```

Run the whole per-URL pipeline (download + whatever tasks are enabled in `conf/default_tasks.json`):

```bash
python bin/call_router.py "<media-url>"
python bin/call_router.py "<media-url>" --dry-run
```

Add a URL / download only, without running follow-up tasks:

```bash
python bin/call_download.py "<media-url>"
```

Manual watermark of a local file with no metadata JSON:

```bash
bin/watermark_manual.sh "INPUT.mp4" "OUTPUT.mp4" "Uploader Name" "2026-04-26" "Video title"
```

Clip/compilation pipeline (separate from the per-URL ingestion pipeline above — see Architecture):

```bash
python bin/clip_from_whisper.py outputs/<run>/<file>.whisper.json   # -> outputs/<run>/clips/clips.jsonl
python -m pipeline.extract --source-video outputs/<run>/<file>_watermarked.mp4 --clips-jsonl inputs/<clips>.jsonl --output-dir clips --manifest-out clips_manifest.json
python -m pipeline.intro --manifest clips_manifest.json --output-dir clips_with_intro --manifest-out clips_with_intro_manifest.json --font fonts/Inter-Bold.otf --intro-seconds 2.0
python -m pipeline.build_manifest --clips-manifest clips_manifest.json --title-image outputs/<run>/monarch.png --output final_manifest.json   # hand-edit before render
python -m pipeline.render --manifest final_manifest.json --output final_film.mp4 --black-seconds 0.5
```

### Tests

No pytest.ini/conftest.py — plain `pytest` discovery from repo root. Test files live in `tests/`, `lib/test_*.py`, and `igp`-adjacent tests under `tests/`.

```bash
python -m pytest                                  # whole suite
python -m pytest tests/test_igp_capture_range.py   # single file
python -m pytest tests/test_igp_capture_range.py::test_name -v   # single test
```

`bin/test_tbfrescue_pipeline_live.py` and `bin/test_tbfrescue_vimeo_pipeline_e2e.py` are **not** part of the pytest suite despite the name — they're manually-run, non-mocked end-to-end scripts that hit live network/vendor sites and write real files under `outputs/`. Run them directly with `python bin/<name>.py`, not via pytest.

## Architecture

**Per-URL ingestion pipeline** (`bin/call_router.py` is the entrypoint):

- `lib/vendor_router.py` detects the vendor (youtube/instagram/facebook/vimeo) from a URL and extracts a `vendor_id`; `metadata/{vendor}__{vendor_id}.json` is the single source of truth for that item's pipeline state.
- `call_router.py` looks up existing metadata for the (canonicalized) URL via `lib/tasks_lib.find_url_json` — checks `metadata/index.jsonl` first, falls back to scanning `metadata/*.json` and repairs the index. If `perform_download` isn't already done, it shells out to `bin/call_download.py`, which dispatches to `downloaders/{youtube,instagram,facebook,vimeo}.py`.
- Each downloader module writes the video, a compact `metadata/{vendor}__{id}.json`, and a gzip'd raw yt-dlp info dict under `metadata/raw/`.
- Remaining tasks come from `conf/default_tasks.json` (`perform_download`, `apply_watermark`, `extract_audio`, `generate_srt`, `burn_srt`, `post_processed`) and are recorded per-item in that item's metadata under `default_tasks`. Each value is `true` (enabled, not yet run), `false` (skip), or a string (the completed output path — treated as done).
- `call_router.execute_tasks` runs each enabled-and-not-yet-done task as its own **subprocess**, via a fixed `TASK_DISPATCH` map to a `bin/call_*.py` script (`call_watermark.py`, `call_extract_audio.py`, `call_captions.py`, `call_burn_srt.py`, `convert_screenshots.py`). Tasks are isolated processes rather than in-process function calls, so heavy per-task deps (whisper, moviepy) don't need to be imported by the router itself, and a failed task doesn't take down the others.
- Per-run artifacts land in `outputs/<YYYY-MM-DD>/<vendor>__<vendor_id>/`.
- Config: `conf/app_config.json` holds task-level settings (watermark styling, transcription caller config, subtitle burn/ASS styling, per-vendor download options incl. `vimeo_download.impersonate` for curl_cffi TLS impersonation) and the cookie hierarchy per vendor. `conf/config.json`'s per-OS `base_dir`/`output_dir`/`metadata_dir` blocks are **not read by any code path** (paths are resolved relative to the repo root via `resolve_repo_path`/`load_config` in `lib/teton_utils.py`) — don't trust that file's `base_dir` for where the repo or its outputs actually live. Its per-OS `youtube_cookie_files` list **is** read, though (`downloaders/youtube.py`'s `web_cookie_file` strategy, via `_load_platform_config`/`_resolve_cookie_candidates`) — on Linux the first candidate is `~/.config/dl_wm/cookies/youtube.cookies.txt`.
  - **2026-08-27**: that file now exists with a real, logged-in YouTube/Google session — exported via `yt-dlp --cookies-from-browser "chrome:$HOME/.config/google-chrome/Default"` from John's regular Chrome profile (logged in as `john_daystrom` / `daystromjohn@gmail.com`, see `/mnt/windows/SharedIdent/identities.json`). This is what fixed the HTTP 403 on video-data download that the `web_browser_firefox` strategy couldn't get past (metadata extraction worked fine via Firefox cookies; only the actual media fetch 403'd — see `tbfrescue-mirror/findings/2026-08-27-youtube-fetch-attempt.md` for the failure and root-cause writeup). Not the isolated `google-chrome-perlgonzales` Chrome profile used for Instagram — that one has no working login, just an anonymous session (10 cookies, no auth tokens).

**Clip/compilation pipeline** (`pipeline/` package: `extract.py` → `intro.py` → `build_manifest.py` → `render.py`) is a separate, manually-run downstream flow that turns one watermarked long-form video plus a clips JSONL (often produced from Whisper word-timestamp data by `bin/clip_from_whisper.py`) into a final compiled film. Each stage writes its own manifest so output can be inspected/hand-edited between steps (`final_manifest.json` in particular is meant to be reviewed before the final render).

**`igp/`** is an independent subsystem: headless-browser capture and extraction of a *single* Instagram post (`/p/...`) via GraphQL response sniffing (`igp/capture.py`, `igp/extract.py`, `igp/cookies.py`, `igp/select.py`) — separate from, and not used by, the yt-dlp-based `downloaders/instagram.py` reel downloader.

**Shared libs**: `lib/teton_utils.py` and `lib/tasks_lib.py` hold cross-cutting concerns — config loading, logging init, repo-relative path resolution, and all metadata read/write/index helpers (`find_url_json`, `upsert_metadata_index`, `update_task_output_path`, `get_task_states`).
