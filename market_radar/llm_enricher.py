"""LLM-basierte Signal-Anreicherung via Claude Haiku.

Erwartet folgende zusaetzliche Spalten in market_signals (Migration noetig):
    llm_summary TEXT        -- LLM-generierte Zusammenfassung
    llm_confidence REAL     -- Signal-Konfidenz 0.0-1.0
    llm_recommendation TEXT -- adopt_now / backlog / watch / ignore / differentiate
    llm_keywords TEXT       -- komma-separierte Keywords
    llm_model TEXT          -- verwendetes Modell
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MAX_TOKENS = 300
TEMPERATURE = 0.2
BODY_EXCERPT_LIMIT = 600
RATE_LIMIT_DELAY = 0.5

VALID_RECOMMENDATIONS = {"adopt_now", "backlog", "watch", "ignore", "differentiate"}

SYSTEM_PROMPT = (
    "Du bist ein Markt-Analyst fuer Software-Produkte. "
    "Bewerte ob das folgende Signal eine echte Produktbewegung oder Rauschen ist."
)

USER_PROMPT_TEMPLATE = """\
Wettbewerber: {competitor_name}
Signal-Typ: {signal_type}
Seitentitel: {page_title}
Produkt-Ziel: {objective}

--- Textauszug (max. 600 Zeichen) ---
{body_excerpt}
--- Ende ---

Antworte ausschliesslich als JSON mit folgenden Schlüsseln:
- "confidence": float 0.0-1.0 (ist das ein echtes Produktsignal?)
- "summary": string (1-2 Saetze auf Deutsch: was macht der Wettbewerber?)
- "recommendation": string (einer von: adopt_now, backlog, watch, ignore, differentiate)
- "keywords": array of strings (relevanteste Feature-Keywords)

Nur JSON, kein Markdown, keine Erklaerung.
"""


@dataclass
class EnrichmentResult:
    """Ergebnis einer LLM-Anreicherung."""

    confidence: float = 0.0
    llm_summary: str = ""
    llm_recommendation: str = "watch"
    keywords: list[str] = field(default_factory=list)
    model_used: str = MODEL


def _get_api_key() -> str:
    """Read Anthropic API key from environment."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY ist nicht gesetzt. Bitte als Umgebungsvariable setzen."
        )
    return key


def _build_prompt(
    signal_row: dict, body_excerpt: str, product_config: dict
) -> str:
    """Build the user prompt for Claude Haiku."""
    return USER_PROMPT_TEMPLATE.format(
        competitor_name=signal_row.get("competitor_slug", "unbekannt"),
        signal_type=signal_row.get("signal_type", "unbekannt"),
        page_title=signal_row.get("title", ""),
        objective=product_config.get("objective", "Nicht definiert"),
        body_excerpt=(body_excerpt or "")[:BODY_EXCERPT_LIMIT],
    )


def _parse_response(response_text: str) -> dict:
    """Parse Claude's JSON response with fallback for malformed output."""
    # Strip potential markdown code fences
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first and last fence lines
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM-Antwort ist kein valides JSON: %s", text[:200])
        return {}

    return data


def enrich_signal(
    signal_row: dict, body_excerpt: str, product_config: dict
) -> EnrichmentResult:
    """Enrich a single signal via Claude Haiku API call.

    Args:
        signal_row: Dict from market_signals table.
        body_excerpt: Text excerpt from the source snapshot.
        product_config: Product configuration dict with 'objective' key.

    Returns:
        EnrichmentResult with LLM assessment. On error returns defaults
        with confidence=0.
    """
    try:
        api_key = _get_api_key()
    except EnvironmentError as exc:
        logger.error(str(exc))
        return EnrichmentResult()

    prompt = _build_prompt(signal_row, body_excerpt, product_config)

    try:
        response = requests.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "temperature": TEMPERATURE,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("API-Aufruf fehlgeschlagen: %s", exc)
        return EnrichmentResult()

    response_json = response.json()
    content_blocks = response_json.get("content", [])
    if not content_blocks:
        logger.warning("Leere Antwort von Claude API")
        return EnrichmentResult()

    response_text = content_blocks[0].get("text", "")
    parsed = _parse_response(response_text)

    if not parsed:
        return EnrichmentResult()

    confidence = parsed.get("confidence", 0.0)
    try:
        confidence = float(confidence)
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.0

    recommendation = parsed.get("recommendation", "watch")
    if recommendation not in VALID_RECOMMENDATIONS:
        recommendation = "watch"

    keywords = parsed.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(k) for k in keywords if k]

    return EnrichmentResult(
        confidence=confidence,
        llm_summary=str(parsed.get("summary", "")),
        llm_recommendation=recommendation,
        keywords=keywords,
        model_used=response_json.get("model", MODEL),
    )


def enrich_batch(
    connection: sqlite3.Connection, config: dict, limit: int = 10
) -> int:
    """Enrich up to `limit` signals that have no LLM summary yet.

    Args:
        connection: SQLite connection (row_factory=sqlite3.Row expected).
        config: Full config dict with 'products' list.
        limit: Max number of signals to enrich per call.

    Returns:
        Number of successfully enriched signals.
    """
    # Ensure LLM columns exist
    _ensure_llm_columns(connection)

    # Build product config lookup
    product_map: dict[str, dict] = {}
    for product in config.get("products", []):
        product_map[product["slug"]] = product

    # Fetch un-enriched signals
    rows = connection.execute(
        """
        SELECT id, product_slug, competitor_slug, signal_type, title,
               summary, source_url, detected_at
        FROM market_signals
        WHERE llm_summary IS NULL
        ORDER BY detected_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    if not rows:
        logger.info("Keine nicht-angereicherten Signale gefunden.")
        return 0

    enriched_count = 0

    for i, row in enumerate(rows):
        signal_dict = dict(row)

        # Lookup body_excerpt from latest snapshot
        snapshot = connection.execute(
            """
            SELECT body_excerpt
            FROM source_snapshots
            WHERE competitor_slug = ? AND source_url = ?
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            (row["competitor_slug"], row["source_url"]),
        ).fetchone()

        body_excerpt = snapshot["body_excerpt"] if snapshot else ""
        product_config = product_map.get(row["product_slug"], {})

        result = enrich_signal(signal_dict, body_excerpt or "", product_config)

        if result.confidence == 0.0 and not result.llm_summary:
            logger.warning(
                "Anreicherung fuer Signal %d fehlgeschlagen, uebersprungen.",
                row["id"],
            )
            continue

        connection.execute(
            """
            UPDATE market_signals
            SET llm_summary = ?,
                llm_confidence = ?,
                llm_recommendation = ?,
                llm_keywords = ?,
                llm_model = ?
            WHERE id = ?
            """,
            (
                result.llm_summary,
                result.confidence,
                result.llm_recommendation,
                ", ".join(result.keywords),
                result.model_used,
                row["id"],
            ),
        )
        enriched_count += 1

        # Rate limiting between calls (skip after last)
        if i < len(rows) - 1:
            time.sleep(RATE_LIMIT_DELAY)

    connection.commit()
    logger.info("%d von %d Signalen angereichert.", enriched_count, len(rows))
    return enriched_count


def _ensure_llm_columns(connection: sqlite3.Connection) -> None:
    """Add LLM enrichment columns to market_signals if missing."""
    existing = {
        col["name"]
        for col in connection.execute("PRAGMA table_info(market_signals)")
    }
    columns = {
        "llm_summary": "TEXT",
        "llm_confidence": "REAL",
        "llm_recommendation": "TEXT",
        "llm_keywords": "TEXT",
        "llm_model": "TEXT",
    }
    for col_name, col_type in columns.items():
        if col_name not in existing:
            connection.execute(
                f"ALTER TABLE market_signals ADD COLUMN {col_name} {col_type}"
            )
