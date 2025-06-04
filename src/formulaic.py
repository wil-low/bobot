import backtrader as bt
import numpy as np
import pandas as pd

class AlphaCombination(bt.Strategy):
    params = (
        ('rebalance_days', 5),
        ('weights_alpha', [1.0, 1.0, 1.0]),  # Equal weighting of the 3 alphas
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
        #if len(self.datas) < 2:
        #    raise ValueError("This strategy requires at least 2 data feeds")
        self.add_timer(
            when=bt.Timer.SESSION_START,
            timername='rebalance',
            weekdays=[0, 1, 2, 3, 4],
            weekcarry=True,
            monthcarry=True
        )
        self.last_rebalance = None

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

    def notify_timer(self, timer, when, *args, **kwargs):
        #if timer.p.timername == 'rebalance':
        self.rebalance_portfolio()

    def rebalance_portfolio(self):
        alphas = []

        for i, d in enumerate(self.datas):
            # Skip if not enough data
            if len(d) < 21:
                alphas.append(0.0)
                return
            self.log(d, f"{self.datas[i].datetime.datetime(0).isoformat()}: {d.close[0]}, {d.volume[0]}")
            
            #exit()
            close = pd.Series(d.close.get(size=21))
            open_ = pd.Series(d.open.get(size=21))
            volume = pd.Series(d.volume.get(size=21))
            returns = close.pct_change().fillna(0)

            # Alpha #1
            signed_power = np.where(returns < 0, returns.rolling(20).std(), close)
            argmax_val = np.argmax(signed_power[-5:])
            alpha1 = pd.Series(np.arange(5))[argmax_val] / 4.0 - 0.5  # rank normalization

            # Alpha #2
            delta_log_vol = np.log(volume).diff(2)
            alpha2 = -1 * delta_log_vol.rank().corr(((close - open_) / open_).rank())

            # Alpha #3
            alpha3 = -1 * open_.rank().corr(volume.rank())

            # Weighted sum
            total_alpha = (
                self.p.weights_alpha[0] * alpha1 +
                self.p.weights_alpha[1] * alpha2 +
                self.p.weights_alpha[2] * alpha3
            )

            alphas.append(total_alpha)

        # Normalize alphas into weights
        alpha_array = np.array(alphas)
        if np.all(alpha_array == 0):
            weights = np.zeros_like(alpha_array)
        else:
            weights = alpha_array - np.mean(alpha_array)
            weights /= np.sum(np.abs(weights))  # Normalize to sum(abs) = 1

        # Rebalance
        total_value = self.broker.getvalue()
        for i, d in enumerate(self.datas):
            target_value = weights[i] * total_value
            order = self.order_target_size(data=d, target=target_value / d.close[0])
            self.log(d, f'weight={weights[i]:.2f}, target_value={target_value:.2f}')
            self.log(d, 'Order %s (%d), %.6f at %.3f' % 
                (d.ticker, order.ref, order.size, order.created.price))

    def next(self):
        self.rebalance_portfolio()
        return
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
