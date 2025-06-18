import collections
import csv
from datetime import timedelta
import backtrader as bt
from broker.broker import BobotBrokerBase

class BinaryOptionsBroker(BobotBrokerBase):
    def __init__(self, logger, bot_token, channel_id, payout=1.8, stake=10, cash=10000, contract_expiration_min = 15, csv_file="analysis/csv/deriv_backtest.csv"):
        super().__init__(logger, contract_expiration_min, bot_token, channel_id)
        self.order_id = 1
        self.payout = payout
        self.stake = stake
        self.cash = cash
        self.contract_expiration_min = contract_expiration_min
        self.open_contracts = []
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