# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Backtrader-based algorithmic trading research for Chinese equity markets (CSI 300, GEB, Shenzhen Composite). Primary workflow is Jupyter notebooks; `.py` files are notebook exports used for headless runs and parameter scans.

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

# Run a standalone script directly
cd notebook && python cta_research.py
cd notebook && python cy_research.py
```

There are no unit tests — `testing/tox.ini` is a skeleton referencing a non-existent Makefile.

## Architecture

### Data layer

Three data feed implementations, all subclassing `bt.feed.DataBase`:

- **CSV via pandas** — used in most notebooks: `pd.read_csv(..., index_col=0)` → `bt.feeds.PandasData(dataname=df, openinterest=None)`. CSV columns are `date,open,close,high,low,volume,money` where `money` is turnover (not standard OHLCV; pass `openinterest=None` to suppress the missing field error).
- **`mongofeed.py` → `MongoData`** — reads from MongoDB `localhost:27017`. Requires `fromdate` and `todate` params. Sets `openinterest=-1`.
- **`sqlitefeed.py` → `SQLiteData`** — reads from a `.db` SQLite file. `dataname` is the file path; `tablename` param selects the table (default `ohlc`). Timestamps stored as Unix integers; converted to UTC datetime on load.

CSV data lives in `notebook/csv_files/`: `000300.XSHG.csv` (CSI 300), `399006.XSHE.csv` (GEB), `399324.XSHE.csv` (Shenzhen Composite), plus `etf.csv`, `idx.csv`, `nss.csv`, and `BTC-USD.db` (SQLite).

### Strategy layer

Strategies are `bt.Strategy` subclasses defined inline in notebooks or `.py` files. Common patterns across all strategies:

- `__init__`: wires up indicators; stores pending order reference to avoid double-ordering
- `notify_order`: clears `self.order` / `self.pending` dict on fill or cancellation
- `next`: checks position, evaluates signal, issues `self.buy()` / `self.sell()` / `self.close()`
- Multi-timeframe: add daily data, then `cerebro.resampledata(feed, name='cy_weekly', timeframe=bt.TimeFrame.Weeks)`; access via `self.dnames.cy_weekly`

### Cerebro configuration (standard across all scripts)

```python
cerebro.broker.setcash(100_000.0)
cerebro.broker.setcommission(0.0005)   # 0.05%
cerebro.broker.set_coc(True)           # cheat-on-close: fill at same bar's close
cerebro.addsizer(bt.sizers.AllInSizerInt, percents=99)
```

Standard analyzers added: `SQN`, `SharpeRatio` (annualized, rf=3%), `DrawDown`, `AnnualReturn`, `Returns` (tann=252), `TradeAnalyzer`.

### Parameter scanning pattern

Both `.py` scripts follow the same pattern: `build_cerebro(**params)` factory → `cerebro.run()` → `extract_metrics(strat)` → accumulate rows into a list → `pd.DataFrame(rows)`. Sweep results are printed as a table and optionally plotted as a heatmap saved to PNG.

### Visualization

- Notebooks use `backtrader_plotting` (Bokeh-based, pinned `bokeh==2.3.3`) for interactive charts: `from backtrader_plotting import Bokeh; cerebro.plot(Bokeh(style='bar'))`
- Standalone `.py` scripts use `matplotlib` with `matplotlib.use('Agg')` for headless PNG output
- `cerebro.plot(iplot=False, style='candle', barup='#FF0033', bardown='#32CD32')` for inline matplotlib in notebooks

## Key Constraints

- `bokeh` must stay at `2.3.3` — `backtrader-plotting 2.0.0` is incompatible with newer Bokeh APIs.
- `mock_broker.py` is incomplete — it imports `from mock_store import Mock_Store` which does not exist in the repo; treat as reference skeleton only.
