# strategy.py

import backtrader as bt

class AntyStrategy(bt.Strategy):
    params = (
        ('trending_bars', 3),
        ('stake', 1),
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
            self.stoch[d] = bt.indicators.Stochastic(d, period=7, period_dfast=4, period_dslow=10)

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
        if not trade.isclosed:
            return
        self.log(trade.data, 'OPERATION PROFIT, GROSS %.2f, NET %.2f' %
                 (trade.pnl, trade.pnlcomm))

    @staticmethod
    def is_rising(data, n, offset=0):
        """Returns True if the last n bars are continuously increasing."""
        return all(data[-i - offset] > data[-i - 1 - offset] for i in range(0, n))

    @staticmethod
    def is_falling(data, n, offset=0):
        """Returns True if the last n bars are continuously decreasing."""
        return all(data[-i - offset] < data[-i - 1 - offset] for i in range(0, n))

    def next(self):
        for i, d in enumerate(self.datas):
            if d.volume == 0:
                continue
            fast_up = (self.stoch[d].percK[0] - self.stoch[d].percK[-1] > 0)
            fast_dir_changed = fast_up != (self.stoch[d].percK[-1] - self.stoch[d].percK[-2] > 0)
            not_over = self.stoch[d].percD < 80 and self.stoch[d].percD > 20 and self.stoch[d].percK < 80 and self.stoch[d].percK > 20

            slow_rising = False
            slow_falling = False
            is_falling = False
            is_rising = False
            signal = 0
            if fast_dir_changed and not_over:
                slow_rising = AntyStrategy.is_rising(self.stoch[d].percD, self.params.trending_bars)
                slow_falling = AntyStrategy.is_falling(self.stoch[d].percD, self.params.trending_bars)
                is_falling = AntyStrategy.is_falling(self.stoch[d].percK, self.params.trending_bars, 1)
                is_rising = AntyStrategy.is_rising(self.stoch[d].percK, self.params.trending_bars, 1)
                if slow_rising and fast_up and is_falling:
                    signal = 1
                elif slow_falling and not fast_up and is_rising:
                    signal = -1

            self.log(d, "%s: o %.5f, h %.5f, l %.5f, c %.5f; %%K %.2f, %%D %.2f; %d/%d/%d %d/%d %d/%d signal %d" %
                (d.datetime.datetime(0).isoformat(), d.open[0], d.high[0], d.low[0], d.close[0], self.stoch[d].percK[0], self.stoch[d].percD[0],
                fast_up, fast_dir_changed, not_over, slow_rising, slow_falling, is_falling, is_rising, signal)
            )

            pos = self.getposition(d)
            if pos is None:
                #signal = 1
                # Flat
                if signal != 0:
                    if signal == 1:
                        # go long
                        order = self.buy(data=d, size=self.params.stake, exectype=bt.Order.Market)
                        print('BUY CREATE %s (%d), %.3f at %.3f' % 
                            (d.ticker, order.ref, order.size, order.created.price))
                        self.log(d, 'BUY CREATE %s (%d), %.3f at %.3f\n' % 
                            (d.ticker, order.ref, order.size, order.created.price))

                    elif signal == -1:
                        # go short
                        order = self.sell(data=d, size=self.params.stake, exectype=bt.Order.Market)
                        print('SELL CREATE %s (%d), %.3f at %.3f' % 
                            (d.ticker, order.ref, order.size, order.created.price))
                        self.log(d, 'SELL CREATE %s (%d), %.3f at %.3f\n' % 
                            (d.ticker, order.ref, order.size, order.created.price))
                            
