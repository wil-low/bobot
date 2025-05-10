import backtrader as bt
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

class CointegratedPairs(bt.Strategy):
    params = (
        ('ci_n', 100),      # Cointegration test window
        ('ci_t', 0.05),     # p-value threshold
        ('z_entry', 2.0),   # Z-score entry threshold
        ('pnl_p', 0.8),     # % of expected reversion to target
        ('pnl_t', 20),      # Minimum expected PnL threshold
        ('cash_p', 0.1),    # % of available cash to use
        ('min_hold', 3),    # Minimum holding period in bars
        ('max_hold', 48),   # Max holding period in bars
        ('trade', {}),
        ('logger', None)
    )

    def log(self, data, txt, dt=None):
        ''' Logging function for this strategy'''
        ticker = ''
        tf = 0
        if data:
            ticker = data.ticker
            tf = data.timeframe_min
        if self.params.logger:
            self.params.logger.debug('%-10s,%-3d: %s' % (ticker, tf, txt))
        else:
            print('%-10s,%-3d: %s' % (ticker, tf, txt))

    def __init__(self):
        if len(self.datas) < 2:
            raise ValueError("This strategy requires at least 2 data feeds")

        self.active_trade = None
        self.entry_price = None
        self.entry_exec_price = {}
        self.holding_period = 0

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(order.data,
                    'BUY EXECUTED (%d), Price: %.6f, Size: %.6f, Cost: %.2f, Comm %.2f (orig_px %.2f)' %
                    (order.ref,
                    order.executed.price,
                    order.executed.size,
                    order.executed.value,
                    order.executed.comm,
                    order.created.price))
            else:
                self.log(order.data,
                     'SELL EXECUTED (%d), Price: %.6f, Size: %.6f, Cost: %.2f, Comm %.2f (orig_px %.2f)' %
                    (order.ref,
                    order.executed.price,
                    order.executed.size,
                    order.executed.value,
                    order.executed.comm,
                    order.created.price))

            # Save actual execution price
            self.entry_exec_price[order.data._name] = order.executed.price

        elif order.status == order.Canceled:
            self.log(order.data, 'Order (%d) Canceled' % order.ref)
        elif order.status == order.Margin:
            self.log(order.data, 'Order (%d) Margin' % order.ref)
        elif order.status == order.Rejected:
            self.log(order.data, 'Order (%d) Rejected' % order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(trade.data, 'OPERATION PROFIT, GROSS %.2f, NET %.2f, cash %.2f' %
                 (trade.pnl, trade.pnlcomm, self.broker.getcash()))

    def next(self):
        if self.active_trade is not None:
            self.track_trade()
            return

        best_pair = None
        best_z = 0
        best_ratio = None
        best_data0 = None
        best_data1 = None
        best_spread = None

        for i in range(len(self.datas)):
            for j in range(i+1, len(self.datas)):
                data0 = self.datas[i]
                data1 = self.datas[j]

                if len(data0) < self.p.ci_n or len(data1) < self.p.ci_n:
                    continue

                series0 = pd.Series(data0.get(size=self.p.ci_n))
                series1 = pd.Series(data1.get(size=self.p.ci_n))

                score, pvalue, _ = coint(series0, series1)
                if pvalue > self.p.ci_t:
                    continue

                beta = np.polyfit(series1, series0, 1)[0]
                spread = series0 - beta * series1
                zscore = (spread.iloc[-1] - spread.mean()) / spread.std()

                self.log(data0, f"{data0.datetime.datetime(0).isoformat()}: p={pvalue}, beta={beta}, zscore={zscore}")

                if abs(zscore) >= self.p.z_entry and abs(zscore) > abs(best_z):
                    price0 = data0.close[0]
                    price1 = data1.close[0]
                    spread_deviation = abs(spread.iloc[-1] - spread.mean())
                    cash = self.broker.get_cash() * self.p.cash_p * self.p.trade['leverage']
                    total_price = price0 + beta * price1 if beta >= 0 else price0 - beta * price1
                    size0 = cash / total_price
                    expected_pnl = spread_deviation * size0 * self.p.pnl_p
                    self.log(data0, f"cash={cash}, total_price={total_price}, size0={size0}")
                    self.log(data0, f"zscore={zscore}, spread_deviation={spread_deviation}, expected_pnl={expected_pnl}")

                    if expected_pnl > self.p.pnl_t:
                        best_pair = (i, j)
                        best_z = zscore
                        best_ratio = beta
                        best_data0 = data0
                        best_data1 = data1
                        best_spread = spread

        if best_pair:
            self.log(data0, f"best_pair found")
            cash = self.broker.get_cash() * self.p.cash_p * self.p.trade['leverage'] / 2
            size0 = cash / best_data0.close[0]
            size1 = cash / best_data1.close[0]

            if best_z > 0:
                self.sell(data=best_data0, size=size0)
                self.buy(data=best_data1, size=size1)
            else:
                self.buy(data=best_data0, size=size0)
                self.sell(data=best_data1, size=size1)

            self.active_trade = (best_data0, best_data1)
            self.entry_price = (best_data0.close[0], best_data1.close[0])
            self.holding_period = 0
            self.target_spread = best_spread.mean() + best_z * best_spread.std() * (1 - self.p.pnl_p)
            spread_deviation = abs(best_spread.iloc[-1] - best_spread.mean())
            self.target_pnl = spread_deviation * size0 * self.p.pnl_p
            self.log(data0, f"target_pnl={self.target_pnl}")

    def track_trade(self):
        data0, data1 = self.active_trade
        beta = np.polyfit(
            pd.Series(data1.get(size=self.p.ci_n)),
            pd.Series(data0.get(size=self.p.ci_n)),
            1
        )[0]

        spread = data0.close[0] - beta * data1.close[0]
        self.holding_period += 1

        if self.entry_price and self.entry_price[0] > 0 and self.entry_price[1] > 0:
            price0_now = data0.close[0]
            price1_now = data1.close[0]
            pos0 = self.getposition(data0)
            pos1 = self.getposition(data1)

            entry0_exec = self.entry_exec_price.get(data0._name, self.entry_price[0])
            entry1_exec = self.entry_exec_price.get(data1._name, self.entry_price[1])

            pnl0 = pos0.size * (price0_now - entry0_exec)
            pnl1 = pos1.size * (price1_now - entry1_exec)
            pnl = pnl0 + pnl1

            self.log(data0, f"{data0.datetime.datetime(0).isoformat()}: pnl={pnl}, holding_period={self.holding_period}, pnl0={pnl0}, pnl1={pnl1}")
            if self.holding_period >= self.p.min_hold and (abs(pnl) >= self.target_pnl or self.holding_period >= self.p.max_hold):
                self.log(data0, f"{data0.datetime.datetime(0).isoformat()}: Close positions")
                for d in [data0, data1]:
                    self.close(d)
                self.active_trade = None
                self.entry_price = None
                self.entry_exec_price = {}
                self.holding_period = 0
                self.target_pnl = None
