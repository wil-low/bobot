import math
from backtrader import backtrader as bt

class UpDown(bt.Indicator):
	lines = ('ud',)

	def __init__(self):
		self.src = self.data.close
		#self.counter = 0

	def ud(self, idx):
		val = self.lines.ud[idx]
		if math.isnan(val):
			return 0
		return val

	def next(self):
		isEqual = self.src[0] == self.src[-1]
		isGrowing = self.src[0] > self.src[-1]
		if isEqual:
			self.lines.ud[0] = 0
		elif isGrowing:
			if self.ud(-1) <= 0:
				self.lines.ud[0] = 1
			else:
				self.lines.ud[0] = self.ud(-1) + 1
		else:
			if self.ud(-1) >= 0:
				self.lines.ud[0] = -1
			else:
				self.lines.ud[0] = self.ud(-1) - 1
		'''
		self.counter += 1
		s = f'{len(self.lines.ud)}: '
		for i in range(0, len(self.lines.ud)):
			s += f'{self.lines.ud[-i]}, '
		print(f'{self.counter}: {s}; {self.src[0]} == {self.src[-1]}')
		if self.counter == 10:
			raise
		'''

class ConnorsRSI(bt.Indicator):
	lines = ('crsi',)
	params = (
		('rsi_period', 3),
		('updown_len', 2),
		('roc_len', 100),
	)

	def __init__(self):
		self.src = self.data.close
		self.rsi = bt.indicators.RSI_Safe(self.src, period=self.params.rsi_period)
		self.updown = UpDown(self.data)
		self.updownrsi = bt.indicators.RSI_Safe(self.updown, period=self.params.updown_len)
		self.roc = bt.indicators.RateOfChange(self.src, period=1)
		self.percentrank = bt.indicators.PercentRank(self.roc, period=self.params.roc_len)
		#self.counter = 0

	def next(self):
		#self.counter += 1
		#print(f'{self.counter}: {self.rsi[0]} + {self.updownrsi[0]} ({self.updown[0]}, {self.updown[-1]}, {self.updown[-2]}) + {self.percentrank[0] * 100} = {self.lines.crsi[0]}')
		self.lines.crsi[0] = (self.rsi[0] + self.updownrsi[0] + self.percentrank[0] * 100) / 3.0
