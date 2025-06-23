import requests


import collections
import backtrader as bt
from datetime import datetime, timezone

from notifier import TgNotifier


class BobotBrokerBase(bt.broker.BrokerBase):
    def log(self, txt, dt=None):
        ''' Logging function for this broker'''
        ticker = '<broker>'
        if self.logger:
            self.logger.debug('%-10s: %s' % (ticker, txt))
        else:
            print('%-10s: %s' % (ticker, txt))

    def __init__(self, logger, timeframe, bot_token, channel_id):
        super().__init__()
        self.logger = logger
        self.timeframe = timeframe
        self.is_ready = False
        self.trades = []
        self.trades_offset = 0
        self.trades_limit = 50
        self.positions = {}
        self.ws = None
        self.notifs = collections.deque()
        self.notifier = None
        if bot_token is not None and channel_id is not None:
            self.notifier = TgNotifier(logger, bot_token, channel_id)

    def ready(self):
        return self.is_ready;

    def get_notification(self):
        try:
            return self.notifs.popleft()
        except IndexError:
            pass
        return None

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
