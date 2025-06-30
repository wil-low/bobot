import requests


import base64
import collections
import csv
import hashlib
import hmac
import json
import os
import threading
from datetime import datetime, timezone

from broker.broker import BobotBrokerBase


class OKXBroker(BobotBrokerBase):
    def __init__(self, logger, contract_expiration_min, bot_token, channel_id, api_key, api_secret, api_passphrase, tickers):
        super().__init__(logger, contract_expiration_min, bot_token, channel_id, tickers)
        self.cash = 10000.0  # initial virtual balance
        self.HEADERS = {
            'OK-ACCESS-KEY': api_key,
            'OK-ACCESS-PASSPHRASE': api_passphrase,
            'x-simulated-trading': '1',
            'Content-Type': 'application/json'
        }
        self.api_secret = api_secret.encode()
        self.is_ready = True
        #self._connect()

    BASE_URL = "https://www.okx.com"  # Same for demo, but use demo credentials

    def make_signature(self, method, path, body):
        # Get current timestamp in ISO 8601 format
        iso_timestamp = datetime.now(timezone.utc).isoformat()[0:23] + 'Z'
        data = iso_timestamp + method + path + body
        #self.logger.debug(data)
        result = self.HEADERS
        result['OK-ACCESS-SIGN'] = base64.b64encode(hmac.new(self.api_secret, data.encode(), hashlib.sha256).digest()).decode()
        result['OK-ACCESS-TIMESTAMP'] = iso_timestamp
        return result

    def _connect(self):
        def on_open(ws):
            self.log("WebSocket connected.")
            auth_msg = {"authorize": self.api_token}
            ws.send(json.dumps(auth_msg))

        def on_error(ws, message):
            self.log(f"on_error: {str(message)}")

        def on_message(ws, message):
            #print(f"on_message: {message}")
            data = json.loads(message)
            if "error" in data:
                self.log(f"ERROR in {data['msg_type']}: {data['error']['message']}")
            else:
                if data['msg_type'] == 'authorize':
                    self.log(f"on_message: {message}")
                    if "authorize" in data:
                        self.cash = data['authorize']['balance']
                        self.log(f"balance: {data['authorize']['balance']}")
                        self.subscribe_positions()
                elif data['msg_type'] == 'portfolio':
                    if "portfolio" in data:
                        self.log(f"Positions: {len(data['portfolio']['contracts'])}")
                        self.positions = {}
                        for c in data['portfolio']['contracts']:
                            self.add_position(c['symbol'], c['contract_type'] == 'CALL', 1, c['buy_price'])
                        self.is_ready = True
                        ws.sock.ping()
                elif data['msg_type'] == 'proposal':
                    self.log(f"on_message: {message}")
                    payout = data['proposal']['payout'] / data['proposal']['ask_price'] - 1
                    if payout > self.min_payout:
                        msg = {
                            "buy": data['proposal']['id'],
                            "price": 100000000000,
                            "passthrough": {
                                "symbol": data['echo_req']['symbol'],
                                "contract_type": data['echo_req']['contract_type']
                            }
                        }
                        if self.ws:
                            self.ws.send(json.dumps(msg))
                        else:
                            self.log("⚠️ WebSocket not connected")
                    else:
                        self.log(f"Skipping proposal for {data['echo_req']['symbol']}, payout {payout} < {self.min_payout}")
                elif data['msg_type'] == 'buy':
                    self.log(f"✅ Trade placed: {data['buy']['contract_id']}")
                    self.add_position(data['passthrough']['symbol'], data['passthrough']['contract_type'] == 'CALL', 1, data['buy']['buy_price'])
                elif data['msg_type'] == 'profit_table':
                    self.log(f"on_message: {message}")
                    for t in data['profit_table']['transactions']:
                        self.trades.append(t)
                    if data['profit_table']['count'] > 0:
                        self.trades_offset += self.trades_limit
                        self.get_trades_chunk()
                    else:
                        self.write_trades_csv()

        def run_ws():
            print("run_ws")
            self.ws = websocket.WebSocketApp(
                f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}",
                on_open=on_open,
                on_error=on_error,
                on_message=on_message
            )
            self.ws.run_forever()

        t = threading.Thread(target=run_ws)
        t.daemon = True
        t.start()

    def getcash(self):
        return self.cash

    def getvalue(self):
        return self.cash

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
            exectype=exectype,
            valid=valid,
            parent=parent
        )
        order.owner = owner
        order.data = data
        order.ref = self.order_id
        self.order_id += 1

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
            exectype=exectype,
            valid=valid,
            parent=parent
        )
        order.owner = owner
        order.data = data
        order.ref = self.order_id
        self.order_id += 1

        self.submit(order)  # Submit the order to the broker
        return order

    def submit(self, order):
        data = order.data
        dt = data.datetime.datetime(0)
        symbol = data.ticker

        path = '/api/v5/trade/order'

        form_data = {
            "instId": data.ticker,
            "tdMode": "isolated",
            #"clOrdId": "b15",
            "side": "buy" if order.isbuy() else "sell",
            "ordType": "limit" if order.exectype == bt.Order.Limit else "market",
            "sz": order.size
        }
        if order.price is not None:
            form_data['px'] = order.price
        #if stop_loss is not None:
        #    form_data['slTriggerPx'] = stop_loss
        #    form_data['slOrdPx'] = -1  # market
        #    #form_data['reduceOnly'] = True
        #if take_profit is not None:
        #    form_data['tpTriggerPx'] = take_profit
        #    form_data['tpOrdPx'] = -1  # market

        try:
            form_data = json.dumps(form_data)
            self.logger.debug(form_data)
            headers = self.make_signature('POST', path, form_data)
            self.logger.debug(headers)
            response = requests.post(f"{self.BASE_URL}{path}", data = form_data, headers = headers)
            response.raise_for_status()
            json_data = response.json()
            if json_data['code'] == '0':
                json_data['code'] = 'ok'
                json_data['data'] = {'order_id': json_data['data'][0]['ordId']}
            self.logger.debug(json_data)
        # If the request fails (404) then print the error.
        except requests.exceptions.HTTPError as error:
            self.logger.error(error)
            order.rejected()

        # Store a notification for the order
        self.notify(order)
        return order

    def subscribe_positions(self):
        def get_portfolio():
            #self.log("get_portfolio")
            msg = {
                "portfolio": 1
            }
            if self.ws:
                try:
                    self.ws.send(json.dumps(msg))
                except websocket.WebSocketConnectionClosedException:
                    os._exit(1)
            else:
                self.log("WebSocket not connected")

            # Re-run the get_portfolio function every 30 seconds
            self._schedule_next_get_portfolio()

        def start_get_portfolio():
            # Call get_portfolio initially
            get_portfolio()

        # Start the periodic call using Timer
        self._schedule_next_get_portfolio = lambda: threading.Timer(30, get_portfolio).start()

        # First call to start the periodic checks
        start_get_portfolio()

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
