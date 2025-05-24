# alloc.py

from datetime import datetime
import json
import os
import sqlite3
import numpy as np
import pandas as pd

class AlphaStrategy:
    def __init__(self, logger, fn, initial_value, today):
        self.logger = logger
        self.abbrev = fn
        output_dir = f"work/{today}"
        os.makedirs(output_dir, exist_ok=True)
        self.alloc_fn = f"{output_dir}/{fn}.json"

        self.initial_value = initial_value
        self.portfolio = {
            "name": self.__class__.__name__,
            "date": today,
            'tickers': {}
        }
        self.load_portfolio()

        self.tickers = AlphaStrategy.load_tickers(f"cfg/{fn}.txt")
        #print(self.tickers)

        self.data = {}
        conn = sqlite3.connect("work/stock.sqlite")
        for t in self.tickers:
            try:
                query = f"""
                SELECT *
                FROM (
                    SELECT date, close
                    FROM prices
                    JOIN tickers ON prices.ticker_id = tickers.id
                    WHERE tickers.symbol = ? AND date < ?
                    ORDER BY date DESC
                    LIMIT 272
                )
                ORDER BY date ASC;
                """
                df = pd.read_sql_query(query, conn, params=(t, today), parse_dates=['date'])
                df.set_index('date', inplace=True)

                if len(df) < 21 * 12:
                    self.log(f"{t} not enough rows in DB ({len(df)})")
                    continue
                self.data[t] = df
                item = {
                    "close": df.close.iloc[-1],
                    "qty": 0
                }
                self.portfolio['tickers'][t] = item
            except FileNotFoundError:
                pass
        conn.close()

        # Align by index and drop missing values
        #data = pd.concat([data[tickers[0]], data[tickers[1]]], axis=1, join='inner').dropna()

    @staticmethod
    def load_tickers(fn):
        with open(fn, "r") as f:
            return [line.strip() for line in f if line.strip()]
        return None

    @staticmethod
    def compute_rsi(series, period=2):
        delta = series.diff()

        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)

        gain_series = pd.Series(gain, index=series.index)
        loss_series = pd.Series(loss, index=series.index)

        avg_gain = gain_series.rolling(window=period, min_periods=period).mean()
        avg_loss = loss_series.rolling(window=period, min_periods=period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def compute_portfolio_transition(old_portfolio, new_portfolio):
        transition = []

        old_tickers = old_portfolio.get('tickers', {})
        new_tickers = new_portfolio.get('tickers', {})

        all_tickers = set(old_tickers.keys()) | set(new_tickers.keys())

        for ticker in sorted(all_tickers):
            old_qty = old_tickers.get(ticker, {}).get('qty', 0)
            new_qty = new_tickers.get(ticker, {}).get('qty', 0)

            if new_qty > old_qty:
                transition.append({
                    'ticker': ticker,
                    'action': 'add',
                    'qty': new_qty - old_qty,
                    'text': f'Increase allocation from {old_qty} to {new_qty}'
                })
            elif new_qty < old_qty:
                transition.append({
                    'ticker': ticker,
                    'action': 'remove',
                    'qty': old_qty - new_qty,
                    'text': f'Reduce allocation from {old_qty} to {new_qty}'
                })
            # If equal, no action needed

        return transition

    def log(self, txt):
        if self.logger:
            self.logger.debug('%s: %s' % (self.abbrev, txt))
        else:
            print('%s: %s' % (self.abbrev, txt))

    def load_portfolio(self):
        try:
            with open(self.alloc_fn) as f:
                self.portfolio = json.load(f)
                #print(self.portfolio)
        except FileNotFoundError:
            self.log("Starting with empty portfolio")

    def save_portfolio(self):
        self.portfolio['value'] = self.get_value()
        with open(self.alloc_fn, 'w') as f:
            json.dump(self.portfolio, f, indent=4)

    def get_value(self, use_initial=False):
        value = 0
        for ticker, info in self.portfolio['tickers'].items():
            value += info['close'] * info['qty']
        if use_initial and value == 0:
            return self.initial_value
        return value

    def allocate(self):
        raise NotImplementedError
    
    def close(self, end_of_week):
        return set()  # tickers for positions to be closed

class RisingAssets(AlphaStrategy):

    def __init__(self, logger, initial_value, today):
        super().__init__(logger, 'ra', initial_value, today)

    def allocate(self):
        self.log(f"========= allocate {self.initial_value}")
        top = []
        value = self.get_value(True)
        for ticker, info in self.portfolio['tickers'].items():
            d = self.data[ticker]
            score = 0
            #print(f"{ticker}: {len(d.close)}")
            for n in [1, 3, 6, 12]:
                sc = d.close.iloc[-1] / d.close.iloc[-21 * n - 1] * 100
                #print(f"sc_{n}: {sc}: {d.close.iloc[-1]} / {d.close.iloc[-21 * n - 1]}")
                score += sc
            score /= 4
            daily_return = d.close / d.close.shift(1)
            volatility = daily_return.rolling(window=63).std()
            rev_vol = 1 / volatility.iloc[-1]
            #print(f"{ticker}: {score}, {volatility.iloc[-1]}")
            top.append({'ticker': ticker, 'score': score, 'rev_vol': rev_vol})
        
        self.portfolio['tickers'] = {}
        vol_sum = 0
        top_sorted = sorted(top, key=lambda x: x['score'], reverse=True)[:5]
        for item in top_sorted:
            #print(f"{item['ticker']}: {item['rev_vol']}, {value}")
            vol_sum += item['rev_vol']

        for item in top_sorted:
            close = self.data[item['ticker']].close.iloc[-1]
            alloc_cash = value * item['rev_vol'] / vol_sum
            alloc = alloc_cash / close
            if alloc < 1 and alloc > 0.5:
                alloc = 1
            else:
                alloc = int(alloc)
            self.log(f"{item['ticker']}: px {close}, {alloc}")
            self.portfolio['tickers'][item['ticker']] = {
                'qty': alloc,
                'close': close,
                'buy_limit': close
            }
        self.portfolio['value'] = self.get_value()
        self.log("Portfolio after alloc:")
        self.log(self.portfolio)


class DynamicTreasures(AlphaStrategy):

    def __init__(self, logger, initial_value, today):
        super().__init__(logger, 'dt', initial_value, today)
        self.remains = self.tickers[-1]

    def allocate(self):
        self.log(f"========= allocate {self.initial_value}")
        top = []
        value = self.get_value(True)
        for ticker, info in self.portfolio['tickers'].items():
            if ticker != self.remains:
                d = self.data[ticker]
                score = 0
                #print(f"{ticker}: {len(d.close)}")
                for n in [1, 2, 3, 4, 5]:
                    sc = d.close.iloc[-1] > d.close.iloc[-21 * n - 1]
                    #print(f"sc_{n}: {sc}: {d.close.iloc[-1]} / {d.close.iloc[-21 * n - 1]}")
                    if sc:
                        score += 5  # % allocation
                #print(f"{ticker}: {score}")
                top.append({'ticker': ticker, 'score': score})
        
        self.portfolio['tickers'] = {}
        for item in top:
            alloc = 0
            if item['score'] > 0:
                close = self.data[item['ticker']].close.iloc[-1]
                alloc_cash = value * item['score'] / 100
                alloc = alloc_cash / close
                alloc = int(alloc)
                self.log(f"{item['ticker']}: px {close}, {alloc}")
                self.portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'close': close,
                    'buy_limit': close
                }

        # remains alloc
        alloc_cash = self.initial_value - self.get_value()
        close = self.data[self.remains].close.iloc[-1]
        alloc = alloc_cash / close
        alloc = int(alloc)
        if alloc > 0:
            self.portfolio['tickers'][self.remains] = {
                'qty': alloc,
                'close': close,
                'buy_limit': close
            }
            self.log(f"{self.remains}: px {close}, {alloc} - remains")
       
        self.portfolio['value'] = self.get_value()
        self.log("Portfolio after alloc:")
        self.log(self.portfolio)


class ETFAvalanches(AlphaStrategy):

    def __init__(self, logger, initial_value, today):
        super().__init__(logger, 'ea', initial_value, today)
        self.remains = self.tickers[-1]

    def allocate(self):
        self.log(f"========= allocate {self.initial_value}")
        top = []
        value = self.get_value(True)
        for ticker, info in self.portfolio['tickers'].items():
            if ticker != self.remains:
                d = self.data[ticker]
                score = 0
                rev_vol = 0
                if d.close.iloc[-1] < d.close.iloc[-21 * 12 - 1]:  # negative total return over the past year
                    if d.close.iloc[-1] < d.close.iloc[-21 * 1 - 1]:  # negative total return over the past month
                        rsi = AlphaStrategy.compute_rsi(d.close).iloc[-1]
                        if rsi > 70:
                            score = d.close.iloc[-1] * 1.03  # put a sell limit order 3.0% above the current price
                            daily_return = d.close / d.close.shift(1)
                            volatility = daily_return.rolling(window=100).std()
                            rev_vol = 1 / volatility.iloc[-1]
                top.append({'ticker': ticker, 'score': score, 'rev_vol': rev_vol})

        self.portfolio['tickers'] = {}
        vol_sum = 0
        top_sorted = sorted(top, key=lambda x: x['rev_vol'], reverse=False)[:5]
        for item in top_sorted:
            #print(f"{item['ticker']}: {item['rev_vol']}, {score}, {value}")
            vol_sum += item['rev_vol']

        for item in top_sorted:
            alloc = 0
            if item['rev_vol'] > 0:
                close = self.data[item['ticker']].close.iloc[-1]
                alloc_cash = value * item['rev_vol'] / vol_sum
                alloc = alloc_cash / close
                alloc = int(alloc)
                self.log(f"{item['ticker']}: px {close}, {alloc}")
                self.portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'close': close,
                    'sell_limit': close
                }
        # remains alloc
        alloc_cash = self.initial_value - self.get_value()
        close = self.data[self.remains].close.iloc[-1]
        alloc = alloc_cash / close
        alloc = int(alloc)
        if alloc > 0:
            self.portfolio['tickers'][self.remains] = {
                'qty': alloc,
                'close': close,
                'buy_limit': close
            }
            self.log(f"{self.remains}: px {close}, {alloc} - remains")

        self.portfolio['value'] = self.get_value()
        self.log("Portfolio after alloc:")
        self.log(self.portfolio)

    def close(self, end_of_week):
        self.log(f"========= close {self.initial_value}, eow {end_of_week}")
        result = set()  # tickers for positions to be closed
        for ticker, info in self.portfolio['tickers'].items():
            if ticker != self.remains and info['qty'] > 0:
                d = self.data[ticker]
                if d.close.iloc[-1] > d.close.iloc[-21 * 1 - 1]:  # positive total return over the past month
                    result.insert(ticker)
                rsi = AlphaStrategy.compute_rsi(d.close).iloc[-1]
                if rsi < 15:
                    result.insert(ticker)
        return result


class MeanReversion(AlphaStrategy):

    def __init__(self, logger, initial_value, today):
        super().__init__(logger, 'mr', initial_value, today)
        self.long_trend_ticker = self.tickers[-2]
        self.remains = self.tickers[-1]

    def allocate(self):
        self.log(f"========= allocate {self.initial_value}")
        trend_d = self.data[self.long_trend_ticker].close
        if trend_d.iloc[-1] > trend_d.iloc[-21 * 6 - 1]:  # SPY’s total return over the last six months (126 trading days) is positive
            self.log(f"{self.long_trend_ticker} trend is positive: {trend_d.iloc[-1]} > {trend_d.iloc[-21 * 6 - 1]}")
            top = []
            value = self.get_value(True)
            for ticker, info in self.portfolio['tickers'].items():
                if ticker != self.remains and ticker != self.long_trend_ticker:
                    d = self.data[ticker]
                    #print(f"{ticker} check")
                    if d.close.iloc[-1] < d.close.iloc[-21 * 12 - 1]:  # negative total return over the past year
                        if d.close.iloc[-1] < d.close.iloc[-21 * 1 - 1]:  # negative total return over the past month
                            weekly_series = d.close.resample('W').last()
                            #print(weekly_series)
                            rsi = AlphaStrategy.compute_rsi(weekly_series).iloc[-1]
                            #exit()
                            if rsi < 20:  # The Weekly 2-period RSI of the stock is below 20
                                #print(f"allocate {ticker}: rsi {rsi}")
                                daily_return = d.close / d.close.shift(1)
                                volatility = daily_return.rolling(window=100).std()
                                top.append({'ticker': ticker, 'volatility': volatility.iloc[-1]})

            top_sorted = sorted(top, key=lambda x: x['volatility'], reverse=False)[:10]
            #print(top_sorted)
            alloc_cash = value / 10

            self.portfolio['tickers'] = {}
            for item in top_sorted:
                alloc = 0
                if item['volatility'] > 0:
                    close = self.data[item['ticker']].close.iloc[-1]
                    alloc = alloc_cash / close
                    alloc = int(alloc)
                    self.log(f"{item['ticker']}: px {close}, {alloc}")
                self.portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'close': close,
                    'buy_limit': close
                }
            # remains alloc
            alloc_cash = self.initial_value - self.get_value()
            close = self.data[self.remains].close.iloc[-1]
            alloc = alloc_cash / close
            alloc = int(alloc)
            if alloc > 0:
                self.portfolio['tickers'][self.remains] = {
                    'qty': alloc,
                    'close': close,
                    'buy_limit': close
                }
                self.log(f"{self.remains}: px {close}, {alloc} - remains")

            self.portfolio['value'] = self.get_value()
            self.log("Portfolio after alloc:")
            self.log(self.portfolio)
        else:
            self.log(f"{self.long_trend_ticker} trend is negative: {trend_d.iloc[-1]} < {trend_d.iloc[-21 * 6 - 1]}")

    def close(self, end_of_week):
        self.log(f"close {self.initial_value}, end_of_week {end_of_week}")
        result = set()  # tickers for positions to be closed
        for ticker, info in self.portfolio['tickers'].items():
            if ticker != self.remains and info['qty'] > 0:
                d = self.data[ticker]
                if end_of_week:
                    weekly_series = d.close.resample('W').last()
                    #print(weekly_series)
                    rsi = AlphaStrategy.compute_rsi(weekly_series).iloc[-1]
                    if rsi > 80:
                        result.insert(ticker)
                if d.close.iloc[-1] / info['buy_limit'] < 0.9:  # the current price is more than 10% below the entry price
                    result.insert(ticker)
        return result
