# Transcription engines

`bin/transcribe_media.py` is the pipeline's default transcription caller
(`lib/transcription_caller.py` invokes it as a subprocess when no
`transcription.caller_command`/`caller_module` override is set in
`conf/app_config.json` — see that module for the full lookup order).

As of 2026-09-18 there's more than one engine available. Each engine is its
own `bin/transcribe_media_<engine>.py` script sharing one CLI contract
(positional media path, `--outdir`, `--chunk-seconds`, `--srt`/`--txt`/
`--no-txt`/`--vtt`/`--json`/`--minute-json`/`--source-url`/`--jsonl`) defined
by `lib/transcribe_common.py`. Any of them can be dropped into
`conf/app_config.json`'s `transcription.caller_command` interchangeably, or
run directly for a one-off video — nothing else in the pipeline
(`call_captions.py`, `call_router.py`, etc.) needs to know which engine is
active.

Engine selection is **manual** — there's no auto-detection or per-video
override flag yet. To switch the pipeline's default engine, edit
`conf/app_config.json`:
```json
"transcription": {
  "caller_command": "python bin/transcribe_media_faster_whisper.py {input} --outdir <dir> --srt --no-txt"
}
```
Or just invoke the engine script directly for a specific video, same
arguments as `transcribe_media.py`:
```
python bin/transcribe_media_faster_whisper.py INPUT.mp4 --outdir OUTDIR --srt --no-txt
```
This was a deliberate choice, not an oversight — automatic engine
selection/fallback is easy to add later once there's real signal for when
each engine should be picked, rather than guessing at the rule up front.

## whisper (`bin/transcribe_media.py`) — default

- **Backend**: `openai-whisper`, PyTorch.
- **Install**: `setup_env.sh` step 3 (`pip install --no-build-isolation
  openai-whisper==20230314`), deliberately kept out of `environment.yml` —
  a naive `pip install` resolves full CUDA wheel variants
  (`nvidia-cuda-*`, 600MB+ each) this machine doesn't need (no discrete
  GPU), which previously blew through a disk-quota-like limit. Installing
  CPU-only torch first (`pip install torch --index-url
  https://download.pytorch.org/whl/cpu`) sidesteps it.
- **Tradeoffs**: highest memory footprint of the engines here. On this
  machine (3.2GB RAM) it's reliable for short clips (~7-13 min tested
  clean) but got OOM-killed on a 100-minute video even chunked down to
  20-minute pieces via `--chunk-seconds`.

## faster-whisper (`bin/transcribe_media_faster_whisper.py`) — added 2026-09-18

- **Backend**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
  CTranslate2 instead of PyTorch. Same Whisper model weights, different
  (lower-memory, ~4x faster on CPU) inference engine — not a different
  model or lower accuracy.
- **Install**: `pip install faster-whisper` (pinned as of this writing:
  `faster-whisper==1.2.1`, `ctranslate2==4.8.2`). No CUDA-wheel problem
  like openai-whisper had — confirmed via a real install on this machine,
  no `nvidia-cuda-*` packages pulled. Lives in `setup_env.sh` alongside
  the whisper install step, same reasoning as above (kept out of
  `environment.yml`); pinned versions documented in
  `requirements-lock.txt`'s comment block.
- **Config**: `transcribe_media_faster_whisper.py` loads models with
  `compute_type="int8"` on CPU — the lowest-memory quantization mode,
  which is the whole point of reaching for this engine on a memory-
  constrained machine.
- **Why added**: `bin/transcribe_media.py` (openai-whisper) got killed for
  memory on a 100-minute Facebook/YouTube video repeatedly, even running
  alone with no other heavy process contending, even with 20-minute
  chunking. See the 2026-09-18 session for the full story — including an
  orphaned openai-whisper process that outlived its own "killed for
  memory" notification and kept silently eating ~740MB in the background
  for nearly an hour, which was the actual cause of several *unrelated*
  memory-pressure symptoms that day, not a real flaw in the chunking
  approach itself. Worth remembering if a future session sees mysterious
  memory pressure with no obvious process behind it: check for an
  orphaned `transcribe_media.py`/`transcribe_media_faster_whisper.py`
  (`ps -ef | grep transcribe_media`) before assuming a new bug.
- **Validation status**: engine script built and CLI-contract-verified
  (accepts the same flags, same output files). Real-content smoke test
  (short clip, compared against the existing openai-whisper SRT for the
  same video) was in progress but got starved by the orphaned process
  above before finishing — rerun and confirm output quality before
  trusting this on anything you can't easily re-transcribe.

## Kaldi and others — not yet added

Mentioned as likely future additions (2026-09-18 conversation). No script
exists yet. When one is added, follow the same shape: a
`bin/transcribe_media_kaldi.py` implementing `transcribe_one(audio_path, *,
model_name, language, task) -> {"text", "segments", "language"}` (segments
optionally carrying a `"words"` list of `{"word", "start", "end"}` for
fine-grained SRT timing — see `lib/transcribe_common.srt_rows_from_segments`
for how that's consumed), calling `transcribe_common.run_cli(...)` for
everything else. Add its section here with the same install/tradeoffs/
validation-status shape as the two above.

## Shared plumbing (`lib/transcribe_common.py`)

Everything that doesn't vary by engine: CLI arg parsing, repo-root/output-
path resolution, source-URL lookup from clip-selection JSONLs, ffmpeg-based
audio chunking (`run_chunked_transcription`, offsetting each chunk's
segment timestamps by its start time and stitching results back together),
SRT/VTT formatting (word-timestamp-aware caption splitting via
`srt_rows_from_segments`), minute-summary JSON, and manifest writing. Each
engine script only supplies the actual "transcribe this audio → segments"
call plus a version-string getter; `run_cli()` handles the rest identically
regardless of engine. This was factored out of the original monolithic
`bin/transcribe_media.py` on 2026-09-18 specifically so adding faster-
whisper (and future engines) wouldn't mean re-implementing chunking/SRT-
writing/manifest logic per engine — `tests/test_transcribe_media.py` still
passes unchanged against the refactored file, confirming the extraction
didn't change behavior.
