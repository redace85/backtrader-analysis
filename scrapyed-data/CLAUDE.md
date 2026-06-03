# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Scrapy-based data collection pipeline that fetches OHLCV market data from Yahoo Finance and Sina Finance, storing results in SQLite databases consumed by the parent `backtrader-analysis` project.

## Setup

```bash
python3 -m venv .
source bin/activate
pip install -r requirements.txt
```

Node.js must be installed — the Sina Finance spider shells out to `node` to decode the proprietary KLC binary encoding.

## Running

```bash
# Activate venv first
source bin/activate
cd iscrapy

# Run a single spider
scrapy crawl yahoo-finance -a symbol=BTC-USD
scrapy crawl sina-finance -a symbol=sz399006   # ChiNext
scrapy crawl sina-finance -a symbol=sh000001   # SSE Composite

# Run all daily updates
bash update_daily.sh
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `DB_PATH` | `/Users/liuji/lite-data` | Directory where `{symbol}.db` SQLite files are written |
| `TELE_TOKEN` | `''` | Telegram bot token for `TelegramPipeline` |
| `TELE_ALARM_ID` | `@scrapy_crypto_infos` | Telegram chat ID for error alerts |

## Architecture

### Spider → Pipeline flow

Each spider yields `IscrapyItem(item_id, data, msg, failed)`. The item passes through two pipelines (both defined in `iscrapy/pipelines.py`):

1. **`StorePipeline`** (priority 100, always enabled) — writes OHLCV rows to `{DB_PATH}/{symbol}.db` using `INSERT OR REPLACE` on `timestamp` as the primary key. Creates the `ohlc` table if the file doesn't exist. Schema: `timestamp INTEGER PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, volume INTEGER`.
2. **`TelegramPipeline`** (priority 300, disabled in `settings.py`) — sends error items to `TELE_ALARM_ID` and success items to `spider.chat_id`. Re-enable by uncommenting in `ITEM_PIPELINES`.

### Spiders

**`yahoo-finance`** (`iscrapy/spiders/yahoo_finance.py`) — calls the Yahoo Finance v8 chart API. Accepts `-a symbol=`, `-a period1=`, `-a period2=` (Unix timestamps). Defaults to the last 5 days if periods are omitted.

**`sina-finance`** (`iscrapy/spiders/sina_finance.py`) — fetches full history for a Chinese A-share symbol from `finance.sina.com.cn/realstock/company/{symbol}/hisdata/klc_kl.js`. The response body is a KLC type-1479 binary-encoded string (base64-like, proprietary). Decoding is done by piping the encoded string through an embedded Node.js script (`_NODE_SCRIPT`) via `subprocess`. The JS `d()` function handles all Sina KLC subtypes; only type 1479 (full OHLCV history) is used here.

### SQLite output

Output files land in `DB_PATH` as `{symbol}.db`, e.g. `BTC-USD.db`, `sz399006.db`. These are the same format used by `sqlitefeed.py` (`SQLiteData`) in the parent backtrader notebooks — `dataname` is the file path, `tablename='ohlc'`.
