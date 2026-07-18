# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`dl_wm` is a Python workflow for downloading social media (Instagram/Facebook/YouTube), watermarking,
transcribing/captioning, and cutting the result into clips, driven by per-URL JSON metadata files rather
than a database.

## Setup

```bash
conda env create -f environment.yml      # first time
conda env update -f environment.yml --prune   # refresh deps
conda activate dl_wm                     # alias: `cad` (added to ~/.bashrc by setup_env.sh)
```

`setup_env.sh` does the above plus two things `environment.yml` can't express: pins
`setuptools==68.2.2` (needed for `pkg_resources`) and installs `openai-whisper` with
`--no-build-isolation` (version via `WHISPER_VERSION` env var, default `20230314`).

Health check (validates imports, `conf/` paths, ffmpeg, fonts):

```bash
python bin/doctor.py
```

`dl_wm_backup.yml` is a fully pinned conda export (lockfile snapshot), not the file to edit for
dependency changes — edit `environment.yml`/`requirements-lock.txt`.

## Running

```bash
python bin/call_router.py "<media-url>" [--dry-run]     # full pipeline for one URL
python bin/call_download.py "<media-url>"                 # download only
bin/watermark_manual.sh IN.mp4 OUT.mp4 "Uploader" "2026-04-26" "Title"  # watermark w/o metadata JSON
```

Clip pipeline (Whisper-driven, simple path):

```bash
python bin/clip_from_whisper.py outputs/<run>/<file>.whisper.json   # -> outputs/<run>/clips/clips.jsonl
python bin/render_clips.py outputs/<run>/clips/clips.jsonl          # or: bin/render_clips_from_jsonl.sh ...
```

Modular manifest pipeline (`pipeline/`, stage-separated so intermediate output is inspectable/editable):

```bash
python -m pipeline.extract --source-video ... --clips-jsonl ... --output-dir clips --manifest-out clips_manifest.json
python -m pipeline.intro --manifest clips_manifest.json --output-dir clips_with_intro --manifest-out clips_with_intro_manifest.json --font fonts/Inter-Bold.otf
python -m pipeline.build_manifest --clips-manifest clips_manifest.json --title-image outputs/<run>/monarch.png --output final_manifest.json
python -m pipeline.render --manifest final_manifest.json --output final_film.mp4
```

Each stage reads/writes a manifest JSON where `path` points at the current active clip file and is
advanced by the next stage; `final_manifest.json` is meant to be hand-edited before the final render.

## Tests

`pytest` against `tests/*.py` and `lib/test_*.py`. It's not pinned in `environment.yml` — install it in
the `dl_wm` env if missing (`pip install pytest`).

## Architecture

**Metadata JSON is the state machine.** There's no database. Each downloaded item gets a metadata file
in `metadata/` named `{vendor}__{vendor_id}.json` (see `lib/vendor_router.py::metadata_filename`),
seeded from `conf/default_tasks.json`. Inside, `default_tasks` maps task name -> `true` (pending),
`false`/absent (skip), or a string (completed, value is the output path). `bin/call_router.py` reads a
URL's metadata, and for each task with a script in its `TASK_DISPATCH` table, shells out to that
`bin/call_*.py` script if the task is still pending. `lib/tasks_lib.py` owns reading/writing/locating
these metadata files (`find_url_json`, `get_task_states`, `update_task_output_path`, etc.).

**Vendor routing.** `lib/vendor_router.py` is the single source of truth for turning a raw URL into
`(vendor, vendor_id, kind)` and a canonical URL (`detect_vendor`, `extract_vendor_id`,
`canonicalize_vendor_url`). Everything downstream (downloaders, metadata filenames, cookie lookup) keys
off this.

**Downloader contract.** `downloaders/{instagram,facebook,youtube}.py` each expose
`download(url, output_dir, metadata_dir, registry_record, cookie_path, video_download_cfg) -> dict`
(must include `vendor`, `vendor_id`, `metadata_file`, `original_filename`). They're yt-dlp based and use
`lib/metadata_compactor.py` to write both a compact metadata JSON and a raw (gzip by default) metadata
sidecar. `bin/call_download.py` resolves candidate cookie files per vendor from
`conf/app_config.json:video_download.cookie_hierarchy` (falling back to glob patterns in `conf/`) and
retries across cookie files when a download fails with an identity/rate-limit block
(`is_cookie_identity_blocked_error`).

**`igp/` is a separate path, not part of the main downloader chain.** It's a standalone Playwright-based
"Instagram /p/ probe" (`capture.py`/`cookies.py`/`download.py`/`extract.py`/`select.py`, invoked via
`bin/igp_probe.sh`) that drives a real headless browser to fetch Instagram media via request-context
fetches instead of yt-dlp. Reach for it when the yt-dlp path is blocked/stale for a given post, not as
the default download path.

**Config layering** (`conf/`):
- `config.json` — platform-specific paths/cookies, keyed by `Darwin`/`Linux`/`default` (python_path,
  base_dir, output_dir, logging, youtube_cookie_files, browser_cookie_order).
- `app_config.json` — app-wide behavior: `video_download` (format/cookie hierarchy), `watermark_config`,
  `transcription` (pluggable — set `caller_command`/`caller_module` or drop in `bin/transcribe_media.py`
  for auto-detect), `subtitle_burn`/`subtitle_style_presets`, `youtube_download.strategies` (ordered
  fallback chain: cookie file -> browser cookies -> android client).
- `default_tasks.json` — the task flags newly downloaded items get seeded with.

`lib/teton_utils.py` loads both platform (`load_config`) and app (`load_app_config`) configs and resolves
`$HOME`/relative paths against the repo root. **It has a strict convention**: new functions must be
added alphabetically with a docstring, and the module's header comment block (`# Function List:`) must
be updated to match — don't skip updating the header when adding/removing a function there.

**Watermarking & subtitles**: `lib/watermarker2.py` burns text via ffmpeg using
`app_config.watermark_config`; `bin/call_burn_srt.py` burns `.srt` files using `subtitle_burn` /
`subtitle_style_presets`. `bin/generate_clip_srts.py` slices per-clip subtitles directly from a source
Whisper JSON's word timestamps when available (the old equal-time `short_srt.py` shortening path is
disabled — it produced timings that could lead the audio).

Example manifests for the modular pipeline live in `examples/manifests/`.
