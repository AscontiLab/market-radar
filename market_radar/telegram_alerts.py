"""Telegram-Alerts fuer Market Radar — Adopt-Now-Signale per Push-Nachricht."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import requests

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_alert(signal: dict, bot_token: str, chat_id: str) -> bool:
    """Sendet ein einzelnes Signal als Telegram-Nachricht (HTML parse mode).

    Returns True bei Erfolg, False bei Fehler.
    """
    label = signal.get("title", "Unbekanntes Signal")
    competitor = signal.get("competitor_slug", "?")
    product = signal.get("product_slug", "?")
    score = signal.get("priority_score", 0.0)
    summary = signal.get("summary", "")
    llm_summary = signal.get("llm_summary") or ""
    source_url = signal.get("source_url", "")

    lines = [
        "\U0001f514 <b>Market Radar: Adopt Now</b>",
        "",
        f"<b>{label}</b> bei {competitor}",
        f"Produkt: {product}",
        f"Score: {score:.3f}",
        "",
        summary,
    ]

    if llm_summary:
        lines.append("")
        lines.append(f"KI: {llm_summary}")

    if source_url:
        lines.append("")
        lines.append(f'\U0001f517 <a href="{source_url}">Quelle</a>')

    text = "\n".join(lines)

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        url = TELEGRAM_API_URL.format(token=bot_token)
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"Telegram-Fehler: HTTP {response.status_code} — {response.text[:200]}")
            return False
        return True
    except Exception as exc:
        print(f"Telegram-Fehler: {exc}")
        return False


def send_digest_alerts(
    connection: sqlite3.Connection,
    config: dict,
    bot_token: str,
    chat_id: str,
    since_hours: int = 24,
) -> int:
    """Sendet Telegram-Alerts fuer neue Adopt-Now-Signale.

    - Filtert auf recommendation = 'adopt_now' oder llm_recommendation = 'adopt_now'
    - Prueft llm_confidence > 0.6 (wenn vorhanden)
    - Markiert gesendete Signale mit telegram_sent_at
    - Returns Anzahl gesendeter Nachrichten
    """
    query = """
        SELECT id, product_slug, competitor_slug, signal_type, title, summary,
               source_url, source_type, source_kind, detected_at,
               repo_fit, market_strength, actionability,
               recommendation, llm_summary, llm_confidence, llm_recommendation
        FROM market_signals
        WHERE telegram_sent_at IS NULL
          AND detected_at >= datetime('now', ?)
          AND (
              recommendation = 'adopt_now'
              OR llm_recommendation = 'adopt_now'
          )
          AND (llm_confidence IS NULL OR llm_confidence > 0.6)
        ORDER BY detected_at DESC
    """

    since_param = f"-{since_hours} hours"
    rows = connection.execute(query, (since_param,)).fetchall()

    sent_count = 0
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        signal = dict(row)

        # Priority-Score berechnen (analog signals.py)
        repo_fit = signal.get("repo_fit") or 0.0
        market_strength = signal.get("market_strength") or 0.0
        actionability = signal.get("actionability") or 0.0
        signal["priority_score"] = round(
            repo_fit * 0.45 + market_strength * 0.2 + actionability * 0.35,
            4,
        )

        ok = send_alert(signal, bot_token, chat_id)
        if ok:
            connection.execute(
                "UPDATE market_signals SET telegram_sent_at = ? WHERE id = ?",
                (now, signal["id"]),
            )
            sent_count += 1

    connection.commit()
    return sent_count
