"""Real, non-mocked run of the full pipeline (download + whatever
conf/default_tasks.json turns on — currently perform_download,
apply_watermark, extract_audio, generate_srt) against the 6 tbfrescue.org
Vimeo videos, one at a time.

This is bin/call_router.py itself, subprocess-invoked exactly as a real
user would run it — no stubbed pieces. Requires the vimeo_download config
in conf/app_config.json (referer + impersonate) and a curl_cffi version
yt-dlp supports (>=0.10,<0.16). Hits live network, writes real output
files under outputs/.
"""
import json
import os
import subprocess
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)

INPUT_FILE = os.path.join(root_dir, "inputs", "tbfrescue_vimeo.json")


def main():
    videos = json.load(open(INPUT_FILE))["videos"]
    results = []

    for v in videos:
        url = v["embed_url"]
        print(f"\n{'=' * 60}\nRunning pipeline for {v['id']} ({v['section']}): {url}\n{'=' * 60}")

        proc = subprocess.run(
            [sys.executable, os.path.join(root_dir, "bin", "call_router.py"), url],
            cwd=root_dir,
        )
        ok = proc.returncode == 0
        results.append({"id": v["id"], "section": v["section"], "success": ok, "returncode": proc.returncode})
        print(f"[{'OK' if ok else 'FAIL'}] {v['id']} -> exit code {proc.returncode}")

    n_ok = sum(r["success"] for r in results)
    print(f"\n{n_ok}/{len(results)} completed pipeline runs (download + configured tasks) without error.")
    for r in results:
        print(f"  {r['id']} ({r['section']}): {'OK' if r['success'] else 'FAIL (exit ' + str(r['returncode']) + ')'}")

    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
