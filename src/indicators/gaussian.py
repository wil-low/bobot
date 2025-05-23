from backtrader import Indicator, LinePlotterIndicator
from scipy.ndimage import gaussian_filter1d
import numpy as np

class Gaussian1D(Indicator):
	lines = ('gaussian1d',)
	params = (
		('sigma', 3),  # Standard deviation for Gaussian kernel
		('lookback', 100),  # Lookback period for the indicator
	)

	def __init__(self):
		# Ensure enough data is available
		self.addminperiod(self.params.lookback)

	def next(self):
		# Get the lookback period of data
		lookback_data = np.array(self.data.get(size=self.params.lookback))

		# Apply Gaussian smoothing
		smoothed_value = gaussian_filter1d(lookback_data, self.params.sigma)[-1]

		# Assign to the indicator's line
		self.lines.gaussian1d[0] = smoothed_value
