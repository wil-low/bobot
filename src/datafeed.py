# datafeed.py

import collections
import traceback
import backtrader as bt
import websocket
import threading
import json
from datetime import datetime, timezone
import time

class DerivLiveData(bt.feeds.DataBase):
    """
    A Backtrader live data feed that connects to Deriv WebSocket and streams tick data.
    """

    def log(self, txt, dt=None):
        ''' Logging function for this feed'''
        ticker = self.symbol
        if self.logger:
            self.logger.debug('%-10s: %s' % (ticker, txt))
        else:
            print('%-10s: %s' % (ticker, txt))

    def __init__(self, logger, app_id, symbol, granularity, history_size):
        self.logger = logger
        self.app_id = app_id
        self.symbol = symbol
        self.history_size = history_size
        self.granularity = granularity
        self.realtime_md = False
        self.md = collections.deque()
        self.ws = None
        self.thread = None

    def start(self):
        super().start()
        self._start_ws()

    def _start_ws(self):
        def on_message(ws, message):
            data = json.loads(message)
            if data['msg_type'] == 'candles':
                # historical MD
                self.log(data)
                for candle in data['candles']:
                    self.md.append(candle)
            elif data['msg_type'] == 'ohlc':
                # real-time MD
                if data['ohlc']['epoch'] % self.granularity == 0:
                    self.log(data)
                    self.md.append(data['ohlc'])
                    self.realtime_md = True
                    ws.sock.ping()

        def on_error(ws, message):
            self.log(f"[DerivLiveData] on_error: {str(message)}")

        def run_ws():
            self.ws = websocket.WebSocketApp(f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}",
                on_open=lambda ws: ws.send(json.dumps({
                    "ticks_history": self.symbol,
                    "adjust_start_time": 1,
                    "count": self.history_size,
                    "end": "latest",
                    "granularity": self.granularity,
                    "start": 1,
                    "style": "candles",
                    "subscribe": 1
                })),
                on_message=on_message,
                on_error=on_error
            )
            self.ws.run_forever()

        self.thread = threading.Thread(target=run_ws)
        self.thread.daemon = True
        self.thread.start()

    def islive(self):
        return True

    def _load(self):
        #self.log("_load")
        if len(self.md) == 0:
            time.sleep(0.5)
            return None

        c = self.md.popleft()
        self.log(c)
        dt = datetime.fromtimestamp(c['epoch'], timezone.utc)
        self.lines.datetime[0] = bt.date2num(dt)
        self.lines.open[0] = float(c['open'])
        self.lines.high[0] = float(c['high'])
        self.lines.low[0] = float(c['low'])
        self.lines.close[0] = float(c['close'])
        self.lines.volume[0] = 1 if self.realtime_md else 0

        #dt = datetime.now(timezone.utc)
        #self.log(f"diff from now: {bt.date2num(dt)} - {self.lines.datetime[0]} = {bt.date2num(dt) - self.lines.datetime[0]}")
        return True
