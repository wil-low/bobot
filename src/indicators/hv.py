import backtrader as bt
import numpy as np

class HistoricalVolatility(bt.Indicator):
	lines = ('hv',)  # Define the indicator line
	params = (
		('period', 10),
		('weekly', False),
	)

	def __init__(self):
		self.addminperiod(self.params.period)  # Ensure enough data before calculation
		per = 1
		if self.params.weekly:
			per = 7
		self.multiplier = np.sqrt(365 / per) * 100

	def next(self):
		if len(self) < self.params.period:
			return  # Not enough data

		# Convert array.array to NumPy array for calculations
		closes = np.array(self.data.close.get(size=self.params.period))

		# Compute log returns
		log_returns = np.log(closes[1:] / closes[:-1])

		# Calculate standard deviation of log returns (Historical Volatility)
		self.lines.hv[0] = np.std(log_returns, ddof=1) * self.multiplier  # Annualized HV
