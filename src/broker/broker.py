import os
import websocket
import threading
import collections
import backtrader as bt
from datetime import datetime, timezone

from notifier import LogNotifier, TgNotifier

class InstrumentInfo:
    def __init__(self, symbol):
        self.symbol = symbol
        self.max_leverage = None
        self.price_scale = None
        self.price_step = None
        self.min_order_qty = None
        self.qty_step = None 


class BobotBrokerBase(bt.broker.BrokerBase):
    def log(self, txt, dt=None):
        ''' Logging function for this broker'''
        ticker = '<broker>'
        if self.logger:
            self.logger.debug('%-10s: %s' % (ticker, txt))
        else:
            print('%-10s: %s' % (ticker, txt))

    def __init__(self, logger, timeframe, bot_token, channel_id, tickers):
        super().__init__()
        self.logger = logger
        self.timeframe = timeframe
        self.tickers = tickers
        self.is_ready = False
        self.trades = []
        self.trades_offset = 0
        self.trades_limit = 50
        self.positions = {}
        self.ws = None
        self.notifs = collections.deque()
        self.datas = {}
        self.notifier = None
        if bot_token is not None and channel_id is not None:
            self.notifier = TgNotifier(logger, bot_token, channel_id)
        else:
            self.notifier = LogNotifier(logger)

    def ready(self):
        return self.is_ready;

    def notify(self, order):
        self.notifs.append(order.clone())

    def get_notification(self):
        try:
            return self.notifs.popleft()
        except IndexError:
            pass
        return None

    def find_data(self, ticker):
        for d in self.datas:
            if d.ticker == ticker:
                return d
        return None

    def keep_alive(self, message, interval=30):
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

            # Re-run the send_ping function every n seconds
            self._schedule_next_ping()

        def start_send_ping():
            # Call send_ping initially
            send_ping()

        # Start the periodic call using Timer
        self._schedule_next_ping = lambda: threading.Timer(interval, send_ping).start()

        # First call to start the periodic checks
        start_send_ping()

    def post_message(self, message):
        if self.notifier:
            response = self.notifier.post_message(message)
            #self.log(f"post_message: {response}")

    def register_ticker(self, ticker):
        ''' Register available tickers from a strategy, to compose batched messages '''
        if self.notifier:
            self.notifier.register_ticker(ticker)

    def add_message(self, ticker, timestamp, message):
        ''' Add message to a batch, send only when all tickers have updated the timestamp '''
        if self.notifier:
            self.notifier.add_message(ticker, timestamp, self.timeframe, message)

    def add_position(self, symbol, is_buy, price, size, id=None, status='open'):
        if not is_buy:
            size = -size
        p = bt.Position(size, price)
        p.ref = id
        p.status = status
        self.log(f"Add position for {symbol}: px {price}, size {size}, ref={p.ref}")
        self.positions[symbol] = p

    def getposition(self, data):
        #self.log(f"getposition for {data.ticker}")
        return self.positions.get(data.ticker, bt.Position(0, 0))

    def cancel_all(self, data):
        raise NotImplementedError

    def get_open_orders(self, data=None):
        raise NotImplementedError
