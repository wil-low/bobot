# strategy.py

from datetime import datetime
import json
import backtrader as bt

class AntyStrategy(bt.Strategy):
    params = (
        ('trade', {}),
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

    def next(self):
        # only have 1 position across all symbols
        #for i, d in enumerate(self.datas):
        #    if self.getposition(d) is not None:
        #        return

        for i, d in enumerate(self.datas):
            if d.volume == 0:
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
                slow_rising = AntyStrategy.is_rising(self.stoch[d].percD, self.params.trending_bars)
                slow_falling = AntyStrategy.is_falling(self.stoch[d].percD, self.params.trending_bars)
                if self.params.require_fast_trend:
                    fast_was_rising = AntyStrategy.is_rising(self.stoch[d].percK, self.params.trending_bars, 1)
                    fast_was_falling = AntyStrategy.is_falling(self.stoch[d].percK, self.params.trending_bars, 1)
                else:
                    fast_was_rising = True
                    fast_was_falling = True
                if slow_rising and fast_up and fast_was_falling:
                    signal = 1
                elif slow_falling and not fast_up and fast_was_rising:
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


class RSIPowerZonesStrategy(bt.Strategy):
    params = (
        ('trade', {}),
        ('enable_short', True),
        ('ma_period', 200),
        ('rsi_period', 4),
        ('rsi_long_1st', 30),
        ('rsi_long_2nd', 25),
        ('rsi_short_1st', 70),
        ('rsi_short_2nd', 75),
        ('logger', None),
        ('leverage', None),
        ('min_hour', 0),
        ('max_hour', 24),
    )

    def log(self, data, txt, dt=None):
        ''' Logging function for this strategy'''
        dt = dt or self.data.datetime.date(0)
        if self.params.logger:
            self.params.logger.debug('%-10s: %s' % (data.ticker, txt))
        else:
            print('%-10s: %s' % (data.ticker, txt))

    def __init__(self):
        # To keep track of pending orders and buy price/commission
        self.o = dict()
        self.sma = dict()
        self.rsi = dict()
        param_dict = dict(self.params._getitems())
        json_params = json.dumps(param_dict)
        self.params.logger.debug(f"Strategy params: {json_params}")

        for d in self.datas:
            self.sma[d] = bt.indicators.SimpleMovingAverage(d, period=self.params.ma_period)
            self.rsi[d] = bt.indicators.RSI_Safe(d, period=self.params.rsi_period)

        self.broker.post_message(f"{self.__class__.__name__} started")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # Buy/Sell order submitted/accepted to/by broker - Nothing to do
            return

        # Check if an order has been completed
        # Attention: broker could reject order if not enough cash
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(order.data,
                    'BUY EXECUTED, Price: %.6f, Cost: %.2f, Comm %.2f' %
                    (order.executed.price,
                    order.executed.value,
                    order.executed.comm))

            else:  # Sell
                self.log(order.data, 'SELL EXECUTED, Price: %.6f, Cost: %.2f, Comm %.2f' %
                        (order.executed.price,
                        order.executed.value,
                        order.executed.comm))

            self.bar_executed = len(self)

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(order.data, 'Order Canceled/Margin/Rejected')

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(trade.data, 'OPERATION PROFIT, GROSS %.2f, NET %.2f' %
                 (trade.pnl, trade.pnlcomm))

    def next(self):
        if self.broker.getcash() < self.params.trade['stake']:
            return
        # Simply log the closing price of the series from the reference
        for i, d in enumerate(self.datas):
            if d.volume == 0:
                continue
            if d.datetime.datetime(0).hour < self.params.min_hour or d.datetime.datetime(0).hour >= self.params.max_hour:
                continue
            self.log(d, '%s: Close: %.6f, SMA %.6f, RSI %.2f' % (d.datetime.datetime(0).isoformat(), d.close[0], self.sma[d][0], self.rsi[d][0]))

            pos = self.getposition(d)
            #self.log(f"Position: {pos}")

            # Check if we are in the market
            if not pos:
                if d.close[0] > self.sma[d][0]:  # uptrend
                    if self.rsi[d][0] < self.params.rsi_long_2nd:
                        self.send_order(d, False, True)
                    elif self.rsi[d][0] < self.params.rsi_long_1st:
                        self.send_order(d, False, False)
                elif self.params.enable_short:  # downtrend
                    if self.rsi[d][0] > self.params.rsi_short_2nd:
                        self.send_order(d, True, True)
                    elif self.rsi[d][0] > self.params.rsi_short_1st:
                        self.send_order(d, True, False)

    def send_order(self, data, is_sell, is_double):
        side = 'ВВЕРХ'
        side_icon = '⬆️'
        if is_sell:
            side = 'ВНИЗ'
            side_icon = '⬇️'
        size = self.params.trade['stake']
        double_str = ''
        if is_double:
            size *= 2
            double_str = 'УДВОИТЬ'
        if self.params.trade['send_orders']:
            if is_sell:
                self.order = self.sell(data=data, size=size, exectype=bt.Order.Market)
            else:
                self.order = self.buy(data=data, size=size, exectype=bt.Order.Market)
            self.log(data, '%s CREATE, %.2f at %.6f %s\n' % (side, self.order.size, data.close[0], double_str))
        if self.params.trade['send_signals']:
            message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({self.params.trade['expiration_min']} мин)    {data.ticker}    {side_icon}    {side}    {double_str}"
            self.broker.post_message(message)
