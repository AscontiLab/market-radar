# Market Radar

`market-radar` ist ein Competitor- und Similar-Tool-Scanner fuer zwei interne Produkte:

- `stock-scanner`
- `sports-scanner`

Der Zweck ist kein allgemeines Konkurrenz-Monitoring, sondern ein verwertbarer
Decision Feed:

- Was bauen aehnliche Tools gerade?
- Welche Muster werden zum Marktstandard?
- Was ist fuer unsere Scanner direkt relevant?
- Was sollten wir uebernehmen, beobachten oder bewusst anders machen?

## Aktueller Stand

Der aktuelle Stand ist `v0.3`:

- Watchlist fuer `stock-scanner` und `sports-scanner`
- SQLite-Storage fuer Produkte, Wettbewerber, Snapshots und Signale
- Web-Snapshots fuer Produktseiten, Changelogs und Feature-Seiten
- GitHub-Snapshots fuer `README` und `latest release`
- heuristische Signal-Erkennung mit Keyword-Matching
- `decision_queue` mit Priorisierung und Deduplizierung (ROW_NUMBER)
- `decision_digest` mit 3 bis 5 verdichteten Produktentscheidungen
- inhaltliche Snapshot-Diffs (Jaccard-Distanz, Satz-basiert)
- LLM-Enrichment via Claude Haiku (Konfidenz, Summary, Recommendation)
- kleine lokale Dashboard-Ansicht
- Integration in `unified-dashboard` unter `/market-radar`
- `run-all` Pipeline-Befehl fuer kompletten Durchlauf
- Cron-Job Mo-Fr 07:15 UTC via `run_market_radar.sh`

## Projektstruktur

- `main.py`
  Einstiegspunkt fuer die CLI
- `products.yaml`
  interne Produkte, Wettbewerber, Keywords, Signaltypen, Quellen
- `market_radar/config.py`
  laedt die Konfiguration
- `market_radar/storage.py`
  SQLite-Schema und Migrationen
- `market_radar/seed.py`
  schreibt Produkte und Wettbewerber in die Datenbank
- `market_radar/collector.py`
  holt Web-Snapshots und nutzt einfache source-specific Extractors
- `market_radar/github_collector.py`
  holt GitHub-`README`- und Release-Snapshots
- `market_radar/signals.py`
  erzeugt erste Markt-Signale und die `decision_queue`
- `market_radar/digest.py`
  verdichtet die Queue zum `decision_digest`
- `market_radar/dashboard.py`
  kleine lokale HTTP-Ansicht
- `data/market_radar.db`
  lokale SQLite-Datenbank

## Quellenmodell

Web-Quellen laufen als:

- `source_type = web`
- `source_kind = page`

GitHub-Quellen laufen als:

- `source_type = github`
- `source_kind = readme`
- `source_kind = release`

## Wichtige Befehle

```bash
cd /home/claude-agent/market-radar

# Komplette Pipeline (empfohlen)
python3 main.py run-all              # ohne LLM
python3 main.py run-all --enrich     # mit Claude Haiku Enrichment

# Einzelschritte
python3 main.py plan
python3 main.py init-db
python3 main.py seed
python3 main.py fetch-snapshots --limit 3
python3 main.py fetch-github --limit 3
python3 main.py generate-signals
python3 main.py decision-queue --limit 10
python3 main.py decision-digest --limit 5

# Neue Befehle (v0.3)
python3 main.py backfill             # source_type/source_kind nachtraeglich setzen
python3 main.py diff --limit 20      # inhaltliche Snapshot-Diffs anzeigen
python3 main.py enrich --limit 20    # LLM-Enrichment fuer offene Signale

# Dashboard
python3 main.py dashboard --host 127.0.0.1 --port 8791
```

Hinweis:

- `8787` war lokal bereits belegt, daher wurde zuletzt mit `8791` getestet.
- `GITHUB_TOKEN` optional fuer hoehere API-Limits.
- `ANTHROPIC_API_KEY` noetig fuer LLM-Enrichment (Claude Haiku).

## Quellextraktion

Fuer die wichtigsten Web-Quellen gibt es bereits einfache, gezielte Extractors:

- `TradingView`
- `TrendSpider`
- `OddsJam`
- `Pikkit`

Diese bevorzugen Meta-Descriptions sowie sichtbare Heading- und Listen-Inhalte
und filtern offensichtliches UI-, Script- und Social-Rauschen weg.

## Bewertungslogik

Die erste Pipeline arbeitet bewusst einfach und nachvollziehbar:

1. Snapshot einsammeln
2. Signaltyp per Keywords und Seitentext erkennen
3. `repo_fit`, `market_strength` und `actionability` bewerten
4. Empfehlung ableiten:
   - `adopt_now`
   - `backlog`
   - `watch`
   - `ignore`
   - `differentiate`
5. mehrere Einzelsignale im `decision_digest` zusammenfassen

## Offene naechste Schritte

1. ~~Snapshot-Diffs inhaltlich statt nur ueber Hashes auswerten~~ (erledigt: diff.py)
2. ~~Deduplizierung und Signal-Clustering ausbauen~~ (erledigt: ROW_NUMBER Dedup)
3. ~~LLM-Enrichment fuer bessere Signal-Qualitaet~~ (erledigt: llm_enricher.py)
4. GitHub-Releases staerker von README-Signalen unterscheiden
5. aus dem Digest direkte Feature-Vorschlaege pro Repo ableiten
6. LLM-Enrichment-Ergebnisse im Dashboard anzeigen
7. Telegram-Alerts fuer adopt_now Signale
