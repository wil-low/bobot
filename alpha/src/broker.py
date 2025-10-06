# broker.py

import requests


class RStockTrader:
    URL = "https://api.stockstrader.com"

    def __init__(self, params):
        super().__init__()
        self.params = params
        self.HEADERS = {'Authorization': f"Bearer {self.params['api_key']}"}
        self.HEADERS_URLENCODED = self.HEADERS
        self.HEADERS_URLENCODED['Content-Type'] = "application/x-www-form-urlencoded"
        self.cash = 0  # Initial cash balance
        self.value = 0 # Initial equity
        self.positions = {}  # Holds open positions
        self.orders = {}  # Track active orders
        self.fetch_data()

    def getcash(self):
        """ Return available cash in the account """
        return self.cash

    def getvalue(self):
        """ Return total account value (cash + positions) """
        return self.equity

    def fetch_data(self):
        skip = 0
        self.positions = {}
        while True:
            url = f"{RStockTrader.URL}/api/v1/accounts/{self.params['account_id']}/deals?skip={skip}&limit=100"
            response = requests.get(url, headers = self.HEADERS)
            response.raise_for_status()
            data = response.json()
            #print(data)
            if data['code'] == 'ok':
                if len(data['data']) == 0:
                    break
                for item in data['data']:
                    if item['status'] == 'open':
                        ticker = item['ticker']
                        pos = ticker.find('.')
                        if pos >= 0:
                            ticker = ticker[0:pos]
                        pos = {
                            'side': item['side'],
                            'qty': abs(item['volume']),
                            'entry_time': item['open_time'],
                            'entry': item['open_price'],
                            'close': item['close_price'],
                            'type': 'limit' if item['side'] == 'sell' else 'market'
                        }
                        #print(f"{ticker},{pos['qty']},{pos['entry']},{pos['close']}")
                        self.positions[ticker] = pos
                skip += 100
            else:
                break

        response = requests.get(f"{RStockTrader.URL}/api/v1/accounts/{self.params['account_id']}", headers = self.HEADERS)
        response.raise_for_status()
        data = response.json()
        #print(data)
        if data['code'] == 'ok':
            self.cash = data['data']['margin']['free_margin']
            self.equity = data['data']['margin']['equity']
        #print(self.positions)
