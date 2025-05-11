import requests


import collections
import backtrader as bt
from datetime import datetime, timezone


class BobotBrokerBase(bt.broker.BrokerBase):
    def log(self, txt, dt=None):
        ''' Logging function for this broker'''
        ticker = '<broker>'
        if self.logger:
            self.logger.debug('%-10s: %s' % (ticker, txt))
        else:
            print('%-10s: %s' % (ticker, txt))

    def __init__(self, logger, bot_token, channel_id):
        super().__init__()
        self.logger = logger
        self.is_ready = False
        self.trades = []
        self.trades_offset = 0
        self.trades_limit = 50
        self.positions = {}
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.ws = None
        self.notifs = collections.deque()

    def ready(self):
        return self.is_ready;

    def get_notification(self):
        try:
            return self.notifs.popleft()
        except IndexError:
            pass
        return None

    def post_message(self, message):
        if self.bot_token is not None and self.channel_id is not None:
            url = f'https://api.telegram.org/bot{self.bot_token}/sendMessage'
            payload = {
                'chat_id': self.channel_id,
                'text': message,
                'disable_notification': True,
                'disable_web_page_preview': True
            }
            response = requests.post(url, data=payload)
            self.log(f"post_message: {response.json()}")
