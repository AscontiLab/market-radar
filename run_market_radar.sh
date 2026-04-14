#!/usr/bin/env bash
# Taeglicher Market Radar Scan — via Cron Mo-Fr 07:00 UTC
set -euo pipefail
cd /home/claude-agent/market-radar
export PATH="/usr/bin:/usr/local/bin:$PATH"

# Credentials laden
if [ -f "$HOME/.stock_scanner_credentials" ]; then
    set -a
    source "$HOME/.stock_scanner_credentials"
    set +a
fi

LOG="data/market_radar_$(date +%Y-%m-%d).log"
python3 main.py run-all --enrich >> "$LOG" 2>&1
echo "[$(date -u +%FT%TZ)] Market Radar completed" >> "$LOG"
