# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Backtrader-based algorithmic trading research for Chinese equity markets (CSI 300, GEB, Shenzhen Composite) and crypto (BTC, ETH). Primary workflow is Jupyter notebooks; `.py` files are notebook exports used for headless runs and parameter scans.

## Setup

```bash
python3 -m venv .
source bin/activate
pip install -r requirements.txt
```

## Running

```bash
# Launch notebook server
cd notebook && bash launch-jupyter-note.bash
# Equivalent: jupyter-notebook --ip=0.0.0.0 --no-browser .

# Run standalone scripts directly (must run from notebook/ so relative paths resolve)
cd notebook && python cta_research.py       # Chinese equity CTA, outputs cta_equity.png + cta_sharpe_heatmap.png
cd notebook && python cy_research.py        # CSI 300 weekly KAMA+Stochastic strategy
cd notebook && python btc_research.py       # BTC SQLite feed, includes Buy & Hold baseline
cd notebook && python crypto_research.py    # BTC+ETH CTA, outputs crypto_equity.png + crypto_sharpe_heatmap.png
```

There are no unit tests.

## Architecture

### Data feeds

Three `bt.feed.DataBase` subclasses:

- **CSV via pandas** (`cta_research.py`, `cy_research.py`): `pd.read_csv(..., index_col=0)` → `bt.feeds.PandasData(dataname=df, openinterest=None)`. CSV columns are `date,open,close,high,low,volume,money` where `money` is turnover; `openinterest=None` suppresses the missing field error.
- **`mongofeed.py` → `MongoData`**: reads from MongoDB `localhost:27017`. Requires `fromdate` and `todate` params. Sets `openinterest=-1`.
- **`sqlitefeed.py` → `SQLiteData`**: reads from a `.db` SQLite file. `dataname` is the file path; `tablename` param selects the table (default `ohlc`, validated against `[A-Za-z_][A-Za-z0-9_]*`). Timestamps stored as Unix integers; converted to UTC datetime on load. Used by `btc_research.py` and `crypto_research.py`.

CSV/SQLite data lives in `notebook/csv_files/`: Chinese equity CSVs, `BTC-USD.db`, `ETH-USD.db`, `sh000001.db`, `sz399006.db`, plus `etf.csv`, `idx.csv`, `nss.csv`.

### Strategy patterns

All strategies follow the same structure:

- `__init__`: wire up indicators; store pending order reference (`self.order` or `self.pending` dict keyed by instrument name) to prevent double-ordering
- `notify_order`: clear `self.order` / `self.pending[name]` on fill or cancellation
- `next`: check position, evaluate signal, call `self.buy()` / `self.sell()` / `self.close()`

Multi-timeframe setup: add daily data first, then `cerebro.resampledata(feed, name='cy_weekly', timeframe=bt.TimeFrame.Weeks)`; access via `self.dnames.cy_weekly`.

Concrete strategies:

- **`CTAStrategy`** (`cta_research.py`, `crypto_research.py`): Multi-instrument EMA crossover filtered by ADX. ATR-based position sizing (`risk_pct * portfolio / (ATR * atr_mult)`). ATR trailing stop that ratchets in the direction of the trade.
- **`CyStrategy`** (`cy_research.py`, `btc_research.py`): Single instrument; KAMA on weekly + DMI + StochasticFull on daily; trades on `CrossOver(percD, percDSlow)`.
- **`BuyAndHoldStrategy`** (`btc_research.py`): Baseline — buys all-in on `nextstart`, never sells.

### Cerebro configuration (standard across all scripts)

```python
cerebro.broker.setcash(100_000.0)
cerebro.broker.setcommission(0.0005)   # 0.05% equities; crypto_research uses 0.001 (0.1%)
cerebro.broker.set_coc(True)           # cheat-on-close: fill at same bar's close
cerebro.addsizer(bt.sizers.AllInSizerInt, percents=99)  # cy_research / btc_research only
```

Standard analyzers: `SQN`, `SharpeRatio` (annualized, rf=3%), `DrawDown`, `AnnualReturn`, `Returns` (tann=252 for equities, tann=365 for crypto), `TradeAnalyzer`. CTA scripts also add `TimeReturn` for equity curve plotting.

### Parameter scanning pattern

All `.py` scripts share the same pattern: `build_cerebro(**params)` factory → `cerebro.run()` → `extract_metrics(strat)` → accumulate rows → `pd.DataFrame(rows)`. Results are printed as a table; CTA scripts also save a Sharpe heatmap PNG.

### Visualization

- Notebooks use `backtrader_plotting` (Bokeh-based): `from backtrader_plotting import Bokeh; cerebro.plot(Bokeh(style='bar'))`
- Standalone `.py` scripts use `matplotlib` with `matplotlib.use('Agg')` for headless PNG output
- `cerebro.plot(iplot=False, style='candle', barup='#FF0033', bardown='#32CD32')` for inline matplotlib in notebooks

## Key Constraints

- `bokeh` must stay at `2.3.3` — `backtrader-plotting 2.0.0` is incompatible with newer Bokeh APIs.
- `mock_broker.py` is broken — it imports `from mock_store import Mock_Store` which does not exist in the repo; treat as reference skeleton only.
- All scripts use relative paths (`./csv_files/`) and must be run from the `notebook/` directory.
