from __future__ import annotations


TIER_WEIGHTS = {
    "must_track": 0.95,
    "nice_to_track": 0.6,
    "ignore_for_now": 0.15,
}

SIGNAL_WEIGHTS = {
    "scanner_logic_change": 0.95,
    "signal_explainability": 0.9,
    "backtesting_or_review_feature": 0.9,
    "alerting_or_execution_feature": 0.88,
    "portfolio_or_journal_link": 0.84,
    "ai_assistant_or_automation": 0.72,
    "ui_speed_or_operator_workflow": 0.7,
    "pricing_or_packaging_change": 0.45,
    "odds_or_market_coverage_change": 0.95,
    "clv_or_roi_analytics": 0.92,
    "bankroll_or_portfolio_review": 0.88,
    "bet_sync_or_execution_support": 0.86,
    "signal_confidence_or_explanation": 0.82,
    "ai_or_model_feature": 0.7,
    "social_or_copy_betting_feature": 0.3,
}


def clamp(score: float) -> float:
    return max(0.0, min(1.0, round(score, 4)))


def score_repo_fit(signal_type: str, competitor_tier: str) -> float:
    return clamp(
        SIGNAL_WEIGHTS.get(signal_type, 0.5) * TIER_WEIGHTS.get(competitor_tier, 0.3)
    )


def score_market_strength(
    signal_type: str,
    competitor_tier: str,
    changed: bool,
    keyword_hits: int,
) -> float:
    base = 0.3 + (0.35 if changed else 0.15)
    base += min(keyword_hits, 4) * 0.08
    base += 0.18 if competitor_tier == "must_track" else 0.05
    base += 0.06 if signal_type in {"pricing_or_packaging_change", "ai_or_model_feature"} else 0.0
    return clamp(base)


def score_actionability(signal_type: str, changed: bool, keyword_hits: int) -> float:
    base = 0.35
    if changed:
        base += 0.2
    base += min(keyword_hits, 5) * 0.08
    if signal_type in {
        "scanner_logic_change",
        "backtesting_or_review_feature",
        "alerting_or_execution_feature",
        "odds_or_market_coverage_change",
        "clv_or_roi_analytics",
        "bankroll_or_portfolio_review",
        "bet_sync_or_execution_support",
    }:
        base += 0.1
    if signal_type in {"social_or_copy_betting_feature", "pricing_or_packaging_change"}:
        base -= 0.08
    return clamp(base)


def recommendation_for(
    repo_fit: float,
    market_strength: float,
    actionability: float,
) -> str:
    if repo_fit >= 0.78 and actionability >= 0.72:
        return "adopt_now"
    if repo_fit >= 0.58 and market_strength >= 0.55:
        return "backlog"
    if market_strength >= 0.45:
        return "watch"
    if repo_fit <= 0.22:
        return "ignore"
    return "differentiate"
