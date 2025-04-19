# broker.py

import collections
import os
from datetime import datetime, timezone, timedelta

import requests
import backtrader as bt
import websocket
import json
import threading
import csv

class DerivBroker(bt.broker.BrokerBase):
    def log(self, txt, dt=None):
        ''' Logging function for this broker'''
        ticker = '<broker>'
        if self.logger:
            self.logger.debug('%-10s: %s' % (ticker, txt))
        else:
            print('%-10s: %s' % (ticker, txt))

    def __init__(self, logger, app_id, api_token, contract_expiration_min, bot_token, channel_id):
        super().__init__()
        self.logger = logger
        self.cash = 10000.0  # initial virtual balance
        self.is_ready = False
        self.trades = []
        self.trades_offset = 0
        self.trades_limit = 50
        self.positions = {}
        self.order_id = 1
        self.app_id = app_id
        self.api_token = api_token
        self.contract_expiration_min = contract_expiration_min
        self.bot_token = bot_token
        self.channel_id = channel_id
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


class BinaryOptionsBroker(bt.BrokerBase):
    def log(self, txt, dt=None):
        ''' Logging function for this broker'''
        ticker = '<broker>'
        if self.logger:
            self.logger.debug('%-10s: %s' % (ticker, txt))
        else:
            print('%-10s: %s' % (ticker, txt))

    def __init__(self, logger, payout=1.8, stake=10, cash=10000, contract_expiration_min = 15, csv_file="analysis/csv/deriv_backtest.csv"):
        super().__init__()
        self.logger = logger
        self.order_id = 1
        self.positions = {}
        self.payout = payout
        self.stake = stake
        self.cash = cash
        self.contract_expiration_min = contract_expiration_min
        self.open_contracts = []
        self.notifs = collections.deque()
        self.csv_file = csv_file
        
        # Initialize CSV file with header if it doesn't exist
        self._initialize_csv()

    def start(self):
        self.value = self.cash
        self.startingcash = self.cash

    def getcash(self):
        return self.cash

    def getvalue(self):
        return self.cash

    def getposition(self, data):
        #self.log(f"getposition for {data.ticker}")
        return self.positions.get(data)

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

        expiry = dt + timedelta(minutes=self.contract_expiration_min)
        if order.valid is not None:
            delta_days = order.valid - bt.date2num(dt)
            expiry = dt + timedelta(days=delta_days)

        entry_price = data.close[0]
        direction = 'CALL' if order.isbuy() else 'PUT'

        stake = abs(order.size)  # Get stake from order quantity

        contract = {
            'symbol': symbol,
            'data': data,
            'direction': direction,
            'entry_time': dt,
            'entry_price': entry_price,
            'expiry': expiry,
            'stake': stake,
            'order': order,
        }

        self.cash -= stake
        self.open_contracts.append(contract)

        p = bt.Position(order.size, 1)
        p.adjbase = 1
        self.log(f"Add position for {symbol}: px {entry_price}, size {order.size}")
        self.positions[data] = p

        comminfo = self.getcommissioninfo(order.data)
        order.execute(
            data, order.size, 1,
            0, 0, 0,
            order.size, order.size, 0,
            comminfo.margin, 0,
            0, 0)
        
        order.completed()
        order.addcomminfo(comminfo)

        # Store a notification for the order
        self.notify(order)

    def next(self):
        # Iterate over all data streams passed into the broker
        resolved = []
        for contract in self.open_contracts:
            data = contract['data']
            # The date for the current bar
            now = bt.num2date(data.datetime[0])

            if now >= contract['expiry']:
                current_price = data.close[0]
                won = (
                    contract['direction'] == 'CALL' and current_price > contract['entry_price']
                ) or (
                    contract['direction'] == 'PUT' and current_price < contract['entry_price']
                )

                # Debugging PnL calculation and logic
                #self.log(f"Processing contract {contract['direction']} at {now}. Entry: {contract['entry_price']}, Current Price: {current_price}, Won: {won}")

                contract_sell_price = 0
                if won:
                    pnl = contract['stake'] * (self.payout - 1)  # Positive PnL for winning
                    contract_sell_price = contract['stake'] * self.payout
                    self.cash += contract_sell_price
                    #self.log(f"Won contract. PnL: {pnl}, Cash after win: {self.cash}")
                else:
                    pnl = -contract['stake']  # Negative PnL for losing
                    #self.log(f"Lost contract. PnL: {pnl}, Cash after loss: {self.cash}")

                # Log the trade details before it's completed
                self.log(f"Expired contract {data.ticker} {contract['direction']}, Won: {won}, PnL: {pnl}, Cash: {self.cash}")

                # Write to CSV when contract expires
                self._write_contract_to_csv(contract, won, contract_sell_price)
                
                order = contract['order']
                data = contract['data']
                comminfo = self.getcommissioninfo(order.data)

                # Handle exit order
                exit_order = bt.SellOrder(owner=order.owner, data=data, size=order.size) if order.isbuy() else bt.BuyOrder(owner=order.owner, data=data, size=-order.size)
                exit_order.ref = self.order_id
                self.order_id += 1
                exit_order.parent = order  # Link back to the entry order

                exit_price = data.close[0]

                exit_order.execute(
                    data, exit_order.size, exit_price,
                    exit_order.size, exit_price, 0,
                    0, 0, 0,
                    comminfo.margin, pnl,
                    0, 0
                )

                exit_order.completed()
                exit_order.addcomminfo(comminfo)
                self.notify(exit_order)
                self.positions[data] = None

                resolved.append(contract)

        for c in resolved:
            self.open_contracts.remove(c)


    def notify(self, order):
        self.notifs.append(order.clone())

    def get_notification(self):
        try:
            return self.notifs.popleft()
        except IndexError:
            pass

        return None

    def _initialize_csv(self):
        # Create CSV file and write the header
        with open(self.csv_file, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                'app_id', 'buy_price', 'contract_id', 'contract_type', 'duration_type',
                'longcode', 'payout', 'purchase_time', 'sell_price', 'sell_time',
                'shortcode', 'transaction_id', 'underlying_symbol'
            ])

    def _write_contract_to_csv(self, contract, won, sell_price):
        # Prepare row to be written to CSV
        entry_time = contract['entry_time'].strftime('%Y-%m-%d %H:%M:%S')
        expiry_time = contract['expiry'].strftime('%Y-%m-%d %H:%M:%S')
        row = [
            1,  # Example app_id
            contract['stake'],  # Buy price
            contract['order'].ref,  # Contract ID
            contract['direction'],  # Contract Type (CALL/PUT)
            'minutes',  # Duration Type
            f"Win payout if {contract['data'].ticker} is strictly {'higher' if contract['direction'] == 'CALL' else 'lower'} than entry spot at 15 minutes after contract start time.",
            self.payout * contract['stake'],  # Payout
            entry_time,  # Purchase time
            sell_price,  # Sell price (if applicable)
            expiry_time,  # Sell time (expiry time)
            f"{contract['direction']}_{contract['data'].ticker}_{self.payout}_{contract['order'].ref}",  # Shortcode
            contract['order'].ref,  # Transaction ID
            contract['data'].ticker  # Underlying symbol
        ]
        
        # Write row to CSV
        with open(self.csv_file, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(row)

    def post_message(self, message):
        pass
