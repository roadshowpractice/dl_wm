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
3. (Optional) If the environment already exists and you need to refresh dependencies:
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

## Run

Use the router with a media URL:

```bash
python bin/call_router.py "<media-url>"
```

Dry run mode:

```bash
python bin/call_router.py "<media-url>" --dry-run
```
