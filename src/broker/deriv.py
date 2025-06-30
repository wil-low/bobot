import websocket
import csv
import json
import os
import threading
import backtrader as bt
from datetime import datetime, timezone

from broker.broker import BobotBrokerBase


class DerivBroker(BobotBrokerBase):
    def __init__(self, logger, bot_token, channel_id, app_id, api_token, contract_expiration_min, min_payout, tickers):
        super().__init__(logger, contract_expiration_min, bot_token, channel_id, tickers)
        self.cash = 10000.0  # initial virtual balance
        self.min_payout = min_payout
        self.order_id = 1
        self.app_id = app_id
        self.api_token = api_token
        self.contract_expiration_min = contract_expiration_min
        self._connect()

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
            self.log(f"run_ws, app_id={self.app_id}")
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

    def buy_contract(self, symbol, is_buy, size):
        msg = {
            "proposal": 1,
            "amount": size,
            "basis": "stake",
            "contract_type": 'CALL' if is_buy else 'PUT',
            "currency": "USD",
            "duration": self.contract_expiration_min,
            "duration_unit": "m",
            "symbol": symbol
        }
        if self.ws:
            self.ws.send(json.dumps(msg))
        else:
            self.log("⚠️ WebSocket not connected")

        order = bt.BuyOrder(simulated=True, size=size) if is_buy else bt.SellOrder(simulated=True, size=size)
        order.ref = self.order_id
        order.created.price = 0

        self.order_id += 1
        return order

    def getcash(self):
        return self.cash

    def getvalue(self):
        return self.cash

    def buy(self, owner=None, data=None, size=None, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None, trailamount=None,
            trailpercent=None, parent=None, transmit=True, **kwargs):
        self.log("Executing BUY")
        return self.buy_contract(data.ticker, True, size)

    def sell(self, owner=None, data=None, size=None, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None, trailamount=None,
             trailpercent=None, parent=None, transmit=True, **kwargs):
        self.log("Executing SELL")
        return self.buy_contract(data.ticker, False, size)

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
