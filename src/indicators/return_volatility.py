import backtrader as bt

class ReturnVolatility(bt.Indicator):
    lines = ('returns_std',)
    params = (('period', 25),)

    def __init__(self):
        # Simple 1-bar return: close / close[-1] - 1
        returns = (self.data.close / self.data.close(-1)) - 1
        self.lines.returns_std = bt.ind.StandardDeviation(returns, period=self.p.period)
