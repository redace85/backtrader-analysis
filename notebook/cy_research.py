import backtrader as bt
import datetime
import pandas as pd
import matplotlib.pyplot as plt

# csv data source
dataframe = pd.read_csv('./csv_files/000300.XSHG.csv', parse_dates=True, index_col=0)

# pandasdata feeder
feed = bt.feeds.PandasData(dataname=dataframe, openinterest=None)

MaT = ['SMA', 'EMA', 'WMA', 'DEMA', 'TEMA', 'TRIMA', 'KAMA', 'MAMA', 'T3']


class CyStrategy(bt.Strategy):
    params = (
        ('period', 5),
    )

    def log(self, txt):
        dt = self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        self.kama = bt.indicators.KAMA(
            self.dnames.cy_weekly,
            period=self.p.period,
        )

        self.dmi = bt.indicators.DM(
            self.dnames.cy_daily,
            period=self.p.period,
        )

        self.kd = bt.indicators.StochasticFull(
            self.dnames.cy_daily,
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


cerebro = bt.Cerebro(oldtrades=True, oldbuysell=True)
cerebro.adddata(feed, name='cy_daily')
cy_weekly = cerebro.resampledata(feed, name='cy_weekly', timeframe=bt.TimeFrame.Weeks)

cerebro.addstrategy(CyStrategy, period=9)

cerebro.broker.setcash(100000.0)
cerebro.broker.setcommission(0.0005)
cerebro.broker.set_coc(True)
cerebro.broker.set_fundstartval(50)

cerebro.addsizer(bt.sizers.AllInSizerInt, percents=99)

cerebro.addanalyzer(bt.analyzers.SQN)

print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())

result = cerebro.run()

print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())

strat = result[0]
for a_name in strat.analyzers.getnames():
    strat.analyzers.getbyname(a_name).pprint()

print('valid len:{}, trades:{}'.format(
    strat.valid_len,
    strat.analyzers.sqn.get_analysis()['trades']
))
print(strat.valid_len / strat.analyzers.sqn.get_analysis()['trades'])

plot_params = dict(
    style='candle',
    barup='#FF0033',
    bardown='#32CD32',
    volup='#F66269',
    voldown='#43A047',
)

cerebro.plot(iplot=False, **plot_params)
plt.show()
