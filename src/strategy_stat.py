import backtrader as bt
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint, adfuller

class CointegratedPairs(bt.Strategy):
    params = (
        ('ci_n', 100),       # Cointegration test window
        ('ci_t', 0.05),     # p-value threshold
        ('z_entry', 2.0),   # Z-score entry threshold
        ('pnl_p', 0.5),     # % of expected reversion to target
        ('pnl_t', 5),       # Minimum target PnL threshold
        ('cash_p', 0.1),    # % of available cash to use
        ('min_hold', 0),    # Minimum holding period in bars
        ('max_hold', 14),    # Max holding period in bars
        ('trade', {}),
        ('logger', None)
    )

    def log(self, data, txt, dt=None):
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
        self.entry_beta = None
        self.target_pnl = None

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
        best_expected_pnl = None

        for i in range(len(self.datas)):
            for j in range(i+1, len(self.datas)):
                data0 = self.datas[i]
                data1 = self.datas[j]

                if len(data0) < self.p.ci_n or len(data1) < self.p.ci_n:
                    continue
                #self.log(None, f"len passed")

                if data0.volume == 0 or data1.volume == 0:
                    continue

                series0 = pd.Series(np.log(data0.get(size=self.p.ci_n)))
                series1 = pd.Series(np.log(data1.get(size=self.p.ci_n)))

                score, pvalue, table = coint(series0, series1)
                #self.log(None, f"{score}, {pvalue}, {table}")

                #spread = series0 - series1  # log ratio
                #print(adfuller(spread))

                #if pvalue > self.p.ci_t:
                #    self.log(None, f"{data0.ticker} - {data1.ticker}: coint pvalue > threshold ({pvalue} vs {self.p.ci_t}), skipping pair; ts: {data0.datetime.datetime(0).isoformat()}, {data1.datetime.datetime(0).isoformat()}")
                #    continue

                beta = np.polyfit(series1, series0, 1)[0]
                spread = series0 - beta * series1
                zscore = (spread.iloc[-1] - spread.mean()) / spread.std()

                self.log(data0, f"{data0.datetime.datetime(0).isoformat()}: p={pvalue}, beta={beta}, zscore={zscore}")

                if abs(zscore) >= self.p.z_entry and abs(zscore) > abs(best_z):
                    price0 = data0.close[0]
                    price1 = data1.close[0]

                    total_cash = self.broker.get_cash() * self.p.cash_p * self.p.trade['leverage']
                    total_price = abs(price0) + abs(beta) * abs(price1)
                    size0 = total_cash / total_price

                    spread_deviation = abs(np.exp(spread.iloc[-1] - spread.mean()) - 1)
                    expected_pnl = spread_deviation * total_cash * self.p.pnl_p

                    self.log(data0, f"cash={total_cash}, total_price={total_price}, size0={size0}")
                    self.log(data0, f"zscore={zscore}, spread_deviation={spread_deviation}, expected_pnl={expected_pnl}")

                    if expected_pnl > self.p.pnl_t and size0 >= 0.01:
                        best_pair = (i, j)
                        best_z = zscore
                        best_ratio = beta
                        best_data0 = data0
                        best_data1 = data1
                        best_spread = spread
                        best_expected_pnl = expected_pnl

        if best_pair:
            self.log(best_data0, f"Best pair found: {best_data0.ticker} - {best_data1.ticker}")

            price0 = best_data0.close[0]
            price1 = best_data1.close[0]
            total_cash = self.broker.get_cash() * self.p.cash_p * self.p.trade['leverage']
            #total_price = abs(price0) + abs(best_ratio) * abs(price1)
            #size0 = total_cash / total_price
            #size1 = abs(best_ratio) * size0

            # Allocate half of total cash to each side
            notional_per_leg = total_cash / 2

            price0 = best_data0.close[0]
            price1 = best_data1.close[0]

            size0 = notional_per_leg / price0
            size1 = notional_per_leg / price1

            if size0 < 0.01 or size1 < 0.01:
                self.log(best_data0, "Trade skipped: position size too small")
                return

            if best_z > 0:
                if self.params.trade["send_orders"]:
                    self.sell(data=best_data0, size=size0)
                    self.buy(data=best_data1, size=size1)
                else:
                    self.log(best_data0, f"SELL {size0}")
                    self.log(best_data1, f"BUY  {size1}")
            else:
                if self.params.trade["send_orders"]:
                    self.buy(data=best_data0, size=size0)
                    self.sell(data=best_data1, size=size1)
                else:
                    self.log(best_data0, f"BUY  {size0}")
                    self.log(best_data1, f"SELL {size1}")

            self.active_trade = (best_data0, best_data1)
            self.entry_price = (best_data0.close[0], best_data1.close[0])
            self.holding_period = 0
            self.entry_beta = best_ratio
            self.target_spread = best_spread.mean() + best_z * best_spread.std() * (1 - self.p.pnl_p)

            self.target_pnl = best_expected_pnl
            self.log(best_data0, f"target_pnl={self.target_pnl}")

    def track_trade(self):
        data0, data1 = self.active_trade
        spread = np.log(data0.close[0]) - self.entry_beta * np.log(data1.close[0])
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

            pl_close = False
            if pnl > 0:
                pl_close = pnl >= self.target_pnl
            else:
                pl_close = -pnl >= self.target_pnl / 2
            if self.holding_period >= self.p.min_hold and (pl_close or self.holding_period >= self.p.max_hold):
                self.log(data0, f"{data0.datetime.datetime(0).isoformat()}: Close positions")
                if self.params.trade["send_orders"]:
                    for d in [data0, data1]:
                        self.close(d)
                self.active_trade = None
                self.entry_price = None
                self.entry_exec_price = {}
                self.holding_period = 0
                self.target_pnl = None
                self.entry_beta = None


class MarketNeutral(bt.Strategy):
    params = (
        ('slope_period', 10),     # Slope calculation period
        ('extreme_percent', 40),  # n % from each end of ranking will be traded
        ('allocation', 2500),     # $ allocation for each traded asset
        ('min_order_value', 10),  # do not correct position if order value is less
        ('trade', {}),
        ('logger', None)
    )

    def log(self, data, txt, dt=None):
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

        elif order.status == order.Canceled:
            self.log(order.data, 'Order (%d) Canceled' % order.ref)
        elif order.status == order.Margin:
            self.log(order.data, 'Order (%d) Margin' % order.ref)
        elif order.status == order.Rejected:
            self.log(order.data, 'Order (%d) Rejected' % order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(trade.data, 'OPERATION PROFIT, GROSS %.2f, NET %.2f, cash %.2f, value %.2f' %
                 (trade.pnl, trade.pnlcomm, self.broker.getcash(), self.broker.getvalue()))

    def submit_order(self, d, shares):
        self.log(d, f"submit_order {shares}")
        if abs(d.close[0] * shares) > self.p.min_order_value:
            if shares > 0:
                order = self.buy(data=d, size=shares, exectype=bt.Order.Market)
                self.log(d, 'BUY CREATE %s (%d), %.6f at %.3f' % 
                    (d.ticker, order.ref, order.size, order.created.price))
            elif shares < 0:
                order = self.sell(data=d, size=shares, exectype=bt.Order.Market)
                self.log(d, 'SELL CREATE %s (%d), %.6f at %.3f' % 
                    (d.ticker, order.ref, order.size, order.created.price))

    def next(self):
        slopes = []

        for i in range(len(self.datas)):
            d = self.datas[i]

            if len(d) < self.p.slope_period:
                continue
            #self.log(None, f"len passed")

            #if data0.volume == 0:
            #    continue
            # Extract last 'period' close prices from data feed
            closes = [d.close[-i] for i in reversed(range(self.p.slope_period))]
            
            # Calculate period returns (close1 / close0) for the extracted closes
            last_prices = np.array(closes[1:]) / np.array(closes[:-1])
         
            # 🔄 Calculate period returns (close1 / close0)
            #returns = data0.close / data0.close.shift(1)
            #returns = returns.dropna()
            #series = returns.iloc[:, 0].dropna()
            #last_prices = series[-self.p.slope_period:]

            # Create x values (e.g., 0 to 9)
            x = np.arange(len(last_prices))

            # Perform linear regression (1st degree polynomial fit)
            coeffs = np.polyfit(x, last_prices, 1)

            slope, intercept = coeffs
            slopes.append((d, slope))

        slopes_sorted = sorted(slopes, key=lambda x: x[1], reverse=True)
        s_str = ''
        for d, s in slopes_sorted:
            s_str += f"{d.ticker}: {s}, "
        self.log(d, f"{self.datas[i].datetime.datetime(0).isoformat()}: slope={s_str}")
        extreme_len = int(len(slopes_sorted) * self.p.extreme_percent / 100)
        i = 0
        for d, slope in slopes_sorted:
            shares = 0
            if i < extreme_len:
                shares = -self.p.allocation / d.close[0]
            elif i >= len(slopes_sorted) - extreme_len:
                shares = self.p.allocation / d.close[0]
            
            shares = shares - self.getposition(d).size
            self.submit_order(d, shares)
            i += 1

