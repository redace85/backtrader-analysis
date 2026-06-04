"""
crypto_research.py — Multi-instrument CTA strategy research on crypto.

Strategy:
  - Signal:  EMA crossover filtered by ADX trend strength
  - Sizing:  ATR-based (risk_pct of portfolio per instrument)
  - Stop:    ATR trailing stop (ratchets up for longs)
  - Universe: BTC-USD, ETH-USD

Data source: SQLite (.db) files via sqlitefeed.SQLiteData
"""

import os
import sys
import datetime
import math

import backtrader as bt
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

sys.path.insert(0, os.path.dirname(__file__))
from sqlitefeed import SQLiteData

# ── Config ────────────────────────────────────────────────────────────────────

DATA_DIR   = './sqlite_dbs'
START_DATE = datetime.datetime(2018, 1, 1)
END_DATE   = datetime.datetime(2024, 12, 31)
START_CASH = 100_000.0

INSTRUMENTS = {
    'BTC': 'BTC-USD.db',
    'ETH': 'ETH-USD.db',
}


# ── Data loader ───────────────────────────────────────────────────────────────

def load_feed(filename, fromdate=START_DATE, todate=END_DATE):
    return SQLiteData(
        dataname=os.path.join(DATA_DIR, filename),
        tablename='ohlc',
        fromdate=fromdate,
        todate=todate,
    )


# ── CTA Strategy ──────────────────────────────────────────────────────────────

class CTAStrategy(bt.Strategy):
    """
    Multi-instrument trend-following CTA.

    Entry:  fast EMA > slow EMA  AND  ADX > adx_threshold  → long
    Size:   (portfolio_value * risk_pct) / (ATR * atr_mult)
    Stop:   trailing ATR stop — ratchets up each bar, never retreats
    Exit:   stop hit  OR  trend reversal (fast EMA < slow EMA)
    """
    params = dict(
        fast_period=10,
        slow_period=30,
        atr_period=20,
        atr_mult=2.0,
        adx_threshold=20,
        risk_pct=0.02,
        allow_short=False,
    )

    def log(self, txt):
        dt = self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()}, {txt}')

    def __init__(self):
        self.inds = {}
        for d in self.datas:
            fast = bt.ind.EMA(d.close, period=self.p.fast_period)
            slow = bt.ind.EMA(d.close, period=self.p.slow_period)
            atr  = bt.ind.ATR(d, period=self.p.atr_period)
            dm   = bt.ind.DirectionalMovement(d, period=self.p.atr_period)
            self.inds[d._name] = dict(
                fast=fast, slow=slow, atr=atr, adx=dm.adx,
                stop=None,
            )
        self.pending = {}

    def _target_size(self, data):
        atr = self.inds[data._name]['atr'][0]
        if not math.isfinite(atr) or atr <= 0:
            return 0
        risk_amount = self.broker.getvalue() * self.p.risk_pct
        return max(int(risk_amount / (atr * self.p.atr_mult)), 1)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        name = order.data._name
        self.pending.pop(name, None)
        if order.status == order.Completed:
            action = 'BUY' if order.isbuy() else 'SELL'
            self.log(f'{name} {action} size={order.executed.size:.4f} '
                     f'price={order.executed.price:.2f}')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'{name} order failed: {order.getstatusname()}')

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f'{trade.data._name} TRADE closed  pnl={trade.pnl:.2f}')

    def next(self):
        for d in self.datas:
            name = d._name
            if name in self.pending:
                continue

            ind   = self.inds[name]
            pos   = self.getposition(d)
            close = d.close[0]
            atr   = ind['atr'][0]

            trend_up   = ind['fast'][0] > ind['slow'][0]
            trend_down = ind['fast'][0] < ind['slow'][0]
            strong     = ind['adx'][0] > self.p.adx_threshold

            # ── flat ─────────────────────────────────────────────────────────
            if pos.size == 0:
                size = self._target_size(d)
                if size <= 0:
                    continue
                if trend_up and strong:
                    self.pending[name] = self.buy(data=d, size=size)
                    ind['stop'] = close - atr * self.p.atr_mult
                elif trend_down and strong and self.p.allow_short:
                    self.pending[name] = self.sell(data=d, size=size)
                    ind['stop'] = close + atr * self.p.atr_mult

            # ── long ──────────────────────────────────────────────────────────
            elif pos.size > 0:
                new_stop = close - atr * self.p.atr_mult
                if ind['stop'] is None:
                    ind['stop'] = new_stop
                else:
                    ind['stop'] = max(ind['stop'], new_stop)

                if close < ind['stop'] or trend_down:
                    self.pending[name] = self.close(data=d)
                    ind['stop'] = None

            # ── short ─────────────────────────────────────────────────────────
            elif pos.size < 0:
                new_stop = close + atr * self.p.atr_mult
                if ind['stop'] is None:
                    ind['stop'] = new_stop
                else:
                    ind['stop'] = min(ind['stop'], new_stop)

                if close > ind['stop'] or trend_up:
                    self.pending[name] = self.close(data=d)
                    ind['stop'] = None


# ── Cerebro builder ───────────────────────────────────────────────────────────

def build_cerebro(fast=10, slow=30, atr_period=20, atr_mult=2.0,
                  adx_threshold=20, risk_pct=0.02):
    cerebro = bt.Cerebro()

    for name, filename in INSTRUMENTS.items():
        cerebro.adddata(load_feed(filename), name=name)

    cerebro.addstrategy(
        CTAStrategy,
        fast_period=fast,
        slow_period=slow,
        atr_period=atr_period,
        atr_mult=atr_mult,
        adx_threshold=adx_threshold,
        risk_pct=risk_pct,
    )

    cerebro.broker.setcash(START_CASH)
    cerebro.broker.setcommission(0.001)   # 0.1% typical crypto exchange fee
    cerebro.broker.set_coc(True)

    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio,
                        riskfreerate=0.03,
                        annualize=True,
                        timeframe=bt.TimeFrame.Days,
                        _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='annual')
    cerebro.addanalyzer(bt.analyzers.Returns,
                        timeframe=bt.TimeFrame.Days,
                        tann=365,          # crypto trades 365 days/year
                        _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.TimeReturn,
                        timeframe=bt.TimeFrame.Days,
                        _name='timeret')

    return cerebro


# ── Metrics ───────────────────────────────────────────────────────────────────

def extract_metrics(strat, label=''):
    sqn     = strat.analyzers.sqn.get_analysis()
    sharpe  = strat.analyzers.sharpe.get_analysis()
    dd      = strat.analyzers.drawdown.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    trades  = strat.analyzers.trades.get_analysis()

    total = trades.get('total', {}).get('total', 0)
    won   = trades.get('won',   {}).get('total', 0)
    win_rate = won / total if total else 0.0

    gp = trades.get('won',  {}).get('pnl', {}).get('total', 0.0)
    gl = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0.0))

    return {
        'label':       label,
        'sqn':         sqn.get('sqn', float('nan')),
        'sharpe':      sharpe.get('sharperatio', float('nan')),
        'max_dd_pct':  dd.get('max', {}).get('drawdown', float('nan')),
        'ann_ret_pct': returns.get('rnorm100', float('nan')),
        'tot_ret_pct': returns.get('rtot', float('nan')) * 100,
        'trades':      total,
        'win_rate':    win_rate,
        'pf':          gp / gl if gl else float('inf'),
    }


# ── Equity curve ──────────────────────────────────────────────────────────────

def plot_equity(strat, title='Crypto CTA Portfolio Equity Curve'):
    timeret = strat.analyzers.timeret.get_analysis()
    if not timeret:
        print('No TimeReturn data to plot.')
        return

    dates  = list(timeret.keys())
    rets   = list(timeret.values())
    equity = [START_CASH]
    for r in rets:
        equity.append(equity[-1] * (1 + r))
    equity = equity[1:]

    peak   = pd.Series(equity).cummax()
    dd_pct = (pd.Series(equity) - peak) / peak * 100

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7),
                                   sharex=True,
                                   gridspec_kw={'height_ratios': [3, 1]})
    fig.suptitle(title, fontsize=13)

    ax1.plot(dates, equity, color='#1565C0', linewidth=1.5)
    ax1.axhline(START_CASH, color='gray', linewidth=0.8, linestyle='--')
    ax1.set_ylabel('Portfolio Value ($)')
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:,.0f}'))
    ax1.grid(True, alpha=0.3)

    ax2.fill_between(dates, dd_pct, 0, color='#C62828', alpha=0.6)
    ax2.set_ylabel('Drawdown (%)')
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax2.xaxis.set_major_locator(mdates.YearLocator())
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('crypto_equity.png', dpi=150, bbox_inches='tight')
    print('Equity curve saved → crypto_equity.png')
    plt.show()


# ── Single run ────────────────────────────────────────────────────────────────

SINGLE = dict(fast=10, slow=30, atr_period=20, atr_mult=2.0,
              adx_threshold=20, risk_pct=0.02)

print('=' * 60)
print('Crypto CTA Single Run')
for k, v in SINGLE.items():
    print(f'  {k} = {v}')
print('=' * 60)

cerebro = build_cerebro(**SINGLE)
print(f'Starting Value: {cerebro.broker.getvalue():,.2f}')
result = cerebro.run()
strat  = result[0]
final  = cerebro.broker.getvalue()

print(f'\nFinal Value:  {final:,.2f}')
print(f'Total Return: {(final / START_CASH - 1) * 100:.1f}%')

metrics = extract_metrics(strat, 'single')
print(f'\nSQN:          {metrics["sqn"]:.3f}')
print(f'Sharpe:       {metrics["sharpe"]:.3f}')
print(f'Max DD:       {metrics["max_dd_pct"]:.1f}%')
print(f'Ann Return:   {metrics["ann_ret_pct"]:.1f}%')
print(f'Trades:       {metrics["trades"]}')
print(f'Win Rate:     {metrics["win_rate"]:.1%}')
print(f'Profit Factor:{metrics["pf"]:.2f}')

print('\n── Annual Returns ────────────────────────────────────────────')
annual = strat.analyzers.annual.get_analysis()
for yr, ret in sorted(annual.items()):
    bar = '#' * int(abs(ret * 100 / 2))
    sign = '+' if ret >= 0 else '-'
    print(f'  {yr}: {sign}{abs(ret)*100:5.1f}%  {bar}')

plot_equity(strat)

# ── Parameter scan ────────────────────────────────────────────────────────────
# Sweep: slow MA period  ×  ATR stop multiplier

SLOW_RANGE = [20, 30, 40, 60]
MULT_RANGE = [1.5, 2.0, 2.5, 3.0]

print('\n' + '=' * 60)
print('Parameter Scan: slow_period × atr_mult')
print('=' * 60)

scan_rows = []
for slow in SLOW_RANGE:
    for mult in MULT_RANGE:
        c = build_cerebro(fast=SINGLE['fast'], slow=slow,
                          atr_period=SINGLE['atr_period'], atr_mult=mult,
                          adx_threshold=SINGLE['adx_threshold'],
                          risk_pct=SINGLE['risk_pct'])
        res = c.run()
        s   = res[0]
        label = f'slow={slow:2d} mult={mult}'
        row = extract_metrics(s, label)
        scan_rows.append(row)
        print(f'  {label:<18}  sqn={row["sqn"]:6.3f}  sharpe={row["sharpe"]:6.3f}'
              f'  maxDD={row["max_dd_pct"]:5.1f}%  ann={row["ann_ret_pct"]:5.1f}%'
              f'  trades={row["trades"]:3d}  win%={row["win_rate"]:.1%}')

scan_df = pd.DataFrame(scan_rows).set_index('label')

print('\n── Summary ───────────────────────────────────────────────────')
print(scan_df[['sqn', 'sharpe', 'max_dd_pct', 'ann_ret_pct',
               'trades', 'win_rate', 'pf']].to_string(
    float_format=lambda x: f'{x:.3f}'))

def _safe_idxmax(col):
    s = col.dropna()
    return s.idxmax() if not s.empty else None

def _safe_idxmin(col):
    s = col.dropna()
    return s.idxmin() if not s.empty else None

best = {
    'Best SQN':        _safe_idxmax(scan_df['sqn']),
    'Best Sharpe':     _safe_idxmax(scan_df['sharpe']),
    'Lowest Max DD':   _safe_idxmin(scan_df['max_dd_pct']),
    'Best Annual Ret': _safe_idxmax(scan_df['ann_ret_pct']),
}
print('\n── Best Configurations ───────────────────────────────────────')
for label, idx in best.items():
    print(f'  {label:<18}: {idx}')

# ── Heatmap: Sharpe ratio ─────────────────────────────────────────────────────

sharpe_matrix = scan_df['sharpe'].values.reshape(len(SLOW_RANGE), len(MULT_RANGE))

fig, ax = plt.subplots(figsize=(7, 4))
im = ax.imshow(sharpe_matrix, cmap='RdYlGn', aspect='auto')
ax.set_xticks(range(len(MULT_RANGE)))
ax.set_xticklabels([f'{m}' for m in MULT_RANGE])
ax.set_yticks(range(len(SLOW_RANGE)))
ax.set_yticklabels([f'{s}' for s in SLOW_RANGE])
ax.set_xlabel('ATR Multiplier')
ax.set_ylabel('Slow EMA Period')
ax.set_title('Sharpe Ratio Heatmap (slow × atr_mult) — BTC+ETH')
plt.colorbar(im, ax=ax)

for i in range(len(SLOW_RANGE)):
    for j in range(len(MULT_RANGE)):
        val = sharpe_matrix[i, j]
        ax.text(j, i, f'{val:.2f}', ha='center', va='center', fontsize=9,
                color='black' if abs(val) < 1.5 else 'white')

plt.tight_layout()
plt.savefig('crypto_sharpe_heatmap.png', dpi=150, bbox_inches='tight')
print('\nSharpe heatmap saved → crypto_sharpe_heatmap.png')
plt.show()
