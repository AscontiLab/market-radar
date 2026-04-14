"""Inhaltliches Diff zwischen Snapshots — erkennt WAS sich geaendert hat."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from market_radar.signals import KEYWORD_MAP


# ---------------------------------------------------------------------------
# Datenklasse fuer Diff-Ergebnisse
# ---------------------------------------------------------------------------

@dataclass
class DiffResult:
    """Ergebnis eines inhaltlichen Vergleichs zweier Snapshot-Excerpts."""

    added_phrases: list[str] = field(default_factory=list)
    removed_phrases: list[str] = field(default_factory=list)
    change_summary: str = ""
    change_score: float = 0.0


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    """Teilt Text in Saetze auf (Split an '. ', '! ', '? ')."""
    if not text:
        return []
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    return [s.strip() for s in parts if s.strip()]


def _tokenize(text: str) -> set[str]:
    """Einfache Whitespace-Tokenisierung, lowercase."""
    return set(text.lower().split())


def _jaccard_distance(tokens_a: set[str], tokens_b: set[str]) -> float:
    """1 - Jaccard-Aehnlichkeit. Gibt 0.0 bei identisch, 1.0 bei komplett verschieden."""
    if not tokens_a and not tokens_b:
        return 0.0
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    intersection = tokens_a & tokens_b
    return round(1.0 - len(intersection) / len(union), 4)


def _build_change_summary(added_phrases: list[str]) -> str:
    """Erzeugt eine einzeilige deutsche Zusammenfassung basierend auf KEYWORD_MAP."""
    if not added_phrases:
        return "Keine inhaltlichen Aenderungen erkannt"

    added_text = " ".join(added_phrases).lower()
    matched_types: list[str] = []

    for signal_type, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            if kw.lower() in added_text:
                # Signaltyp-Name lesbarer machen
                label = signal_type.replace("_", " ").replace(" or ", "/")
                matched_types.append(label)
                break

    if matched_types:
        types_str = ", ".join(matched_types[:3])
        return f"Neue Hinweise auf: {types_str}"

    # Fallback: erste Woerter der neuen Phrasen nennen
    preview_words = added_text.split()[:6]
    return f"Neuer Inhalt: {' '.join(preview_words)}..."


# ---------------------------------------------------------------------------
# Kernfunktion: Diff zwischen zwei Excerpts
# ---------------------------------------------------------------------------

def compute_diff(old_excerpt: str, new_excerpt: str) -> DiffResult:
    """Vergleicht zwei body_excerpts und gibt ein DiffResult zurueck.

    - added_phrases:  Saetze die neu hinzugekommen sind
    - removed_phrases: Saetze die verschwunden sind
    - change_score:   Token-basierte Jaccard-Distanz (0.0 = identisch, 1.0 = komplett anders)
    - change_summary: Einzeilige deutsche Zusammenfassung
    """
    old_sentences = _split_sentences(old_excerpt or "")
    new_sentences = _split_sentences(new_excerpt or "")

    old_set = set(old_sentences)
    new_set = set(new_sentences)

    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)

    old_tokens = _tokenize(old_excerpt or "")
    new_tokens = _tokenize(new_excerpt or "")
    score = _jaccard_distance(old_tokens, new_tokens)

    summary = _build_change_summary(added)

    return DiffResult(
        added_phrases=added,
        removed_phrases=removed,
        change_summary=summary,
        change_score=score,
    )


# ---------------------------------------------------------------------------
# Diff fuer die letzten zwei Snapshots eines Competitors
# ---------------------------------------------------------------------------

def diff_latest_snapshots(
    connection: sqlite3.Connection,
    competitor_slug: str,
    source_url: str,
) -> DiffResult | None:
    """Holt die zwei neuesten Snapshots und vergleicht sie.

    Gibt None zurueck wenn weniger als 2 Snapshots existieren
    oder die Content-Hashes identisch sind.
    """
    rows = connection.execute(
        """
        SELECT content_hash, body_excerpt
        FROM source_snapshots
        WHERE competitor_slug = ? AND source_url = ?
        ORDER BY fetched_at DESC
        LIMIT 2
        """,
        (competitor_slug, source_url),
    ).fetchall()

    if len(rows) < 2:
        return None

    newest_hash, newest_excerpt = rows[0]
    older_hash, older_excerpt = rows[1]

    # Keine Aenderung wenn Hashes identisch
    if newest_hash and older_hash and newest_hash == older_hash:
        return None

    return compute_diff(
        old_excerpt=older_excerpt or "",
        new_excerpt=newest_excerpt or "",
    )


# ---------------------------------------------------------------------------
# Batch-Diff ueber alle Competitor+Source-Paare
# ---------------------------------------------------------------------------

def batch_diff_all(connection: sqlite3.Connection) -> list[dict]:
    """Fuehrt Diffs fuer alle Competitor+Source-Paare mit 2+ Snapshots durch.

    Rueckgabe: Liste von Dicts sortiert nach change_score absteigend.
    """
    # Alle Paare mit mindestens 2 Snapshots finden
    pairs = connection.execute(
        """
        SELECT competitor_slug, source_url
        FROM source_snapshots
        GROUP BY competitor_slug, source_url
        HAVING COUNT(*) >= 2
        """
    ).fetchall()

    results: list[dict] = []

    for competitor_slug, source_url in pairs:
        diff = diff_latest_snapshots(connection, competitor_slug, source_url)
        if diff is None:
            continue

        results.append({
            "competitor_slug": competitor_slug,
            "source_url": source_url,
            "change_score": diff.change_score,
            "change_summary": diff.change_summary,
            "added_count": len(diff.added_phrases),
            "removed_count": len(diff.removed_phrases),
        })

    results.sort(key=lambda r: r["change_score"], reverse=True)
    return results
