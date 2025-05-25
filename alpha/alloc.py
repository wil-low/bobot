# alloc.py

import copy
from datetime import datetime
import json
import os
import sqlite3
import numpy as np
import pandas as pd

class AlphaStrategy:
    def __init__(self, logger, key, portfolio, today):
        self.key = key
        self.logger = logger
        self.portfolio = portfolio

        self.tickers = AlphaStrategy.load_tickers(f"cfg/{key}.txt")

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
            except FileNotFoundError:
                pass
        conn.close()

        self.portfolio['equity'] = self.compute_equity(self.portfolio)
        self.allocatable = portfolio['equity'] * 0.97  # reserve for fees
        self.log(f"========= equity {self.portfolio['equity']}, allocatable {self.allocatable}")

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

    def print_p(self, portfolio):
        return json.dumps(portfolio, sort_keys=True)

    def compute_portfolio_transition(self, old_portfolio, new_portfolio):
        adds = []
        removes = []

        old_tickers = old_portfolio.get('tickers', {})
        new_tickers = new_portfolio.get('tickers', {})

        all_tickers = set(old_tickers.keys()) | set(new_tickers.keys())

        for ticker in sorted(all_tickers):
            old_qty = old_tickers.get(ticker, {}).get('qty', 0)
            new_qty = new_tickers.get(ticker, {}).get('qty', 0)

            if new_qty > old_qty:
                diff = round(new_qty - old_qty, 2)
                text = f'Increase {ticker} by {diff}, from {old_qty} to {new_qty}'
                if self.key == 'mr' and old_qty == 0:
                    text += ', record entry price'
                elif self.key == 'ea' and old_qty == 0:
                    text += f", using sell Day order at {new_tickers[ticker]['close']}"
                adds.append({
                    'ticker': ticker,
                    'action': 'add',
                    'qty': diff,
                    'text': text
                })
                new_portfolio['cash'] -= self.data[ticker].close.iloc[-1] * diff
                #print(ticker, self.data[ticker].close.iloc[-1], diff, 'new_cash increased', new_portfolio['cash'])
            elif new_qty < old_qty:
                diff = round(old_qty - new_qty, 2)
                text = f'Reduce {ticker} by {diff}, from {old_qty} to {new_qty}'
                removes.append({
                    'ticker': ticker,
                    'action': 'remove',
                    'qty': diff,
                    'text': text
                })
                new_portfolio['cash'] += self.data[ticker].close.iloc[-1] * diff
                #print(ticker, self.data[ticker].close.iloc[-1], diff, 'new_cash reduced', new_portfolio['cash'])
            # If equal, no action needed

        new_portfolio['equity'] = self.compute_equity(new_portfolio)
        self.log(f"old_p: {self.print_p(old_portfolio)}")
        self.log(f"new_p: {self.print_p(new_portfolio)}")
        return removes + adds

    def log(self, txt):
        if self.logger:
            self.logger.debug('%s: %s' % (self.key, txt))
        else:
            print('%s: %s' % (self.key, txt))

    def compute_equity(self, portfolio):
        portfolio['cash'] = int(portfolio['cash'] * 100) / 100
        equity = portfolio['cash']
        #print(f"compute_eq: cash {equity}")
        for ticker, info in portfolio['tickers'].items():
            close = info['close']  #self.data[ticker].close.iloc[-1]
            #info['close'] = close
            value = close * info['qty']
            equity += value
            #print(f"compute_eq: {ticker}, {close}, {info['qty']}, {value}")
        equity = int(equity * 100) / 100
        #print(f"compute_eq: equity={equity}\n")
        return equity

    def allocate(self):
        raise NotImplementedError
    
    def to_be_closed(self, end_of_week):
        return set()  # tickers for positions to be closed

class RisingAssets(AlphaStrategy):

    def __init__(self, logger, portfolio, today):
        super().__init__(logger, 'ra', portfolio['ra'], today)

    def allocate(self):
        top = []
        for ticker in self.tickers:
            d = self.data[ticker]
            #self.allocatable += d.close.iloc[-1]
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
        
        new_portfolio = {'tickers': {}, 'cash': self.portfolio['cash']}
        vol_sum = 0
        top_sorted = sorted(top, key=lambda x: x['score'], reverse=True)[:5]
        for item in top_sorted:
            #print(f"{item['ticker']}: {item['rev_vol']}, {value}")
            vol_sum += item['rev_vol']

        for item in top_sorted:
            close = self.data[item['ticker']].close.iloc[-1]
            alloc_cash = self.allocatable * item['rev_vol'] / vol_sum
            alloc = alloc_cash / close
            calc_alloc = alloc
            if alloc < 1 and alloc > 0.5:
                alloc = 1
            else:
                alloc = int(alloc * 100) / 100
            self.log(f"{item['ticker']}: px {close}, {alloc}, val {int(close * alloc * 100) / 100}")  #, calculated {calc_alloc}")
            if alloc >= 1:
                new_portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'close': close,
                    'side': 'buy'
                }
        #print('new_cash', new_portfolio['cash'])
        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)


class DynamicTreasures(AlphaStrategy):

    def __init__(self, logger, portfolio, today):
        super().__init__(logger, 'dt', portfolio['dt'], today)
        self.remains = self.tickers[-1]

    def allocate(self):
        top = []
        for ticker in self.tickers:
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
        
        new_portfolio = {'tickers': {}, 'cash': self.portfolio['cash']}
        remains_alloc = self.allocatable
        for item in top:
            alloc = 0
            if item['score'] > 0:
                close = self.data[item['ticker']].close.iloc[-1]
                alloc_cash = self.allocatable * item['score'] / 100
                alloc = alloc_cash / close
                alloc = int(alloc * 100) / 100
                if alloc >= 1:
                    value = int(close * alloc * 100) / 100
                    remains_alloc -= value
                    self.log(f"{item['ticker']}: px {close}, {alloc}, val {value}")
                    new_portfolio['tickers'][item['ticker']] = {
                        'qty': alloc,
                        'close': close,
                        'side': 'buy'
                    }

        # remains alloc
        print('remains alloc', remains_alloc)
        close = self.data[self.remains].close.iloc[-1]
        alloc = remains_alloc / close
        alloc = int(alloc * 100) / 100
        if alloc >= 1:
            new_portfolio['tickers'][self.remains] = {
                '-remains': True,
                'qty': alloc,
                'close': close,
                'side': 'buy'
            }
            self.log(f"{self.remains}: px {close}, {alloc}, val {int(close * alloc * 100) / 100} - remains")
       
        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)

class ETFAvalanches(AlphaStrategy):

    def __init__(self, logger, portfolio, today):
        super().__init__(logger, 'ea', portfolio['ea'], today)
        self.remains = self.tickers[-1]

    def allocate(self):
        top = []
        tickers_to_close = self.to_be_closed(False)
        for ticker in self.tickers:
            if ticker != self.remains and not ticker in tickers_to_close and not ticker in self.portfolio['tickers']:
                d = self.data[ticker]
                if d.close.iloc[-1] < d.close.iloc[-21 * 12 - 1]:  # negative total return over the past year
                    print(f"{ticker}: negative total return over the past year")
                    if True or d.close.iloc[-1] < d.close.iloc[-21 * 1 - 1]:  # negative total return over the past month
                        print(f"{ticker}: negative total return over the past month")
                        #print(f"{ticker}: d.close {d.close}")
                        rsi = AlphaStrategy.compute_rsi(d.close).iloc[-1]
                        #print(f"{ticker}: rsi {AlphaStrategy.compute_rsi(d.close)}")
                        if rsi >= 0:  #> 70:
                            print(f"{ticker}: rsi {rsi}")
                            entry = d.close.iloc[-1] * 1.03  # put a sell limit order 3.0% above the current price
                            entry = int(entry * 100) / 100
                            daily_return = d.close / d.close.shift(1)
                            volatility = daily_return.rolling(window=100).std()
                            top.append({'ticker': ticker, 'entry': entry, 'volatility': volatility.iloc[-1]})

        new_portfolio = copy.deepcopy(self.portfolio)
        print('to_be_closed', tickers_to_close)
        print('allocatable', self.allocatable)
        remains_alloc = self.allocatable
        # remove closed tickers
        for ticker in list(new_portfolio['tickers'].keys()):
            info = new_portfolio['tickers'][ticker]
            if ticker in tickers_to_close:
                del new_portfolio['tickers'][ticker]
            else:
                value = int(self.data[ticker].close.iloc[-1] * info['qty'] * 100) / 100
                remains_alloc -= value


        print('remains alloc1', remains_alloc)
        free_slots = 5 + 1 - len(new_portfolio['tickers'])
        top_sorted = sorted(top, key=lambda x: x['volatility'], reverse=True)[:free_slots]
        alloc_cash = self.allocatable / 5

        for item in top_sorted:
            alloc = 0
            entry = item['entry']
            alloc = alloc_cash / entry
            alloc = int(alloc * 100) / 100
            if alloc >= 1:
                value = int(entry * alloc * 100) / 100
                self.log(f"{item['ticker']}: px {entry}, {alloc}, val {value}")
                remains_alloc -= value
                new_portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'close': entry,
                    'side': 'sell'
                }
        # remains alloc
        print('remains alloc', remains_alloc)
        close = self.data[self.remains].close.iloc[-1]
        alloc = remains_alloc / close
        alloc = int(alloc * 100) / 100
        if alloc >= 1:
            close = self.data[self.remains].close.iloc[-1]
            new_portfolio['tickers'][self.remains] = {
                '-remains': True,
                'qty': alloc,
                'close': close,
                'side': 'buy'
            }
            self.log(f"{self.remains}: px {close}, {alloc}, val {int(close * alloc * 100) / 100} - remains")
        else:
            del new_portfolio['tickers'][self.remains]

        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)

    def to_be_closed(self, end_of_week):
        result = set()  # tickers for positions to be closed
        for ticker, info in self.portfolio['tickers'].items():
            if ticker != self.remains:
                d = self.data[ticker]
                if d.close.iloc[-1] > d.close.iloc[-21 * 1 - 1]:  # positive total return over the past month
                    result.add(ticker)
                rsi = AlphaStrategy.compute_rsi(d.close).iloc[-1]
                if rsi < 15:
                    result.add(ticker)
        return result


class MeanReversion(AlphaStrategy):

    def __init__(self, logger, portfolio, today):
        super().__init__(logger, 'mr', portfolio['mr'], today)
        self.long_trend_ticker = self.tickers[-2]
        self.remains = self.tickers[-1]

    def allocate(self):
        trend_d = self.data[self.long_trend_ticker].close
        if trend_d.iloc[-1] > trend_d.iloc[-21 * 6 - 1]:  # SPY’s total return over the last six months (126 trading days) is positive
            self.log(f"{self.long_trend_ticker} trend is positive: {trend_d.iloc[-1]} > {trend_d.iloc[-21 * 6 - 1]}")
            top = []
            for ticker in self.tickers:
                if ticker != self.remains and ticker != self.long_trend_ticker:
                    try:
                        d = self.data[ticker]
                        #print(f"{ticker} check")
                        if d.close.iloc[-1] < d.close.iloc[-21 * 12 - 1]:  # negative total return over the past year
                            if d.close.iloc[-1] < d.close.iloc[-21 * 1 - 1]:  # negative total return over the past month
                                weekly_series = d.close.resample('W').last()
                                #print(weekly_series)
                                rsi = AlphaStrategy.compute_rsi(weekly_series).iloc[-1]
                                if rsi < 20:  # The Weekly 2-period RSI of the stock is below 20
                                    #print(f"allocate {ticker}: rsi {rsi}")
                                    daily_return = d.close / d.close.shift(1)
                                    volatility = daily_return.rolling(window=100).std()
                                    top.append({'ticker': ticker, 'volatility': volatility.iloc[-1]})
                    except KeyError:
                        pass

            top_sorted = sorted(top, key=lambda x: x['volatility'], reverse=False)[:10]
            alloc_cash = self.allocatable / 10

            new_portfolio = {'tickers': {}, 'cash': self.portfolio['cash']}
            for item in top_sorted:
                alloc = 0
                if item['volatility'] > 0:
                    close = self.data[item['ticker']].close.iloc[-1]
                    alloc = alloc_cash / close
                    alloc = int(alloc)
                    self.log(f"{item['ticker']}: px {close}, {alloc}, val {int(close * alloc * 100) / 100}")
                    if alloc >= 1:
                        new_portfolio['tickers'][item['ticker']] = {
                            'qty': alloc,
                            'entry': close,
                            'close': close,
                            'side': 'buy'
                        }
            # remains alloc
            alloc_cash = self.allocatable - self.compute_equity(new_portfolio)
            close = self.data[self.remains].close.iloc[-1]
            alloc = alloc_cash / close
            alloc = int(alloc * 10) / 10
            if alloc >= 1:
                new_portfolio['tickers'][self.remains] = {
                    '-remains': True,
                    'qty': alloc,
                    'entry': close,
                    'close': close,
                    'side': 'buy'
                }
                self.log(f"{self.remains}: px {close}, {alloc}, val {int(close * alloc * 100) / 100} - remains")
        else:
            self.log(f"{self.long_trend_ticker} trend is negative: {trend_d.iloc[-1]} < {trend_d.iloc[-21 * 6 - 1]}")

        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)

    def to_be_closed(self, end_of_week):
        self.log(f"========= to_be_closed: end_of_week {end_of_week}")
        result = set()  # tickers for positions to be closed
        for ticker, info in self.portfolio.items():
            if ticker != self.remains and info['qty'] > 0:
                d = self.data[ticker]
                if end_of_week:
                    weekly_series = d.close.resample('W').last()
                    #print(weekly_series)
                    rsi = AlphaStrategy.compute_rsi(weekly_series).iloc[-1]
                    if rsi > 80:
                        result.insert(ticker)
                if d.close.iloc[-1] / info['entry'] < 0.9:  # the current price is more than 10% below the entry price
                    result.insert(ticker)
        return result
