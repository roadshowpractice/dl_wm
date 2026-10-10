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
  - **REVERTED 2026-09-01: Instagram downloading is back on yt-dlp, not instaloader.** Root cause: `downloaders/instagram.py` (the instaloader-session version, live 2026-08-25 to 2026-09-01 via commit `c760633`) only fetched the "progressive" (single-file) MP4 URL via a plain `requests.get()`, with no DASH fallback. Some Reels aren't served progressively at all anymore (Instagram-side, not account-side) — for those the progressive URL 404s on Instagram's own CDN every time, confirmed against **two different live, verified Instagram sessions** (`haddamgoel` and `merrillp.jensen` — the latter is John's own account) with identical 404s, same asset ID, both accounts. That ruled out cookie/session/blocking as the cause. `yt-dlp`'s own Instagram extractor correctly falls back to DASH video+audio streams and merges them with ffmpeg, so John had this file-level-reverted back to its pre-`c760633` version (`git checkout c760633^ -- downloaders/instagram.py`) — everything else that commit added (Vimeo downloader, this CLAUDE.md's own additions, `bin/clip_driver_ballard.sh`, the test scripts) was left untouched, only `downloaders/instagram.py` itself moved. `conf/app_config.json`'s `"instagram": {"username": ...}` block (instaloader-only) was removed as dead config — auth is cookie-file-based again, same `cookie_hierarchy.instagram` list (`conf/instagram.cookies.txt` etc.) used for Facebook/YouTube. `bin/bridge_instagram_cookies_to_session.py` is left in place but now unused/dead code, deliberately (John, 2026-09-01: "we'll probably use instaloader again when yt-dlp starts failing again" — this has flip-flopped before and may again; don't delete it as unused-code cleanup without checking first).
  - **Note if this flips back again**: the *reason* instaloader was adopted in the first place (per the `c760633` commit message) was "yt-dlp's Instagram extractor kept breaking" — a different failure mode than the DASH-progressive gap that caused this reversion. If yt-dlp starts failing again, check what specifically broke before assuming it's the same DASH issue re-emerging.

**Which browser profile / cookie file is which account** (surveyed 2026-10-03 from the live Chrome cookie DBs — re-check with `ds_user_id`/`c_user`, never guess from profile names):

| Chrome user-data-dir / profile | Launcher | Instagram | Facebook |
|---|---|---|---|
| `google-chrome/Default` | `google-chrome.desktop` | — | 1236192977 (merrill.p.jensen) |
| `google-chrome/Profile 2` (Claude-in-Chrome) | `JohnDaystrom.desktop` | haddamgoel (38012325418) | 1236192977 (merrill.p.jensen) |
| `google-chrome/JustinRiggs1970` | `JustinR.desktop` | — | 61585496017234 (JustinR) |
| `google-chrome/goelhaddam1970` | — (launcher deleted 2026-10-03) | — (empty profile) | — |
| `google-chrome-goel/Default` | `Goel_Instagram.desktop` | haddamgoel (38012325418) | — |
| `google-chrome-perlgonzales/Default` | — | haddamgoel (38012325418) | — |

- **2026-10-08 Facebook kill-file status (Tim Ballard, `officialtimballard` = id 100044614771436):**
  - **BLOCKED by TB 2026-10-08:** merrill.p.jensen (1236192977) and 61577459351712. Both get "This content isn't available" while logged in; the page loads logged-out.
  - JustinR (61585496017234): John believes it's blocked too (2026-10-08), not verified.
  - **Current scrape account: 61590880705869**, logged into Profile 2 on 2026-10-08, cookies in `conf/facebook.daystrom.cookies.txt` (first in `cookie_hierarchy.facebook`).
    **Read-only. Never comment, react, reply, share or follow from it**, so TB doesn't kill-file it as well.
- **merrillp.jensen (4067475941)** is not logged into Instagram in any Chrome profile; its only session is `conf/instagram.cookies.2.txt`. timballard89 blocks this account.
- `conf/instagram.cookies.haddamgoel.txt` is the primary Instagram cookie file — refresh it with `bin/export_browser_cookies.py instagram.com conf/instagram.cookies.haddamgoel.txt ~/.config/google-chrome-goel/Default`. `conf/instagram.cookies.txt` is a **symlink** to it, so older scripts defaulting to that name get haddamgoel.
- `conf/insta.justin.txt` is logged out (empty `ds_user_id`) and was dropped from `cookie_hierarchy.instagram`.
- **2026-10-03**: yt-dlp saves its cookie jar back into its `cookiefile` on exit, so an expired session overwrote `conf/instagram.cookies.txt` with an empty jar. `bin/call_download.py` now hands Instagram/Facebook/Vimeo downloads a temp copy. Scripts that call `yt-dlp --cookies conf/...` directly can still overwrite the file.

**Clip/compilation pipeline** (`pipeline/` package: `extract.py` → `intro.py` → `build_manifest.py` → `render.py`) is a separate, manually-run downstream flow that turns one watermarked long-form video plus a clips JSONL (often produced from Whisper word-timestamp data by `bin/clip_from_whisper.py`) into a final compiled film. Each stage writes its own manifest so output can be inspected/hand-edited between steps (`final_manifest.json` in particular is meant to be reviewed before the final render).

**`igp/`**: headless-browser capture and extraction of a *single* Instagram post (`/p/...`) via GraphQL response sniffing (`igp/capture.py`, `igp/extract.py`, `igp/cookies.py`, `igp/select.py`). Run by hand via `bin/igp_probe.sh URL`, and (since 2026-10-03) automatically by `downloaders/instagram.py` — see below. Needs `playwright` + `playwright install chromium` in the `dl_wm` env (not part of `environment.yml`, installed ad hoc 2026-09-06).

**Instagram photo posts and carousels (2026-10-03)**: yt-dlp can't download photo-only posts. It either raises "No video formats found" or (with `ignoreerrors`) returns no entries. In both cases `downloaders/instagram.py` now runs `python -m igp.capture` as a subprocess (`download_carousel_via_igp`) and copies every slide in at original size as `<run_id>__NN.<ext>` (`<run_id>.<ext>` for a single photo). The old og:image cover fallback, which was a cropped thumbnail as small as 364x364, only runs if igp fails. Video carousels still go through yt-dlp. Verified live: Dc49pIWgPmP (5 photos), DSQ7RTLgdqo / DSKjnKdjYFK / DROQ1ehkb8i (single photos), DR-s9d5ktL_ (2 videos). Two igp fixes went with it: `find_post_model` no longer discards the post's own HTML page for mentioning "inbox"/"messaging", and `build_post_model` prefers models whose assets carry media URLs over bare permalink matches.

**Carousels in `call_router.py` (2026-10-03)**: the downloader records only the first file as `perform_download`, so before this every later slide stopped at download. Now:
- Every later **video** item (`carousel_followup_items`) runs through the same task chain. Its task state lives in a `<media>.json` sidecar next to the file (`item_task_state`), which the task scripts already check before searching `metadata/`. A re-run resumes from the sidecar.
- If slide 1 is a photo but later slides are videos, slide 1 is skipped and the videos are still processed.
- Photo-only posts still skip the video/audio pipeline (watermark etc. are video-only).
- Live-verified on DR-s9d5ktL_ (2 videos). A mixed photo-then-video carousel is unit-tested only — no live case yet.

Gotcha seen 2026-10-03: faster-whisper misdetected Spanish (Ecuador Assembly speech, Dd-8_CpozeL) as Italian. Re-run by hand with `--language es`, after moving the existing `.whisper.json` aside (the transcriber reuses it otherwise). There's no per-post language setting in the pipeline yet.

**Fixed 2026-09-06**: `igp/cookies.py`'s Netscape cookie parser could load a cookie with a corrupted, wildly out-of-range `expires` value (seen: a `wd` cookie at `13433699653000000` — an unconverted raw epoch value from a `yt-dlp --cookies-from-browser` export) and pass it straight to `context.add_cookies()`. Playwright rejects the *entire batch* if even one cookie's expires isn't `-1` or a plausible Unix timestamp, silently killing every carousel capture. Fix: clamp any `expires` past ~year 2100 down to `-1` (session cookie) instead of passing it through. Confirmed fixed against a real 5-image carousel post (`instagram.com/p/Dc49pIWgPmP/`) — all 5 slides captured cleanly afterward.

**`igp/profile_history.py`** (added 2026-09-06): sibling tool to `igp/capture.py` but for a whole profile's timeline instead of one post — Instagram's UI only loads ~12 posts per page and can't jump to old history, so for an account with hundreds of posts this sniffs the same private-API GraphQL response (`xdt_api__v1__feed__user_timeline_graphql_connection`) while scrolling headless to trigger pagination. Writes one JSONL record per post (`shortcode`, `taken_at`, `caption`, `carousel_count`, `collaborators`) — metadata only, no media. Usage: `python3 -m igp.profile_history <username> <cookie_file> <outdir> [max_rounds]`. Validated against `joha_libertaria` (789 posts, 771 captured/98%).

**Fixed 2026-09-26 (`igp/profile_history.py`)**: the scraper was logging *other accounts'* posts (ads, "suggested", Reels tray) as the target's, because (a) it kept every post-like JSON node without checking the owner, and (b) John's logged-in IG account is **blocked by timballard89**, so the profile page shows "Sorry, this page isn't available" and IG fills the page with unrelated content. Fixes: `extract_posts_from_json(..., owner=username)` drops nodes whose `user`/`owner.username` isn't the target (unless the target is a coauthor); `scrape()` detects the blocked-page text and retries **logged out**; logged out, the grid arrives in HTML rather than GraphQL, so it collects `/p/` and `/reel/` links from the DOM and fills `taken_at` and caption via `yt_dlp` (`_fill_dates_with_ytdlp`). Logged out only shows the latest ~12 posts, which is fine for day checks, not deep history. Verified: `ig_posts_on_day.py timballard89 2026-09-25` → exactly his 5 reels. The old junk timeline was moved to `outputs/ig_timelines/timballard89.jsonl.bad_2026-09-24`.

**collabnet (2026-10-04)** — a second pipeline, deliberately named apart from the per-link one (`call_router`/`dllink`): it walks an Instagram collaborator network account by account, metadata only. `bin/collabnet.py QUEUE.txt` (wrapper `~/.local/bin/collabnet` activates the env and mounts the USB drive) reads a queue file (one account per line, `#` comments) and for each account: scrapes it with `igp.profile_history.scrape` (pause 3-6 s per scroll, 3-6 min gap between accounts) unless a non-empty `<account>_<date>/` timeline or forensic capture already exists (the old flat `<account>.jsonl` files don't count, they're partial), then writes a word sort (`bin/ig_word_sort.py`); the graph (`bin/ig_collab_graph.py --touching <queue>`) is drawn ONCE, when the queue is finished (John 2026-10-04: not after every account), with a dated copy in `graph/history/`. `--snowball` appends each account's new collaborators to the queue file. Output: `~/Desktop/claude/<date>/collabnet_<queue stem>/` (`run_*.log`, `status.tsv`, `word_sorts/`, `graph/`). `ig_collab_graph.py` merges every scrape under `outputs/ig_timelines/` and counts a co-authored post once by shortcode (it appears in each partner's grid). Needs `scipy` in the env for graphs over ~500 nodes (pip-installed 2026-10-04). **John's standing rule for every graph: always a key, and edges defined by colour bands** (`EDGE_BANDS`: 1 / 2-4 / 5-19 / 20-99 / 100+ shared posts, one blue hue faint -> bright, width grows too, band counts in the key, key outside the drawing). No numbers on edges; he rejected that as clutter.

**Added 2026-10-04 (after collabnet):** `dllink --list FILE` (wrapper now tracked in `bin/wrappers/`, `~/.local/bin/{dllink,collabnet}` are symlinks to it): every URL in a file, paced, per-link logs, `FILE.done` for resume. `call_router.py` now **exits 1 when something failed** (it used to exit 0 after logging errors). `lib/drive_check.py` proves outputs/ (USB, automount at /mnt/ubuntu26, `errors=remount-ro`) is writable by writing/reading/deleting a test file; dllink and collabnet run it before every link/account. collabnet writes `capped_<queue>.txt` for accounts that hit `--rounds`. `bin/ig_tagged_posts.py ACCOUNT --name REGEX --queue Q` lists posts tying to an account (collaborator / @ / name; its solo posts excluded) -> `.tsv` + `.urls.txt` for `dllink --list`.

**Evidence-grade group graphs (2026-10-04):** `bin/ig_group_members.py --seeds FILE --out DIR` decides membership from data: tier 1 = documented seeds (each with its source), tier 2 = accounts co-posting with >= `--min-seeds` (default 2) different seeds, with every shortcode in `members_by_data.tsv`. `ig_collab_graph.py` gained `--inputs` (explicit scrape files), `--members` (keep only links between members), `--evidence` (`inputs.tsv` with sha256 of each input, `edge_posts.tsv` with every post behind every link, `members.tsv`, `manifest.json` with git commit/dirty files, script sha256, versions, command and output hashes), `--names` (labels "Display Name / @handle" from `metadata/` uploader fields + an optional TSV) and `--label-all`.

**`bin/fb_post.py`** (added 2026-09-29): post text + one image to your own Facebook timeline via headless Chromium + a Netscape cookies.txt. Dry run by default (fills the composer, screenshots, stops); `--post` clicks Post. Logs every step and `/api/graphql/` response to `<outdir>/fb_post_<time>.jsonl`. Cookies: `bin/export_browser_cookies.py facebook.com conf/facebook.merrill.cookies.txt "~/.config/google-chrome/Profile 2"` (gitignored); `bin/check_cookie_file.py <file> facebook.com` shows what the loader sees, no values. `igp.cookies.load_netscape_cookies` now takes a `site` arg (default `instagram.com`) — it used to drop every non-Instagram cookie, which was why FB showed the login page. **Dry run passed 2026-09-29**; **first live `--post` 2026-09-29** ("The Good Guy Edit", https://www.facebook.com/merrill.p.jensen/posts/10234395772575750). The photo goes in via the "Add photos or videos" file chooser after the link preview has loaded, and the script aborts if no `blob:` thumbnail shows up (a preview that arrives late silently replaces the photo). Permalink comes from `post_id` in `ComposerStoryCreateMutation`; `--profile` sets the username in it.

**Screenshot OCR / collaborator collection (2026-10-03)**: `bin/ocr_screenshots.py` reads 1366x768 desktop screenshots with Tesseract (`apt tesseract-ocr` + `-spa`/`-por`, `pip pytesseract`). For Chrome-on-Instagram screenshots, `find_instagram_layout` measures the open post's rectangles from pixels: the URL bar is fixed at y 78-112; the caption panel is the ~499px white column, and its left edge moves with the photo's shape; header strip and caption area are split by the panel's divider lines. It then reads URL, header, caption and photo text separately. Kinds: `post`, `post_with_collaborators` (header "a and b", or "a and N others" -> `others_count`), `collaborators_list` (Instagram's Collaborators pop-up, which names everyone), `profile`. `--draw-boxes` writes `<stem>.boxes.png` for checking. `bin/ocr_collabs.sh DIR [OUTDIR]` drives a whole folder and writes `collabs_by_screenshot.tsv`, `collabs_by_post.tsv` (merges a post's screenshots, so a pop-up fills in "+N others") and `collab_pairs.tsv`. `COLLECT_ONLY=1` rebuilds the TSVs without re-OCR. Shortcodes are checked by length (11 = ok; OCR sometimes adds or drops a character). Importing cv2 sets `LD_LIBRARY_PATH` to conda's lib/, which breaks the system tesseract; the script strips it. First full run, 45 screenshots, ~6 min: `~/Desktop/claude/2026-10-03/ocr/ocr_screenshots_2026-10-02/`. **How screenshots are taken (confirmed with John 2026-10-03):** he browses in Claude-in-Chrome's own tab; when he types "s", Claude photographs that tab with the extension (`screenshot`, `save_to_disk`) and copies it to `~/Desktop/claude/<date>/screenshots/tab_<time>_<shortcode>.jpg`. Full-screen grabs (`xfce4-screenshooter -f`) catch whatever window is on top, the terminal included, so they aren't used. Tab photos are page-only (~1358x650, no URL bar). The script's Instagram layout mode doesn't handle them yet: needs a page-view mode, with the shortcode taken from the filename.

**Shared libs**: `lib/teton_utils.py` and `lib/tasks_lib.py` hold cross-cutting concerns — config loading, logging init, repo-relative path resolution, and all metadata read/write/index helpers (`find_url_json`, `upsert_metadata_index`, `update_task_output_path`, `get_task_states`).

**Photo watermarks (2026-10-09)**: the video watermark step can't read stills, so `call_router.py` now runs `bin/call_watermark_images.py <metadata json>` for photo posts (and the photo slides of mixed carousels) when `apply_watermark` is `true`. `lib/image_watermarker.py` copies the video look with PIL: uploader top-left yellow, date bottom-left cyan, slide "N/M" bottom-right red (where video has the timestamp), sizes scaled to image width (1080 px = config size). Output `<stem>_watermarked.<ext>` next to each photo; the first is recorded as `apply_watermark`. For the date, `igp/capture.py` now keeps the post's `taken_at` and `downloaders/instagram.py` passes it as `timestamp`, so Instagram photo posts get a `video_date`. Facebook photo posts (`downloaders/facebook_photos.py`) now write the standard compact metadata, so `perform_download` is recorded (before this, dllink marked good photo downloads FAILED). Live-checked on Ballard's 2026-10-08 Tribune posts (FB 5 photos, IG 7).
