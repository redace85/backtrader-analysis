import backtrader as bt
import datetime
import sqlite3
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from sqlitefeed import SQLiteData

DB_PATH = './sqlite_dbs/BTC-USD.db'

# ── Walk-forward parameters ────────────────────────────────────────────────────
IS_DAYS      = 730          # in-sample window (days)
OOS_DAYS     = 180          # out-of-sample window (days)
STEP_DAYS    = OOS_DAYS     # step size — OOS windows are non-overlapping
SCAN_PERIODS = list(range(5, 25, 2))
SELECT_BY    = 'sqn'        # metric used to pick best IS period


# ── Strategies ─────────────────────────────────────────────────────────────────

class CTAStrategy(bt.Strategy):
    params = (('period', 5),)

    def log(self, txt):
        dt = self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        self.kama  = bt.indicators.KAMA(self.dnames.btc_weekly, period=self.p.period)
        self.dmi   = bt.indicators.DM(self.dnames.btc_daily,    period=self.p.period)
        self.kd    = bt.indicators.StochasticFull(self.dnames.btc_daily, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.kd.percD, self.kd.percDSlow, plot=False)
        self.buy_signal  = self.cross == 1
        self.sell_signal = self.cross == -1
        self.order     = None
        self.start_len = 0

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return

    def prenext(self):
        pass

    def nextstart(self):
        self.start_len = len(self)

    def next(self):
        if self.order:
            return
        if not self.position:
            if self.buy_signal[0]:
                self.order = self.buy()
        else:
            if self.sell_signal[0]:
                self.order = self.sell()

    def stop(self):
        self.valid_len = len(self) - self.start_len


class BuyAndHoldStrategy(bt.Strategy):
    params = (('period', 'BAH'),)

    def __init__(self):
        self.order     = None
        self.start_len = 0

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return

    def nextstart(self):
        self.start_len = len(self)
        self.order = self.buy()

    def next(self):
        pass

    def stop(self):
        self.valid_len = len(self) - self.start_len


# ── Cerebro builders ───────────────────────────────────────────────────────────

def _build_cerebro_window(fromdate, todate):
    """Base cerebro with daily + weekly BTC feeds filtered to [fromdate, todate]."""
    from_dt = datetime.datetime.combine(fromdate, datetime.time.min)
    to_dt   = datetime.datetime.combine(todate,   datetime.time.max)

    feed = SQLiteData(dataname=DB_PATH, tablename='ohlc',
                      fromdate=from_dt, todate=to_dt)

    cerebro = bt.Cerebro(oldtrades=True, oldbuysell=True)
    cerebro.adddata(feed, name='btc_daily')
    cerebro.resampledata(feed, name='btc_weekly', timeframe=bt.TimeFrame.Weeks)

    cerebro.broker.setcash(100_000.0)
    cerebro.broker.setcommission(0.0005)
    cerebro.broker.set_coc(True)
    cerebro.broker.set_fundstartval(50)

    cerebro.addsizer(bt.sizers.AllInSizerInt, percents=99)

    cerebro.addanalyzer(bt.analyzers.SQN)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio,
                        riskfreerate=0.03, annualize=True,
                        timeframe=bt.TimeFrame.Days, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown,   _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='annual')
    cerebro.addanalyzer(bt.analyzers.Returns,
                        timeframe=bt.TimeFrame.Days, tann=365, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    return cerebro


def build_cerebro_cta(period, fromdate, todate):
    c = _build_cerebro_window(fromdate, todate)
    c.addstrategy(CTAStrategy, period=period)
    return c


def build_cerebro_bah(fromdate, todate):
    c = _build_cerebro_window(fromdate, todate)
    c.addstrategy(BuyAndHoldStrategy)
    return c


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_db_date_range(db_path, tablename='ohlc'):
    """Return (min_date, max_date) as datetime.date objects from the SQLite DB."""
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    cur.execute(f'SELECT MIN(timestamp), MAX(timestamp) FROM {tablename}')
    min_ts, max_ts = cur.fetchone()
    conn.close()
    return (datetime.datetime.utcfromtimestamp(min_ts).date(),
            datetime.datetime.utcfromtimestamp(max_ts).date())


def _nan(v):
    return v if v is not None else float('nan')


def extract_metrics(strat):
    sqn     = strat.analyzers.sqn.get_analysis()
    sharpe  = strat.analyzers.sharpe.get_analysis()
    dd      = strat.analyzers.drawdown.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    trades  = strat.analyzers.trades.get_analysis()

    total_trades  = trades.get('total', {}).get('total', 0)
    won           = trades.get('won',   {}).get('total', 0)
    lost          = trades.get('lost',  {}).get('total', 0)
    win_rate      = won / total_trades if total_trades else 0.0
    gross_profit  = trades.get('won',  {}).get('pnl', {}).get('total', 0.0)
    gross_loss    = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0.0))
    profit_factor = gross_profit / gross_loss if gross_loss else float('inf')

    return {
        'period':             strat.p.period,
        'sqn':                _nan(sqn.get('sqn')),
        'sharpe':             _nan(sharpe.get('sharperatio')),
        'max_drawdown_pct':   dd.get('max', {}).get('drawdown',  float('nan')),
        'max_drawdown_money': dd.get('max', {}).get('moneydown', float('nan')),
        'total_return_pct':   returns.get('rtot',     float('nan')) * 100,
        'annual_return_pct':  returns.get('rnorm100', float('nan')),
        'total_trades':       total_trades,
        'won':                won,
        'lost':               lost,
        'win_rate':           win_rate,
        'avg_win':            trades.get('won',  {}).get('pnl', {}).get('average', 0.0),
        'avg_loss':           trades.get('lost', {}).get('pnl', {}).get('average', 0.0),
        'profit_factor':      profit_factor,
        'valid_len':          strat.valid_len,
    }


def generate_windows(data_start, data_end, is_days, oos_days, step_days):
    """Yield (is_start, is_end, oos_start, oos_end) for rolling walk-forward."""
    one_day   = datetime.timedelta(days=1)
    is_delta  = datetime.timedelta(days=is_days  - 1)
    oos_delta = datetime.timedelta(days=oos_days - 1)
    step      = datetime.timedelta(days=step_days)

    is_start = data_start
    while True:
        is_end    = is_start  + is_delta
        oos_start = is_end    + one_day
        oos_end   = oos_start + oos_delta
        if oos_end > data_end:
            break
        yield is_start, is_end, oos_start, oos_end
        is_start += step


def run_is_scan(is_start, is_end, periods, select_by=SELECT_BY):
    """Scan all periods on the IS window; return (best_period, scan_df)."""
    rows = []
    for p in periods:
        res = build_cerebro_cta(p, is_start, is_end).run()
        rows.append(extract_metrics(res[0]))
    scan_df = pd.DataFrame(rows).set_index('period')
    col = scan_df[select_by].dropna()
    best_period = int(col.idxmax()) if not col.empty else periods[0]
    return best_period, scan_df


def run_oos_window(period, oos_start, oos_end):
    """Run CTA and B&H on the OOS window; return (cta_metrics, bah_metrics)."""
    cta_m = extract_metrics(build_cerebro_cta(period, oos_start, oos_end).run()[0])
    bah_m = extract_metrics(build_cerebro_bah(oos_start, oos_end).run()[0])
    return cta_m, bah_m


# ── Walk-forward main loop ─────────────────────────────────────────────────────

data_start, data_end = get_db_date_range(DB_PATH)
print(f'Data range : {data_start} → {data_end}')
print(f'IS={IS_DAYS}d  OOS={OOS_DAYS}d  step={STEP_DAYS}d  '
      f'scan periods={SCAN_PERIODS}  select_by={SELECT_BY}')

windows = list(generate_windows(data_start, data_end, IS_DAYS, OOS_DAYS, STEP_DAYS))
print(f'Walk-forward windows: {len(windows)}\n')

oos_rows_cta = []
oos_rows_bah = []

for i, (is_start, is_end, oos_start, oos_end) in enumerate(windows, 1):
    print('─' * 60)
    print(f'Window {i}/{len(windows)}  '
          f'IS:{is_start}→{is_end}  OOS:{oos_start}→{oos_end}')

    best_period, scan_df = run_is_scan(is_start, is_end, SCAN_PERIODS)
    print(f'  IS scan (best period={best_period} by {SELECT_BY}):')
    print(scan_df[['sqn', 'sharpe', 'max_drawdown_pct',
                   'annual_return_pct', 'total_trades']].to_string(
        float_format=lambda x: f'{x:.3f}'))

    cta_m, bah_m = run_oos_window(best_period, oos_start, oos_end)

    base = {'window': i, 'is_start': is_start, 'is_end': is_end,
            'oos_start': oos_start, 'oos_end': oos_end,
            'best_is_period': best_period}
    oos_rows_cta.append({**base, **cta_m})
    oos_rows_bah.append({**base, **bah_m})

    print(f'  OOS CTA(p={best_period}): '
          f'ret={cta_m["total_return_pct"]:+.1f}%  '
          f'sharpe={cta_m["sharpe"]:.3f}  '
          f'maxDD={cta_m["max_drawdown_pct"]:.1f}%  '
          f'trades={cta_m["total_trades"]}')
    print(f'  OOS B&H:         '
          f'ret={bah_m["total_return_pct"]:+.1f}%  '
          f'sharpe={bah_m["sharpe"]:.3f}  '
          f'maxDD={bah_m["max_drawdown_pct"]:.1f}%')

# ── OOS aggregate summary ──────────────────────────────────────────────────────
print('\n' + '=' * 60)
print('Walk-Forward OOS Summary')
print('=' * 60)

cta_df = pd.DataFrame(oos_rows_cta).set_index('window')
bah_df = pd.DataFrame(oos_rows_bah).set_index('window')

detail_cols = ['oos_start', 'oos_end', 'best_is_period',
               'total_return_pct', 'annual_return_pct',
               'max_drawdown_pct', 'sharpe', 'sqn',
               'total_trades', 'win_rate']

print('\n── CTA OOS per window ──────────────────────────────────────────')
print(cta_df[detail_cols].to_string(float_format=lambda x: f'{x:.3f}'))

print('\n── B&H OOS per window ──────────────────────────────────────────')
bah_detail = ['oos_start', 'oos_end',
              'total_return_pct', 'annual_return_pct',
              'max_drawdown_pct', 'sharpe']
print(bah_df[bah_detail].to_string(float_format=lambda x: f'{x:.3f}'))

agg_cols = ['total_return_pct', 'annual_return_pct', 'max_drawdown_pct',
            'sharpe', 'sqn', 'total_trades', 'win_rate', 'profit_factor']

print('\n── Aggregated OOS means ────────────────────────────────────────')
agg = pd.DataFrame({
    'CTA': cta_df[agg_cols].mean(),
    'B&H': bah_df[agg_cols].mean(),
})
print(agg.to_string(float_format=lambda x: f'{x:.3f}'))

beat    = (cta_df['total_return_pct'] > bah_df['total_return_pct']).sum()
total_w = len(cta_df)
print(f'\n── CTA beat B&H: {beat}/{total_w} windows '
      f'({beat / total_w:.0%} by total_return_pct)')
