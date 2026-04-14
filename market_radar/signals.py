from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from market_radar.scoring import (
    recommendation_for,
    score_actionability,
    score_market_strength,
    score_repo_fit,
)


KEYWORD_MAP = {
    "scanner_logic_change": [
        "scanner",
        "screener",
        "filter",
        "scan",
        "ranking",
        "watchlist",
    ],
    "signal_explainability": [
        "explain",
        "reason",
        "transparen",
        "confidence",
        "why",
        "signal quality",
    ],
    "backtesting_or_review_feature": [
        "backtest",
        "review",
        "journal",
        "analytics",
        "performance",
        "history",
    ],
    "alerting_or_execution_feature": [
        "alert",
        "notification",
        "execution",
        "workflow",
        "automation",
    ],
    "portfolio_or_journal_link": [
        "portfolio",
        "journal",
        "trades",
        "outcome",
        "tagging",
    ],
    "ai_assistant_or_automation": [
        "ai",
        "assistant",
        "copilot",
        "automation",
        "agent",
    ],
    "ui_speed_or_operator_workflow": [
        "dashboard",
        "workflow",
        "tab",
        "panel",
        "faster",
        "layout",
    ],
    "pricing_or_packaging_change": [
        "pricing",
        "plan",
        "tier",
        "pro",
        "premium",
        "subscription",
    ],
    "odds_or_market_coverage_change": [
        "odds",
        "line",
        "market",
        "book",
        "sportsbook",
        "coverage",
    ],
    "clv_or_roi_analytics": [
        "clv",
        "roi",
        "yield",
        "performance",
        "analytics",
        "edge",
    ],
    "bankroll_or_portfolio_review": [
        "bankroll",
        "stake",
        "unit",
        "portfolio",
        "tracking",
    ],
    "bet_sync_or_execution_support": [
        "sync",
        "execution",
        "slip",
        "place bet",
        "booksync",
        "shopping",
    ],
    "signal_confidence_or_explanation": [
        "confidence",
        "expected value",
        "ev",
        "explain",
        "model",
    ],
    "ai_or_model_feature": [
        "ai",
        "model",
        "prediction",
        "assistant",
        "automation",
    ],
    "social_or_copy_betting_feature": [
        "social",
        "community",
        "copy",
        "follow",
        "leaderboard",
    ],
}

MIN_MATCHES = {
    "pricing_or_packaging_change": 2,
    "ai_assistant_or_automation": 1,
    "ai_or_model_feature": 1,
    "social_or_copy_betting_feature": 2,
}

STRONG_KEYWORDS = {
    "pricing_or_packaging_change": {"pricing", "plan", "tier", "subscription"},
    "ai_assistant_or_automation": {"assistant", "copilot", "automation", "agent"},
    "ai_or_model_feature": {"model", "prediction", "assistant", "automation"},
    "social_or_copy_betting_feature": {"copy", "leaderboard", "community", "social"},
}

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class CandidateSignal:
    product_slug: str
    competitor_slug: str
    competitor_tier: str
    signal_type: str
    title: str
    summary: str
    source_url: str
    source_type: str
    source_kind: str
    detected_at: str
    changed: bool
    keyword_hits: int
    evidence: list[str]
    detection_mode: str


def generate_signals(connection: sqlite3.Connection, config: dict) -> int:
    product_map = {product["slug"]: product for product in config.get("products", [])}
    competitor_map = {}
    for product in config.get("products", []):
        for competitor in product.get("competitors", []):
            competitor_map[competitor["slug"]] = {
                "product_slug": product["slug"],
                "tier": competitor["tier"],
                "name": competitor["name"],
            }

    rows = connection.execute(
        """
        SELECT id, competitor_slug, source_url, fetched_at, title, body_excerpt, content_hash
             , COALESCE(source_type, '') AS source_type, COALESCE(source_kind, '') AS source_kind
        FROM source_snapshots
        ORDER BY competitor_slug, source_url, fetched_at DESC
        """
    ).fetchall()

    grouped: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[(row["competitor_slug"], row["source_url"])].append(row)

    inserted = 0
    for (competitor_slug, source_url), snapshots in grouped.items():
        competitor_info = competitor_map.get(competitor_slug)
        if not competitor_info:
            continue

        latest = snapshots[0]
        previous = snapshots[1] if len(snapshots) > 1 else None
        changed = previous is None or latest["content_hash"] != previous["content_hash"]
        product_slug = competitor_info["product_slug"]
        product = product_map[product_slug]

        candidates = build_candidate_signals(
            product_slug=product_slug,
            competitor_slug=competitor_slug,
            competitor_tier=competitor_info["tier"],
            source_url=source_url,
            source_type=latest["source_type"] or infer_source_type(source_url),
            source_kind=latest["source_kind"] or infer_source_kind(source_url),
            latest=latest,
            previous=previous,
            priority_signal_types=product.get("priority_signal_types", []),
        )

        for candidate in candidates:
            # Duplikat-Pruefung: gleicher content_hash fuer selbe Quelle ueberspringen
            existing = connection.execute(
                """
                SELECT 1 FROM market_signals ms
                JOIN source_snapshots ss
                  ON ss.competitor_slug = ms.competitor_slug
                 AND ss.source_url = ms.source_url
                WHERE ms.product_slug = ?
                  AND ms.competitor_slug = ?
                  AND ms.signal_type = ?
                  AND ms.source_url = ?
                  AND ss.content_hash = ?
                LIMIT 1
                """,
                (
                    candidate.product_slug,
                    candidate.competitor_slug,
                    candidate.signal_type,
                    candidate.source_url,
                    latest["content_hash"],
                ),
            ).fetchone()
            if existing:
                continue

            repo_fit = score_repo_fit(candidate.signal_type, candidate.competitor_tier)
            market_strength = score_market_strength(
                candidate.signal_type,
                candidate.competitor_tier,
                candidate.changed,
                candidate.keyword_hits,
            )
            actionability = score_actionability(
                candidate.signal_type,
                candidate.changed,
                candidate.keyword_hits,
            )
            recommendation = recommendation_for(repo_fit, market_strength, actionability)

            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO market_signals (
                    product_slug, competitor_slug, signal_type, title, summary,
                    source_url, source_type, source_kind, detected_at, repo_fit, market_strength, actionability,
                    recommendation, detection_mode, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.product_slug,
                    candidate.competitor_slug,
                    candidate.signal_type,
                    candidate.title,
                    candidate.summary,
                    candidate.source_url,
                    candidate.source_type,
                    candidate.source_kind,
                    candidate.detected_at,
                    repo_fit,
                    market_strength,
                    actionability,
                    recommendation,
                    candidate.detection_mode,
                    json.dumps(candidate.evidence),
                ),
            )
            inserted += cursor.rowcount

    connection.commit()
    return inserted


def build_candidate_signals(
    product_slug: str,
    competitor_slug: str,
    competitor_tier: str,
    source_url: str,
    source_type: str,
    source_kind: str,
    latest: sqlite3.Row,
    previous: sqlite3.Row | None,
    priority_signal_types: list[str],
) -> list[CandidateSignal]:
    latest_text = f"{latest['title']} {latest['body_excerpt']}".lower()
    previous_text = (
        f"{previous['title']} {previous['body_excerpt']}".lower() if previous else ""
    )
    sentences = [
        sentence.strip()
        for sentence in SENTENCE_SPLIT_RE.split(latest["body_excerpt"] or "")
        if sentence.strip()
    ]

    candidates: list[CandidateSignal] = []
    for signal_type in priority_signal_types:
        matches = [
            keyword
            for keyword in KEYWORD_MAP.get(signal_type, [])
            if keyword_match(keyword, latest_text)
        ]
        if not matches:
            continue
        if not is_signal_match_valid(signal_type, matches):
            continue

        changed = previous is None or latest["content_hash"] != previous["content_hash"]
        mode = "baseline_scan"
        if previous is not None and changed:
            mode = "snapshot_diff"

        evidence = sentences_for_matches(sentences, matches)
        summary = build_summary(signal_type, latest["title"], matches, changed, evidence)

        candidates.append(
            CandidateSignal(
                product_slug=product_slug,
                competitor_slug=competitor_slug,
                competitor_tier=competitor_tier,
                signal_type=signal_type,
                title=f"{competitor_slug}: {humanize_signal_type(signal_type)}",
                summary=summary,
                source_url=source_url,
                source_type=source_type,
                source_kind=source_kind,
                detected_at=latest["fetched_at"],
                changed=changed,
                keyword_hits=len(matches),
                evidence=evidence,
                detection_mode=mode,
            )
        )

    return candidates


def is_signal_match_valid(signal_type: str, matches: list[str]) -> bool:
    min_matches = MIN_MATCHES.get(signal_type, 1)
    if len(matches) >= min_matches:
        return True

    strong_keywords = STRONG_KEYWORDS.get(signal_type, set())
    return any(match in strong_keywords for match in matches)


def keyword_match(keyword: str, text: str) -> bool:
    escaped = re.escape(keyword.lower())
    if " " in keyword or "-" in keyword:
        pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
        return re.search(pattern, text) is not None

    if keyword.endswith("en"):
        pattern = rf"\b{escaped}"
        return re.search(pattern, text) is not None

    pattern = rf"\b{escaped}\b"
    return re.search(pattern, text) is not None


def sentences_for_matches(sentences: list[str], matches: list[str]) -> list[str]:
    evidence: list[str] = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in matches):
            evidence.append(sentence[:220])
        if len(evidence) >= 3:
            break
    if evidence:
        return evidence
    return [f"Matched keywords: {', '.join(matches[:4])}"]


def build_summary(
    signal_type: str,
    page_title: str,
    matches: list[str],
    changed: bool,
    evidence: list[str],
) -> str:
    change_prefix = "Neue oder geaenderte Hinweise auf" if changed else "Bestehende Hinweise auf"
    evidence_text = evidence[0] if evidence else f"Keywords: {', '.join(matches[:3])}"
    return (
        f"{change_prefix} {humanize_signal_type(signal_type).lower()} bei '{page_title}'. "
        f"Signale: {', '.join(matches[:4])}. Hinweis: {evidence_text}"
    )


def infer_source_type(source_url: str) -> str:
    return "github" if source_url.startswith("github://") else "web"


def infer_source_kind(source_url: str) -> str:
    if source_url.startswith("github://"):
        if source_url.endswith("/readme"):
            return "readme"
        if source_url.endswith("/release"):
            return "release"
    return "page"


def humanize_signal_type(signal_type: str) -> str:
    return signal_type.replace("_", " ").strip().title()


def build_decision_queue(
    connection: sqlite3.Connection,
    product_slug: str | None = None,
    limit: int = 10,
) -> list[dict]:
    params: list[object] = []
    where = ""
    if product_slug:
        where = "WHERE product_slug = ?"
        params.append(product_slug)

    # Deduplizierung: pro (competitor_slug, signal_type) nur den hoechsten Score behalten
    query = f"""
        SELECT product_slug, competitor_slug, signal_type, title, summary,
               recommendation, repo_fit, market_strength, actionability,
               detected_at, source_type, source_kind, source_url
        FROM (
            SELECT ms.product_slug, ms.competitor_slug, ms.signal_type, ms.title, ms.summary,
                   ms.recommendation, ms.repo_fit, ms.market_strength, ms.actionability,
                   ms.detected_at, ms.source_type, ms.source_kind, ms.source_url,
                   ROW_NUMBER() OVER (
                       PARTITION BY ms.competitor_slug, ms.signal_type
                       ORDER BY (ms.repo_fit * 0.45 + ms.market_strength * 0.2 + ms.actionability * 0.35) DESC,
                                ms.detected_at DESC
                   ) AS rn
            FROM market_signals ms
            JOIN (
                SELECT product_slug, competitor_slug, signal_type, MAX(detected_at) AS latest_detected_at
                FROM market_signals
                {where}
                GROUP BY product_slug, competitor_slug, signal_type
            ) latest
              ON latest.product_slug = ms.product_slug
             AND latest.competitor_slug = ms.competitor_slug
             AND latest.signal_type = ms.signal_type
             AND latest.latest_detected_at = ms.detected_at
        ) ranked
        WHERE rn = 1
        ORDER BY
            (repo_fit * 0.45 + market_strength * 0.2 + actionability * 0.35) DESC,
            detected_at DESC
        LIMIT ?
    """
    params.append(limit)
    rows = connection.execute(query, params).fetchall()

    queue = []
    for row in rows:
        queue.append(
            {
                "product_slug": row["product_slug"],
                "competitor_slug": row["competitor_slug"],
                "signal_type": row["signal_type"],
                "title": row["title"],
                "summary": row["summary"],
                "recommendation": row["recommendation"],
                "source_type": row["source_type"] or infer_source_type(row["source_url"]),
                "source_kind": row["source_kind"] or infer_source_kind(row["source_url"]),
                "source_url": row["source_url"],
                "priority_score": round(
                    row["repo_fit"] * 0.45
                    + row["market_strength"] * 0.2
                    + row["actionability"] * 0.35,
                    4,
                ),
                "detected_at": row["detected_at"],
            }
        )
    return queue
