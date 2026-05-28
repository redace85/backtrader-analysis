import backtrader as bt
import sqlite3
import datetime


class SQLiteData(bt.feed.DataBase):
    params = (('tablename', 'ohlc'),)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # dataname is the path to the .db file
        self.conn = None
        self.iter = None
        self.data = None

    def start(self):
        super().start()
        if self.data is None:
            self.conn = sqlite3.connect(self.p.dataname)
            cur = self.conn.cursor()

            where_clauses = []
            params = []
            if self.p.fromdate is not None:
                where_clauses.append('timestamp >= ?')
                params.append(int(self.p.fromdate.timestamp()))
            if self.p.todate is not None:
                where_clauses.append('timestamp <= ?')
                params.append(int(self.p.todate.timestamp()))

            sql = f'SELECT timestamp, open, high, low, close, volume FROM {self.p.tablename}'
            if where_clauses:
                sql += ' WHERE ' + ' AND '.join(where_clauses)
            sql += ' ORDER BY timestamp'

            cur.execute(sql, params)
            self.data = cur.fetchall()
            self.conn.close()
            self.conn = None

        self.iter = iter(self.data)

    def stop(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _load(self):
        if self.iter is None:
            return False

        try:
            row = next(self.iter)
        except StopIteration:
            return False

        ts, open_, high, low, close, volume = row
        dt = datetime.datetime.utcfromtimestamp(ts)

        self.lines.datetime[0] = bt.date2num(dt)
        self.lines.open[0] = open_
        self.lines.high[0] = high
        self.lines.low[0] = low
        self.lines.close[0] = close
        self.lines.volume[0] = volume
        self.lines.openinterest[0] = -1

        return True
