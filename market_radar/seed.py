from __future__ import annotations

import json
import sqlite3
from typing import Any


def seed_config(connection: sqlite3.Connection, config: dict[str, Any]) -> None:
    products = config.get("products", [])
    for product in products:
        connection.execute(
            """
            INSERT INTO tracked_products (
                slug, name, category, repo_url, objective, keywords_json,
                priority_signal_types_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                category = excluded.category,
                repo_url = excluded.repo_url,
                objective = excluded.objective,
                keywords_json = excluded.keywords_json,
                priority_signal_types_json = excluded.priority_signal_types_json
            """,
            (
                product["slug"],
                product["name"],
                product["category"],
                product.get("repo_url"),
                product.get("objective"),
                json.dumps(product.get("keywords", [])),
                json.dumps(product.get("priority_signal_types", [])),
            ),
        )

        for competitor in product.get("competitors", []):
            connection.execute(
                """
                INSERT INTO tracked_competitors (
                    slug, product_slug, name, tier, relevance, source_urls_json,
                    watch_for_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    product_slug = excluded.product_slug,
                    name = excluded.name,
                    tier = excluded.tier,
                    relevance = excluded.relevance,
                    source_urls_json = excluded.source_urls_json,
                    watch_for_json = excluded.watch_for_json
                """,
                (
                    competitor["slug"],
                    product["slug"],
                    competitor["name"],
                    competitor["tier"],
                    competitor.get("relevance"),
                    json.dumps(competitor.get("source_urls", [])),
                    json.dumps(competitor.get("watch_for", [])),
                ),
            )

    connection.commit()
