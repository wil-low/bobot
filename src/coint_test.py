import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from statsmodels.tsa.stattools import coint, adfuller
from statsmodels.tsa.vector_ar.vecm import coint_johansen

# Load historical data
# * ['GLD', 'GDX'] ADF on Spread: -3.0246050335566568 0.03265961833678251 {'1%': -3.432954851668868, '5%': -2.862690812247962, '10%': -2.5673826214832887}
# * ['GLD', 'GOLD'] ADF on Spread: -2.73499263306581 0.06817627231519799 {'1%': -3.4355754676859886, '5%': -2.8638475772391665, '10%': -2.5679985805677017}
# ["NVDA", "AMD"] ADF on Spread: -2.2842464559282334 0.1770991507242201 {'1%': -3.432954851668868, '5%': -2.862690812247962, '10%': -2.5673826214832887}
# ["GDX", "GDXJ"] ADF on Spread: -1.8567133087594023 0.35269031070690604 {'1%': -3.4329715599546646, '5%': -2.862698190651408, '10%': -2.567386549839784}
# ["MSFT", "AAPL"] ADF on Spread: -2.144470918484471 0.22701247700514776 {'1%': -3.4329642237790847, '5%': -2.862694950990622, '10%': -2.5673848250020415}
# ["USO", "BNO"] ADF on Spread: -1.7807707864004105 0.39004938408182854 {'1%': -3.4329799947351503, '5%': -2.862701915447137, '10%': -2.5673885329713495}
# ["USO", "XOP"] ADF on Spread: -2.1268151031900997 0.2338696913356273 {'1%': -3.4329652692893364, '5%': -2.8626954126892405, '10%': -2.567385070816339}
# ["COP", "OXY"] ADF on Spread: -0.41710091794174664 0.9072041440891878 {'1%': -3.4329631791044304, '5%': -2.8626944896608433, '10%': -2.5673845793841457}
# * ['AU', 'HMY'] ADF on Spread: -3.2188178716924725 0.018920941467349343 {'1%': -3.4329610922579095, '5%': -2.8626935681060375, '10%': -2.567384088736619}
# * ['PAAS', 'AG'] ADF on Spread: -2.8449695992359474 0.05213173793139272 {'1%': -3.4329631791044304, '5%': -2.8626944896608433, '10%': -2.5673845793841457}
# ['HL', 'CDE'] ADF on Spread: -1.276321080850705 0.6399346343377244 {'1%': -3.4329715599546646, '5%': -2.862698190651408, '10%': -2.567386549839784}
# ['SLV', 'SIL'] ADF on Spread: -1.9445868903050407 0.3113852863551866 {'1%': -3.4329631791044304, '5%': -2.8626944896608433, '10%': -2.5673845793841457}
# ['IVV', 'VTI'] ADF on Spread: -1.3585392763540367 0.6019837322723719 {'1%': -3.432955889694659, '5%': -2.8626912706428715, '10%': -2.567382865538409}
# ['KO', 'PEP'] ADF on Spread: -2.4214569510444957 0.13577169388625515 {'1%': -3.432962135264372, '5%': -2.862694028699462, '10%': -2.567384333962417}
# ['V', 'MA'] ADF on Spread: -1.4233274789824262 0.5710429573450821 {'1%': -3.432954851668868, '5%': -2.862690812247962, '10%': -2.5673826214832887}
# ['MCD', 'YUM'] ADF on Spread: -2.6121403623088173 0.09051397165478164 {'1%': -3.4329652692893364, '5%': -2.8626954126892405, '10%': -2.567385070816339}
# ['GLD', 'IAU'] ADF on Spread: -0.24572130543410634 0.9328477702047613 {'1%': -3.4329810529006184, '5%': -2.862702382731847, '10%': -2.5673887817601657}
# ['PPLT', 'SBSW'] ADF on Spread: -2.2456996960668794 0.19007893823623523 {'1%': -3.4329527780962255, '5%': -2.8626898965523724, '10%': -2.567382133955709}
# ['PPLT', 'PALL'] ADF on Spread: -1.5632393663187794 0.502028543848676 {'1%': -3.432955889694659, '5%': -2.8626912706428715, '10%': -2.567382865538409}
# ['FNV', 'RGLD'] ADF on Spread: -1.9689296041468254 0.3003603000506202 {'1%': -3.432960050084045, '5%': -2.8626931078801285, '10%': -2.567383843706519}
# ['SO', 'D'] ADF on Spread: 0.9345369932719957 0.993524889609864 {'1%': -3.4329527780962255, '5%': -2.8626898965523724, '10%': -2.567382133955709}
# ['VZ', 'T'] ADF on Spread: -1.8763722326004995 0.3432566756131209 {'1%': -3.4329527780962255, '5%': -2.8626898965523724, '10%': -2.567382133955709}

tickers = ["GDXJ", "GOLD"]

data = {}

for t in tickers:
    fn = f'datasets/tiingo/{t}.csv'
    df = pd.read_csv(fn, parse_dates=['date'], index_col='date')
    data[t] = np.log(df['adjClose'])

# Align by index and drop missing values
data = pd.concat([data[tickers[0]], data[tickers[1]]], axis=1, join='inner').dropna()
data.columns = tickers

# Create DataFrame for Johansen test
df_data = pd.DataFrame({
    tickers[0]: data[tickers[0]],
    tickers[1]: data[tickers[1]]
}).dropna()

# Engle-Granger test
eg_score, eg_pvalue, eg_crit = coint(data[tickers[0]], data[tickers[1]])

# ADF test on spread
spread = data[tickers[0]] - data[tickers[1]]
adf_result = adfuller(spread.dropna())

# Johansen test
johansen_result = coint_johansen(df_data, det_order=0, k_ar_diff=1)

print("Tickers:", tickers)
print("Engle-Granger:", eg_score, eg_pvalue, eg_crit)
print("Johansen Trace Stats:", johansen_result.lr1)
print("Johansen Crit Values:\n", johansen_result.cvt)
print("#", tickers, "ADF on Spread:", adf_result[0], adf_result[1], adf_result[4])

# Plot
import matplotlib.pyplot as plt
plt.figure(figsize=(14, 6))
plt.subplot(2, 1, 1)
plt.plot(data[tickers[0]], label=f"log({tickers[0]})")
plt.plot(data[tickers[1]], label=f"log({tickers[1]})")
plt.title("Log Prices")
plt.legend()

plt.subplot(2, 1, 2)
plt.plot(spread, label=f"Spread = log({tickers[0]}) - log({tickers[1]})", color="purple")
plt.axhline(spread.mean(), color="gray", linestyle="--")
plt.title("Log Price Spread")
plt.legend()
plt.tight_layout()
plt.show()

