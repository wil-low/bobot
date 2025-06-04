# datafeed.py

import os
import backtrader as bt
import pandas as pd
import sqlite3
import queue
import threading
from datetime import datetime, timezone
import websocket

class HistDataCSVData(bt.feeds.GenericCSVData):
    params = (
        ('timeframe', bt.TimeFrame.Minutes),
        ('headers', False),
        ('separator', ';'),
        ('dtformat', '%Y%m%d %H%M%S'),
        ('volume', 5),
        ('openinterest', -1),
        ('reverse', False)
    )

    #def _loadline(self, linetokens):
    #    try:
    #        # Force volume to 1 regardless of input
    #        linetokens[5] = 1.0
    #    except IndexError:
    #        return False  # Skip malformed lines
    #    return super()._loadline(linetokens)

class TiingoCSVData(bt.feeds.GenericCSVData):
	params = (
		('timeframe', bt.TimeFrame.Days),
		('headers', True),
		('separator', ','),
		('dtformat', '%Y-%m-%d'),
		('close', 6),
		('high', 7),
		('low', 8),
		('open', 9),
		('volume', 10),
		('openinterest', -1),
		('reverse', False)
	)


class SQLiteData(bt.feeds.PandasData):
    @classmethod
    def from_sqlite(cls, symbol, database, fromdate=None, todate=None):
        # Load data from SQLite
        conn = sqlite3.connect(database)
        query = """
            SELECT p.date, p.open, p.high, p.low, p.close, p.volume
            FROM prices p
            JOIN tickers t ON t.id = p.ticker_id
            WHERE t.symbol = ?
            ORDER BY p.date
        """
        df = pd.read_sql(query, conn, params=(symbol,), parse_dates=["date"])
        conn.close()

        df.set_index('date', inplace=True)
        if fromdate:
            df = df[df.index >= pd.to_datetime(fromdate)]
        if todate:
            df = df[df.index <= pd.to_datetime(todate)]

        # Return a PandasData instance
        return cls(dataname=df)


class BobotLiveDataBase(bt.feeds.DataBase):
    """
    A Backtrader live data base feed
    """
    def log(self, txt, dt=None):
        ''' Logging function for this feed'''
        ticker = self.symbol
        tf = self.timeframe_min
        if self.logger:
            self.logger.debug('%-10s,%-3d: %s' % (ticker, tf, txt))
        else:
            print('%-10s,%-3d: %s' % (ticker, tf, txt))

    def __init__(self, logger, symbol, granularity, history_size):
        self.logger = logger
        self.symbol = symbol
        self.history_size = history_size
        self.granularity = granularity
        self.md = queue.Queue()
        self._last_candle = None
        self._candle_consumed = True
        self.ohlc = {}
        self.last_epoch = 0
        self.last_ts = 0
        self.ws = None
        self.thread = None
        print("LiveDataBase init")

    def islive(self):
        return True

    def _load(self):
        #self.log(f"_load {self.symbol}")
        if self._candle_consumed:
            try:
                self._last_candle = self.md.get(timeout=0.1)
                self._candle_consumed = False
            except queue.Empty:
                return None

        # Return same candle until Backtrader accepts it
        c = self._last_candle

        #self.log(c)

        dt = datetime.fromtimestamp(c['epoch'], timezone.utc)
        self.lines.datetime[0] = bt.date2num(dt)
        self.lines.open[0] = float(c['open'])
        self.lines.high[0] = float(c['high'])
        self.lines.low[0] = float(c['low'])
        self.lines.close[0] = float(c['close'])
        self.lines.volume[0] = c['volume']

        #dt = datetime.now(timezone.utc)
        #self.log(f"diff from now: {bt.date2num(dt)} - {self.lines.datetime[0]} = {bt.date2num(dt) - self.lines.datetime[0]}")

        self._candle_consumed = True  # Only set to True after setting lines
        return True

    def keep_alive(self, message):
        def send_ping():
            #self.log(f"send_ping {message}")
            if self.ws:
                try:
                    if len(message) > 0:
                        self.ws.send(message)
                    else:
                        self.ws.sock.ping()
                except websocket.WebSocketConnectionClosedException:
                    self.log("ping: WebSocketConnectionClosedException, exiting")
                    os._exit(1)
            else:
                self.log("ping: WebSocket not connected")

            # Re-run the send_ping function every 30 seconds
            self._schedule_next_ping()

        def start_send_ping():
            # Call send_ping initially
            send_ping()

        # Start the periodic call using Timer
        self._schedule_next_ping = lambda: threading.Timer(30, send_ping).start()

        # First call to start the periodic checks
        start_send_ping()

    def reset_ohlc(self):
        self.ohlc = {
            'open': self.ohlc['close'],
            'high': self.ohlc['close'],
            'low': self.ohlc['close'],
            'close': None,
            'volume': 0
        }

    def update_ohlc(self, epoch, px):
        #self.log(f"update_ohlc {epoch}, {px}")
        self.ohlc['epoch'] = epoch
        self.ohlc['close'] = px
        self.ohlc['volume'] = 1
        if self.ohlc['high'] is None or px > self.ohlc['high']:
            self.ohlc['high'] = px
        if self.ohlc['low'] is None or px < self.ohlc['low']:
            self.ohlc['low'] = px
