from backtrader import Indicator, LinePlotterIndicator
import backtrader as bt
import numpy as np

class HalfTrend(bt.Indicator):
	lines = ('signal', 'atr_high', 'atr_low')  # Define indicator lines
	params = (
		('amplitude', 1),  # Amplitude for calculating high and low prices
		('channel_deviation', 1),  # Deviation multiplier
		('atr_period', 100),  # Period for ATR calculation
	)

	def __init__(self):
		# Define buffers for internal calculations
		self.addminperiod(self.params.atr_period)  # Ensure enough data
		self.trend = [0]
		self.next_trend = 0
		self.max_low_price = None
		self.min_high_price = None

		# Initialize ATR
		self.atr = bt.indicators.AverageTrueRange(period=self.params.atr_period)

	def next(self):
		# Get the current index
		i = len(self.data) - 1

		# Initialize max_low_price and min_high_price on the first bar
		if self.max_low_price is None:
			self.max_low_price = self.data.low[0]
			self.min_high_price = self.data.high[0]

		# Calculate rolling high and low over the amplitude period
		high_price = max(self.data.high.get(size=self.params.amplitude))
		low_price = min(self.data.low.get(size=self.params.amplitude))

		# Calculate channel deviation
		dev = self.params.channel_deviation * self.atr[0]

		# Trend calculation logic
		if self.next_trend == 1:
			self.max_low_price = max(low_price, self.max_low_price)
			if self.data.close[0] < self.max_low_price:
				self.trend.append(1)
				self.next_trend = 0
				self.min_high_price = high_price
		else:
			self.min_high_price = min(high_price, self.min_high_price)
			if self.data.close[0] > self.min_high_price:
				self.trend.append(0)
				self.next_trend = 1
				self.max_low_price = low_price

		# Set lines and signals
		if self.trend[-1] == 0:
			self.lines.atr_high[0] = self.max_low_price + dev
			self.lines.atr_low[0] = self.max_low_price - dev
			self.lines.signal[0] = 1 if len(self.trend) > 1 and self.trend[-1] != self.trend[-2] else 0
		else:
			self.lines.atr_high[0] = self.min_high_price + dev
			self.lines.atr_low[0] = self.min_high_price - dev
			self.lines.signal[0] = -1 if len(self.trend) > 1 and self.trend[-1] != self.trend[-2] else 0
