# connors.py

import copy
from datetime import datetime
import json
import os
import sqlite3
import numpy as np
import pandas as pd
from strategy.base import AllocStrategy


class CRSISP500(AllocStrategy):
    # Rebalances daily
    SLOT_COUNT = 15

    def __init__(self, logger, key, portfolio, today):
        super().__init__(logger, key, portfolio, today, 110)
        self.params = {
            'crsi_setup': 10,  # The stock closes with ConnorsRSI(3, 2, 100) value less than W, where W is 5 or 10
            'percents_setup': 50,  # The stock closing price is in the bottom X % of the day's range, where X = 25, 50, 75 or 100
            'percents_entry': 4,  # If the previous day was a Setup, submit a limit order to buy at a price Y % below yesterday's close, where Y is 2, 4, 6, 8 or 10
            'crsi_exit': 50  # Exit when the stock closes with ConnorsRSI(3, 2, 100) value greater than Z, where W is 50 or 70
        }
        self.remains = self.tickers[-1]

    def allocate(self, excluded_symbols):
        tickers_to_close = self.to_be_closed()
        new_portfolio = copy.deepcopy(self.portfolio)
        top = []
        for ticker in self.tickers:
            if ticker != self.remains and not ticker in tickers_to_close and not ticker in self.portfolio['tickers']:
                try:
                    d = self.data[ticker]
                    #print(f"{ticker} check")
                    day_range = d.high.iloc[-1] - d.low.iloc[-1]
                    bottom_percent = d.low.iloc[-1] + day_range * self.params['percents_setup'] / 100
                    crsi10 = self.compute_crsi(d.close).iloc[-110:]
                    crsi = crsi10.iloc[-1]
                    #self.log(f"{ticker}: crsi {crsi}, {d.close.iloc[-1]} < {bottom_percent}")
                    if crsi < self.params['crsi_setup'] and d.close.iloc[-1] < bottom_percent:
                        #self.log(ticker)
                        #self.log(d.close.iloc[-110:])
                        #self.log(crsi10)
                        #exit()
                        px = self.floor2(d.close.iloc[-1] * (100 - self.params['percents_entry']) / 100)
                        top.append({'ticker': ticker, 'crsi': crsi, 'entry': px})
                except KeyError:
                    pass

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

        free_slots = self.SLOT_COUNT - occupied_slots
        top_sorted = sorted(top, key=lambda x: x['crsi'], reverse=False)[:free_slots]
        free_slots -= len(top_sorted)

        for item in top_sorted:
            alloc = 0
            entry = item['entry']
            alloc = round(alloc_slot / entry, 2)
            if alloc >= 1:
                value = self.floor2(entry * alloc)
                self.log(f"{item['ticker']:5s} px {entry} * {alloc} = {value}, crsi {item['crsi']:.2f}")
                new_portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'close': entry,
                    'type': 'limit'
                }

                #ticker = item['ticker']
                #open = self.data[ticker].open.iloc[-1]
                #low = self.data[ticker].low.iloc[-1]
                #high = self.data[ticker].high.iloc[-1]
                #close = self.data[ticker].close.iloc[-1]
                #self.log(self.data[ticker].close.iloc[-10:])
                #self.log(f"{ticker}: send order: entry {entry}, yesterday: open {open}, low {low}, high {high}, close {close}")
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
            self.log(f"{self.remains:5s} {close} * {alloc} = {value} - remains")
        elif self.remains in new_portfolio['tickers']:
            self.log(f"Close position: {self.remains}")
            del new_portfolio['tickers'][self.remains]

        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)

    def to_be_closed(self):
        result = set()  # tickers for positions to be closed
        for ticker, info in self.portfolio['tickers'].items():
            if ticker != self.remains:
                d = self.data[ticker]
                crsi = AllocStrategy.compute_crsi(d.close).iloc[-1]
                if crsi > self.params['crsi_exit']:
                    self.log(f"close {ticker}: crsi={crsi:.2f}")
                    result.add(ticker)
        return result

    def get_tickers(self):
        # load from DB instead of file
        conn = sqlite3.connect(AllocStrategy.DB_FILE)

        query = f"""
        SELECT t.symbol FROM tickers t
        INNER JOIN sp500 sp ON t.symbol = sp.symbol
        WHERE t.disabled = 0
        ORDER BY t.symbol
        """
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        tickers = [row[0] for row in rows]
        tickers.append('SPYM')  # remains
        return tickers


class TPS(AllocStrategy):
    # Rebalances daily
    SLOT_COUNT = 2

    def __init__(self, logger, key, portfolio, today):
        super().__init__(logger, key, portfolio, today, 202)
        self.params = {
            'long_entry': 25,
            'long_exit': 70,
            'short_entry': 75,
            'short_exit': 30
        }

    def allocate(self, excluded_symbols):
        tickers_to_close = self.to_be_closed()
        self.log(tickers_to_close)
        new_portfolio = copy.deepcopy(self.portfolio)
        top = []
        for ticker in self.tickers:
            try:
                d = self.data[ticker]
                sma = self.compute_sma(d.close, 200)
                rsi = self.compute_rsi(d.close, 2)
                if not ticker in self.portfolio['tickers']:
                    # new ticker
                    if d.close.iloc[-1] > sma.iloc[-1] and rsi.iloc[-2] < self.params['long_entry'] and rsi.iloc[-1] < self.params['long_entry']:
                        # 2 periods below, go long
                        top.append({'ticker': ticker, 'rsi': rsi.iloc[-1], 'side': 'buy', 'lots': 1, 'last_px': d.close.iloc[-1]})
                    elif d.close.iloc[-1] < sma.iloc[-1] and rsi.iloc[-2] > self.params['short_entry'] and rsi.iloc[-1] > self.params['short_entry']:
                        # 2 periods above, go short
                        top.append({'ticker': ticker, 'rsi': rsi.iloc[-1], 'side': 'sell', 'lots': 1, 'last_px': d.close.iloc[-1]})
                else:
                    # existing position
                    if not ticker in tickers_to_close:
                        info = self.portfolio['tickers'][ticker]
                        if (info['qty'] > 0 and d.close.iloc[-1] < info['last_px']) or (info['qty'] < 0 and d.close.iloc[-1] > info['last_px']):
                            lots = info['last_lot']
                            if lots < 4:
                                top.append({'ticker': ticker, 'rsi': rsi.iloc[-1], 'side': 'buy' if info['qty'] > 0 else 'sell', 'lots': lots + 1, 'last_px': d.close.iloc[-1]})
            except KeyError:
                pass

        alloc_slot = self.allocatable / self.SLOT_COUNT
        self.log(f"alloc_slot = {alloc_slot:.2f} per lot")

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
                occupied_slots += 1

        free_slots = self.SLOT_COUNT - occupied_slots
        top_sorted = sorted(top, key=lambda x: abs(x['rsi'] - 50), reverse=True)[:free_slots]
        free_slots -= len(top_sorted)

        for item in top_sorted:
            alloc = 0
            entry = item['last_px']
            lots = item['lots']
            alloc = round(alloc_slot / entry / 10 * lots, 2)
            if alloc >= 1:
                value = self.floor2(entry * alloc)
                if item['side'] == 'sell':
                    alloc = -alloc
                self.log(f"{item['ticker']}: px {entry}, {alloc}, val {value}, rsi {item['rsi']:.2f}, lots {lots}")
                new_portfolio['tickers'][item['ticker']] = {
                    'last_lot': item['lots'],
                    'last_px': entry,
                    'qty': alloc,
                    'close': entry,
                    'type': 'market'
                }
            else:
                free_slots += 1

        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)

    def to_be_closed(self):
        result = set()  # tickers for positions to be closed
        for ticker, info in self.portfolio['tickers'].items():
            d = self.data[ticker]
            rsi = AllocStrategy.compute_rsi(d.close).iloc[-1]
            self.log(f"{ticker}: rsi={rsi:.2f}")
            if info['qty'] > 0 and rsi > self.params['long_exit']:
                result.add(ticker)
            if info['qty'] < 0 and rsi < self.params['short_exit']:
                result.add(ticker)
        return result


class VolPanics(AllocStrategy):
    # Rebalances daily
    SLOT_COUNT = 1

    def __init__(self, logger, key, portfolio, today):
        super().__init__(logger, key, portfolio, today, 202)

    def allocate(self, excluded_symbols):
        tickers_to_close = self.to_be_closed()
        self.log(tickers_to_close)
        new_portfolio = copy.deepcopy(self.portfolio)
        top = []
        for ticker in self.tickers:
            d = self.data[ticker]
            sma = self.compute_sma(d.close, 5)
            rsi = self.compute_rsi(d.close, 4)
            self.log(f"{ticker} close={d.close.iloc[-1]}, sma={sma.iloc[-1]:.2f}, rsi={rsi.iloc[-1]:.2f}")
            if not ticker in self.portfolio['tickers']:
                # new ticker
                if d.close.iloc[-1] > sma.iloc[-1] and rsi.iloc[-1] > 70:
                    top.append({'ticker': ticker, 'rsi': rsi.iloc[-1], 'lots': 1, 'last_px': d.close.iloc[-1]})
            else:
                # existing position
                if not ticker in tickers_to_close:
                    info = self.portfolio['tickers'][ticker]
                    if d.close.iloc[-1] > info['last_px']:
                        lots = info['last_lot']
                        if lots < 4:
                            top.append({'ticker': ticker, 'rsi': rsi.iloc[-1], 'lots': lots + 1, 'last_px': d.close.iloc[-1]})

        alloc_slot = self.allocatable / self.SLOT_COUNT
        self.log(f"alloc_slot = {alloc_slot:.2f} per lot")

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
                occupied_slots += 1

        free_slots = self.SLOT_COUNT - occupied_slots
        top_sorted = sorted(top, key=lambda x: abs(x['rsi'] - 50), reverse=True)[:free_slots]
        free_slots -= len(top_sorted)

        for item in top_sorted:
            alloc = 0
            entry = item['last_px']
            lots = item['lots']
            alloc = round(alloc_slot / entry / 10 * lots, 2)
            if alloc >= 1:
                value = self.floor2(entry * alloc)
                alloc = -alloc
                self.log(f"{item['ticker']}: px {entry}, {alloc}, val {value}, rsi {item['rsi']:.2f}, lots {lots}")
                new_portfolio['tickers'][item['ticker']] = {
                    'last_lot': item['lots'],
                    'last_px': entry,
                    'qty': alloc,
                    'close': entry,
                    'type': 'market'
                }
            else:
                free_slots += 1

        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)

    def to_be_closed(self):
        result = set()  # tickers for positions to be closed
        for ticker, info in self.portfolio['tickers'].items():
            d = self.data[ticker]
            sma = self.compute_sma(d.close, 5)
            if d.close.iloc[-1] < sma.iloc[-1]:
                result.add(ticker)
        return result

    def get_tickers(self):
        return ['VXX']


class MomentumPinball(AllocStrategy):
    # Rebalances daily
    SLOT_COUNT = 1

    def __init__(self, logger, key, portfolio, today):
        super().__init__(logger, key, portfolio, today, 202)

    def allocate(self, excluded_symbols):
        new_portfolio = {'tickers': {}}
        top = []
        for ticker in self.tickers:
            d = self.data[ticker]
            roc = d.close - d.close.shift(1)
            rsi = self.compute_rsi(roc, 3)
            atr = self.compute_atr(d.high, d.low, d.close, 14)
            atr_percent = self.floor2(atr.iloc[-1] / d.close.iloc[-1] * 100)
            self.log(f"{ticker} close={d.close.iloc[-1]}, roc={roc.iloc[-1]:.2f}, rsi={rsi.iloc[-1]:.2f}, atr%={atr_percent:.2f}")
            text = None
            # of the first four bars trading range on 15m TF
            if rsi.iloc[-1] < 30:  # buy setup
                text = "BUY  stop above the 4-bar HIGH"
            elif rsi.iloc[-1] > 70:  # sell setup
                text = "SELL stop below the 4-bar LOW"
            if text is not None:
                top.append({'ticker': ticker, 'close': d.close.iloc[-1], 'rsi': self.floor2(rsi.iloc[-1]), 'atr%': atr_percent, 'text': text})

        top_sorted = sorted(filter(lambda x: x['atr%'] >= 3, top), key=lambda x: x['atr%'], reverse=True)[:5]
        for item in top_sorted:
            t = item['ticker']
            del item['ticker']
            new_portfolio['tickers'][t] = item

        return new_portfolio, None

    def get_tickers(self):
        # load from DB instead of file
        conn = sqlite3.connect(AllocStrategy.DB_FILE)

        query = f"""
        SELECT t.symbol FROM tickers t
        INNER JOIN sp500 sp ON t.symbol = sp.symbol
        WHERE t.disabled = 0
        ORDER BY t.symbol
        """
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        tickers = [row[0] for row in rows]
        return tickers
