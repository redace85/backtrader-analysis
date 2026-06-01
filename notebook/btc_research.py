import backtrader as bt
import datetime
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from sqlitefeed import SQLiteData

DB_PATH = './csv_files/BTC-USD.db'


class CyStrategy(bt.Strategy):
    params = (
        ('period', 5),
    )

    def log(self, txt):
        dt = self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        self.kama = bt.indicators.KAMA(
            self.dnames.btc_weekly,
            period=self.p.period,
        )

        self.dmi = bt.indicators.DM(
            self.dnames.btc_daily,
            period=self.p.period,
        )

        self.kd = bt.indicators.StochasticFull(
            self.dnames.btc_daily,
            period=self.p.period,
        )

        self.cross = bt.indicators.CrossOver(self.kd.percD, self.kd.percDSlow, plot=False)

        self.buy_signal = self.cross == 1
        self.sell_signal = self.cross == -1

        self.order = None
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
        self.log('Valid trading len:{}'.format(self.valid_len))


class BuyAndHoldStrategy(bt.Strategy):
    params = (('period', 'BAH'),)

    def log(self, txt):
        dt = self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        self.order = None
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
        self.log('B&H valid_len:{}'.format(self.valid_len))


def _build_cerebro_base():
    """Create a cerebro with data feeds, broker settings, and analyzers (no strategy)."""
    feed = SQLiteData(dataname=DB_PATH, tablename='ohlc')

    cerebro = bt.Cerebro(oldtrades=True, oldbuysell=True)
    cerebro.adddata(feed, name='btc_daily')
    cerebro.resampledata(feed, name='btc_weekly', timeframe=bt.TimeFrame.Weeks)

    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(0.0005)
    cerebro.broker.set_coc(True)
    cerebro.broker.set_fundstartval(50)

    cerebro.addsizer(bt.sizers.AllInSizerInt, percents=99)

    cerebro.addanalyzer(bt.analyzers.SQN)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio,
                        riskfreerate=0.03,
                        annualize=True,
                        timeframe=bt.TimeFrame.Days,
                        _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='annual')
    cerebro.addanalyzer(bt.analyzers.Returns,
                        timeframe=bt.TimeFrame.Days,
                        tann=252,
                        _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    return cerebro


def build_cerebro(period):
    """Build and configure a cerebro instance for CyStrategy with a given period."""
    cerebro = _build_cerebro_base()
    cerebro.addstrategy(CyStrategy, period=period)
    return cerebro


def build_cerebro_bah():
    """Build and configure a cerebro instance for the Buy & Hold baseline."""
    cerebro = _build_cerebro_base()
    cerebro.addstrategy(BuyAndHoldStrategy)
    return cerebro


def extract_metrics(strat, start_cash):
    """Extract key metrics from a completed strategy run."""
    sqn = strat.analyzers.sqn.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    dd = strat.analyzers.drawdown.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    total_trades = trades.get('total', {}).get('total', 0)
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    win_rate = won / total_trades if total_trades else 0.0

    avg_win = trades.get('won', {}).get('pnl', {}).get('average', 0.0)
    avg_loss = trades.get('lost', {}).get('pnl', {}).get('average', 0.0)
    gross_profit = trades.get('won', {}).get('pnl', {}).get('total', 0.0)
    gross_loss = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0.0))
    profit_factor = gross_profit / gross_loss if gross_loss else float('inf')

    return {
        'period': strat.p.period,
        'sqn': sqn.get('sqn', float('nan')),
        'sharpe': sharpe.get('sharperatio', float('nan')),
        'max_drawdown_pct': dd.get('max', {}).get('drawdown', float('nan')),
        'max_drawdown_money': dd.get('max', {}).get('moneydown', float('nan')),
        'total_return_pct': returns.get('rtot', float('nan')) * 100,
        'annual_return_pct': returns.get('rnorm100', float('nan')),
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': win_rate,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'profit_factor': profit_factor,
        'valid_len': strat.valid_len,
    }


# ── single run ────────────────────────────────────────────────────────────────
SINGLE_PERIOD = 9

print('=' * 60)
print(f'Single run  period={SINGLE_PERIOD}')
print('=' * 60)

cerebro = build_cerebro(SINGLE_PERIOD)
print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())
result = cerebro.run()
print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())

strat = result[0]
for a_name in strat.analyzers.getnames():
    strat.analyzers.getbyname(a_name).pprint()

print('\nvalid_len={}, trades={}'.format(
    strat.valid_len,
    strat.analyzers.sqn.get_analysis()['trades']
))
if strat.analyzers.sqn.get_analysis()['trades']:
    print('bars/trade ratio: {:.2f}'.format(
        strat.valid_len / strat.analyzers.sqn.get_analysis()['trades']
    ))

# ── parameter research scan ───────────────────────────────────────────────────
SCAN_PERIODS = list(range(5, 25, 2))   # [5, 7, 9, ..., 23]

print('\n' + '=' * 60)
print('Parameter scan: period in', SCAN_PERIODS)
print('=' * 60)

rows = []
scan_strats = []
for p in SCAN_PERIODS:
    c = build_cerebro(p)
    start_cash = c.broker.getvalue()
    res = c.run()
    s = res[0]
    scan_strats.append(s)
    row = extract_metrics(s, start_cash)
    rows.append(row)
    print(f'  period={p:2d}  sqn={row["sqn"]:.3f}  sharpe={row["sharpe"]:.3f}'
          f'  maxDD={row["max_drawdown_pct"]:.1f}%  ann={row["annual_return_pct"]:.1f}%'
          f'  trades={row["total_trades"]}  win%={row["win_rate"]:.1%}')

results_df = pd.DataFrame(rows).set_index('period')

print('\n── Research summary ─────────────────────────────────────────')
print(results_df[[
    'sqn', 'sharpe', 'max_drawdown_pct', 'annual_return_pct',
    'total_trades', 'win_rate', 'profit_factor',
]].to_string(float_format=lambda x: f'{x:.3f}'))

def _safe_idxmax(col):
    s = col.dropna()
    return s.idxmax() if not s.empty else None

def _safe_idxmin(col):
    s = col.dropna()
    return s.idxmin() if not s.empty else None

best = {
    'Best SQN':        _safe_idxmax(results_df['sqn']),
    'Best Sharpe':     _safe_idxmax(results_df['sharpe']),
    'Lowest MaxDD':    _safe_idxmin(results_df['max_drawdown_pct']),
    'Best Annual Ret': _safe_idxmax(results_df['annual_return_pct']),
}
print('\n── Best periods ──────────────────────────────────────────────')
for label, idx in best.items():
    print(f'  {label}: period={idx}')

annual_df = pd.DataFrame({
    p: dict(s.analyzers.annual.get_analysis())
    for p, s in zip(SCAN_PERIODS, scan_strats)
}).T
annual_df.index.name = 'period'
print('\n── Annual returns by period (%) ──────────────────────────────')
print((annual_df * 100).round(2).to_string())

# ── Buy & Hold baseline ───────────────────────────────────────────────────────
print('\n' + '=' * 60)
print('Buy & Hold baseline')
print('=' * 60)

cerebro_bah = build_cerebro_bah()
print('Starting Portfolio Value: %.2f' % cerebro_bah.broker.getvalue())
result_bah = cerebro_bah.run()
print('Final Portfolio Value: %.2f' % cerebro_bah.broker.getvalue())

strat_bah = result_bah[0]
metrics_bah = extract_metrics(strat_bah, 100000.0)

# ── Strategy vs Buy & Hold comparison ────────────────────────────────────────
print('\n' + '=' * 60)
print('Strategy comparison: CyStrategy vs Buy & Hold')
print('=' * 60)

metrics_single = extract_metrics(strat, 100000.0)

best_sqn_period = _safe_idxmax(results_df['sqn'])
best_strat = scan_strats[SCAN_PERIODS.index(best_sqn_period)]
metrics_best = extract_metrics(best_strat, 100000.0)

comparison_rows = [
    {**metrics_single,  'strategy': f'CyStrategy(period={SINGLE_PERIOD})'},
    {**metrics_best,    'strategy': f'CyStrategy best SQN(period={best_sqn_period})'},
    {**metrics_bah,     'strategy': 'Buy & Hold'},
]
comparison_df = pd.DataFrame(comparison_rows).set_index('strategy')

cmp_cols = [
    'total_return_pct', 'annual_return_pct', 'max_drawdown_pct',
    'sharpe', 'sqn', 'total_trades', 'win_rate', 'profit_factor',
]
print(comparison_df[cmp_cols].to_string(float_format=lambda x: f'{x:.3f}'))

# ── plot single-run chart ─────────────────────────────────────────────────────
plot_params = dict(
    style='candle',
    barup='#FF0033',
    bardown='#32CD32',
    volup='#F66269',
    voldown='#43A047',
)

cerebro.plot(iplot=False, **plot_params)
plt.show()
