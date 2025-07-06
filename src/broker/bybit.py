import time
import requests
import websocket
import csv
import hashlib
import hmac
import json
import os
import threading
import decimal
from datetime import datetime, timezone
import backtrader as bt

from broker.broker import BobotBrokerBase, InstrumentInfo

class BybitBroker(BobotBrokerBase):

    DEMO_URL = "https://api-demo.bybit.com"
    #MAIN_URL = "https://api.bybit.nl"

    def __init__(self, logger, bot_token, channel_id, api_key, api_secret, tickers):
        super().__init__(logger, 0, bot_token, channel_id, tickers)
        self.cash = 10000.0  # initial virtual balance
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window = str(5000)
        self.url = BybitBroker.DEMO_URL
        self.HEADERS = {
            'X-BAPI-API-KEY': api_key,
            'X-BAPI-SIGN': None,
            'X-BAPI-SIGN-TYPE': '2',
            'X-BAPI-TIMESTAMP': None,
            'X-BAPI-RECV-WINDOW': self.recv_window,
            'Content-Type': 'application/json'
        }
        self.is_ready = False
        self.instrument_info = {}  # ticker: InstrumentInfo
        self.get_account_info()
        self._connect()

    def http_request(self, endpoint, method, payload, log_response=True):
        self.logger.debug(f"{method} {endpoint}: {payload}")
        headers = self.make_signature(payload)
        #self.logger.debug(headers)
        json_data = None
        try:
            if method == "POST":
                response = requests.post(self.url + endpoint, headers=headers, data=payload)
            else:
                response = requests.get(self.url + endpoint + "?" + payload, headers=headers)
            response.raise_for_status()
            json_data = response.json()
            if log_response:
                self.logger.debug(f"http_response: {json_data}")
        # If the request fails (404) then print the error.
        except requests.exceptions.HTTPError as error:
            self.logger.error(error)
        time.sleep(0.5)
        return json_data

    def make_signature(self, payload):
        timestamp = str(int(time.time() * 1000))
        param_str = timestamp + self.api_key + self.recv_window + payload
        #self.logger.debug(f"param_str={param_str}")
        hash = hmac.new(bytes(self.api_secret, "utf-8"), param_str.encode("utf-8"), hashlib.sha256)
        signature = hash.hexdigest()
        result = self.HEADERS
        result['X-BAPI-SIGN'] = signature
        result['X-BAPI-TIMESTAMP'] = timestamp
        return result
        
    def _connect(self):
        def on_open(ws):
            self.log("WebSocket connected.")
            # Generate expires.
            expires = int((time.time() + 1) * 1000)
            # Generate signature.
            signature = str(hmac.new(
                bytes(self.api_secret, "utf-8"),
                bytes(f"GET/realtime{expires}", "utf-8"), digestmod="sha256"
            ).hexdigest())
            # Authenticate with API.
            ws.send(
                json.dumps({
                    "op": "auth",
                    "args": [self.api_key, expires, signature]
                })
            )

        def on_error(ws, message):
            self.log(f"on_error: {str(message)}")

        def on_message(ws, message):
            self.log(f"on_message: {message}")
            data = json.loads(message)
            if not data.get('success', True):
                self.log(f"ERROR in {data['op']}: {data['ret_msg']}")
            else:
                if data.get('op', None) == 'auth':
                    self.keep_alive(json.dumps({"op": "ping"}), 20)
                    self.subscribe_positions()
                    self.get_position_info()
                    self.is_ready = True
                else:
                    topic = data.get('topic', None)
                    if topic == 'position.linear':
                        for p in data['data']:
                            self.add_position(p['symbol'], p['side'] != 'Sell', float(p['entryPrice']), float(p['size']))

        def run_ws():
            print("run_ws")
            self.ws = websocket.WebSocketApp(
                "wss://stream-demo.bybit.com/v5/private",
                #"wss://stream.bybit.com/v5/private",
                on_open=on_open,
                on_error=on_error,
                on_message=on_message
            )
            self.ws.run_forever()

        t = threading.Thread(target=run_ws)
        t.daemon = True
        t.start()

    def get_account_info(self):
        self.http_request('/v5/account/wallet-balance', 'GET', f"accountType=UNIFIED")

    def get_position_info(self):
        result = self.http_request('/v5/position/list', 'GET', f"category=linear&settleCoin=USDT")
        self.positions = {}
        for pos in result['result']['list']:
            if pos['symbol'] in self.tickers:
                self.add_position(pos['symbol'], pos['side'] == 'Buy', float(pos['avgPrice']), float(pos['size']))

    def getcash(self):
        return self.cash

    def getvalue(self):
        return self.cash

    def get_instrument_info(self, symbol):
        result = self.instrument_info.get(symbol, None)
        if result:
            return result
        try:
            url = f"https://api.bybit.com/v5/market/instruments-info"
            params = {
                "category": "linear",
                "symbol": symbol
            }
            response = requests.get(url, params=params)
            response.raise_for_status()
            json_data = response.json()
            self.logger.debug(json_data)
            result = InstrumentInfo(symbol)
            info = json_data['result']['list'][0]
            result.max_leverage = info['leverageFilter']['maxLeverage']
            result.price_scale = int(info['priceScale'])
            result.min_order_qty = float(info['lotSizeFilter']['minOrderQty'])
            result.qty_step = decimal.Decimal(info['lotSizeFilter']['qtyStep'])
            self.instrument_info[symbol] = result
            self.set_leverage(symbol, result.max_leverage)
        # If the request fails (404) then print the error.
        except requests.exceptions.HTTPError as error:
            self.logger.error(error)
        return result

    def set_leverage(self, symbol, leverage):
        form_data = {
            "category": "linear",
            "symbol": symbol,
            "buyLeverage": leverage,
            "sellLeverage": leverage
        }

        form_data = json.dumps(form_data)
        #self.logger.debug(form_data)
        result = self.http_request('/v5/position/set-leverage', 'POST', form_data)
        self.logger.debug(result)

    def normalize_price(self, symbol, value):
        info = self.get_instrument_info(symbol)
        return f"%.{info.price_scale}f" % value

    def normalize_qty(self, symbol, value):
        info = self.get_instrument_info(symbol)
        value = decimal.Decimal(value)
        qty_step = decimal.Decimal(info.qty_step)
        # Round down to nearest multiple of qty_step
        result = (value // qty_step) * qty_step
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
        symbol = data.ticker
        if order.price is not None:
            order.price = str(self.normalize_price(symbol, order.price))
        if not order.reduceOnly:
            order.size = self.normalize_qty(symbol, abs(order.size))

        self.log(f"submit: {symbol}, isbuy={order.isbuy()}, size={order.size}")
        form_data = {
            "category": "linear",
            "symbol": data.ticker,
            "side": "Buy" if order.isbuy() else "Sell",
            "orderType": "Limit" if order.exectype == bt.Order.Limit else "Market",
            "qty": str(abs(order.size))
        }
        if order.price is not None:
            form_data['price'] = str(order.price)
        if order.stopLoss is not None:
            order.stopLoss = str(self.normalize_price(symbol, order.stopLoss))
            form_data['stopLoss'] = order.stopLoss
        if order.takeProfit is not None:
            order.takeProfit = str(self.normalize_price(symbol, order.takeProfit))
            form_data['takeProfit'] = order.takeProfit
        if order.reduceOnly:
            form_data['reduceOnly'] = order.reduceOnly

        form_data = json.dumps(form_data)
        #self.logger.debug(form_data)
        result = self.http_request('/v5/order/create', 'POST', form_data)
        if result['retCode'] != 0:
            order.reject()
        else:
            order.ref = result['result']['orderId']

        # Store a notification for the order
        self.notify(order)
        return order

    def cancel(self, order):
        data = order.data
        symbol = data.ticker

        form_data = {
            "category": "linear",
            "symbol": symbol,
            "orderId": order.ref
        }
        form_data = json.dumps(form_data)
        #self.logger.debug(form_data)
        result = self.http_request('/v5/order/cancel', 'POST', form_data)

    def cancel_all(self, data):
        symbol = data.ticker

        form_data = {
            "category": "linear",
            "symbol": symbol
        }
        form_data = json.dumps(form_data)
        #self.logger.debug(form_data)
        result = self.http_request('/v5/order/cancel-all', 'POST', form_data)

    def subscribe_positions(self):
        #self.log("get_portfolio")
        msg = {
            "op": "subscribe",
            "args": [
                "position.linear"
            ]
        }
        if self.ws:
            try:
                self.ws.send(json.dumps(msg))
            except websocket.WebSocketConnectionClosedException:
                os._exit(1)

    def get_open_orders(self, data=None):
        result = []
        params = "category=linear&orderFilter=Order"
        if data:
            params += f"&symbol={data.ticker}"
        else:
            params += "&settleCoin=USDT"
        response = self.http_request('/v5/order/realtime', 'GET', params)
        for item in response['result']['list']:
            data = self.find_data(item['symbol'])
            if data is not None:
                o = None
                if item['side'] == 'Buy':
                    o = bt.BuyOrder(data=data, size=float(item['qty']), price=float(item['price']), exectype=bt.Order.Limit, simulated=True)
                else:
                    o = bt.SellOrder(data=data, size=float(item['qty']), price=float(item['price']), exectype=bt.Order.Limit, simulated=True)
                result.append(o)
        return result

    def get_trades(self, date_from, date_to):
        self.is_ready = False
        self.trades = []
        self.trades_offset = 0
        self.trades_from = date_from
        self.trades_to = date_to
        cursor = None
        while True:
            cursor = self.get_trades_chunk(cursor)
            print(cursor)
            if not cursor:
                break 
        self.write_trades_csv()

    def get_trades_chunk(self, cursor):
        startTime = int(datetime.strptime(self.trades_from, "%Y%m%d %H%M%S").timestamp() * 1000)
        params = f"category=linear&limit=100&startTime={startTime}"
        if cursor is not None:
            params += f"&cursor={cursor}"
        response = self.http_request('/v5/position/closed-pnl', 'GET', params, False)
        self.trades += response['result']['list']
        return response['result']['nextPageCursor']

    def write_trades_csv(self):
        # Convert Unix timestamps to human-readable format
        for trade in self.trades:
            trade["createdTime"] = datetime.fromtimestamp(float(trade["createdTime"]) / 1000, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            trade["updatedTime"] = datetime.fromtimestamp(float(trade["updatedTime"]) / 1000, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

        # Output file name
        output_file = "analysis/csv/bybit_export.csv"

        # Write to CSV
        with open(output_file, mode="w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self.trades[0].keys())
            writer.writeheader()
            writer.writerows(self.trades)

        print(f"Total {len(self.trades)} trades. CSV file saved as: {output_file}")
        self.is_ready = True
