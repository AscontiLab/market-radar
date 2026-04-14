from __future__ import annotations

from collections import defaultdict

from market_radar.signals import build_decision_queue


SIGNAL_LABELS = {
    "scanner_logic_change": "Scanner-Logik",
    "signal_explainability": "Signal-Erklaerung",
    "backtesting_or_review_feature": "Review und Backtesting",
    "alerting_or_execution_feature": "Alerting und Execution",
    "portfolio_or_journal_link": "Portfolio- und Journal-Kopplung",
    "ai_assistant_or_automation": "AI und Automatisierung",
    "ui_speed_or_operator_workflow": "Operator-Workflow",
    "pricing_or_packaging_change": "Pricing und Packaging",
    "odds_or_market_coverage_change": "Odds- und Marktabdeckung",
    "clv_or_roi_analytics": "CLV- und ROI-Analyse",
    "bankroll_or_portfolio_review": "Bankroll- und Portfolio-Review",
    "bet_sync_or_execution_support": "Bet-Sync und Execution",
    "signal_confidence_or_explanation": "Signal-Confidence",
    "ai_or_model_feature": "AI- oder Modell-Feature",
    "social_or_copy_betting_feature": "Social- oder Copy-Betting",
}

SOURCE_KIND_WEIGHT = {
    "release": 1.25,
    "readme": 1.10,
    "page": 1.0,
}


def build_decision_digest(connection, product_slug: str | None = None, limit: int = 5) -> list[dict]:
    queue = build_decision_queue(connection, product_slug=product_slug, limit=60)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in queue:
        grouped[(item["product_slug"], item["signal_type"])].append(item)

    digest: list[dict] = []
    for (product, signal_type), items in grouped.items():
        ordered = sorted(
            items,
            key=lambda item: item["priority_score"] * SOURCE_KIND_WEIGHT.get(item["source_kind"], 1.0),
            reverse=True,
        )
        top = ordered[:3]
        recommendation = digest_recommendation(top)

        llm_summaries = [
            item["llm_summary"] for item in top
            if item.get("llm_summary") is not None
        ]
        llm_confidences = [
            item["llm_confidence"] for item in top
            if item.get("llm_confidence") is not None
        ]
        avg_confidence = (
            round(sum(llm_confidences) / len(llm_confidences), 2)
            if llm_confidences
            else None
        )

        digest.append(
            {
                "product_slug": product,
                "signal_type": signal_type,
                "signal_label": SIGNAL_LABELS.get(signal_type, signal_type),
                "recommendation": recommendation,
                "priority_score": round(
                    sum(item["priority_score"] * SOURCE_KIND_WEIGHT.get(item["source_kind"], 1.0) for item in top)
                    / max(len(top), 1),
                    4,
                ),
                "competitors": [item["competitor_slug"] for item in top],
                "source_mix": sorted({f"{item['source_type']}:{item['source_kind']}" for item in top}),
                "decision": build_decision_text(product, signal_type, top, recommendation),
                "evidence": [item["title"] for item in top],
                "llm_summaries": llm_summaries,
                "avg_confidence": avg_confidence,
            }
        )

    digest.sort(key=lambda item: item["priority_score"], reverse=True)
    return digest[:limit]


def digest_recommendation(items: list[dict]) -> str:
    adopt_count = sum(1 for item in items if item["recommendation"] == "adopt_now")
    github_release_count = sum(1 for item in items if item["source_kind"] == "release")
    avg_score = sum(item["priority_score"] for item in items) / max(len(items), 1)

    if github_release_count >= 2:
        return "adopt_now"
    if adopt_count >= 2 or (adopt_count >= 1 and github_release_count >= 1):
        return "adopt_now"
    if avg_score >= 0.72:
        return "backlog"
    if avg_score >= 0.58:
        return "watch"
    return "differentiate"


def build_decision_text(
    product_slug: str,
    signal_type: str,
    items: list[dict],
    recommendation: str,
) -> str:
    competitors = ", ".join(item["competitor_slug"] for item in items)
    label = SIGNAL_LABELS.get(signal_type, signal_type)
    if recommendation == "adopt_now":
        return f"{label} wird bei {competitors} stark sichtbar. Fuer {product_slug} jetzt aktiv pruefen und in ein konkretes Feature uebersetzen."
    if recommendation == "backlog":
        return f"{label} taucht bei {competitors} wiederholt auf. Fuer {product_slug} in die naechste Roadmap-Runde aufnehmen."
    if recommendation == "watch":
        return f"{label} ist sichtbar, aber noch nicht dominant. Fuer {product_slug} weiter beobachten."
    return f"{label} ist eher ein Differenzierungs- oder Nischensignal. Fuer {product_slug} nicht blind uebernehmen."
