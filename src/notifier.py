from datetime import datetime
import requests

class TgNotifier:
    def __init__(self, bot_token, channel_id):
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.last_sent_timestamp = None
        self.tickers = {}  # ticker: timestamp
        self.messages = {}  # ticker: message

    def post_message(self, message):
        text = message
        #print(f"post_message:\n{text}")
        url = f'https://api.telegram.org/bot{self.bot_token}/sendMessage'
        payload = {
            'chat_id': self.channel_id,
            'text': text,
            'disable_notification': True,
            'disable_web_page_preview': True
        }
        response = requests.post(url, data=payload)
        return response.json()

    def register_ticker(self, ticker):
        ''' Register available tickers from a strategy, to compose batched messages '''
        if not ticker in self.tickers:
            self.tickers[ticker] = None

    def add_message(self, ticker, timestamp, message):
        ''' Add message to a batch, send only when all tickers have updated the timestamp '''
        if ticker in self.tickers:
            self.tickers[ticker] = timestamp
            self.messages[ticker] = message
            if self.last_sent_timestamp != timestamp and all(self.tickers, lambda t: self.tickers[t] == timestamp):
                message = ''
                for k in sorted(self.tickers.keys()):
                    message += f"\n{self.messages[k]}"
                self.post_message(message)
                self.last_sent_timestamp = timestamp
        else:
            raise KeyError(f"Unknown ticker: {ticker}")
