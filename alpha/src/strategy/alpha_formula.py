# alloc.py

import copy
from datetime import datetime
import json
import os
import sqlite3
import numpy as np
import pandas as pd
from strategy.base import AllocStrategy


class RisingAssets(AllocStrategy):
    # Rebalances monthly
    def __init__(self, logger, key, portfolio, today):
        super().__init__(logger, key, portfolio, today)
        if len(self.portfolio['tickers']) == 0:
            self.rebalance = True
        else:
            # first_working_day of month
            today_date = datetime.strptime(today, '%Y-%m-%d')
            day = 1
            while True:
                d = datetime(today_date.year, today_date.month, day)
                if d.weekday() < 5:  # 0=Monday, ..., 4=Friday
                    self.rebalance = day == today_date.day
                    break
                day += 1
        if self.rebalance:
            self.log(f"trying to rebalance")

    def allocate(self, excluded_symbols):
        if self.rebalance:
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
                self.log(f"{ticker}: score={score:.2f}, rev_vol={rev_vol:.2f}")
                top.append({'ticker': ticker, 'score': score, 'rev_vol': rev_vol})
            
            new_portfolio = {'tickers': {}}
            vol_sum = 0
            top_sorted = sorted(top, key=lambda x: x['score'], reverse=True)[:5]
            for item in top_sorted:
                #print(f"{item['ticker']}: {item['rev_vol']:.2f}, {item['score']:.2f}")
                vol_sum += item['rev_vol']

            for item in top_sorted:
                close = self.data[item['ticker']].close.iloc[-1]
                alloc_perc = item['rev_vol'] / vol_sum
                alloc_cash = self.allocatable * alloc_perc
                alloc = round(alloc_cash / close)
                if alloc >= 1:
                    value = self.floor2(close * alloc)
                    self.log(f"{item['ticker']}: px {close}, {alloc}, val {value} ({alloc_perc * 100:.2f}%)")
                    new_portfolio['tickers'][item['ticker']] = {
                        'qty': alloc,
                        'entry': close if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['entry'],
                        'entry_time': self.today_open if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['entry_time'],
                        'close': close,
                        'type': 'market'
                    }
                else:
                    self.error(f"{item['ticker']} doesn't fit into alloc ({alloc})")
        else:
            new_portfolio = copy.deepcopy(self.portfolio)
        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)


class DynamicTreasures(AllocStrategy):
    # Rebalances weekly
    def __init__(self, logger, key, portfolio, today):
        self.remains ='SCHR'
        super().__init__(logger, key, portfolio, today)
        if len(self.portfolio['tickers']) == 0:
            self.rebalance = True
        else:
            self.rebalance = datetime.strptime(today, '%Y-%m-%d').weekday() == 0
        if self.rebalance:
            self.log(f"trying to rebalance")

    def get_tickers(self):
        tickers = super().get_tickers()
        for t in self.portfolio['tickers']:
            if t not in tickers:
                tickers.append(t)
        if self.remains not in tickers:
            tickers.append(self.remains)
        return tickers

    def allocate(self, excluded_symbols):
        if self.rebalance:
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
                    self.log(f"{ticker}: score={score}")
                    top.append({'ticker': ticker, 'score': score})
            
            new_portfolio = {'tickers': {}}
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
                            'entry': close if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['entry'],
                            'entry_time': self.today_open if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['entry_time'],
                            'close': close,
                            'type': 'market'
                        }
                    else:
                        self.error(f"{item['ticker']} doesn't fit into alloc ({alloc})")

            # remains alloc
            close = self.data[self.remains].close.iloc[-1]
            alloc = int(remains_alloc / close)
            if alloc >= 1:
                new_portfolio['tickers'][self.remains] = {
                    '-remains': True,
                    'qty': alloc,
                    'entry': close if self.remains not in self.portfolio['tickers'] else self.portfolio['tickers'][self.remains]['entry'],
                    'entry_time': self.today_open if self.remains not in self.portfolio['tickers'] else self.portfolio['tickers'][self.remains]['entry_time'],
                    'close': close,
                    'type': 'market'
                }
                value = self.floor2(close * alloc)
                self.log(f"{self.remains}: px {close}, {alloc}, val {value} - remains")
        else:
            new_portfolio = copy.deepcopy(self.portfolio)
        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)


class ETFAvalanches(AllocStrategy):
    # Rebalances daily
    SLOT_COUNT = 5
    ENTRY_DELTA = 1.5  # put a sell limit order ENTRY_DELTA% above the current price
    RSI_EXIT = 15

    def __init__(self, logger, key, portfolio, today):
        self.remains = 'SCHO'
        super().__init__(logger, key, portfolio, today)
        self.log(f"trying to rebalance")

    def get_tickers(self):
        tickers = super().get_tickers()
        for t in self.portfolio['tickers']:
            if t not in tickers:
                tickers.append(t)
        if self.remains not in tickers:
            tickers.append(self.remains)
        return tickers

    def allocate(self, excluded_symbols):
        top = []
        tickers_to_close = self.to_be_closed()
        for ticker in self.tickers:
            if ticker != self.remains and not ticker in tickers_to_close and not ticker in self.portfolio['tickers']:
                d = self.data[ticker]
                if d.close.iloc[-1] < d.close.iloc[-21 * 12 - 1]:  # negative total return over the past year
                    self.log(f"{ticker}: -year")
                    if d.close.iloc[-1] < d.close.iloc[-21 * 1 - 1]:  # negative total return over the past month
                        self.log(f"{ticker}: -month")
                        #print(f"{ticker}: d.close {d.close.iloc[-10:]}")
                        rsi = AllocStrategy.compute_rsi(d.close).iloc[-10:]
                        self.log(f"{ticker}: rsi check {rsi.iloc[-1]:.2f}, close {d.close.iloc[-1]}")
                        if rsi.iloc[-1] > 70:
                            #self.log(f"{ticker}: rsi {rsi.iloc[-1]}")
                            threshold = self.floor2(d.close.iloc[-1] * (1 + self.ENTRY_DELTA * 2 / 100))  # make sure we are not too close to exit condition
                            if d.close.iloc[-21 * 1 - 1] > threshold:
                                entry = self.floor2(d.close.iloc[-1] * (1 + self.ENTRY_DELTA / 100))
                                daily_return = d.close / d.close.shift(1)
                                volatility = daily_return.rolling(window=100).std()
                                top.append({'ticker': ticker, 'entry': entry, 'close': d.close.iloc[-1], 'stop': d.close.iloc[-21 * 1 - 1], 'rsi': rsi.iloc[-1], 'volatility': volatility.iloc[-1]})
                            else:
                                self.log(f"{ticker}: below threshold")

        alloc_slot = self.allocatable / self.SLOT_COUNT
        self.log(f"alloc_slot = {alloc_slot:.2f}")

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

        top = sorted(top, key=lambda x: x['volatility'], reverse=True)
        self.log(f"Top candidates:")
        for item in top:
            self.log(f"   {item['ticker']:5s} vol={item['volatility']:.5f}, rsi={item['rsi']:.2f}, px={item['close']:.2f}     {self.data[item['ticker']].index[-1].strftime("%Y-%m-%d")}")

        free_slots = self.SLOT_COUNT - occupied_slots
        top_sorted = top[:free_slots]
        free_slots -= len(top_sorted)

        for item in top_sorted:
            alloc = 0
            entry = item['entry']
            alloc = self.floor2(alloc_slot / entry)
            if alloc >= 1:
                alloc = -alloc
                value = self.floor2(entry * alloc)
                self.log(f"{item['ticker']}: px {entry}, {alloc}, val {value}")
                new_portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'entry': entry if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['entry'],
                    'entry_time': self.today_open if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['entry_time'],
                    'close': entry,
                    'stop': item['stop'],
                    'type': 'limit'
                }
            else:
                self.error(f"{item['ticker']} doesn't fit into alloc ({alloc})")
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
                'entry': close if self.remains not in self.portfolio['tickers'] else self.portfolio['tickers'][self.remains]['entry'],
                'entry_time': self.today_open if self.remains not in self.portfolio['tickers'] else self.portfolio['tickers'][self.remains]['entry_time'],
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
                    self.log(f"{ticker}: +month - to be closed")
                    result.add(ticker)
                else:
                    rsi = AllocStrategy.compute_rsi(d.close).iloc[-1]
                    if rsi < self.RSI_EXIT:
                        self.log(f"{ticker}: rsi {rsi} - to be closed")
                        result.add(ticker)
                if 'stop' in info:
                    stop_px = info['stop']
                    low = d.low.iloc[-1]
                    high = d.high.iloc[-1]
                    #self.log(f"{ticker}: checking stop {stop_px} vs high {high}, low {low}")
                    if high > stop_px:  # stop order triggered
                        result.add(ticker)
        return result


class MeanReversion(AllocStrategy):
    # Rebalances weekly, checks stops daily
    SLOT_COUNT = 10
    STOP_SIZE = 5  # percents
    RSI_ENTRY = 20
    RSI_EXIT = 70
    TTL_DAYS = 42  # close position after TTL_DAYS

    TTL_SECS = TTL_DAYS * 24 * 60 * 60

    def __init__(self, logger, key, portfolio, today):
        self.long_trend_ticker = 'SPYM'
        self.remains = 'SCHO'
        super().__init__(logger, key, portfolio, today)
        self.weekday = datetime.strptime(today, '%Y-%m-%d').weekday()
        if len(self.portfolio['tickers']) == 0:
            self.rebalance = True
        else:
            self.rebalance = self.weekday == 0
        if self.rebalance:
            self.log(f"trying to rebalance")

    def allocate(self, excluded_symbols):
        trend_d = self.data[self.long_trend_ticker].close
        tickers_to_close = self.to_be_closed(excluded_symbols)
        new_portfolio = copy.deepcopy(self.portfolio)
        top = []
        if self.rebalance:  # These rules are checked at the end of the business week
            if trend_d.iloc[-1] > trend_d.iloc[-21 * 6 - 1]:  # SPY’s total return over the last six months (126 trading days) is positive
                self.log(f"{self.long_trend_ticker} trend is positive: {trend_d.iloc[-1]} > {trend_d.iloc[-21 * 6 - 1]}")
                for ticker in self.tickers:
                    if ticker != self.remains and ticker != self.long_trend_ticker and not ticker in tickers_to_close and not ticker in self.portfolio['tickers'] and not ticker in excluded_symbols:
                        try:
                            d = self.data[ticker]
                            close_now = d.close.iloc[-1]
                            close_year = d.close.iloc[-21 * 12 - 1]
                            close_month = d.close.iloc[-21 * 1 - 1]
                            #self.log(f"{ticker} check: {close_now}, year {close_year}, month {close_month}")
                            weekly_series = d.close.resample('W').last()
                            #print(weekly_series)
                            rsi = AllocStrategy.compute_rsi(weekly_series).iloc[-1]
                            #self.log(f"{ticker} passed, rsi {rsi}")
                            if rsi < self.RSI_ENTRY:  # The Weekly 2-period RSI of the stock is below 20
                                if close_month / close_now > 1.5:
                                    self.error(f"{ticker}: {close_now}, year {close_year}, month {close_month} - significant price drop, check for splits or fraud!")
                                daily_return = d.close / d.close.shift(1)
                                volatility = daily_return.rolling(window=100).std()
                                #self.log(f"append {ticker}: rsi {rsi:.2f}, volatility {volatility.iloc[-1]:.5f}")
                                top.append({'ticker': ticker, 'close': close_now, 'rsi': rsi, 'volatility': volatility.iloc[-1]})
                        except KeyError:
                            pass
            else:
                self.log(f"{self.long_trend_ticker} trend is negative: {trend_d.iloc[-1]} < {trend_d.iloc[-21 * 6 - 1]}")

        alloc_slot = self.allocatable / self.SLOT_COUNT
        self.log(f"alloc_slot = {alloc_slot:.2f}")

        new_portfolio = copy.deepcopy(self.portfolio)
        if len(tickers_to_close) > 0:
            self.log(f"Close positions: {tickers_to_close}")

        free_value = self.allocatable
        occupied_slots = 0
        # remove closed tickers
        for ticker in list(new_portfolio['tickers'].keys()):
            if ticker in tickers_to_close:
                del new_portfolio['tickers'][ticker]
            else:
                if ticker != self.remains:
                    occupied_slots += 1
                    info = new_portfolio['tickers'][ticker]
                    free_value -= info['close'] * info['qty']

        top = sorted(top, key=lambda x: x['volatility'], reverse=False)

        self.log(f"Excluded_symbols: {excluded_symbols}")

        exclude_str = ''
        exclude_count = 50

        self.log(f"Top candidates:")
        for item in top:
            self.log(f"   {item['ticker']:5s} vol {item['volatility']:.5f}, rsi {item['rsi']:5.2f}, px {item['close']:6.2f}     {self.data[item['ticker']].index[-1].strftime("%Y-%m-%d")}")
            if exclude_count > 0:
                exclude_str += f"{item['ticker']},"
                exclude_count -= 1
        self.log(f"--exclude {exclude_str}")

        free_slots = self.SLOT_COUNT - occupied_slots
        top_sorted = top[:free_slots]
        free_slots -= len(top_sorted)

        for item in top_sorted:
            close = self.data[item['ticker']].close.iloc[-1]
            alloc = self.floor2(alloc_slot / close)
            value = self.floor2(close * alloc)
            self.log(f"{item['ticker']}: px {close}, {alloc}, val {value}")
            if alloc >= 1:
                new_portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'entry': close if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['entry'],
                    'entry_time': self.today_open if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['entry_time'],
                    'close': close,
                    'stop': self.floor2(close * (100 - self.STOP_SIZE) / 100),
                    'type': 'market'
                }
                free_value -= value
            else:
                self.error(f"{ticker} doesn't fit into alloc ({alloc})")
                free_slots += 1
        # remains alloc
        close = self.data[self.remains].close.iloc[-1]
        #self.log(f"free_value {self.floor2(free_value)}, close {close}")
        alloc = int(free_value / close)
        if alloc >= 1:
            close = self.data[self.remains].close.iloc[-1]
            value = self.floor2(close * alloc)
            new_portfolio['tickers'][self.remains] = {
                '-remains': True,
                'qty': alloc,
                'entry': close if self.remains not in self.portfolio['tickers'] else self.portfolio['tickers'][self.remains]['entry'],
                'entry_time': self.today_open if self.remains not in self.portfolio['tickers'] else self.portfolio['tickers'][self.remains]['entry_time'],
                'close': close,
                'type': 'market'
            }
            self.log(f"{self.remains}: px {close}, {alloc}, val {value} - remains")
        elif self.remains in new_portfolio['tickers']:
            self.log(f"Close position: {self.remains}")
            del new_portfolio['tickers'][self.remains]

        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)

    def to_be_closed(self, excluded_symbols):
        result = set()  # tickers for positions to be closed
        for ticker, info in self.portfolio['tickers'].items():
            if ticker != self.remains and ticker not in excluded_symbols:
                d = self.data[ticker]
                if self.weekday == 0:  # Monday (end of week in fact)
                    weekly_series = d.close.resample('W').last()
                    #print(weekly_series)
                    rsi = AllocStrategy.compute_rsi(weekly_series).iloc[-1]
                    self.log(f"{ticker}: weekly rsi={rsi:.2f}")
                    if rsi > self.RSI_EXIT:
                        result.add(ticker)
                    else:
                        if self.today_open - info['entry_time'] >= self.TTL_SECS:
                            self.log(f"{ticker}: TTL expired")
                            result.add(ticker)
                stop_px = info['stop']
                low = d.low.iloc[-1]
                high = d.high.iloc[-1]
                #self.log(f"{ticker}: checking stop {stop_px} vs high {high}, low {low}")
                if low < stop_px:  # stop order triggered
                    result.add(ticker)
        return result

    def get_tickers(self):
        # load from DB instead of file
        conn = sqlite3.connect(AllocStrategy.DB_FILE)

        query = f"""
        SELECT p.ticker_id, t.symbol
        FROM (
            SELECT ticker_id, AVG(adjClose * adjVolume) AS avg_dollar_volume
            FROM prices
            WHERE date >= DATE(?, 'start of month', '-200 days')
              AND ticker_id IN (
                  SELECT id 
                  FROM tickers
                  WHERE type in ('CS', 'ADRC') AND disabled=0
              )
            GROUP BY ticker_id
        ) AS p
        JOIN tickers t ON t.id = p.ticker_id
        ORDER BY p.avg_dollar_volume DESC
        LIMIT 500;
        """
        cursor = conn.cursor()
        cursor.execute(query, (self.today,))
        rows = cursor.fetchall()
        tickers = [row[1] for row in rows]
        # add existing positions that could be pushed out of top 500
        for t in self.portfolio['tickers']:
            if t not in tickers and t != self.remains:
                tickers.append(t)
        tickers += [self.long_trend_ticker, self.remains]  # long trend and remains
        return tickers
