# Market Radar Status

Stand: 2026-04-14

## Ziel

`market-radar` beobachtet aehnliche Produkte fuer:

- `stock-scanner`
- `sports-scanner`

und uebersetzt externe Produktbewegungen in einen internen Decision Feed.

## Was funktioniert (v0.3)

- Watchlist fuer beide internen Produkte (18 Wettbewerber)
- Web- und GitHub-Quellen in einer SQLite-Datenbank
- Heuristische Signal-Erkennung + LLM-Enrichment (Claude Haiku)
- Deduplizierte `decision_queue` (ROW_NUMBER per competitor+signal)
- `decision_digest` mit verdichteten Empfehlungen
- Inhaltliche Snapshot-Diffs (Jaccard, satzbasiert)
- `run-all` Pipeline-Befehl
- Cron: Mo-Fr 07:15 UTC via `run_market_radar.sh`
- Dashboard lokal + Anbindung an `unified-dashboard`

## Relevante Pfade

- Repo: `AscontiLab/market-radar`
- Lokal: `/home/claude-agent/market-radar`
- DB: `/home/claude-agent/market-radar/data/market_radar.db`
- Config: `/home/claude-agent/market-radar/products.yaml`

## Wichtigste Befehle

```bash
cd /home/claude-agent/market-radar
python3 main.py run-all --enrich     # Komplette Pipeline
python3 main.py diff --limit 20      # Snapshot-Diffs
python3 main.py enrich --limit 20    # LLM-Enrichment
python3 main.py dashboard --port 8791
```
