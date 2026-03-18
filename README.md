# dl_wm

`dl_wm` is a small Python workflow for downloading media and running follow-up tasks (like watermarking) through script entrypoints in `bin/`.

## Setup (Conda via `.yml`)

This project ships an `environment.yml` file you can use directly.

1. Create the conda environment:
   ```bash
   conda env create -f environment.yml
   ```
2. Activate the environment:
   ```bash
   conda activate dl_wm
   ```
3. (Optional) Add a shortcut alias so `cad` activates this environment:
   ```bash
   echo "alias cad='conda activate dl_wm'" >> ~/.bashrc
   source ~/.bashrc
   ```
4. (Optional) If the environment already exists and you need to refresh dependencies:
   ```bash
   conda env update -f environment.yml --prune
   ```

## Configuration

Edit these JSON files before running workflows:

- `conf/config.json` (platform-specific output directory)
- `conf/app_config.json` (metadata and app-level settings)

## Verify your setup

Run the doctor check:

```bash
python bin/doctor.py
```

This validates:
- required imports
- writable output/metadata directories
- `ffmpeg` availability


## Caption/Transcription tasks

- `extract_audio` now writes a transcript text file (`.txt`) beside the media file.
- `generate_srt` writes an `.srt` file beside the media file.
- `burn_srt` burns subtitles onto the watermarked output (or fallback input video) using `bin/call_burn_srt.py` and settings under `subtitle_burn` in `conf/app_config.json`.
- Configure your imported transcription caller under `transcription` in `conf/app_config.json` (or drop `bin/transcribe_media.py` and it will be auto-detected).

## Run

Use the router with a media URL:

```bash
python bin/call_router.py "<media-url>"
```

Dry run mode:

```bash
python bin/call_router.py "<media-url>" --dry-run
```

## Add-url examples

Add a new URL (writes `vendor`, `vendor_id`, optional `kind`, and metadata file names like `{vendor}__{vendor_id}.json`):

```bash
python bin/call_download.py "https://www.instagram.com/reel/<CODE>/"
python bin/call_download.py "https://www.youtube.com/watch?v=<ID>"
python bin/call_download.py "https://www.youtube.com/shorts/<ID>"  # normalized to watch?v=<ID>
```


## Clip pipeline (question-driven)

Generate a clips manifest from Whisper JSON:

```bash
python bin/clip_from_whisper.py outputs/<run>/<file>.whisper.json
```

This writes `outputs/<run>/clips/clips.jsonl` by default, supports absolute or repo-relative input paths, and writes repo-root-relative paths into clip manifests.

Render clips from the generated JSONL:

```bash
python bin/render_clips.py outputs/<run>/clips/clips.jsonl
# or wrapper:
bin/render_clips_from_jsonl.sh outputs/<run>/clips/clips.jsonl
```

Quality note: `accurate` mode now performs decode-first seeking (`-i ... -ss ... -t ...`) to avoid boundary frame drops, and default encode settings were raised to `PRESET=medium` and `CRF=18`.

If `clips.jsonl` is omitted, `bin/render_clips.py` auto-selects the most recent `outputs/*/clips/clips.jsonl`.


## Modular manifest pipeline (Python)

This repo now includes a stage-based pipeline under `pipeline/`.
Each stage is intentionally separate so you can inspect/edit outputs between steps.

1. **Stage 1 — Extract clips**
   ```bash
   python -m pipeline.extract      --source-video outputs/<run>/<file>_watermarked.mp4      --clips-jsonl inputs/clips_first10min.jsonl      --output-dir clips      --manifest-out clips_manifest.json
   ```

2. **Stage 2 — Optional intro/cards**
   ```bash
   python -m pipeline.intro      --manifest clips_manifest.json      --output-dir clips_with_intro      --manifest-out clips_with_intro_manifest.json      --font fonts/Inter-Bold.otf      --black-seconds 0.5
   ```

3. **Stage 3 — Build final manifest (critical checkpoint)**
   ```bash
   python -m pipeline.build_manifest      --clips-manifest clips_manifest.json      --title-image outputs/<run>/monarch.png      --output final_manifest.json
   ```
   Review and manually edit `final_manifest.json` before render.

4. **Stage 4 — Final render**
   ```bash
   python -m pipeline.render      --manifest final_manifest.json      --output final_film.mp4      --black-seconds 0.5
   ```

Example manifests are in `examples/manifests/`.
