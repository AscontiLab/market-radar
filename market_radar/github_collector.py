from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests


GITHUB_API = "https://api.github.com"
WHITESPACE_RE = re.compile(r"\s+")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
MARKDOWN_CODE_RE = re.compile(r"`([^`]+)`")
MARKDOWN_HEADER_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
MARKDOWN_DECORATOR_RE = re.compile(r"[*_>#-]+")
HTML_TAG_RE = re.compile(r"<[^>]+>")
FRONTMATTER_RE = re.compile(r"^---\s.*?\s---\s", re.DOTALL)


@dataclass
class GitHubSnapshot:
    source_url: str
    source_type: str
    source_kind: str
    fetched_at: str
    status_code: int
    content_hash: str
    title: str
    body_excerpt: str
    raw_path: str


def fetch_github_readme(repo_name: str, raw_dir: Path, token: str | None = None) -> GitHubSnapshot:
    url = f"{GITHUB_API}/repos/{repo_name}/readme"
    response = requests.get(url, timeout=20, headers=_headers(token))
    response.raise_for_status()
    payload = response.json()

    raw_content = base64.b64decode(payload["content"]).decode("utf-8", errors="replace")
    excerpt = markdown_excerpt(raw_content)
    fetched_at = datetime.now(UTC).isoformat()
    blob = {
        "repo": repo_name,
        "kind": "readme",
        "name": payload.get("name"),
        "path": payload.get("path"),
        "sha": payload.get("sha"),
        "content": raw_content,
    }
    return _to_snapshot(
        repo_name=repo_name,
        kind="readme",
        title=f"GitHub README: {repo_name}",
        body_excerpt=excerpt,
        payload=blob,
        status_code=response.status_code,
        fetched_at=fetched_at,
        raw_dir=raw_dir,
    )


def fetch_github_latest_release(
    repo_name: str,
    raw_dir: Path,
    token: str | None = None,
) -> GitHubSnapshot | None:
    url = f"{GITHUB_API}/repos/{repo_name}/releases/latest"
    response = requests.get(url, timeout=20, headers=_headers(token))
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()

    release_text = "\n".join(
        filter(
            None,
            [
                payload.get("name"),
                payload.get("tag_name"),
                payload.get("body"),
            ],
        )
    )
    excerpt = release_excerpt(payload)
    fetched_at = datetime.now(UTC).isoformat()
    release_title = payload.get("name") or payload.get("tag_name") or "Latest release"
    return _to_snapshot(
        repo_name=repo_name,
        kind="release",
        title=f"GitHub Release: {repo_name} - {release_title}",
        body_excerpt=excerpt,
        payload=payload,
        status_code=response.status_code,
        fetched_at=fetched_at,
        raw_dir=raw_dir,
    )


def markdown_excerpt(markdown: str, limit: int = 900) -> str:
    text = FRONTMATTER_RE.sub("", markdown)
    text = MARKDOWN_IMAGE_RE.sub(r"\1", text)
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    text = MARKDOWN_CODE_RE.sub(r"\1", text)
    text = MARKDOWN_HEADER_RE.sub("", text)
    text = MARKDOWN_DECORATOR_RE.sub(" ", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text[:limit]


def release_excerpt(payload: dict, limit: int = 900) -> str:
    parts = [
        payload.get("name") or payload.get("tag_name") or "Latest release",
        payload.get("published_at") or "",
        markdown_excerpt(payload.get("body") or "", limit=1200),
    ]
    text = " ".join(part for part in parts if part).strip()
    return WHITESPACE_RE.sub(" ", text)[:limit]


def _to_snapshot(
    repo_name: str,
    kind: str,
    title: str,
    body_excerpt: str,
    payload: dict,
    status_code: int,
    fetched_at: str,
    raw_dir: Path,
) -> GitHubSnapshot:
    raw_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    raw_path = raw_dir / f"github_{repo_name.replace('/', '__')}_{kind}_{content_hash}.json"
    raw_path.write_text(serialized, encoding="utf-8")
    return GitHubSnapshot(
        source_url=f"github://{repo_name}/{kind}",
        source_type="github",
        source_kind=kind,
        fetched_at=fetched_at,
        status_code=status_code,
        content_hash=content_hash,
        title=title,
        body_excerpt=body_excerpt,
        raw_path=str(raw_path),
    )


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "market-radar/0.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
