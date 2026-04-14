# Market Radar Status

Stand: 2026-04-13

## Ziel

`market-radar` beobachtet aehnliche Produkte fuer:

- `stock-scanner`
- `sports-scanner`

und uebersetzt externe Produktbewegungen in einen internen Decision Feed.

## Was funktioniert

- Watchlist fuer beide internen Produkte
- Web- und GitHub-Quellen in einer SQLite-Datenbank
- erste Signaltypen und Priorisierung
- `decision_queue`
- `decision_digest`
- kleine lokale Dashboard-Ansicht
- Anbindung an `unified-dashboard`

## Relevante lokale Pfade

- Repo-Ordner: `/home/claude-agent/market-radar`
- DB: `/home/claude-agent/market-radar/data/market_radar.db`
- Konfiguration: `/home/claude-agent/market-radar/products.yaml`

## Letzte sinnvolle Befehle

```bash
cd /home/claude-agent/market-radar
python3 main.py fetch-snapshots --limit 3
python3 main.py fetch-github --limit 3
python3 main.py generate-signals
python3 main.py decision-queue --limit 10
python3 main.py decision-digest --limit 5
python3 main.py dashboard --host 127.0.0.1 --port 8791
```

## Hinweise

- `market-radar` ist noch nicht als Git-Repo initialisiert.
- Die produktive Anzeige laeuft derzeit ueber `unified-dashboard` unter `/market-radar`.
