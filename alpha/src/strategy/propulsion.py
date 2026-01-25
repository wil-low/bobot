# ivy.py

import copy
from datetime import datetime
#import sqlite3
#import numpy as np
#import pandas as pd
from strategy.base import AllocStrategy


class Propulsion(AllocStrategy):
    # Rebalances daily
    STOP = 0.01

    def __init__(self, logger, key, portfolio, today):
        super().__init__(logger, key, portfolio, today, 150, True)
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
        self.rebalance = True
        if self.rebalance:
            self.log(f"trying to rebalance")

    def floor2(self, val, ticker=None):
        mul = 100
        if ticker is not None and 'JPY' not in ticker:
            mul = 100000
        return int(val * mul) / mul

    def allocate(self, excluded_symbols):
        top = []
        tickers_to_close = self.to_be_closed(excluded_symbols)
        for ticker in self.tickers:
            if ticker in tickers_to_close:
                continue
            d = self.data[ticker]
            d_ema8 = AllocStrategy.compute_ema(d.close, 8)
            d_ema21 = AllocStrategy.compute_ema(d.close, 21)
            if ticker in self.portfolio['tickers']:
                item = self.portfolio['tickers'][ticker]
                print(f"{ticker}: {item}")
                trail_stop = False
                if 'trail_tgt' in item:
                    if item['qty'] > 0:
                        if d.close.iloc[-1] > item['trail_tgt']:
                            del(item['trail_tgt'])
                            self.log(f"{ticker:6s}: trail_tgt reached")
                            trail_stop = True
                    else:
                        if d.close.iloc[-1] < item['trail_tgt']:
                            del(item['trail_tgt'])
                            self.log(f"{ticker:6s}: trail_tgt reached")
                            trail_stop = True
                else:
                    trail_stop = True

                if trail_stop:
                    if item['qty'] > 0:
                        item['stop'] = self.floor2(max(item['stop'], d_ema21.iloc[-1]), ticker)
                    else:
                        item['stop'] = self.floor2(min(item['stop'], d_ema21.iloc[-1]), ticker)

            else:
                weekly_close = d.close.resample('W').last()
                w_ema8 = AllocStrategy.compute_ema(weekly_close, 8)
                w_ema21 = AllocStrategy.compute_ema(weekly_close, 21)
                side = 0  # no order
                entry = self.floor2(d_ema8.iloc[-1], ticker)

                if w_ema8.iloc[-1] > w_ema21.iloc[-1] and d_ema8.iloc[-1] > d_ema21.iloc[-1] and d.close.iloc[-1] > d_ema8.iloc[-1]:
                    side = 1   # long
                elif w_ema8.iloc[-1] < w_ema21.iloc[-1] and d_ema8.iloc[-1] < d_ema21.iloc[-1] and d.close.iloc[-1] < d_ema8.iloc[-1]:
                    side = -1  # short
                
                stop_delta = max(entry * self.STOP, abs(entry - d_ema21.iloc[-1]))
                stop = self.floor2(entry - stop_delta * side, ticker)
                trail_tgt = self.floor2(entry + stop_delta * side, ticker)
                tgt = self.floor2(entry + 2 * stop_delta * side, ticker)

                self.log(f"{ticker:6s}: {d.close.iloc[-1]:9.5f}, ema8 {d_ema8.iloc[-1]:9.5f}, ema21 {d_ema21.iloc[-1]:9.5f}, side {side}")
                top.append({'ticker': ticker, 'side': side, 'entry': entry, 'stop': stop, 'trail_tgt': trail_tgt, 'tgt': tgt})
        
        alloc_cash = self.floor2(self.allocatable) / len(self.tickers)
        print(f"allocatable={self.allocatable}, alloc_cash={alloc_cash}")

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

        for item in top:
            alloc = 0
            if item['side'] != 0:
                entry = item['entry']
                alloc = int(alloc_cash / self.usd_rates[item['ticker']])
                value = self.floor2(entry * alloc)
                alloc *= item['side']
                self.log(f"{item['ticker']}: px {entry}, {alloc}, val {value}")
                new_portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'entry': item['entry'] if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['entry'],
                    'stop': item['stop'] if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['stop'],
                    'trail_tgt': item['trail_tgt'] if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['trail_tgt'],
                    'tgt': item['tgt'] if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['tgt'],
                    'entry_time': self.today_open if item['ticker'] not in self.portfolio['tickers'] else self.portfolio['tickers'][item['ticker']]['entry_time'],
                    'close': entry,
                    'type': 'limit'
                }
        return new_portfolio, self.compute_portfolio_transition(self.portfolio, new_portfolio)

    def get_tickers(self):
        tickers = [
            "EURUSD",
            "USDJPY",
            "EURGBP",
            "AUDNZD",
            "USDCAD",
            "EURCHF"
        ]
        return tickers

    def to_be_closed(self, excluded_symbols):
        result = set()  # tickers for positions to be closed
        for ticker, info in self.portfolio['tickers'].items():
            if ticker not in excluded_symbols:
                d = self.data[ticker]
                self.log(f"to_be_closed {ticker}: stop {info['stop']}, tgt {info['tgt']}, high {d.high.iloc[-1]}, low {d.low.iloc[-1]}")
                if info['qty'] > 0:
                    if info['tgt'] < d.high.iloc[-1]:  # take profit order triggered
                        result.add(ticker)
                    if info['stop'] > d.low.iloc[-1]:  # stop order triggered
                        result.add(ticker)
                else:
                    if info['tgt'] > d.low.iloc[-1]: # take profit order triggered
                        result.add(ticker)
                    if info['stop'] < d.high.iloc[-1]:  # stop order triggered
                        result.add(ticker)
        return result