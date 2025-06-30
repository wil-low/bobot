import requests
import csv
import json
import decimal
from datetime import datetime, timezone
import backtrader as bt

from broker.broker import BobotBrokerBase, InstrumentInfo

class RStockTrader(BobotBrokerBase):

    URL = "https://api.stockstrader.com"

    def __init__(self, logger, bot_token, channel_id, account_id, api_key):
        super().__init__(logger, 0, bot_token, channel_id)
        self.HEADERS = {'Authorization': f'Bearer {api_key}'}
        self.HEADERS_URLENCODED = self.HEADERS
        self.HEADERS_URLENCODED['Content-Type'] = "application/x-www-form-urlencoded"
        self.account_id = account_id
        self.cash = 0  # Initial cash balance
        self.value = 0 # Initial equity
        self.positions = {}  # Holds open positions
        self.orders = {}  # Track active orders
        self.instrument_info = {}  # ticker: InstrumentInfo
        self.get_account_info()
        #self.get_order_info()
        self.get_position_info()
        self.is_ready = True

    def get_account_info(self):
        response = requests.get(f"{RStockTrader.URL}/api/v1/accounts/{self.account_id}", headers = self.HEADERS)
        response.raise_for_status()
        data = response.json()
        self.log(f"get_account_info: {data}")
        if data['code'] == 'ok':
            self.cash = data['data']['margin']['balance']
            self.equity = data['data']['margin']['equity']

    def get_open_orders(self):
        self.orders = {}
        orders = []
        url = f"{RStockTrader.URL}/api/v1/accounts/{self.account_id}/orders?status=active"
        response = requests.get(url, headers = self.HEADERS)
        response.raise_for_status()
        data = response.json()
        self.log(f"get_order_info: {data}")
        if data['code'] == 'ok':
            for item in data['data']:
                o = None
                data = self.find_data('frx' + item['ticker'])
                if item['side'] == 'buy':
                    o = bt.BuyOrder(data=data, size=item['volume'], price=item['price'], exectype=bt.Order.Limit, simulated=True)
                else:
                    o = bt.SellOrder(data=data, size=item['volume'], price=item['price'], exectype=bt.Order.Limit, simulated=True)
                o.ref = item['id']
                #pos.ref = item['id']
                #pos.status = item['status']
                self.orders[o.ref] = o
                orders.append(o)
                #self.log(f"Add order: {o}")
        return orders

    def get_position_info(self):
        url = f"{RStockTrader.URL}/api/v1/accounts/{self.account_id}/deals?"
        response = requests.get(url, headers = self.HEADERS)
        response.raise_for_status()
        data = response.json()
        self.log(f"get_position_info: {data}")
        if data['code'] == 'ok':
            self.positions = {}
            for item in data['data']:
                if item['status'] == 'open':
                    pos_size = item['volume']
                    self.add_position('frx' + item['ticker'], item['side'] == 'buy', item['open_price'], pos_size, item['id'])
                    self.log(f"Add position: {item}")

    def getcash(self):
        return self.cash

    def getvalue(self):
        return self.cash

    def get_instrument_info(self, ticker):
        symbol = ticker.replace('frx', '')
        result = self.instrument_info.get(symbol, None)
        if result:
            return result
        try:
            response = requests.get(f"{RStockTrader.URL}/api/v1/accounts/{self.account_id}/instruments/{symbol}", headers = self.HEADERS)
            #response.raise_for_status()
            data = response.json()
            self.log(f"get_instrument_info: {symbol}, {data}")
            if data['code'] == 'ok':
                result = InstrumentInfo(symbol)
                info = data['data']
                result.max_leverage = 1 / info['leverage']
                result.price_step = str(info['min_tick'])
                result.min_order_qty = info['min_volume']
                result.qty_step = str(info['volume_step'])
                self.instrument_info[symbol] = result
        # If the request fails (404) then print the error.
        except requests.exceptions.HTTPError as error:
            self.logger.error(error)
        return result

    def normalize_price(self, symbol, value):
        info = self.get_instrument_info(symbol)
        value = decimal.Decimal(value)
        price_step = decimal.Decimal(info.price_step)
        # Round down to nearest multiple of price_step
        result = (value // price_step) * price_step
        self.log(f"normalize_price {result}, {price_step}")
        # Optional: quantize to remove excess digits
        result = result.quantize(price_step, rounding=decimal.ROUND_DOWN)
        return result

    def normalize_qty(self, symbol, value):
        info = self.get_instrument_info(symbol)
        value = decimal.Decimal(value)
        qty_step = decimal.Decimal(info.qty_step)
        # Round down to nearest multiple of qty_step
        result = (value // qty_step) * qty_step
        self.log(f"normalize_qty {result}, {qty_step}")
        # Optional: quantize to remove excess digits
        result = result.quantize(qty_step, rounding=decimal.ROUND_DOWN)
        return result
    
    def buy(self, owner=None, data=None, size=None, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None, trailamount=None,
            trailpercent=None, parent=None, transmit=True, **kwargs):
        self.log("Executing BUY")
        # Create the buy order
        order = bt.BuyOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            parent=parent
        )
        order.owner = owner
        order.data = data
        order.reduceOnly = kwargs.get('reduceOnly', False)
        order.stopLoss = kwargs.get('stopLoss', None)
        order.takeProfit = kwargs.get('takeProfit', None)

        self.submit(order)  # Submit the order to the broker
        return order

    def sell(self, owner=None, data=None, size=None, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None, trailamount=None,
             trailpercent=None, parent=None, transmit=True, **kwargs):
        self.log("Executing SELL")
        # Create the sell order
        order = bt.SellOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            parent=parent
        )
        order.owner = owner
        order.data = data
        order.reduceOnly = kwargs.get('reduceOnly', False)
        order.stopLoss = kwargs.get('stopLoss', None)
        order.takeProfit = kwargs.get('takeProfit', None)

        self.submit(order)  # Submit the order to the broker
        return order

    def submit(self, order):
        data = order.data
        symbol = data.ticker.replace('frx', '')

        if order.reduceOnly:
            # close deal directly
            self.close_position(symbol)
            return

        if order.price is not None:
            order.price = str(self.normalize_price(symbol, order.price))
        if not order.reduceOnly:
            order.size = self.normalize_qty(symbol, abs(order.size))
        self.log(f"submit: {symbol}, isbuy={order.isbuy()}, size={order.size}")

        form_data = {
            'ticker': symbol,
            'side': "buy" if order.isbuy() else "sell",
            'volume': str(abs(order.size)),
            "type": "limit" if order.exectype == bt.Order.Limit else "market"
        }

        if order.price is not None:
            form_data['price'] = str(order.price)
        if order.stopLoss is not None:
            order.stopLoss = str(self.normalize_price(symbol, order.stopLoss))
            form_data['stop_loss'] = order.stopLoss
        if order.takeProfit is not None:
            order.takeProfit = str(self.normalize_price(symbol, order.takeProfit))
            form_data['take_profit'] = order.takeProfit

        self.logger.debug(form_data)

        try:
            response = requests.post(f"{RStockTrader.URL}/api/v1/accounts/{self.account_id}/orders", data = form_data, headers = self.HEADERS_URLENCODED)
            self.log(f"submit: {symbol}, {response.text}")
            response.raise_for_status()
            data = response.json()
            if data['code'] == 'ok':
                order.ref = data['data']['order_id']
                self.orders[order.ref] = order
            else:
                self.log(f"submit error: {data}")
                order.reject()
        # If the request fails (404) then print the error.
        except requests.exceptions.HTTPError as error:
            self.logger.error(error)

        # Store a notification for the order
        self.notify(order)
        return order

    def cancel(self, order):
        response = requests.delete(f"{RStockTrader.URL}/api/v1/accounts/{self.account_id}/orders/{order.ref}", headers=self.HEADERS)
        if response.status_code == 200:
            del self.orders[order.ref]
            order.cancel()

    def cancel_all(self, data):
        symbol = data.ticker
        for o in self.orders.copy().values():
            print(f"cancel_all: ref {o.ref}")
            if o.data.ticker == symbol:
                self.cancel(o)

    def close_position(self, symbol):
        pos = self.positions.get(symbol, None)
        if pos is not None:
            response = requests.delete(f"{RStockTrader.URL}/api/v1/accounts/{self.account_id}/deals/{pos.ref}", headers=self.HEADERS)
            response.raise_for_status()
            data = response.json()
            self.log(f"close_position: {symbol}, {data}")
            if response.status_code == 200:
                del self.positions[symbol]

    def get_trades(self, date_from, date_to):
        self.is_ready = False
        self.trades = []
        self.trades_offset = 0
        self.trades_from = date_from
        self.trades_to = date_to
        self.get_trades_chunk()

    def get_trades_chunk(self):
        msg = {
            "profit_table": 1,
            "description": 1,
            "limit": self.trades_limit,
            "offset": self.trades_offset,
            "sort": "ASC",
            "date_from": self.trades_from,
            "date_to": self.trades_to
        }
        self.log(msg)
        if self.ws:
            self.ws.send(json.dumps(msg))
        else:
            self.log("⚠️ WebSocket not connected")

    def write_trades_csv(self):
        # Convert Unix timestamps to human-readable format
        for trade in self.trades:
            trade["purchase_time"] = datetime.fromtimestamp(trade["purchase_time"], timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            trade["sell_time"] = datetime.fromtimestamp(trade["sell_time"], timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

        # Output file name
        output_file = "analysis/csv/deriv_export.csv"

        # Write to CSV
        with open(output_file, mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self.trades[0].keys())
            writer.writeheader()
            writer.writerows(self.trades)

        print(f"Total {len(self.trades)} trades. CSV file saved as: {output_file}")
        self.is_ready = True
