import json
import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

from lib.metadata_compactor import build_compact_metadata, write_raw_metadata
from lib.teton_utils import load_app_config
from lib.vendor_router import VENDOR_YOUTUBE, extract_vendor_id, metadata_filename


MIN_YT_DLP_VERSION = "2024.10.22"
RETRYABLE_FAILURE_MARKERS = [
    "only images are available",
    "requested format is not available",
    "n challenge solving failed",
    "error solving n challenge request",
    "sign in to confirm you are not a bot",
]
COOKIE_SOURCE_UNAVAILABLE_MARKERS = [
    "could not find firefox cookies database",
    "could not find chrome cookies database",
    "could not find chromium cookies database",
    "could not find brave cookies database",
    "could not copy chrome cookie database",
    "could not copy chromium cookie database",
    "could not decrypt chrome cookies",
    "could not decrypt chromium cookies",
    "unsupported browser",
]
DEFAULT_YT_FORMAT = "bestvideo[height<=?1080]+bestaudio/best"
_REMOTE_COMPONENTS_SUPPORTED: Optional[bool] = None


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _version_key(version_text):
    pieces = []
    for chunk in str(version_text).strip().split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        pieces.append(int(digits))
    return tuple(pieces)


def _ensure_supported_yt_dlp(min_version=MIN_YT_DLP_VERSION):
    try:
        result = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as err:
        raise RuntimeError(
            "yt-dlp is missing or not executable. Install/repair yt-dlp before downloading."
        ) from err

    detected = (result.stdout or "").strip()
    if not detected:
        raise RuntimeError("Could not determine yt-dlp version from 'yt-dlp --version'.")

    if _version_key(detected) < _version_key(min_version):
        raise RuntimeError(
            f"yt-dlp {detected} is too old. Minimum supported version is {min_version}. "
            "Please update yt-dlp and rerun."
        )


def _supports_remote_components() -> bool:
    global _REMOTE_COMPONENTS_SUPPORTED
    if _REMOTE_COMPONENTS_SUPPORTED is not None:
        return _REMOTE_COMPONENTS_SUPPORTED
    try:
        result = subprocess.run(["yt-dlp", "--help"], capture_output=True, text=True, check=True)
        help_text = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        _REMOTE_COMPONENTS_SUPPORTED = "--remote-components" in help_text
    except (FileNotFoundError, subprocess.CalledProcessError):
        _REMOTE_COMPONENTS_SUPPORTED = False
    return _REMOTE_COMPONENTS_SUPPORTED


def _load_platform_config() -> Dict:
    config_path = os.path.join(_repo_root(), "conf", "config.json")
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as fh:
        loaded = json.load(fh)
    return loaded if isinstance(loaded, dict) else {}


def _detect_platform_key() -> str:
    current = (sys.platform or "").lower()
    if current.startswith("linux"):
        return "linux"
    if current == "darwin":
        return "darwin"
    return "default"


def _get_platform_section(platform_cfg: Dict) -> Dict:
    platform_key = _detect_platform_key()
    if not isinstance(platform_cfg, dict):
        return {}
    for key, value in platform_cfg.items():
        if str(key).lower() == platform_key and isinstance(value, dict):
            return value
    default_value = platform_cfg.get("default") or platform_cfg.get("Default")
    return default_value if isinstance(default_value, dict) else {}


def _expand_path(path_value: Optional[str]) -> Optional[str]:
    if not path_value or not isinstance(path_value, str):
        return None
    expanded = os.path.expandvars(os.path.expanduser(path_value))
    if not os.path.isabs(expanded):
        expanded = os.path.join(_repo_root(), expanded)
    return os.path.abspath(expanded)


def _parse_last_json_line(stdout_text: str) -> Optional[Dict]:
    for line in reversed((stdout_text or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            maybe = json.loads(line)
            if isinstance(maybe, dict):
                return maybe
        except json.JSONDecodeError:
            continue
    return None


def _contains_retryable_marker(stdout_text: str, stderr_text: str) -> bool:
    combined = f"{stdout_text or ''}\n{stderr_text or ''}".lower()
    return any(marker in combined for marker in RETRYABLE_FAILURE_MARKERS)


def _cookie_source_unavailable(stdout_text: str, stderr_text: str) -> bool:
    combined = f"{stdout_text or ''}\n{stderr_text or ''}".lower()
    return any(marker in combined for marker in COOKIE_SOURCE_UNAVAILABLE_MARKERS)


def _resolve_cookie_candidates(
    explicit_cookie_path: Optional[str],
    strategy: Dict,
    platform_section: Dict,
    video_download_cfg: Dict,
) -> List[str]:
    candidates = []

    if explicit_cookie_path:
        candidates.append(explicit_cookie_path)

    strategy_cookie = strategy.get("cookie_file") if isinstance(strategy, dict) else None
    if strategy_cookie:
        candidates.append(strategy_cookie)

    for container in (platform_section, video_download_cfg):
        if isinstance(container, dict):
            listed = container.get("youtube_cookie_files")
            if isinstance(listed, list):
                candidates.extend(item for item in listed if isinstance(item, str))

    resolved = []
    seen = set()
    for candidate in candidates:
        resolved_path = _expand_path(candidate)
        if not resolved_path or resolved_path in seen:
            continue
        seen.add(resolved_path)
        if os.path.exists(resolved_path):
            resolved.append(resolved_path)
    return resolved


def _resolve_browser_order(strategy: Dict, platform_section: Dict, youtube_cfg: Dict) -> List[str]:
    order = []
    strategy_browser = strategy.get("browser") if isinstance(strategy, dict) else None
    if strategy_browser:
        order.append(strategy_browser)

    for container in (platform_section, youtube_cfg):
        if isinstance(container, dict):
            listed = container.get("browser_cookie_order")
            if isinstance(listed, list):
                order.extend(item for item in listed if isinstance(item, str))

    deduped = []
    seen = set()
    for browser in order:
        key = browser.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(browser.strip())
    return deduped


def _build_command(url: str, output_template: str, fmt: str, strategy: Dict) -> List[str]:
    cmd = [
        "yt-dlp",
        "--print-json",
        "--format",
        fmt,
        "--merge-output-format",
        "mp4",
        "--no-playlist",
        "--output",
        output_template,
    ]

    if strategy.get("use_remote_components") and _supports_remote_components():
        cmd.extend(["--remote-components", "ejs:github"])

    extractor_arg = strategy.get("extractor_arg")
    if extractor_arg:
        cmd.extend(["--extractor-args", str(extractor_arg)])

    return cmd


def _run_yt_dlp(command: List[str]) -> Tuple[int, str, str]:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout or "", result.stderr or ""


def download(url, output_dir, metadata_dir, registry_record, cookie_path=None, video_download=None):
    vendor_id = extract_vendor_id(VENDOR_YOUTUBE, url)
    if not vendor_id:
        return {
            "success": False,
            "error": "Could not extract YouTube video ID from URL",
            "strategy": None,
            "vendor": VENDOR_YOUTUBE,
            "vendor_id": None,
            "stdout": "",
            "stderr": "",
            "retryable": False,
        }

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(metadata_dir, exist_ok=True)

    _ensure_supported_yt_dlp()

    output_template = os.path.join(output_dir, f"{VENDOR_YOUTUBE}__{vendor_id}.%(ext)s")
    metadata_path = os.path.join(metadata_dir, metadata_filename(VENDOR_YOUTUBE, vendor_id))

    app_config = load_app_config() or {}
    video_download_cfg = video_download if isinstance(video_download, dict) else {}
    youtube_cfg = app_config.get("youtube_download", {}) if isinstance(app_config.get("youtube_download"), dict) else {}

    strategies = youtube_cfg.get("strategies") if isinstance(youtube_cfg.get("strategies"), list) else []
    if not strategies:
        strategies = [
            {
                "name": "web_cookie_file",
                "use_remote_components": True,
                "cookies_mode": "file",
                "format": video_download_cfg.get("format", DEFAULT_YT_FORMAT),
            },
            {
                "name": "android_fallback",
                "use_remote_components": False,
                "cookies_mode": "none",
                "extractor_arg": "youtube:player_client=android",
                "format": "best",
            },
        ]

    platform_cfg = _load_platform_config()
    platform_section = _get_platform_section(platform_cfg)

    attempts = []

    for strategy in strategies:
        strategy_name = strategy.get("name", "unnamed_strategy")
        fmt = strategy.get("format") or video_download_cfg.get("format") or DEFAULT_YT_FORMAT
        command = _build_command(url=url, output_template=output_template, fmt=fmt, strategy=strategy)

        cookies_mode = (strategy.get("cookies_mode") or "none").lower()
        credential_attempts = [("none", [])]
        if cookies_mode == "file":
            cookie_files = _resolve_cookie_candidates(cookie_path, strategy, platform_section, video_download_cfg)
            if not cookie_files:
                attempts.append({
                    "strategy": strategy_name,
                    "success": False,
                    "retryable": True,
                    "stdout": "",
                    "stderr": "No cookie file found for file-cookie strategy",
                    "credential_source": "file:none",
                    "command": command,
                })
                print(f"[youtube] strategy={strategy_name} no valid cookie file found; trying next strategy")
                continue
            credential_attempts = [
                (f"file:{selected_cookie}", ["--cookies", selected_cookie]) for selected_cookie in cookie_files
            ]
        elif cookies_mode == "browser":
            browser_order = _resolve_browser_order(strategy, platform_section, youtube_cfg)
            if not browser_order:
                attempts.append({
                    "strategy": strategy_name,
                    "success": False,
                    "retryable": True,
                    "stdout": "",
                    "stderr": "No browser cookie sources configured",
                    "credential_source": "browser:none",
                    "command": command,
                })
                print(f"[youtube] strategy={strategy_name} no browser configured; trying next strategy")
                continue
            credential_attempts = [
                (f"browser:{selected_browser}", ["--cookies-from-browser", selected_browser])
                for selected_browser in browser_order
            ]

        attempted_unavailable_source = False

        for credential_source, credential_args in credential_attempts:
            attempt_command = command + credential_args + [url]
            print(
                f"[youtube] attempting strategy={strategy_name} "
                f"cookies_mode={cookies_mode} credential={credential_source}"
            )
            rc, stdout_text, stderr_text = _run_yt_dlp(attempt_command)
            if stdout_text.strip():
                print(f"[youtube][{strategy_name}] yt-dlp stdout:\n{stdout_text}")
            if stderr_text.strip():
                print(f"[youtube][{strategy_name}] yt-dlp stderr:\n{stderr_text}")

            info = _parse_last_json_line(stdout_text)
            source_unavailable = rc != 0 and _cookie_source_unavailable(stdout_text, stderr_text)
            retryable = rc != 0 and (_contains_retryable_marker(stdout_text, stderr_text) or source_unavailable)

            attempt_result = {
                "strategy": strategy_name,
                "success": rc == 0 and isinstance(info, dict),
                "retryable": retryable,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "credential_source": credential_source,
                "command": attempt_command,
            }
            attempts.append(attempt_result)

            if rc != 0:
                if source_unavailable:
                    attempted_unavailable_source = True
                    print(
                        f"[youtube] strategy={strategy_name} credential={credential_source} "
                        "cookie source unavailable; trying next credential"
                    )
                    continue
                if retryable:
                    print(f"[youtube] strategy={strategy_name} failed with retryable marker; continuing")
                    continue
                return {
                    "success": False,
                    "strategy": strategy_name,
                    "vendor": VENDOR_YOUTUBE,
                    "vendor_id": vendor_id,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "error": "yt-dlp failed with a non-retryable error",
                    "retryable": False,
                    "attempts": attempts,
                }

            if not info:
                return {
                    "success": False,
                    "strategy": strategy_name,
                    "vendor": VENDOR_YOUTUBE,
                    "vendor_id": vendor_id,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "error": "yt-dlp succeeded but did not emit JSON metadata",
                    "retryable": False,
                    "attempts": attempts,
                }

            downloaded_path = info.get("_filename")
            ext = info.get("ext")
            if ext:
                candidate = os.path.join(output_dir, f"{VENDOR_YOUTUBE}__{vendor_id}.{ext}")
                if os.path.exists(candidate):
                    downloaded_path = candidate

            if not downloaded_path:
                return {
                    "success": False,
                    "strategy": strategy_name,
                    "vendor": VENDOR_YOUTUBE,
                    "vendor_id": vendor_id,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "error": "Could not determine downloaded YouTube file path",
                    "retryable": False,
                    "attempts": attempts,
                }

            compact = build_compact_metadata(
                info,
                url=url,
                vendor=VENDOR_YOUTUBE,
                vendor_id=vendor_id,
                downloaded_path=downloaded_path,
            )

            raw_mode = (app_config or {}).get("raw_metadata_mode", "gzip")
            raw_path = write_raw_metadata(
                info,
                metadata_dir=metadata_dir,
                vendor=VENDOR_YOUTUBE,
                vendor_id=vendor_id,
                mode=raw_mode,
            )
            if raw_path:
                compact["raw_metadata_path"] = raw_path

            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(compact, f, indent=2, ensure_ascii=False)

            record = {
                **(registry_record or {}),
                "success": True,
                "strategy": strategy_name,
                "output_path": downloaded_path,
                "metadata": info,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "attempts": attempts,
                "vendor": VENDOR_YOUTUBE,
                "vendor_id": vendor_id,
                "metadata_file": os.path.basename(metadata_path),
                "metadata_path": metadata_path,
                "original_filename": downloaded_path,
                "to_process": downloaded_path,
            }

            return record

        if attempted_unavailable_source:
            print(f"[youtube] strategy={strategy_name} exhausted cookie sources; trying next strategy")

    final_attempt = attempts[-1] if attempts else {}
    return {
        "success": False,
        "strategy": final_attempt.get("strategy"),
        "vendor": VENDOR_YOUTUBE,
        "vendor_id": vendor_id,
        "stdout": final_attempt.get("stdout", ""),
        "stderr": final_attempt.get("stderr", ""),
        "error": "All YouTube strategies failed",
        "retryable": bool(final_attempt.get("retryable")),
        "attempts": attempts,
    }
