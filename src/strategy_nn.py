# strategy_nn.py

import csv
from datetime import datetime
import math
import os

from numpy import nan
import backtrader as bt

class AntyCollector(bt.Strategy):
    params = (
        ('trending_bars', 3),
        ('overbought', 20),
        ('oversold', 80),
        ('require_fast_trend', False),
        ('logger', None),
    )

    def log(self, data, txt, dt=None):
        ''' Logging function for this strategy'''
        ticker = ''
        if data:
            ticker = data.ticker
        if self.params.logger:
            self.params.logger.debug('%-10s: %s' % (ticker, txt))
        else:
            print('%-10s: %s' % (ticker, txt))

    def __init__(self):
        self.log(None, f"params: {self.params._getkwargs()}")
        self.o = dict()
        self.stoch = dict()
        for d in self.datas:
            self.stoch[d] = bt.indicators.Stochastic(d, period=7, period_dfast=4, period_dslow=10, safediv=True)

        # indicator A: percK
        # indicator B: percD

        self.input_length = 5
        self.output_file = 'anty_training_data.csv'

        self.log_counter = 0
        # Write CSV header only once
        if not os.path.exists(self.output_file):
            with open(self.output_file, mode='w', newline='') as f:
                writer = csv.writer(f)
                input_headers = ["Ticker"] + [f"A{i}" for i in range(self.input_length)] + [f"B{i}" for i in range(self.input_length)]
                output_headers = ['Up1', 'Up2', 'Up3']
                writer.writerow(input_headers + output_headers)

    def next(self):
        self.log_counter += 1
        if self.log_counter % 10000 == 0:
            print(self.datas[0].datetime.datetime(0).isoformat())

        for i, d in enumerate(self.datas):
            if d.volume == 0:
                continue
            # Skip if not enough data
            if len(d) < self.input_length + 3:
                continue
            
            perc_d = self.stoch[d].percD[-(self.input_length - 1 + 3)]
            if perc_d == 0 or perc_d == nan:
                continue

            eidx = -3  # entry index

            fast_up = (self.stoch[d].percK[eidx] - self.stoch[d].percK[eidx - 1] > 0)
            fast_dir_changed = fast_up != (self.stoch[d].percK[eidx - 1] - self.stoch[d].percK[eidx - 2] > 0)
            not_over = (
                self.stoch[d].percD[eidx] < self.params.oversold and
                self.stoch[d].percD[eidx] > self.params.overbought and
                self.stoch[d].percK[eidx] < self.params.oversold and
                self.stoch[d].percK[eidx] > self.params.overbought
            )

            slow_rising = False
            slow_falling = False
            fast_was_rising = False
            fast_was_falling = False
            signal = 0
            if fast_dir_changed and not_over:
                percD = self.stoch[d].percD
                slow_rising = Anty.is_rising(percD, self.params.trending_bars, -eidx)
                slow_falling = Anty.is_falling(percD, self.params.trending_bars, -eidx)
                if self.params.require_fast_trend:
                    fast_was_rising = Anty.is_rising(self.stoch[d].percK, self.params.trending_bars, 1 - eidx)
                    fast_was_falling = Anty.is_falling(self.stoch[d].percK, self.params.trending_bars, 1 - eidx)
                else:
                    fast_was_rising = True
                    fast_was_falling = True
                if slow_rising and fast_up and fast_was_falling:
                    signal = 1
                elif slow_falling and not fast_up and fast_was_rising:
                    signal = -1

            self.log(d, "%s: o %.5f, h %.5f, l %.5f, c %.5f; %%K %.2f, %%D %.2f; %d/%d/%d, %d/%d, %d/%d; signal %d" %
                (d.datetime.datetime(0).isoformat(), d.open[0 + eidx], d.high[0 + eidx], d.low[0 + eidx], d.close[0 + eidx], self.stoch[d].percK[0 + eidx], self.stoch[d].percD[0 + eidx],
                fast_up, fast_dir_changed, not_over, slow_rising, slow_falling, fast_was_rising, fast_was_falling, signal)
            )

            if signal != 0:
                 # Collect last self.input_length normalized indicator A, B, C values (scale to [0, 1] here if needed)
                a_values = [self.stoch[d].percK[eidx - i] for i in range(0, self.input_length)]
                b_values = [self.stoch[d].percD[eidx - i] for i in range(0, self.input_length)]

                # Normalize values between 0 and 1 for NN input
                def normalize(values):
                    min_v, max_v = 0, 100
                    return [(v - min_v) / (max_v - min_v) if max_v > min_v else 0.0 for v in values]

                a_norm = normalize(a_values)
                b_norm = normalize(b_values)

                # Check if a_norm or b_norm contain NaN values
                if any(math.isnan(x) for x in a_norm) or any(math.isnan(x) for x in b_norm):
                    #print("Error: One of the arrays contains NaN values.")
                    continue

                def assign_outcome(idx):
                    return 1 if d.close[idx] > d.close[eidx] else 0

                # Get future price movements
                up1 = assign_outcome(-2)
                up2 = assign_outcome(-1)
                up3 = assign_outcome(-0)

                # Write row to CSV
                with open(self.output_file, mode='a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([d.ticker] + a_norm + b_norm + [up1, up2, up3])

class Anty(bt.Strategy):
    params = (
        ('trade', {}),
        ('trending_bars', 3),
        ('overbought', 25),
        ('oversold', 75),
        ('require_fast_trend', True),
        ('pivot_lookback', 20),
        ('min_d_diff', 20),
        ('min_hour', 0),
        ('max_hour', 24),
        ('logger', None),
    )

    def log(self, data, txt, dt=None):
        ''' Logging function for this strategy'''
        ticker = ''
        if data:
            ticker = data.ticker
        if self.params.logger:
            self.params.logger.debug('%-10s: %s' % (ticker, txt))
        else:
            print('%-10s: %s' % (ticker, txt))

    def __init__(self):
        self.log(None, f"params: {self.params._getkwargs()}")
        self.o = dict()
        self.stoch = dict()
        for d in self.datas:
            self.stoch[d] = bt.indicators.Stochastic(d, period=7, period_dfast=4, period_dslow=10, safediv=True)

        if self.params.trade['send_signals']:
            self.broker.post_message(f"{self.__class__.__name__} started")

    def notify_order(self, order):
        #self.log(order.data, f"notify_order: {str(order)}")
        if order.status in [order.Submitted, order.Accepted]:
            # Buy/Sell order submitted/accepted to/by broker - Nothing to do
            return

        # Check if an order has been completed
        # Attention: broker could reject order if not enough cash
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(order.data,
                    'BUY EXECUTED (%d), Price: %.6f, Cost: %.2f, Comm %.2f (orig_px %.2f)' %
                    (order.ref,
                      order.executed.price,
                    order.executed.value,
                    order.executed.comm,
                    order.created.price))

            else:  # Sell
                self.log(order.data,
                     'SELL EXECUTED (%d), Price: %.6f, Cost: %.2f, Comm %.2f (orig_px %.2f)' %
                    (order.ref,
                      order.executed.price,
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
        #self.log(trade.data, f"notify_trade: {str(trade)}, cash {self.broker.getcash()}")
        if not trade.isclosed:
            return
        self.log(trade.data, 'OPERATION PROFIT, GROSS %.2f, NET %.2f, cash %.2f' %
                 (trade.pnl, trade.pnlcomm, self.broker.getcash()))

    @staticmethod
    def is_rising(data, n, offset=0):
        """Returns True if the last n bars are continuously increasing."""
        return all(data[-i - offset] > data[-i - 1 - offset] for i in range(0, n))

    @staticmethod
    def is_falling(data, n, offset=0):
        """Returns True if the last n bars are continuously decreasing."""
        return all(data[-i - offset] < data[-i - 1 - offset] for i in range(0, n))

    @staticmethod
    def latest_pivot(d, is_buy, lookback):
        result = 500
        for i in range(1, lookback):
            if is_buy:
                if (d[-i] < d[-i + 1]) and (d[-i] < d[-i - 1]):
                    result = i
                    break
            else:
                if (d[-i] > d[-i + 1]) and (d[-i] > d[-i - 1]):
                    result = i
                    break
        return result  

    def next(self):
        # only have 1 position across all symbols
        #for i, d in enumerate(self.datas):
        #    if self.getposition(d) is not None:
        #        return

        for i, d in enumerate(self.datas):
            if d.volume == 0:
                continue
            if d.datetime.datetime(0).hour < self.params.min_hour or d.datetime.datetime(0).hour >= self.params.max_hour:
                continue
            fast_up = (self.stoch[d].percK[0] - self.stoch[d].percK[-1] > 0)
            fast_dir_changed = fast_up != (self.stoch[d].percK[-1] - self.stoch[d].percK[-2] > 0)
            not_over = (
                self.stoch[d].percD < self.params.oversold and
                self.stoch[d].percD > self.params.overbought and
                self.stoch[d].percK < self.params.oversold and
                self.stoch[d].percK > self.params.overbought
            )

            slow_rising = False
            slow_falling = False
            fast_was_rising = False
            fast_was_falling = False
            signal = 0
            if fast_dir_changed and not_over:
                percD = self.stoch[d].percD
                slow_rising = Anty.is_rising(percD, self.params.trending_bars)
                slow_falling = Anty.is_falling(percD, self.params.trending_bars)
                if self.params.require_fast_trend:
                    fast_was_rising = Anty.is_rising(self.stoch[d].percK, self.params.trending_bars, 1)
                    fast_was_falling = Anty.is_falling(self.stoch[d].percK, self.params.trending_bars, 1)
                else:
                    fast_was_rising = True
                    fast_was_falling = True
                if slow_rising and fast_up and fast_was_falling:
                    pivot = Anty.latest_pivot(percD, True, self.params.pivot_lookback)
                    self.log(d, f"pivot_up {pivot}")
                    if pivot < 10 and (d.high[0] + d.low[0]) / 2 > (d.high[-pivot] + d.low[-pivot]) / 2 and percD[0] - percD[-pivot] > self.params.min_d_diff:
                        signal = 1
                elif slow_falling and not fast_up and fast_was_rising:
                    pivot = Anty.latest_pivot(percD, False, self.params.pivot_lookback)
                    self.log(d, f"pivot_dn {pivot}")
                    if pivot < 10 and (d.high[0] + d.low[0]) / 2 < (d.high[-pivot] + d.low[-pivot]) / 2 and percD[-pivot] - percD[0] > self.params.min_d_diff:
                        signal = -1

            self.log(d, "%s: o %.5f, h %.5f, l %.5f, c %.5f; %%K %.2f, %%D %.2f; %d/%d/%d, %d/%d, %d/%d; signal %d" %
                (d.datetime.datetime(0).isoformat(), d.open[0], d.high[0], d.low[0], d.close[0], self.stoch[d].percK[0], self.stoch[d].percD[0],
                fast_up, fast_dir_changed, not_over, slow_rising, slow_falling, fast_was_rising, fast_was_falling, signal)
            )

            if signal != 0:
                if signal == 1:
                    # go long
                    order = self.buy(data=d, size=self.params.trade['stake'], exectype=bt.Order.Market)
                    #print('BUY CREATE %s (%d), %.3f at %.3f' % 
                    #    (d.ticker, order.ref, order.size, order.created.price))
                    self.log(d, 'BUY CREATE %s (%d), %.3f at %.3f\n' % 
                        (d.ticker, order.ref, order.size, order.created.price))
                elif signal == -1:
                    # go short
                    order = self.sell(data=d, size=self.params.trade['stake'], exectype=bt.Order.Market)
                    #print('SELL CREATE %s (%d), %.3f at %.3f' % 
                    #    (d.ticker, order.ref, order.size, order.created.price))
                    self.log(d, 'SELL CREATE %s (%d), %.3f at %.3f\n' % 
                        (d.ticker, order.ref, order.size, order.created.price))
                    
                return
