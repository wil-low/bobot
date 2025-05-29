# alloc.py

import copy
from datetime import datetime
import json
import os
import sqlite3
import numpy as np
import pandas as pd

class AlphaStrategy:
    DB_FILE = "work/stock.sqlite"

    def __init__(self, logger, key, portfolio, today):
        self.key = key
        self.logger = logger
        self.portfolio = portfolio

        self.log(f"========= init =========")
        conn = sqlite3.connect(AlphaStrategy.DB_FILE)

        self.tickers = []
        if self.key == 'mr':
            # load from DB instead of file
            query = f"""
            SELECT ticker_id, t.symbol
                FROM (
                    SELECT ticker_id, AVG(close * volume) AS avg_dollar_volume
                    FROM prices
                    WHERE date >= DATE(?, '-200 days')
                    GROUP BY ticker_id
                    ORDER BY avg_dollar_volume DESC
                )  
                JOIN tickers t ON ticker_id = t.id
                WHERE t.type='CS' AND t.disabled = 0
                LIMIT 500
            """
            cursor = conn.cursor()
            cursor.execute(query, (today,))
            rows = cursor.fetchall()
            self.tickers = [row[1] for row in rows] + ['SPY', 'SHY']  # long trend and remains
        else:
            self.tickers = AlphaStrategy.load_tickers(f"cfg/{key}.txt")

        self.data = {}
        for t in self.tickers:
            try:
                query = f"""
                SELECT *
                FROM (
                    SELECT date, close, low, high
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

                if len(df) < 21 * 12 + 1:
                    self.log(f"{t} not enough rows in DB ({len(df)})")
                    continue
                self.data[t] = df
            except FileNotFoundError:
                pass
        conn.close()

        # expire Day Limit orders
        for ticker in list(self.portfolio['tickers'].keys()):
            info = self.portfolio['tickers'][ticker]
            if info['type'] == 'limit':
                entry = info['close']
                qty = info['qty']
                low = self.data[ticker].low.iloc[-1]
                high = self.data[ticker].high.iloc[-1]
                if not ((qty > 0 and entry > low) or (qty < 0 and entry < high)):  # not filled
                    value = self.floor2(entry * qty)
                    self.portfolio['cash'] += value
                    del self.portfolio['tickers'][ticker]
                    self.log(f"{ticker}: day order expired")
        self.portfolio['cash'] = self.floor2(self.portfolio['cash'])
        # update prices by previous day close
        self.log(f"update prices:")
        equity = self.portfolio['cash']
        for ticker, info in self.portfolio['tickers'].items():
            close = self.data[ticker].close.iloc[-1]
            info['close'] = close
            value = self.floor2(close * info['qty'])
            equity += value
            self.log(f"   {ticker}, {close}, {info['qty']}, {value}")
        equity = self.floor2(equity)
        self.compute_cash(self.portfolio, equity)
        self.allocatable = self.floor2(portfolio['equity'] * 0.98)  # reserve for fees
        self.log(f"equity={self.portfolio['equity']}, cash={self.portfolio['cash']}, allocatable={self.allocatable}")

    @staticmethod
    def load_tickers(fn):
        with open(fn, "r") as f:
            return [line.strip() for line in f if line.strip() and line[0] != '#']
        return None

    @staticmethod
    def load_all_tickers_from_db():
        conn = sqlite3.connect(AlphaStrategy.DB_FILE)
        query = f"""
        SELECT id, symbol FROM tickers ORDER BY symbol
        """
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        return [row[1] for row in rows]

    @staticmethod
    def compute_rsi(series, period=2):
        delta = series.diff()

        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)

        gain_series = pd.Series(gain, index=series.index)
        loss_series = pd.Series(loss, index=series.index)

        avg_gain = gain_series.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_loss = loss_series.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def floor2(self, val):
        return int(val * 100) / 100

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

            diff = round(new_qty - old_qty, 2)
            if diff > 0:
                text = f'Buy {diff} of {ticker}, change from {old_qty} to {new_qty}'
                if self.key == 'mr' and old_qty == 0:
                    text += ', record entry price'
                adds.append({
                    'ticker': ticker,
                    'action': 'buy',
                    'qty': diff,
                    'text': text
                })
                #print(ticker, self.data[ticker].close.iloc[-1], diff, 'new_cash increased', new_portfolio['cash'])
            elif diff < 0:
                diff = abs(diff)
                text = f'Sell {diff} of {ticker}, change from {old_qty} to {new_qty}'
                if self.key == 'ea' and old_qty == 0:
                    text += f", using DAY LIMIT order at {new_tickers[ticker]['close']}"
                removes.append({
                    'ticker': ticker,
                    'action': 'sell',
                    'qty': diff,
                    'text': text
                })
                #print(ticker, self.data[ticker].close.iloc[-1], diff, 'new_cash reduced', new_portfolio['cash'])
            # If equal, no action needed

        self.compute_cash(new_portfolio, old_portfolio['equity'])
        self.log(f"old_p: {self.print_p(old_portfolio)}")
        self.log(f"new_p: {self.print_p(new_portfolio)}")
        return removes + adds

    def log(self, txt):
        if self.logger:
            self.logger.debug('%s: %s' % (self.key, txt))
        else:
            print('%s: %s' % (self.key, txt))

    def compute_cash(self, portfolio, prev_equity):
        portfolio['equity'] = prev_equity
        cash = prev_equity
        #print(f"compute_eq: cash {cash}")
        for ticker, info in portfolio['tickers'].items():
            close = info['close']  #self.data[ticker].close.iloc[-1]
            #info['close'] = close
            value = self.floor2(close * info['qty'])
            cash -= value
            #print(f"compute_eq: {ticker}, {close}, {info['qty']}, {value}")
        #print(f"compute_eq: cash={cash}\n")
        portfolio['cash'] = self.floor2(cash)
        return cash

    def allocate(self):
        raise NotImplementedError
    
    def to_be_closed(self):
        return set()  # tickers for positions to be closed


class RisingAssets(AlphaStrategy):
    # Rebalances monthly
    def __init__(self, logger, portfolio, today):
        super().__init__(logger, 'ra', portfolio['ra'], today)
        self.reinvest = False
        if len(self.portfolio['tickers']) == 0:
            self.reinvest = True
        else:
            # first_working_day of month
            today_date = datetime.strptime(today, '%Y-%m-%d')
            day = 1
            while True:
                d = datetime(today_date.year, today_date.month, day)
                if d.weekday() < 5:  # 0=Monday, ..., 4=Friday
                    self.reinvest = day == today_date.day
                    break
                day += 1

    def allocate(self):
        if self.reinvest:
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
                    alloc = int(alloc)
                value = self.floor2(close * alloc)
                self.log(f"{item['ticker']}: px {close}, {alloc}, val {value}")  #, calculated {calc_alloc}")
                if alloc >= 1:
                    new_portfolio['tickers'][item['ticker']] = {
                        'qty': alloc,
                        'close': close,
                        'type': 'market'
                    }
        else:
            new_portfolio = copy.deepcopy(self.portfolio)
        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)


class DynamicTreasures(AlphaStrategy):
    # Rebalances weekly
    def __init__(self, logger, portfolio, today):
        super().__init__(logger, 'dt', portfolio['dt'], today)
        self.remains = self.tickers[-1]
        self.reinvest = False
        if len(self.portfolio['tickers']) == 0:
            self.reinvest = True
        else:
            self.reinvest = datetime.strptime(today, '%Y-%m-%d').weekday() == 0

    def allocate(self):
        if self.reinvest:
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
                    alloc = int(alloc_cash / close)
                    if alloc >= 1:
                        value = self.floor2(close * alloc)
                        remains_alloc -= value
                        self.log(f"{item['ticker']}: px {close}, {alloc}, val {value}")
                        new_portfolio['tickers'][item['ticker']] = {
                            'qty': alloc,
                            'close': close,
                            'type': 'market'
                        }

            # remains alloc
            close = self.data[self.remains].close.iloc[-1]
            alloc = int(remains_alloc / close)
            if alloc >= 1:
                new_portfolio['tickers'][self.remains] = {
                    '-remains': True,
                    'qty': alloc,
                    'close': close,
                    'type': 'market'
                }
                value = self.floor2(close * alloc)
                self.log(f"{self.remains}: px {close}, {alloc}, val {value} - remains")
        else:
            new_portfolio = copy.deepcopy(self.portfolio)
        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)


class ETFAvalanches(AlphaStrategy):
    # Rebalances daily
    SLOT_COUNT = 5

    def __init__(self, logger, portfolio, today):
        super().__init__(logger, 'ea', portfolio['ea'], today)
        self.remains = self.tickers[-1]

    def allocate(self):
        top = []
        tickers_to_close = self.to_be_closed()
        for ticker in self.tickers:
            if ticker != self.remains and not ticker in tickers_to_close and not ticker in self.portfolio['tickers']:
                d = self.data[ticker]
                if d.close.iloc[-1] < d.close.iloc[-21 * 12 - 1]:  # negative total return over the past year
                    #print(f"{ticker}: negative total return over the past year")
                    if d.close.iloc[-1] < d.close.iloc[-21 * 1 - 1]:  # negative total return over the past month
                        #print(f"{ticker}: negative total return over the past month")
                        #print(f"{ticker}: d.close {d.close.iloc[-10:]}")
                        rsi = AlphaStrategy.compute_rsi(d.close).iloc[-10:]
                        #print(f"{ticker}: rsi {rsi}")
                        if rsi.iloc[-1] > 70:
                            #print(f"{ticker}: rsi {rsi}")
                            entry = self.floor2(d.close.iloc[-1] * 1.03)  # put a sell limit order 3.0% above the current price
                            daily_return = d.close / d.close.shift(1)
                            volatility = daily_return.rolling(window=100).std()
                            top.append({'ticker': ticker, 'entry': entry, 'volatility': volatility.iloc[-1]})

        alloc_slot = self.allocatable / self.SLOT_COUNT
        self.log(f"alloc_slot = {alloc_slot}")

        new_portfolio = copy.deepcopy(self.portfolio)
        if len(tickers_to_close) > 0:
            self.log(f"Close positions: {tickers_to_close}")

        occupied_slots = 0
        # remove closed tickers
        for ticker in list(new_portfolio['tickers'].keys()):
            info = new_portfolio['tickers'][ticker]
            if ticker in tickers_to_close:
                del new_portfolio['tickers'][ticker]
            else:
                if ticker != self.remains:
                    occupied_slots += 1

        free_slots = self.SLOT_COUNT - occupied_slots
        top_sorted = sorted(top, key=lambda x: x['volatility'], reverse=True)[:free_slots]
        free_slots -= len(top_sorted)

        for item in top_sorted:
            alloc = 0
            entry = item['entry']
            alloc = int(alloc_slot / entry)
            if alloc >= 1:
                alloc = -alloc
                value = self.floor2(entry * alloc)
                self.log(f"{item['ticker']}: px {entry}, {alloc}, val {value}")
                new_portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'close': entry,
                    'type': 'limit'
                }
            else:
                free_slots += 1
        # remains alloc
        close = self.data[self.remains].close.iloc[-1]
        alloc = int(alloc_slot * free_slots / close)
        if alloc >= 1:
            close = self.data[self.remains].close.iloc[-1]
            value = self.floor2(close * alloc)
            new_portfolio['tickers'][self.remains] = {
                '-remains': True,
                'qty': alloc,
                'close': close,
                'type': 'market'
            }
            self.log(f"{self.remains}: px {close}, {alloc}, val {value} - remains")
        elif self.remains in new_portfolio['tickers']:
            self.log(f"Close position: {self.remains}")
            del new_portfolio['tickers'][self.remains]

        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)

    def to_be_closed(self):
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
    # Rebalances weekly, checks stops daily
    SLOT_COUNT = 10

    def __init__(self, logger, portfolio, today):
        super().__init__(logger, 'mr', portfolio['mr'], today)
        self.long_trend_ticker = self.tickers[-2]
        self.remains = self.tickers[-1]
        self.weekday = datetime.strptime(today, '%Y-%m-%d').weekday()
        self.reinvest = False
        if len(self.portfolio['tickers']) == 0:
            self.reinvest = True
        else:
            self.reinvest = self.weekday == 0

    def allocate(self):
        trend_d = self.data[self.long_trend_ticker].close
        tickers_to_close = self.to_be_closed()
        new_portfolio = copy.deepcopy(self.portfolio)
        top = []
        if self.reinvest:  # These rules are checked at the end of the business week
            if trend_d.iloc[-1] > trend_d.iloc[-21 * 6 - 1]:  # SPY’s total return over the last six months (126 trading days) is positive
                self.log(f"{self.long_trend_ticker} trend is positive: {trend_d.iloc[-1]} > {trend_d.iloc[-21 * 6 - 1]}")
                for ticker in self.tickers:
                    if ticker != self.remains and ticker != self.long_trend_ticker and not ticker in tickers_to_close and not ticker in self.portfolio['tickers']:
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
            else:
                self.log(f"{self.long_trend_ticker} trend is negative: {trend_d.iloc[-1]} < {trend_d.iloc[-21 * 6 - 1]}")

        alloc_slot = self.allocatable / self.SLOT_COUNT
        self.log(f"alloc_slot = {alloc_slot}")

        new_portfolio = copy.deepcopy(self.portfolio)
        if len(tickers_to_close) > 0:
            self.log(f"Close positions: {tickers_to_close}")

        occupied_slots = 0
        # remove closed tickers
        for ticker in list(new_portfolio['tickers'].keys()):
            info = new_portfolio['tickers'][ticker]
            if ticker in tickers_to_close:
                del new_portfolio['tickers'][ticker]
            else:
                if ticker != self.remains:
                    occupied_slots += 1

        free_slots = self.SLOT_COUNT - occupied_slots
        top_sorted = sorted(top, key=lambda x: x['volatility'], reverse=False)[:free_slots]
        free_slots -= len(top_sorted)

        for item in top_sorted:
            close = self.data[item['ticker']].close.iloc[-1]
            alloc = int(alloc_slot / close)
            value = self.floor2(close * alloc)
            self.log(f"{item['ticker']}: px {close}, {alloc}, val {value}")
            if alloc >= 1:
                new_portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'entry': close,
                    'close': close,
                    'type': 'market'
                }
            else:
                free_slots += 1
        # remains alloc
        close = self.data[self.remains].close.iloc[-1]
        alloc = int(alloc_slot * free_slots / close)
        if alloc >= 1:
            close = self.data[self.remains].close.iloc[-1]
            value = self.floor2(close * alloc)
            new_portfolio['tickers'][self.remains] = {
                '-remains': True,
                'qty': alloc,
                'close': close,
                'type': 'market'
            }
            self.log(f"{self.remains}: px {close}, {alloc}, val {value} - remains")
        elif self.remains in new_portfolio['tickers']:
            self.log(f"Close position: {self.remains}")
            del new_portfolio['tickers'][self.remains]

        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)

    def to_be_closed(self):
        result = set()  # tickers for positions to be closed
        for ticker, info in self.portfolio['tickers'].items():
            if ticker != self.remains and info['qty'] > 0:
                d = self.data[ticker]
                if self.weekday == 0:  # Monday (end of week in fact)
                    weekly_series = d.close.resample('W').last()
                    #print(weekly_series)
                    rsi = AlphaStrategy.compute_rsi(weekly_series).iloc[-1]
                    #self.log(f"{ticker}: weekly rsi={rsi}")
                    if rsi > 80:
                        result.add(ticker)
                if info['close'] / info['entry'] < 0.95:  # the current price is more than 10% below the entry price
                    result.add(ticker)
        return result
