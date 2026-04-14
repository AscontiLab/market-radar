"""Translate digest entries into actionable feature suggestions."""

from __future__ import annotations


FEATURE_TEMPLATES: dict[str, list[str]] = {
    "scanner_logic_change": [
        "Neuen Filter/Screener-Parameter hinzufuegen: {keywords}",
        "Ranking-Algorithmus um {keywords} erweitern",
    ],
    "signal_explainability": [
        "Signal-Begruendung im Dashboard anzeigen (warum wurde dieses Signal ausgeloest?)",
        "Confidence-Score pro Signal einfuehren",
    ],
    "backtesting_or_review_feature": [
        "Backtesting-Modul: historische Performance der Signale auswerten",
        "Review-Dashboard: vergangene Signale nach Erfolg bewerten",
    ],
    "alerting_or_execution_feature": [
        "Telegram-Alert erweitern: {keywords}-basierte Benachrichtigungen",
        "Alert-Regeln konfigurierbar machen (Schwellwerte, Kombinations-Alerts)",
    ],
    "portfolio_or_journal_link": [
        "Trading-Journal: Signale mit tatsaechlichen Trades verknuepfen",
        "Portfolio-Ansicht: offene Positionen neben aktiven Signalen zeigen",
    ],
    "ai_assistant_or_automation": [
        "KI-Zusammenfassung: taegliche Signal-Analyse per Claude Haiku",
        "Automatische Signal-Priorisierung per LLM",
    ],
    "ui_speed_or_operator_workflow": [
        "Dashboard-Performance optimieren (lazy loading, partial updates)",
        "Keyboard-Shortcuts fuer haeufige Aktionen",
    ],
    "pricing_or_packaging_change": [
        "Beobachten und Pricing-Strategie dokumentieren",
    ],
    "odds_or_market_coverage_change": [
        "Neue Liga/Markt hinzufuegen: {keywords}",
        "Odds-Provider erweitern fuer bessere Line-Abdeckung",
    ],
    "clv_or_roi_analytics": [
        "CLV-Tracking implementieren (Closing Line Value)",
        "ROI-Dashboard mit Zeitreihen-Analyse",
    ],
    "bankroll_or_portfolio_review": [
        "Bankroll-Management-Dashboard mit Kelly-Criterion-Anzeige",
        "Gewinn/Verlust-Uebersicht nach Zeitraum und Strategie",
    ],
    "bet_sync_or_execution_support": [
        "Bet-Tracking automatisieren (manuelle Eingabe vereinfachen)",
        "Schnell-Wett-Button mit vorberechneten Stakes",
    ],
    "signal_confidence_or_explanation": [
        "Signal-Confidence prominent im Dashboard anzeigen",
        "Erklaerungstext pro Signal generieren (EV-Breakdown)",
    ],
    "ai_or_model_feature": [
        "Eigenes Prediction-Modell trainieren/evaluieren",
        "Model-Vergleich: eigenes Modell vs. Marktquoten",
    ],
    "social_or_copy_betting_feature": [
        "Bewusst ignorieren — Social/Copy-Features passen nicht zur Strategie",
    ],
}

# Map recommendation to priority level
_RECOMMENDATION_PRIORITY = {
    "adopt_now": "high",
    "backlog": "medium",
    "watch": "low",
    "differentiate": "low",
}

_PRIORITY_SORT_KEY = {"high": 0, "medium": 1, "low": 2}


def _extract_keywords(entry: dict) -> str:
    """Extract keywords from a digest entry for template filling."""
    # Try llm_keywords from the underlying signals first
    for summary in entry.get("llm_summaries", []):
        if summary:
            # Use first LLM summary as fallback keyword source
            words = summary.split()[:5]
            return " ".join(words)

    # Fall back to evidence titles
    evidence = entry.get("evidence", [])
    if evidence:
        titles = [t for t in evidence if t]
        if titles:
            return titles[0][:60]

    # Fall back to competitors
    competitors = entry.get("competitors", [])
    if competitors:
        return ", ".join(competitors)

    return entry.get("signal_type", "unbekannt")


def generate_feature_suggestions(
    digest: list[dict],
    config: dict,
) -> list[dict]:
    """Generate actionable feature suggestions from digest entries.

    Only processes entries with recommendation 'adopt_now' or 'backlog'.
    Returns sorted list with high-priority suggestions first.
    """
    suggestions: list[dict] = []

    for entry in digest:
        recommendation = entry.get("recommendation", "")
        if recommendation not in ("adopt_now", "backlog"):
            continue

        signal_type = entry.get("signal_type", "")
        templates = FEATURE_TEMPLATES.get(signal_type, [])
        if not templates:
            continue

        keywords = _extract_keywords(entry)
        priority = _RECOMMENDATION_PRIORITY.get(recommendation, "low")

        for template in templates:
            suggestion_text = template.replace("{keywords}", keywords)
            suggestions.append(
                {
                    "product_slug": entry.get("product_slug", ""),
                    "signal_type": signal_type,
                    "signal_label": entry.get("signal_label", signal_type),
                    "recommendation": recommendation,
                    "suggestion": suggestion_text,
                    "priority": priority,
                    "competitors": entry.get("competitors", []),
                }
            )

    suggestions.sort(key=lambda s: _PRIORITY_SORT_KEY.get(s["priority"], 99))
    return suggestions


def format_suggestions_text(suggestions: list[dict]) -> str:
    """Format suggestions as readable German text, grouped by product_slug."""
    if not suggestions:
        return "Keine Feature-Vorschlaege vorhanden."

    # Group by product_slug
    by_product: dict[str, list[dict]] = {}
    for s in suggestions:
        slug = s["product_slug"]
        by_product.setdefault(slug, []).append(s)

    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("FEATURE-VORSCHLAEGE AUS MARKET RADAR")
    lines.append("=" * 70)

    for product_slug, items in sorted(by_product.items()):
        lines.append("")
        lines.append(f"--- {product_slug} ---")
        lines.append("")

        for item in items:
            priority_tag = item["priority"].upper()
            competitors_str = ", ".join(item["competitors"])
            lines.append(f"  [{priority_tag}] {item['suggestion']}")
            lines.append(f"         Signal: {item['signal_label']} | Konkurrenten: {competitors_str}")
            lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)
