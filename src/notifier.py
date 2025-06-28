from datetime import datetime
import requests

class NotifierBase:
    def __init__(self, logger):
        self.logger = logger
        self.last_sent_timestamp = None
        self.tickers = {}  # ticker: timestamp
        self.messages = {}  # ticker: message

    def post_message(self, message):
        raise NotImplementedError

    def register_ticker(self, ticker):
        ''' Register available tickers from a strategy, to compose batched messages '''
        if not ticker in self.tickers:
            self.tickers[ticker] = None

    def add_message(self, ticker, timestamp, tf, message):
        ''' Add message to a batch, send only when all tickers have updated the timestamp '''
        if ticker in self.tickers:
            self.tickers[ticker] = timestamp
            self.messages[ticker] = message
            if self.last_sent_timestamp != timestamp and all(self.tickers[t] == timestamp for t in self.tickers):
                message = f"{timestamp.isoformat()} ({tf} min)"
                for k in sorted(self.tickers.keys()):
                    if self.messages[k] is not None: 
                        message += f"\n\n{self.messages[k]}"
                self.post_message(message)
                self.last_sent_timestamp = timestamp
        else:
            raise KeyError(f"Unknown ticker: {ticker}")


class LogNotifier(NotifierBase):
    def __init__(self, logger):
        super().__init__(logger)

    def post_message(self, message):
        self.logger.debug(f"LogNotifier.post_message:\n{message}")


class TgNotifier(NotifierBase):
    def __init__(self, logger, bot_token, channel_id):
        super().__init__(logger)
        self.bot_token = bot_token
        self.channel_id = channel_id

    def post_message(self, message):
        text = message
        self.logger.debug(f"TgNotifier.post_message:\n{text}")
        url = f'https://api.telegram.org/bot{self.bot_token}/sendMessage'
        payload = {
            'chat_id': self.channel_id,
            'text': text,
            'parse_mode': 'HTML', #'MarkdownV2',
            'disable_notification': True,
            'disable_web_page_preview': True
        }
        response = requests.post(url, data=payload)
        json = response.json()
        if not json['ok']:
            self.logger.error(json)
