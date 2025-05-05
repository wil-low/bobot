# datafeed.py

import queue
import os
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
        self.md = queue.Queue()
        self._last_candle = None
        self._candle_consumed = True
        self.ohlc = {}
        self.last_ts = 0
        self.ws = None
        self.thread = None

    def start(self):
        super().start()
        self._start_ws()

    def _start_ws(self):
        def on_open(ws):
            #self.log("WebSocket connected.")
            self.keep_alive()
            ws.send(json.dumps({
                "ticks_history": self.symbol,
                "adjust_start_time": 1,
                "count": self.history_size,
                "end": "latest",
                "granularity": self.granularity,
                "start": 1,
                "style": "candles"
            }))

        def on_message(ws, message):
            #print(f"datafeed: {message}")
            data = json.loads(message)
            if "error" in data:
                self.log(f"ERROR in {data['msg_type']}: {data['error']['message']}")
            else:
                if data['msg_type'] == 'candles':
                    # historical MD
                    self.log(data)
                    self.log(f"Historical candles: {len(data['candles'])}")
                    for candle in data['candles']:
                        self.ohlc['close'] = candle['close']
                        self.md.put(candle)
                    self.reset_ohlc()
                    ws.send(json.dumps({
                        "ticks": self.symbol,
                        "subscribe": 1
                    }))
                elif data['msg_type'] == 'tick':
                    # real-time MD
                    #self.log(data)
                    self.update_ohlc(data['tick']['epoch'], data['tick']['quote'])
                    epoch = self.ohlc['epoch']
                    if epoch % self.granularity == 0:
                        self.log(str(self.ohlc))
                        if self.last_ts < epoch:
                            self.md.put(self.ohlc)
                            self.reset_ohlc()
                            self.log(f"last_ts updated: {self.last_ts}")
                        else:
                            self.log(f"duplicate epoch detected: {self.last_ts}")
                    self.realtime_md = True
                    self.last_ts = epoch

        def on_error(ws, message):
            self.log(f"[DerivLiveData] on_error: {str(message)}")

        def run_ws():
            self.ws = websocket.WebSocketApp(f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}",
                on_open=on_open,
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
        self.lines.volume[0] = 1 if self.realtime_md else 0

        #dt = datetime.now(timezone.utc)
        #self.log(f"diff from now: {bt.date2num(dt)} - {self.lines.datetime[0]} = {bt.date2num(dt) - self.lines.datetime[0]}")

        self._candle_consumed = True  # Only set to True after setting lines
        return True

    def keep_alive(self):
        def send_ping():
            #print(f"{self.symbol}: send_ping")
            if self.ws:
                try:
                    self.ws.send(json.dumps({'ping': 1}))
                    #self.ws.sock.ping()
                except websocket.WebSocketConnectionClosedException:
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
            'close': None
        }

    def update_ohlc(self, epoch, px):
        self.ohlc['epoch'] = epoch
        self.ohlc['close'] = px
        if self.ohlc['high'] is None or px > self.ohlc['high']:
            self.ohlc['high'] = px
        if self.ohlc['low'] is None or px < self.ohlc['low']:
            self.ohlc['low'] = px

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

    def _loadline(self, linetokens):
        try:
            # Force volume to 1 regardless of input
            linetokens[5] = 1.0
        except IndexError:
            return False  # Skip malformed lines
        return super()._loadline(linetokens)
