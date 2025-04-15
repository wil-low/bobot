# broker.py

import collections
import os
import time
import traceback
import backtrader as bt
import websocket
import json
import threading

class DerivBroker(bt.broker.BrokerBase):
    def log(self, txt, dt=None):
        ''' Logging function for this broker'''
        ticker = '<broker>'
        if self.logger:
            self.logger.debug('%-10s: %s' % (ticker, txt))
        else:
            print('%-10s: %s' % (ticker, txt))

    def __init__(self, logger, app_id, api_token, contract_expiration_min):
        super().__init__()
        self.logger = logger
        self.cash = 10000.0  # initial virtual balance
        self.is_ready = False
        self.positions = {}
        self.order_id = 1
        self.app_id = app_id
        self.api_token = api_token
        self.contract_expiration_min = contract_expiration_min
        self.ws = None
        self.notifs = collections.deque()
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
                elif data['msg_type'] == 'buy':
                    self.log(f"✅ Trade placed: {data['buy']['contract_id']}")
                    self.add_position(data['passthrough']['symbol'], data['passthrough']['contract_type'] == 'CALL', 1, data['buy_price'])

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
    
    def ready(self):
        return self.is_ready;

    def get_notification(self):
        try:
            return self.notifs.popleft()
        except IndexError:
            pass

        return None

    def add_position(self, symbol, is_buy, price, size):
        if not is_buy:
            size = -size
        p = bt.Position(size, price)
        #self.log(f"Add position for {symbol}: px {price}, size {size}")
        self.positions[symbol] = p

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

    def getposition(self, data):
        #self.log(f"getposition for {data.ticker}")
        return self.positions.get(data.ticker)

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

