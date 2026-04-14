from __future__ import annotations

import hashlib
from html import unescape
import re
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from urllib.parse import urlparse

import requests


TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
META_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?P<key>[^"\']+)["\'][^>]+content=["\'](?P<value>[^"\']+)["\']',
    re.IGNORECASE,
)
SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
BLOCK_RE = re.compile(r"<(h1|h2|h3|p|li)[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
AT_HANDLE_RE = re.compile(r"@\w+")
NON_SIGNAL_LINE_RE = re.compile(
    r"(cookie|privacy|terms|login|sign up|get started|open main menu|skip to|copyright)",
    re.IGNORECASE,
)
WHITESPACE_RE = re.compile(r"\s+")
DOMAIN_EXTRACTORS = {
    "tradingview.com": "extract_tradingview_excerpt",
    "trendspider.com": "extract_trendspider_excerpt",
    "oddsjam.com": "extract_oddsjam_excerpt",
    "pikkit.com": "extract_pikkit_excerpt",
}


@dataclass
class Snapshot:
    source_url: str
    source_type: str
    source_kind: str
    fetched_at: str
    status_code: int
    content_hash: str
    title: str
    body_excerpt: str
    raw_path: str


def fetch_snapshot(source_url: str, raw_dir: Path, timeout: int = 20) -> Snapshot:
    raw_dir.mkdir(parents=True, exist_ok=True)
    response = requests.get(
        source_url,
        timeout=timeout,
        headers={"User-Agent": "market-radar/0.1"},
    )
    response.raise_for_status()

    fetched_at = datetime.now(UTC).isoformat()
    content = response.text
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    title_match = TITLE_RE.search(content)
    title = _clean_text(title_match.group(1)) if title_match else ""
    body_excerpt = _extract_excerpt(source_url, content)[:900]

    raw_path = raw_dir / f"{content_hash}.html"
    raw_path.write_text(content, encoding="utf-8")

    return Snapshot(
        source_url=source_url,
        source_type="web",
        source_kind="page",
        fetched_at=fetched_at,
        status_code=response.status_code,
        content_hash=content_hash,
        title=title,
        body_excerpt=body_excerpt,
        raw_path=str(raw_path),
    )


def _clean_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", unescape(value)).strip()


def _extract_excerpt(source_url: str, html: str) -> str:
    hostname = urlparse(source_url).hostname or ""
    for domain, extractor_name in DOMAIN_EXTRACTORS.items():
        if hostname.endswith(domain):
            return globals()[extractor_name](html)
    return _extract_generic_excerpt(html)


def _extract_generic_excerpt(html: str) -> str:
    without_scripts = SCRIPT_STYLE_RE.sub(" ", html)
    text = TAG_RE.sub(" ", without_scripts)
    return _clean_text(text)


def extract_tradingview_excerpt(html: str) -> str:
    return _compose_excerpt(
        html,
        include_meta_keys={"description", "og:description", "og:title", "twitter:description"},
        max_blocks=12,
    )


def extract_trendspider_excerpt(html: str) -> str:
    return _compose_excerpt(
        html,
        include_meta_keys={"description", "og:description", "og:title"},
        max_blocks=12,
    )


def extract_oddsjam_excerpt(html: str) -> str:
    return _compose_excerpt(
        html,
        include_meta_keys={"description", "og:description", "og:title"},
        max_blocks=14,
    )


def extract_pikkit_excerpt(html: str) -> str:
    return _compose_excerpt(
        html,
        include_meta_keys={"description", "og:description", "og:title", "twitter:description"},
        max_blocks=14,
    )


def _compose_excerpt(html: str, include_meta_keys: set[str], max_blocks: int) -> str:
    without_scripts = SCRIPT_STYLE_RE.sub(" ", html)

    chunks: list[str] = []
    for match in META_RE.finditer(without_scripts):
        key = match.group("key").strip().lower()
        if key not in include_meta_keys:
            continue
        value = _clean_text(match.group("value"))
        if _is_useful_chunk(value):
            chunks.append(value)

    for match in BLOCK_RE.finditer(without_scripts):
        value = _clean_text(TAG_RE.sub(" ", match.group(2)))
        if not _is_useful_chunk(value):
            continue
        chunks.append(value)
        if len(chunks) >= max_blocks:
            break

    if not chunks:
        return _extract_generic_excerpt(html)

    return _clean_text(" ".join(_dedupe_preserve_order(chunks)))


def _is_useful_chunk(value: str) -> bool:
    if not value:
        return False
    if len(value) < 18:
        return False
    if AT_HANDLE_RE.search(value):
        return False
    if NON_SIGNAL_LINE_RE.search(value):
        return False
    alpha_count = sum(char.isalpha() for char in value)
    if alpha_count < max(10, int(len(value) * 0.35)):
        return False
    return True


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result
