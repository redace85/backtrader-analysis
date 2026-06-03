#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$SCRIPT_DIR/bin/activate"

cd "$SCRIPT_DIR/iscrapy"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting daily update"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Fetching BTC-USD..."
scrapy crawl yahoo-finance -a symbol=BTC-USD

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Fetching ETH-USD..."
scrapy crawl yahoo-finance -a symbol=ETH-USD

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Fetching sh000001..."
scrapy crawl sina-finance -a symbol=sh000001

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Fetching sz399006..."
scrapy crawl sina-finance -a symbol=sz399006

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Daily update complete"
