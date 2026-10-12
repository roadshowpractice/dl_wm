# Facebook reels that won't download ("Cannot parse data")

Written 2026-10-12, in plain words. Hit three times so far: Mortensen's R2 (10-10), R3 and R4 (10-12).

## What you see

`dllink` on a Facebook reel stops right away (about 8 seconds) with:

```
ERROR: [facebook] 1645607447070005: Cannot parse data; please report this issue ...
❌ Downloader failed before metadata was generated.
```

The log is in `~/Desktop/claude/<day>/dllink_list_<time>/<reel id>.log` (list runs) or the `tee` log (single runs).

## What it is NOT

- **Not two jobs at once.** A YouTube download running beside it doesn't matter. They share nothing.
- **Not an old yt-dlp.** On 10-12 we had 2026.08.19, which was the newest release. The official standalone build of that newest release failed the same way. `yt-dlp -U` won't fix it.
- **Not a login problem.** The JustinR cookies work: the page opens logged in, and the video is right there in it.

## What it IS: an analogy

yt-dlp is like a mail carrier with **one** address for where the video links live on a Facebook reel page. On Tim's reels, the links are at that address, so it works. On Mortensen's reels, Facebook builds the page differently. The links are on the page, but **at a different address**. The carrier knocks at the usual door, finds nothing, and gives up ("Cannot parse data").

Only the yt-dlp maintainers can teach the carrier the new address, in a future release. We don't have to wait for that.

## The fix: we go to the other address ourselves

**Since 2026-10-12 this is built into the pipeline.** `dllink` and `call_router.py` just work on these reels: when yt-dlp says "Cannot parse data", `downloaders/facebook.py` hands the reel to `downloaders/facebook_dash.py`, and the watermark and SRT steps run as usual. Any other yt-dlp error still fails as before. (The first version was the one-off script `~/Desktop/claude/2026-10-12/analysis/fb_reel_grab.py`.)

It does four things:

1. **Opens the reel** in a hidden Chrome window, logged in as JustinR. It only reads the page: no likes, no views counted as activity by us, no clicks.
2. **Finds the other address.** Facebook keeps a list on the page called `all_video_dash_prefetch_representations`. It lists the video in several sizes (640, 960, 1280, 1920 tall…) and the sound as its own separate track.
   - Why separate? Facebook (like Instagram and YouTube) sends picture and sound as two files ("DASH"), so your phone can switch picture quality without restarting the sound.
3. **Downloads the biggest picture and the sound track** (two files: `v.mp4` and `a.mp4`).
4. **Glues them together** with ffmpeg into one normal `.mp4`. Glue only: nothing is re-encoded, so it's exactly what Facebook serves. The two pieces are deleted after.

It also saves the page it read (`<id>_page.html`) next to the video, so we can show where the links came from.

## How to run it (copy-paste)

Nothing special. Same as any link:

```
dllink https://www.facebook.com/reel/1063875660031210/
```

In the log, the fallback shows up as `Facebook page read (DASH fallback)` and `DASH fallback: 4 video + 1 audio streams`. Next to the video you'll also find `facebook__<id>.page.html` (the page it read), and the metadata says `"download_method": "facebook_dash"`.

## How you know it worked

dllink says the link finished, and the folder has the `.mp4`, `_watermarked.mp4` and `.srt` like any other video. If the log says `no audio stream listed ... video only`, there's no sound: tell Claude.

Its bytes won't match the Instagram copy of the same video (different site, different encode). Compare length and content, not hashes.

## Why we bother

- Without it, **we get none of Mortensen's Facebook videos**: every one has failed through dllink.
- His Facebook and Instagram copies aren't always the same: R1 was deleted from IG, and R2's caption changed on FB. To say what he released, where and when, we need our own copy from each site.

## When it might break

- If Facebook moves the list again, the log says `no DASH video streams for <id> on the page`. The saved `_page.html` is what Claude needs to find the new spot. Don't re-run it over and over against the live site.
- The links inside the page expire after some hours. Each run opens a fresh page, so just re-run the link.

## History

- 2026-10-10: R2 (`1456179773040007`) failed with this error; Claude pulled it by hand from a page capture. Folder: `outputs/2026-10-10/facebook__1456179773040007_capture/`.
- 2026-10-12: R3 (`1645607447070005`) failed in John's D1 run; tried newest yt-dlp (pip and standalone), same error. Wrote `fb_reel_grab.py`; R3 downloaded 1080x1920 with sound, 4:35.8 (same length as the IG copy).
- 2026-10-12 (later): built into the pipeline (`downloaders/facebook_dash.py`), with unit tests. Live: `dllink` on R4 (`1063875660031210`) at 10:00, yt-dlp "Cannot parse data" -> fallback found 4 video + 1 audio streams -> download complete; watermark + SRT then ran in the same dllink run.
