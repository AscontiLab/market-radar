from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from market_radar.collector import fetch_snapshot
from market_radar.config import DEFAULT_DATA_DIR, DEFAULT_DB_PATH, load_products
from market_radar.dashboard import serve_dashboard
from market_radar.digest import build_decision_digest
from market_radar.feature_suggestions import (
    format_suggestions_text,
    generate_feature_suggestions,
)
from market_radar.github_collector import (
    fetch_github_latest_release,
    fetch_github_readme,
)
from market_radar.seed import seed_config
from market_radar.signals import build_decision_queue, generate_signals
from market_radar.storage import backfill_source_types, connect, init_db


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Market radar for internal scanners.")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to products.yaml",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite database path",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="Print product and competitor watchlists.")
    subparsers.add_parser("init-db", help="Initialize the SQLite database.")
    subparsers.add_parser("seed", help="Seed products and competitors into SQLite.")
    subparsers.add_parser(
        "generate-signals",
        help="Create heuristic market signals from stored snapshots.",
    )
    queue_parser = subparsers.add_parser(
        "decision-queue",
        help="Print the highest-priority decisions from generated signals.",
    )
    queue_parser.add_argument("--product", default=None, help="Optional product slug.")
    queue_parser.add_argument("--limit", type=int, default=10, help="Max rows to print.")
    digest_parser = subparsers.add_parser(
        "decision-digest",
        help="Print aggregated product decisions distilled from the decision queue.",
    )
    digest_parser.add_argument("--product", default=None, help="Optional product slug.")
    digest_parser.add_argument("--limit", type=int, default=5, help="Max digest rows.")

    fetch_parser = subparsers.add_parser(
        "fetch-snapshots",
        help="Fetch source snapshots for must-track competitors.",
    )
    fetch_parser.add_argument(
        "--product",
        default=None,
        help="Restrict fetching to a single product slug.",
    )
    fetch_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of competitors per product.",
    )
    github_parser = subparsers.add_parser(
        "fetch-github",
        help="Fetch GitHub README and latest release snapshots for configured repos.",
    )
    github_parser.add_argument(
        "--product",
        default=None,
        help="Restrict fetching to a single product slug.",
    )
    github_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of competitors per product.",
    )
    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Run a small local dashboard for the current decision queue.",
    )
    dashboard_parser.add_argument("--host", default="127.0.0.1")
    dashboard_parser.add_argument("--port", type=int, default=8787)

    # Diff-Kommando: Aenderungen zwischen Snapshots erkennen
    diff_parser = subparsers.add_parser(
        "diff",
        help="Batch-diff all snapshots and show change scores.",
    )
    diff_parser.add_argument("--limit", type=int, default=20, help="Max rows to print.")

    # Enrich-Kommando: LLM-Anreicherung fuer Signale
    enrich_parser = subparsers.add_parser(
        "enrich",
        help="Enrich unenriched signals via LLM (requires ANTHROPIC_API_KEY).",
    )
    enrich_parser.add_argument("--limit", type=int, default=20, help="Max signals to enrich.")

    # Run-All-Kommando: Komplette Pipeline ausfuehren
    run_all_parser = subparsers.add_parser(
        "run-all",
        help="Run the full pipeline: init-db → seed → fetch → signals → digest.",
    )
    run_all_parser.add_argument(
        "--enrich",
        action="store_true",
        default=False,
        help="Also run LLM enrichment at the end.",
    )

    # Backfill-Kommando: source_type/source_kind nachtraeglich setzen
    subparsers.add_parser(
        "backfill",
        help="Backfill NULL source_type/source_kind in source_snapshots.",
    )

    # Alerts-Kommando: Telegram-Alerts fuer Adopt-Now-Signale senden
    alerts_parser = subparsers.add_parser(
        "alerts",
        help="Send Telegram alerts for adopt_now signals.",
    )
    alerts_parser.add_argument(
        "--since-hours",
        type=int,
        default=24,
        help="Look back window in hours (default: 24).",
    )

    # Suggest-Kommando: Feature-Vorschlaege aus Digest ableiten
    suggest_parser = subparsers.add_parser(
        "suggest",
        help="Generate concrete feature suggestions from the decision digest.",
    )
    suggest_parser.add_argument("--product", default=None, help="Optional product slug.")
    suggest_parser.add_argument("--limit", type=int, default=20, help="Max suggestions to show.")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config = load_products(args.config)

    if args.command == "plan":
        print_plan(config)
        return 0

    if args.command == "init-db":
        init_db(args.db)
        print(f"Initialized database at {args.db}")
        return 0

    if args.command == "seed":
        init_db(args.db)
        with connect(args.db) as connection:
            seed_config(connection, config)
        print(f"Seeded config into {args.db}")
        return 0

    if args.command == "fetch-snapshots":
        init_db(args.db)
        with connect(args.db) as connection:
            seed_config(connection, config)
            count = fetch_snapshots(
                connection=connection,
                config=config,
                data_dir=DEFAULT_DATA_DIR,
                product_slug=args.product,
                per_product_limit=args.limit,
            )
        print(f"Fetched {count} snapshots")
        return 0

    if args.command == "generate-signals":
        init_db(args.db)
        with connect(args.db) as connection:
            seed_config(connection, config)
            count = generate_signals(connection, config)
        print(f"Generated {count} market signals")
        return 0

    if args.command == "fetch-github":
        init_db(args.db)
        with connect(args.db) as connection:
            seed_config(connection, config)
            count = fetch_github_snapshots(
                connection=connection,
                config=config,
                data_dir=DEFAULT_DATA_DIR,
                product_slug=args.product,
                per_product_limit=args.limit,
                token=os.getenv("GITHUB_TOKEN"),
            )
        print(f"Fetched {count} GitHub snapshots")
        return 0

    if args.command == "decision-queue":
        init_db(args.db)
        with connect(args.db) as connection:
            queue = build_decision_queue(
                connection=connection,
                product_slug=args.product,
                limit=args.limit,
            )
        print(json.dumps(queue, indent=2, ensure_ascii=False))
        return 0

    if args.command == "decision-digest":
        init_db(args.db)
        with connect(args.db) as connection:
            digest = build_decision_digest(
                connection,
                product_slug=args.product,
                limit=args.limit,
            )
        print(json.dumps(digest, indent=2, ensure_ascii=False))
        return 0

    if args.command == "dashboard":
        serve_dashboard(args.db, host=args.host, port=args.port)
        return 0

    if args.command == "diff":
        from market_radar.diff import batch_diff_all

        init_db(args.db)
        with connect(args.db) as connection:
            results = batch_diff_all(connection)
        # Ergebnistabelle ausgeben
        print(f"{'competitor_slug':<25} {'source_url':<50} {'change_score':>12} {'change_summary'}")
        print("-" * 110)
        for row in results[: args.limit]:
            slug = row.get("competitor_slug", "")
            url = row.get("source_url", "")
            if len(url) > 47:
                url = url[:47] + "..."
            score = row.get("change_score", 0.0)
            summary = row.get("change_summary", "")
            print(f"{slug:<25} {url:<50} {score:>12.2f} {summary}")
        print(f"\n{len(results)} Ergebnisse gesamt, {min(args.limit, len(results))} angezeigt.")
        return 0

    if args.command == "enrich":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("Fehler: ANTHROPIC_API_KEY Umgebungsvariable nicht gesetzt.")
            return 1

        from market_radar.llm_enricher import enrich_batch

        init_db(args.db)
        with connect(args.db) as connection:
            count = enrich_batch(connection, config=config, limit=args.limit)
        print(f"{count} Signale mit LLM angereichert.")
        return 0

    if args.command == "run-all":
        init_db(args.db)
        with connect(args.db) as connection:
            seed_config(connection, config)

            # Snapshots holen
            snapshot_count = fetch_snapshots(
                connection=connection,
                config=config,
                data_dir=DEFAULT_DATA_DIR,
                product_slug=None,
                per_product_limit=5,
            )
            print(f"Fetched {snapshot_count} snapshots")

            # GitHub-Snapshots holen
            github_count = fetch_github_snapshots(
                connection=connection,
                config=config,
                data_dir=DEFAULT_DATA_DIR,
                product_slug=None,
                per_product_limit=5,
                token=os.getenv("GITHUB_TOKEN"),
            )
            print(f"Fetched {github_count} GitHub snapshots")

            # Signale generieren
            signal_count = generate_signals(connection, config)
            print(f"Generated {signal_count} market signals")

            # Decision-Digest erstellen
            digest = build_decision_digest(connection, product_slug=None, limit=5)
            print(f"Decision digest: {len(digest)} items")

            # Feature-Vorschlaege generieren
            suggestions = generate_feature_suggestions(digest, config)
            if suggestions:
                print(f"\n{format_suggestions_text(suggestions)}\n")
            else:
                print("Keine Feature-Vorschlaege aus aktuellem Digest.")

            # Optional: LLM-Anreicherung
            enriched_count = 0
            if args.enrich:
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if not api_key:
                    print("Warnung: ANTHROPIC_API_KEY nicht gesetzt, ueberspringe LLM-Enrichment.")
                else:
                    from market_radar.llm_enricher import enrich_batch

                    enriched_count = enrich_batch(connection, config=config, limit=50)
                    print(f"Enriched {enriched_count} signals via LLM")

            # Telegram-Alerts senden (wenn konfiguriert)
            alert_count = 0
            bot_token = os.getenv("ASCONTILAB_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
            chat_id = os.getenv("ASCONTILAB_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID", "")
            if bot_token and chat_id:
                try:
                    from market_radar.telegram_alerts import send_digest_alerts

                    alert_count = send_digest_alerts(
                        connection, config, bot_token, chat_id, since_hours=24,
                    )
                    print(f"Sent {alert_count} Telegram alerts")
                except Exception as exc:
                    print(f"Warnung: Telegram-Alerts fehlgeschlagen: {exc}")

        # Zusammenfassung
        print("\n--- Pipeline Zusammenfassung ---")
        print(f"  Snapshots:        {snapshot_count}")
        print(f"  GitHub Snapshots: {github_count}")
        print(f"  Signale:          {signal_count}")
        print(f"  Digest Items:     {len(digest)}")
        print(f"  Feature-Vorschlaege: {len(suggestions)}")
        if args.enrich:
            print(f"  LLM-Enriched:     {enriched_count}")
        print(f"  Telegram-Alerts:  {alert_count}")
        return 0

    if args.command == "alerts":
        bot_token = os.getenv("ASCONTILAB_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("ASCONTILAB_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID", "")
        if not bot_token or not chat_id:
            print("Fehler: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID nicht gesetzt.")
            return 1

        from market_radar.telegram_alerts import send_digest_alerts

        init_db(args.db)
        with connect(args.db) as connection:
            count = send_digest_alerts(
                connection, config, bot_token, chat_id, since_hours=args.since_hours,
            )
        print(f"{count} Telegram-Alerts gesendet.")
        return 0

    if args.command == "suggest":
        init_db(args.db)
        with connect(args.db) as connection:
            digest = build_decision_digest(
                connection,
                product_slug=args.product,
                limit=20,
            )
        suggestions = generate_feature_suggestions(digest, config)
        if args.limit:
            suggestions = suggestions[: args.limit]
        print(format_suggestions_text(suggestions))
        return 0

    if args.command == "backfill":
        init_db(args.db)
        with connect(args.db) as connection:
            updated = backfill_source_types(connection)
        print(f"{updated} Zeilen aktualisiert (source_type/source_kind backfilled).")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def print_plan(config: dict) -> None:
    for product in config.get("products", []):
        print(f"[{product['slug']}] {product['name']}")
        print(f"  category: {product['category']}")
        print(f"  repo: {product.get('repo_url', '-')}")
        print(f"  priority_signal_types: {', '.join(product.get('priority_signal_types', []))}")
        for competitor in product.get("competitors", []):
            sources = len(competitor.get("source_urls", []))
            github_sources = len(competitor.get("github_repos", []))
            print(
                f"  - {competitor['slug']} ({competitor['tier']}, {sources} web, {github_sources} github)"
            )
        print()


def fetch_snapshots(
    connection,
    config: dict,
    data_dir: Path,
    product_slug: str | None,
    per_product_limit: int,
) -> int:
    raw_dir = data_dir / "raw"
    total = 0

    for product in config.get("products", []):
        if product_slug and product["slug"] != product_slug:
            continue

        selected = [
            competitor
            for competitor in product.get("competitors", [])
            if competitor.get("tier") == "must_track"
        ][:per_product_limit]

        for competitor in selected:
            for source_url in competitor.get("source_urls", []):
                try:
                    snapshot = fetch_snapshot(source_url, raw_dir=raw_dir)
                except Exception as exc:
                    print(f"  Warnung: {competitor['slug']} ({source_url}) fehlgeschlagen: {exc}")
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO source_snapshots (
                        competitor_slug, source_url, source_type, source_kind, fetched_at, status_code,
                        content_hash, title, body_excerpt, raw_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        competitor["slug"],
                        snapshot.source_url,
                        snapshot.source_type,
                        snapshot.source_kind,
                        snapshot.fetched_at,
                        snapshot.status_code,
                        snapshot.content_hash,
                        snapshot.title,
                        snapshot.body_excerpt,
                        snapshot.raw_path,
                    ),
                )
                total += 1

        connection.commit()

    return total


def fetch_github_snapshots(
    connection,
    config: dict,
    data_dir: Path,
    product_slug: str | None,
    per_product_limit: int,
    token: str | None,
) -> int:
    raw_dir = data_dir / "raw"
    total = 0

    for product in config.get("products", []):
        if product_slug and product["slug"] != product_slug:
            continue

        selected = [
            competitor
            for competitor in product.get("competitors", [])
            if competitor.get("github_repos")
        ][:per_product_limit]

        for competitor in selected:
            for repo_name in competitor.get("github_repos", []):
                try:
                    readme_snapshot = fetch_github_readme(repo_name, raw_dir=raw_dir, token=token)
                    _insert_snapshot(connection, competitor["slug"], readme_snapshot)
                    total += 1
                except Exception as exc:
                    print(f"  Warnung: {competitor['slug']} README ({repo_name}) fehlgeschlagen: {exc}")

                try:
                    release_snapshot = fetch_github_latest_release(
                        repo_name,
                        raw_dir=raw_dir,
                        token=token,
                    )
                    if release_snapshot is not None:
                        _insert_snapshot(connection, competitor["slug"], release_snapshot)
                        total += 1
                except Exception as exc:
                    print(f"  Warnung: {competitor['slug']} Release ({repo_name}) fehlgeschlagen: {exc}")

        connection.commit()

    return total


def _insert_snapshot(connection, competitor_slug: str, snapshot) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO source_snapshots (
            competitor_slug, source_url, source_type, source_kind, fetched_at, status_code,
            content_hash, title, body_excerpt, raw_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            competitor_slug,
            snapshot.source_url,
            snapshot.source_type,
            snapshot.source_kind,
            snapshot.fetched_at,
            snapshot.status_code,
            snapshot.content_hash,
            snapshot.title,
            snapshot.body_excerpt,
            snapshot.raw_path,
        ),
    )
