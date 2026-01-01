# ivy.py

import copy
from datetime import datetime
#import sqlite3
#import numpy as np
#import pandas as pd
from strategy.base import AllocStrategy


class Ivy(AllocStrategy):
    # Rebalances monthly
    SLOT_COUNT = 10

    def __init__(self, logger, key, portfolio, today):
        self.remains = 'CLIP'  # 1-3 Month T-Bill ETF
        super().__init__(logger, key, portfolio, today)
        print(self.portfolio)
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
                if ticker != self.remains:
                    d = self.data[ticker]
                    series = d.close.resample('M').last()
                    #print(series)
                    sma = AllocStrategy.compute_sma(series, 10)
                    score = 10 if d.close.iloc[-1] > sma.iloc[-1] else 0  # % allocation
                    self.log(f"{ticker:5s}: score={score:2d}, {d.close.iloc[-1]:.2f} > {sma.iloc[-1]:.2f}")
                    top.append({'ticker': ticker, 'score': score})
            
            new_portfolio = {'tickers': {}}
            remains_alloc = self.allocatable
            for item in top:
                alloc = 0
                if item['score'] > 0:
                    close = self.data[item['ticker']].close.iloc[-1]
                    alloc_cash = self.floor2(self.allocatable * item['score'] / 100)
                    alloc = self.floor2(alloc_cash / close)
                    cur_qty = 0
                    if item['ticker'] in self.portfolio['tickers']:
                        cur_qty = self.portfolio['tickers'][item['ticker']]['qty']
                    if abs(alloc - cur_qty) < 1:
                        alloc = cur_qty
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

            # remains alloc
            close = self.data[self.remains].close.iloc[-1]
            alloc = self.floor2(remains_alloc / close)
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

    def get_tickers(self):
        tickers = [
            "VTI",
            "VB",
            "VEU",
            "VWO",
            "BND",
            "TIP",
            "VNQ",
            "RWX",
            "PDBC",
            "COMT"
        ]
        tickers.append(self.remains)
        return tickers
