# strategy.py

from datetime import datetime
import json
import backtrader as bt
from indicators.connorsrsi import ConnorsRSI
from indicators.hv import HistoricalVolatility

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
                    pivot = self.latest_pivot(percD, True, self.params.pivot_lookback)
                    self.log(d, f"pivot_up {pivot}")
                    if pivot < 10 and (d.high[0] + d.low[0]) / 2 > (d.high[-pivot] + d.low[-pivot]) / 2 and percD[0] - percD[-pivot] > self.params.min_d_diff:
                        signal = 1
                elif slow_falling and not fast_up and fast_was_rising:
                    pivot = self.latest_pivot(percD, False, self.params.pivot_lookback)
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


class RSIPowerZones(bt.Strategy):
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

        if self.params.trade['send_signals']:
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
            symbol = data.ticker.replace('frx','')
            message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({self.params.trade['expiration_min']} мин)    {symbol}    {side_icon}    {side}    {double_str}"
            self.broker.post_message(message)


class KissIchimoku(bt.Strategy):
    params = (
        ('trade', {}),
        ('max_risk_percent', 5),
        ('enter_at_reverse', False),
        ('logger', None),
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
        self.log(None, f"params: {self.params._getkwargs()}")
        self.order_refs = {}  # Store orders for each data feed
        self.fast_eval_trend = False
        self.order_sent = False
        self.prev_trend0 = []
        self.tickers = []
        self.qty = []
        timeframes = []
        for d in self.datas:
            self.prev_trend0.append(100)
            try:
                idx = self.tickers.index(d.ticker)
            except ValueError:
                self.tickers.append(d.ticker)
                self.qty.append(None)
            try:
                idx = timeframes.index(d.timeframe_min)
            except ValueError:
                timeframes.append(d.timeframe_min)

         # Create 2D array with None as placeholders
        self.datasets = [[None for _ in timeframes] for _ in self.tickers]
        self.ichimoku = [[None for _ in timeframes] for _ in self.tickers]
        self.fast_ema = [[None for _ in timeframes] for _ in self.tickers]
        self.slow_ema = [[None for _ in timeframes] for _ in self.tickers]

        # Index datasets into the matrix
        for d in self.datas:
            i = self.tickers.index(d.ticker)
            j = timeframes.index(d.timeframe_min)
            self.datasets[i][j] = d
            self.ichimoku[i][j] = bt.indicators.Ichimoku(d)
            self.fast_ema[i][j] = bt.indicators.ExponentialMovingAverage(d, period=65)
            self.slow_ema[i][j] = bt.indicators.ExponentialMovingAverage(d, period=200)

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
        self.log(trade.data, 'OPERATION PROFIT, GROSS %.2f, NET %.2f, portfolio %.2f' %
                 (trade.pnl, trade.pnlcomm, self.broker.getvalue()))

    def next(self):
        # only have 1 position across all symbols

        #if not self.order_sent:
        #    o = self.buy(data=self.datasets[0][0],
        #        size=0.1, exectype=bt.Order.Market)
        #    self.order_sent = True
        #else:
        #    self.close(self.datasets[0][0])

        position_exists = False
        for i, _ in enumerate(self.tickers):
            if self.getposition(self.datasets[i][0]):
                position_exists = True
                break

        for i, _ in enumerate(self.tickers):
            new_stop_price = self.ichimoku[i][0].l.kijun_sen[0]
            d = self.datasets[i][0]

            pos = self.getposition(d)
            if not position_exists:
                if d.volume == 0:
                    return
                if self.qty[i] is None:
                    self.log(d, "Calculate qty on %s: o %.5f, h %.5f, l %.5f, c %.5f, stop %.5f" %
                        (d.datetime.datetime(0).isoformat(), d.open[0], d.high[0], d.low[0], d.close[0], new_stop_price)
                    )
                    self.qty[i] = self.params.trade['margin_qty'] * self.params.trade["leverage"] / d.close[0]
                    self.log(d, f"Fixed order qty is {self.qty[i]}")

                #self.log(d, "eval_trend %s: o %.5f, h %.5f, l %.5f, c %.5f" %
                #    (d.datetime.datetime(0).isoformat(), d.open[0], d.high[0], d.low[0], d.close[0])
                #)

                trend0 = None
                trend1 = None
                trend2 = None

                if self.fast_eval_trend:
                    # check 100% bullish/bearish, starting from the largest timeframe (2-1)
                    trend2 = self.eval_trend(i, 2)
                    if trend2 != 4 and trend2 != -4:
                        self.log(d, f"trend2={trend2}, next ticker")
                        continue
                    #self.log(d, f"trend2 is {trend2}")
                    trend1 = self.eval_trend(i, 1)
                    if trend1 != trend2:
                        self.log(d, f"trend1={trend1}, next ticker")
                        continue
                    #self.log(d, f"trend1 is {trend1}")
                    trend0 = self.eval_trend(i, 0)
                    if trend0 != trend2:
                        self.log(d, f"trend0={trend0}, next ticker")
                        self.prev_trend0[i] = trend0
                        continue
                    self.log(d, f"{d.datetime.datetime(0).isoformat()} trends are {trend0}, {trend1}, {trend2}")
                else:
                    trend2 = self.eval_trend(i, 2)
                    trend1 = self.eval_trend(i, 1)
                    trend0 = self.eval_trend(i, 0)
                    self.log(d, f"{d.datetime.datetime(0).isoformat()} trends are {trend0}, {trend1}, {trend2}")
                    if not ((trend2 == 4 or trend2 == -4) and trend0 == trend2 and trend1 == trend2):
                        self.prev_trend0[i] = trend0
                        continue

                signal = 0
                if self.params.enter_at_reverse:
                    if trend0 == 4 and d.close[0] < d.open[0]:
                        signal = 1
                    elif trend0 == -4 and d.close[0] > d.open[0]:
                        signal = -1
                    else:
                        self.log(d, "No reverse bar")
                        self.prev_trend0[i] = 100
                else:
                    signal = 1 if trend0 == 4 else -1

                if signal != 0:
                    bracket = []
                    #self.log(d, f"Prev {self.prev_trend0[i]}, current {trend0}")
                    #if self.prev_trend0[i] == trend0:
                    #    return
                    # only enter position if trend is changed recently
                    self.prev_trend0[i] = trend0

                    if self.params.trade['send_signals']:
                        msg = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}    {d.ticker}:    {'BUY' if signal == 1 else 'SELL'}"
                        self.broker.post_message(msg)

                    if self.params.trade['send_orders']:
                        pos_size = self.qty[i] #self.calculate_position_size(d, abs(d.close[0] - new_stop_price))
                        if signal == 1:
                            # go long
                            bracket = self.buy_bracket(data=d,
                                size=pos_size, exectype=bt.Order.Market, stopprice=new_stop_price, limitexec=None)
                        elif signal == -1:
                            # go short
                            bracket = self.sell_bracket(data=d,
                                size=pos_size, exectype=bt.Order.Market, stopprice=new_stop_price, limitexec=None)
                        
                        self.log(d, '%s CREATE (%d), %.3f at %.3f, stop (%d) at %.3f' % 
                            ("BUY" if bracket[0].isbuy() else "SELL", bracket[0].ref, bracket[0].size, bracket[0].created.price, bracket[1].ref, bracket[1].created.price))
                        self.order_refs[d] = {
                            'main': bracket[0],
                            'stop': bracket[1],
                            'limit': bracket[2]
                        }

            elif pos:
                old_stop = self.order_refs[d]['stop']
                if old_stop is None or not old_stop.alive():
                    return  # Already executed or cancelled

                need_move_stop = False
                if not old_stop.isbuy():
                    need_move_stop = new_stop_price > old_stop.created.price
                else:
                    need_move_stop = new_stop_price < old_stop.created.price
                if need_move_stop:
                    # Cancel old stop
                    self.cancel(old_stop)

                    # Submit new stop order at a new price
                    new_stop = None
                    if old_stop.isbuy():
                        new_stop = self.buy(data=d, size=old_stop.size, exectype=bt.Order.Stop, price=new_stop_price)
                    else:
                        new_stop = self.sell(data=d, size=old_stop.size, exectype=bt.Order.Stop, price=new_stop_price)
                    self.log(d, '%s STOP MOVED (%d), %.3f at %.3f' % 
                        ("BUY" if new_stop.isbuy() else "SELL", new_stop.ref, new_stop.size, new_stop.created.price))
                    self.order_refs[d]['stop'] = new_stop

    def eval_trend(self, i, j):
        d = self.datasets[i][j]
        ichi = self.ichimoku[i][j]
        fast_ema = self.fast_ema[i][j]
        slow_ema = self.slow_ema[i][j]
        close = d.close[0]

        result = 0
        if close > ichi.l.kijun_sen:
            result += 1
        else:
            result -= 1

        if close > ichi.l.senkou_span_a[0] and ichi.l.senkou_span_a[0] > ichi.l.senkou_span_b[0]:
            result += 1
        elif close < ichi.l.senkou_span_a[0] and ichi.l.senkou_span_a[0] < ichi.l.senkou_span_b[0]:
            result -= 1

        if d.close[-ichi.p.chikou] < close:
            result += 1
        else:
            result -= 1

        if fast_ema[0] > fast_ema[-1] and slow_ema[0] > slow_ema[-1] and close > fast_ema[0] and close > slow_ema[0]:
            result += 1
        elif fast_ema[0] < fast_ema[-1] and slow_ema[0] < slow_ema[-1] and close < fast_ema[0] and close < slow_ema[0]:
            result -= 1

        return result

    def calculate_position_size(self, d, stop_diff):
        return self.params.trade['qty']
        risk_value = self.broker.getcash() * self.params.max_risk_percent / 100
        margin_position_size = int(risk_value * self.params.trade["leverage"] / d.close[0])
        risk_position_size = 1;
        if stop_diff > 0:
            risk_position_size = int(risk_value / stop_diff)
        self.log(d, f'calculate_position_size: risk_value {risk_value}, diff {stop_diff}, risk {risk_position_size}, margin {margin_position_size}, cash {self.broker.getcash()}')
        result = min(risk_position_size, margin_position_size)
        return result


class CRSIShort(bt.Strategy):
    # Short Selling Stocks with ConnorsRSI

    Exit_CRSI_20, Exit_CRSI_30, Exit_CRSI_40, Exit_SMA5, Exit_First_Down_Close = range(5)

    params = (
        ('trade', {}),
        ('price_above', 5),  # The stock’s price closes above $X per share.
        ('avg_volume_above', 500000),  # The average volume over the past 21 trading days (approximately one month) is greater than N shares.
        ('crsi_above', 85),  # The stock closes with a ConnorsRSI(3,2,100) value greater than X, where X is 75, 80, 85, 90 or 95.
        ('hv_above', 40),  # The stock’s 100‐day Historical Volatility, or HV(100), is greater than 40.
        ('adx_above', 40),  # The stock’s 10‐day Average Directional Index, or ADX(10), value is greater than 40.
        ('highest_n', 10),  # Today’s High is the highest high in the past N days, where N is 7, 10 or 13.

        # If the previous day was a Setup, then we Enter a trade by:
        ('percent_entry', 6),  # Submitting a limit order to short the stock at a price Y % above yesterday’s close, where Y is 2, 4, 6, 8, or 10.
        ('variable_entry', True),   # Var. Entry Limits is Yes (Y) when the test used an entry limit of 1.5 times normal for stocks that were
                                    # above the MA(200). When the same limit was used regardless of whether the price was above or below
                                    # the MA(200), this column contains a No (N). We see many more Y’s than N’s, indicating that using
                                    # variable entry limits was beneficial.

        # After we’ve entered the trade, we Exit using one of the following methods, selected in advance:
        # a. The stock closes with a ConnorsRSI value less than 20.
        # b. The stock closes with a ConnorsRSI value less than 30.
        # c. The stock closes with a ConnorsRSI value less than 40.
        # d. The closing price of the stock is less than the 5‐day moving average, or MA(5).
        # e. The closing price of the stock is lower than the previous day’s close. We typically refer to this exit as the First Down Close.
        ('exit_rule', Exit_SMA5),
        ('logger', None),
        ('leverage', None),
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
        self.log(None, f"params: {self.params._getkwargs()}")
        self.o = dict()
        self.lot_size = {}
        self.avg_volume = dict()
        self.crsi = dict()
        self.hv = dict()
        self.adx = dict()
        self.highest = dict()
        self.sma5 = dict()
        self.sma200 = dict()
        for d in self.datas:
            self.lot_size[d] = None
            self.avg_volume[d] = bt.indicators.Average(d.volume, period=21)
            self.crsi[d] = ConnorsRSI(d)
            self.hv[d] = HistoricalVolatility(d, period=100)
            self.adx[d] = bt.indicators.AverageDirectionalMovementIndex(d, period=10)
            self.highest[d] = bt.indicators.FindLastIndexHighest(d.close, period=self.params.highest_n)
            if self.params.exit_rule == self.Exit_SMA5:
                self.sma5[d] = bt.indicators.MovingAverageSimple(d, period=5)
            if self.params.variable_entry:
                self.sma200[d] = bt.indicators.MovingAverageSimple(d, period=200)

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

    def next(self):
        for i, d in enumerate(self.datas):
            if self.lot_size[d] is None:
                self.lot_size[d] = self.params.trade['position_value'] / d.close[0]
                self.log(d, f"Lot size = {self.lot_size[d]}, close={d.close[0]}")

            pos = self.getposition(d)
            # Check if we are in the market
            if pos.size == 0:
                if self.o.get(d, None) is not None:
                    self.log(d, f"CANCEL ENTRY ORDER, close {d.close[0]}\n")
                    self.cancel(self.o[d])
                else:
                    # check entry
                    if d.close[0] < self.params.price_above:
                        continue
                    if self.avg_volume[d][0] < self.params.avg_volume_above:
                        continue
                    if self.hv[d][0] < self.params.hv_above:
                        continue
                    if self.crsi[d][0] < self.params.crsi_above:
                        continue
                    # Simply log the closing price of the series from the reference
                    self.log(d, f"C: {d.close[0]}, hi {d.high[0]}, lo {d.low[0]}; crsi {self.crsi[d][0]}, hv {self.hv[d][0]}, adx {self.adx[d][0]}, highest {self.highest[d][0]}")
                    if self.adx[d][0] < self.params.adx_above:
                        continue
                    if self.highest[d][0] != 0:
                        continue
                    entry_offset = self.params.percent_entry
                    if self.params.variable_entry and d.close[0] > self.sma200[d][0]:
                        entry_offset *= 1.5
                    order = self.sell(data=d, exectype=bt.Order.Limit, size=self.lot_size[d], price=d.close[0] * (100 + entry_offset) / 100)
                    self.log(d, 'SELL CREATE (%d), %.3f at %.3f\n' % (order.ref, order.size, order.created.price))
                    self.o[d] = order
            else:
                # check exit
                exit = False
                if self.params.exit_rule == self.Exit_CRSI_20:
                    exit = self.crsi[d][0] < 20
                elif self.params.exit_rule == self.Exit_CRSI_30:
                    exit = self.crsi[d][0] < 30
                elif self.params.exit_rule == self.Exit_CRSI_40:
                    exit = self.crsi[d][0] < 40
                elif self.params.exit_rule == self.Exit_SMA5:
                    exit = d.close[0] < self.sma5[d][0]
                elif self.params.exit_rule == self.Exit_First_Down_Close:
                    exit = d.close[0] < d.close[-1]
                else:
                    raise NotImplementedError(f"exit_rule={self.params.exit_rule}")
                
                if exit:
                    self.log(d, 'EXIT POSITION, size %.2f, %.6f' % (pos.size, d.close[0]))
                    self.close(data=d)


class TPS(bt.Strategy):
    params = (
        ('trade', {}),
        ('long_entry', 25),
        ('long_exit', 70),
        ('short_entry', 75),
        ('short_exit', 30),
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
        self.sma = dict()
        self.rsi = dict()
        self.atr = dict()
        self.pos_stage = dict()
        self.last_entry_price = dict()
        self.lot_size = dict()
        for d in self.datas:
            self.sma[d] = bt.indicators.SMA(d, period=200)
            self.rsi[d] = bt.indicators.RSI_Safe(d, period=2)
            self.atr[d] = bt.indicators.AverageTrueRange(d, period=10)
            self.pos_stage[d] = 0
            self.last_entry_price[d] = None
            self.lot_size[d] = None

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

    def submit_buy(self, d, lot_count, text):
        order = self.buy(data=d, size=self.lot_size[d] * lot_count, exectype=bt.Order.Market)
        self.log(d, 'BUY %s %s (%d), %.3f at %.3f, lot_count %d\n' % 
            (d.ticker, text, order.ref, order.size, order.created.price, lot_count))
        self.last_entry_price[d] = order.created.price

    def submit_sell(self, d, lot_count, text):
        order = self.sell(data=d, size=self.lot_size[d] * lot_count, exectype=bt.Order.Market)
        self.log(d, 'SELL %s %s (%d), %.3f at %.3f, lot_count %d\n' % 
            (d.ticker, text, order.ref, order.size, order.created.price, lot_count))
        self.last_entry_price[d] = order.created.price

    def next(self):
        for i, d in enumerate(self.datas):
            if d.volume == 0:
                continue

            if self.lot_size[d] is None:
                self.lot_size[d] = self.params.trade['position_value'] / d.close[0]
                self.log(d, f"Lot size = {self.lot_size[d]}")
            
            self.log(d, "%s: c %.5f, sma %.5f, rsi %.5f" % (d.datetime.datetime(0).isoformat(), d.close[0], self.sma[d].sma[0], self.rsi[d].rsi[0]))

            level = self.atr[d].atr[-1] / 2
            p = self.getposition(d)
            if p is None or p.size == 0:
                # no position
                self.pos_stage[d] = 1
                if d.close[0] > self.sma[d].sma[0] and self.rsi[d].rsi[-1] < self.params.long_entry and self.rsi[d].rsi[0] < self.params.long_entry:
                        # 2 periods below, go long
                        if self.params.trade['send_orders']:
                            self.submit_buy(d, self.pos_stage[d], 'CREATE')
                            self.pos_stage[d] += 1
                        else:
                            self.log(d, "SIGNAL BUY")
                        if self.params.trade['send_signals']:
                            self.log(d, f"Close={d.close[0]}, level={level}")
                            message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (TF {self.params.trade['expiration_min']} min)\n{d.ticker},   BUY  ⬆️  , rsi={self.rsi[d].rsi[0]:.2f}, sma200={self.sma[d].sma[0]:.4f}"
                            for i in range(1, 4):
                                message += f"\nx{i + 1} at {(d.close[0] - level * i):.3f}"
                            message += f"\nStop at {(d.close[0] - level * 4):.3f}"
                            self.log(d, message)
                            self.broker.post_message(message)

                elif d.close[0] < self.sma[d].sma[0] and self.rsi[d].rsi[-1] > self.params.short_entry and self.rsi[d].rsi[0] > self.params.short_entry:
                        # 2 periods above, go short
                        if self.params.trade['send_orders']:
                            self.submit_sell(d, self.pos_stage[d], 'CREATE')
                            self.pos_stage[d] += 1
                        else:
                            self.log(d, "SIGNAL SELL")
                        if self.params.trade['send_signals']:
                            self.log(d, f"Close={d.close[0]}, level={level}")
                            message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (TF {self.params.trade['expiration_min']} min)\n{d.ticker},   SELL ⬇️  , rsi={self.rsi[d].rsi[0]:.2f}, sma200={self.sma[d].sma[0]:.4f}"
                            for i in range(1, 4):
                                message += f"\nx{i + 1} at {(d.close[0] + level * i):.3f}"
                            message += f"\nStop at {(d.close[0] + level * 4):.3f}"
                            self.log(d, message)
                            self.broker.post_message(message)
                elif self.params.trade['send_signals']:
                    sign = '⚠️' if self.rsi[d].rsi[0] > self.params.long_exit or self.rsi[d].rsi[0] < self.params.short_exit else ' '
                    message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (TF {self.params.trade['expiration_min']} min)\n{d.ticker}, check position, rsi={self.rsi[d].rsi[0]:.2f} {sign}"
                    self.broker.post_message(message)

            else:
                if p.size > 0:
                    # in long position
                    if self.rsi[d].rsi[0] > self.params.long_exit:
                        self.log(d, "CLOSE LONG POSITION")
                        if self.params.trade['send_orders']:
                            self.close(d)
                    elif d.close[0] > self.sma[d].sma[0] and self.pos_stage[d] < 5 and d.close[0] < self.last_entry_price[d]:
                        if self.params.trade['send_orders']:
                            self.submit_buy(d, self.pos_stage[d], 'ADD')
                            self.pos_stage[d] += 1
                elif p.size < 0:
                    # in short position
                    if self.rsi[d].rsi[0] < self.params.short_exit:
                        self.log(d, "CLOSE SHORT POSITION")
                        if self.params.trade['send_orders']:
                            self.close(d)
                    elif d.close[0] < self.sma[d].sma[0] and self.pos_stage[d] < 5 and d.close[0] > self.last_entry_price[d]:
                        if self.params.trade['send_orders']:
                            self.submit_sell(d, self.pos_stage[d], 'ADD')
                            self.pos_stage[d] += 1


class CRSISP500(bt.Strategy):
    params = (
        ('trade', {}),
        ('crsi_setup', 10),  # The stock closes with ConnorsRSI(3, 2, 100) value less than W, where W is 5 or 10
        ('percents_setup', 50),  # The stock closing price is in the bottom X % of the day's range, where X = 25, 50, 75 or 100
        ('percents_entry', 4),  # If the previous day was a Setup, submit a limit order to buy at a price Y % below yesterday's close, where Y is 2, 4, 6, 8 or 10
        ('crsi_exit', 50),  # Exit when the stock closes with ConnorsRSI(3, 2, 100) value greater than Z, where W is 50 or 70
        ('logger', None),
        ('leverage', None),
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

        # To keep track of pending orders
        self.order = {}
        self.crsi = {}
        self.lot_size = {}
        for d in self.datas:
            self.order[d] = None
            self.crsi[d] = ConnorsRSI(d)
            self.lot_size[d] = None

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
        self.log(trade.data, '%s: OPERATION PROFIT, GROSS %.2f, NET %.2f, cash %.2f' %
                 (trade.data.datetime.datetime(0).isoformat(), trade.pnl, trade.pnlcomm, self.broker.getcash()))

    def next(self):
    # Step 1: Calculate used slots globally
        used_slots = sum(
            1 for d in self.datas
            if self.getposition(d).size != 0 or self.order.get(d)
        )
        free_slots = 15 - used_slots

        # Optional logging
        #self.log(None, f"Global: used_slots={used_slots}, free_slots={free_slots}")

        for d in self.datas:
            if d.volume == 0:
                continue

            if self.lot_size[d] is None:
                self.lot_size[d] = self.params.trade['position_value'] / d.close[0]
                self.log(d, f"Lot size = {self.lot_size[d]}")
            
            #self.log(d, "%s: c %.5f, crsi %.5f" % (d.datetime.datetime(0).isoformat(), d.close[0], self.crsi[d][0]))

            p = self.getposition(d)
            # Check if we are in the market
            if p.size == 0:
                if self.order[d]: 
                    self.cancel(self.order[d])
                    self.order[d] = None
                if free_slots > 0:
                    # Not yet ... we MIGHT BUY if ...
                    day_range = d.high[-1] - d.low[-1]
                    bottom_percent = d.low[-1] + day_range * self.params.percents_setup / 100
                    if self.crsi[d][-1] < self.params.crsi_setup and d.close[-1] < bottom_percent:
                        px = d.close[-1] * (100 - self.params.percents_entry) / 100
                        # Keep track of the created order to avoid a 2nd order
                        self.order[d] = self.buy(data=d, price=px, size=self.lot_size[d], exectype=bt.Order.Limit)
                        self.log(d, '%s: BUY CREATE, %.2f at %.2f' % (d.datetime.datetime(0).isoformat(), self.order[d].size, self.order[d].created.price))
                        free_slots -= 1
            else:
                if self.crsi[d][0] > self.params.crsi_exit:
                    self.log(d, '%s: EXIT POSITION, %.2f' % (d.datetime.datetime(0).isoformat(), d.close[0]))
                    self.close(d)
                    self.order[d] = None
        if free_slots >= 0:
            self.log(d, "%s: free slots %d" % (d.datetime.datetime(0).isoformat(), free_slots))
        else:
            raise ValueError("free_slots < 0")
