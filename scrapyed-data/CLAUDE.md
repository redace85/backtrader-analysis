# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Scrapy-based data collection pipeline that fetches daily OHLCV data from Yahoo Finance (crypto/commodities) and Sina Finance (Chinese equities) and stores it in SQLite databases for use by the parent `backtrader-analysis` project.

## Setup

```bash
python3 -m venv .
source bin/activate
pip install -r requirements.txt
```

Requires `node` on PATH — the Sina Finance spider shells out to Node.js to decode the proprietary KLC binary encoding.

## Running

```bash
# Run daily update (fetches BTC-USD, ETH-USD, sh000001, sz399006)
./update_daily.sh

# Run individual spiders from iscrapy/
cd iscrapy
scrapy crawl yahoo-finance -a symbol=BTC-USD
scrapy crawl yahoo-finance -a symbol=BTC-USD -a period1=1609459200 -a period2=1741262400
scrapy crawl sina-finance -a symbol=sz399006   # ChiNext (GEB)
scrapy crawl sina-finance -a symbol=sh000001   # SSE Composite
```

## Architecture

### Spider → Pipeline flow

All spiders yield `IscrapyItem(item_id, data, msg, failed)`. Two pipelines run in order:

1. **`ConditionalPipeline` (priority 100)** — deduplication for `coin-market` spider only; drops items whose price hasn't moved >1% since last run. Uses a per-spider `.db` file in the working directory.
2. **`StorePipeline` (priority 150)** — writes OHLCV rows to SQLite for `yahoo-finance` and `sina-finance` spiders. DB path comes from `DB_PATH` env var (default `/Users/liuji/lite-data`). File named `{symbol}.db`, table `ohlc(timestamp INTEGER PRIMARY KEY, open, high, low, close, volume)`.

`TelegramPipeline` exists but is commented out in `settings.py`.

### Spiders

- **`yahoo-finance`** — hits Yahoo Finance v8 chart API. `period1`/`period2` are Unix timestamps; defaults to last 5 days. Timestamps in the response are Unix integers stored directly.
- **`sina-finance`** — fetches Sina Finance's proprietary KLC-encoded binary blob, pipes it through an embedded Node.js decoder (`_NODE_SCRIPT` in `sina_finance.py`) to get OHLCV JSON. Dates are parsed as UTC midnight timestamps before storage.
- **`coin-market`** — hits CoinMarketCap Pro API. Requires `CMC_API_KEY` env var and `CRYPTO_IDS` list in settings. Sends Telegram notifications via `TelegramPipeline` when price moves significantly.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `DB_PATH` | Directory where `{symbol}.db` files are written | `/Users/liuji/lite-data` |
| `TELE_TOKEN` | Telegram bot token for alerts | `''` |
| `TELE_ALARM_ID` | Telegram chat ID for error alerts | `@scrapy_crypto_infos` |
| `CMC_API_KEY` | CoinMarketCap API key | `''` |

### Database schema

All output `.db` files use the same schema (compatible with `sqlitefeed.py` in the parent project):

```sql
CREATE TABLE ohlc(
    timestamp INTEGER PRIMARY KEY,  -- Unix seconds UTC
    open REAL, high REAL, low REAL, close REAL,
    volume INTEGER
)
```
