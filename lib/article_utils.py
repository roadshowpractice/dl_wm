"""Fetch and extract plain-text article content from URLs.

Used by bin/call_compare_sources.py to pull comparison source articles
alongside video transcripts. Prefers BeautifulSoup for extraction but
falls back to a stdlib HTMLParser-based paragraph extractor when bs4
isn't installed, so this works without adding a new dependency.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - fallback when bs4 isn't installed
    BeautifulSoup = None

USER_AGENT = "Mozilla/5.0 (compatible; dl_wm-compare-sources/1.0)"


class _ParagraphParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paragraphs: list[str] = []
        self._buf: list[str] = []
        self._capture = False

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self._capture = True

    def handle_endtag(self, tag):
        if tag == "p" and self._capture:
            text = "".join(self._buf).strip()
            if text:
                self.paragraphs.append(text)
            self._buf = []
            self._capture = False

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)


def fetch_html(url: str, timeout: int = 15) -> str:
    """Fetch a URL's HTML source using a browser-like User-Agent."""
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response.text


def extract_article_text(html_content: str) -> str:
    """Return clean paragraph text from raw HTML."""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_content, "html.parser")
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    else:
        parser = _ParagraphParser()
        parser.feed(html_content)
        paragraphs = parser.paragraphs

    return "\n\n".join(p for p in paragraphs if p.strip())


def slugify_url(url: str) -> str:
    """Turn a URL into a filesystem-safe slug based on its host and path."""
    stripped = re.sub(r"^https?://", "", url)
    stripped = re.sub(r"^www\.", "", stripped)
    return re.sub(r"\W+", "-", stripped).strip("-")[:120]


def save_article(url: str, outdir: Path) -> Path | None:
    """Fetch a URL, extract its article text, and write it under outdir.

    Returns the output path, or None if the fetch/extraction failed.
    """
    try:
        html_content = fetch_html(url)
    except requests.RequestException:
        return None

    text = extract_article_text(html_content)
    if not text.strip():
        return None

    outdir.mkdir(parents=True, exist_ok=True)
    output_path = outdir / f"{slugify_url(url)}.txt"
    output_path.write_text(text, encoding="utf-8")
    return output_path
