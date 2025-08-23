# hit_and_run.py

import copy
from datetime import datetime
import json
import os
import sqlite3
import numpy as np
import pandas as pd
from strategy.base import AllocStrategy


class HitAndRunBase(AllocStrategy):
    TICKERS = []
    FIRST_RUN = True

    def __init__(self, logger, key, portfolio, today):
        if self.FIRST_RUN:
            self.TICKERS = self.get_ticker_universe()
            self.remains = self.TICKERS[-1]
        super().__init__(logger, key, portfolio, today, 70)
        if self.FIRST_RUN:
            tset = self.tickers.copy()
            for ticker in tset:
                if ticker != self.remains:
                    d = self.data[ticker]
                    adx, plus_di, minus_di = self.compute_adx(d.high, d.low, d.close, 14)
                    #self.log(f"{ticker} check: adx={adx.iloc[-1]:.2f}")
                    if adx.iloc[-1] < 30:
                        #self.log(f"{ticker} removed: adx={adx.iloc[-1]:.2f}")
                        self.tickers.remove(ticker)
                    #else:
                    #    self.log(f"{ticker} added: adx={adx.iloc[-1]:.2f}")
            self.FIRST_RUN = False

    @staticmethod
    def get_ticker_universe():
        # load from DB instead of file
        conn = sqlite3.connect(AllocStrategy.DB_FILE)

        query = f"""
        SELECT 
            t.symbol
        FROM (
            SELECT ticker_id, 
                   AVG(close * volume) AS avg_dollar_volume,
                   (SELECT close 
                    FROM prices p2 
                    WHERE p2.ticker_id = p1.ticker_id
                    ORDER BY date DESC 
                    LIMIT 1) AS last_close
            FROM prices p1
            WHERE date >= DATE('now', 'start of month', '-200 days')
              AND ticker_id IN (
                  SELECT id 
                  FROM tickers
                  WHERE type IN ('CS', 'ADRC') 
                    AND disabled=0
              )
            GROUP BY ticker_id
        ) AS p
        JOIN tickers t ON t.id = p.ticker_id
        WHERE p.last_close > 20
          AND p.avg_dollar_volume < 500000
        ORDER BY p.avg_dollar_volume DESC
        """

        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        tickers = [row[0] for row in rows]
        tickers.append('SPLG')  # remains
        return tickers
    
    def get_tickers(self):
        return self.TICKERS

class ExpansionBreakout(HitAndRunBase):
    # Rebalances daily
    SLOT_COUNT = 5

    def allocate(self, excluded_symbols):
        tickers_to_close = self.to_be_closed()
        new_portfolio = copy.deepcopy(self.portfolio)
        top = []
        for ticker in self.tickers:
            if ticker != self.remains and not ticker in tickers_to_close and not ticker in excluded_symbols and not ticker in self.portfolio['tickers']:
                try:
                    d = self.data[ticker]

                    direction = 0
                    
                    if d.high.iloc[-1] >= d.high.rolling(window=60, min_periods=1).max().iloc[-1]:
                        # today is 2 month high
                        direction = 1
                        self.log(f"{ticker} 2 month high")
                    elif d.low.iloc[-1] <= d.low.rolling(window=60, min_periods=1).min().iloc[-1]:
                        # today is 2 month low
                        direction = -1
                        self.log(f"{ticker} 2 month low")
                    
                    if direction == 0:
                        continue

                    # largest daily range for previous 9 days
                    day_range = d.high - d.low
                    max_range_9d = day_range.rolling(window=9, min_periods=1).max()

                    if day_range.iloc[-1] < max_range_9d.iloc[-1]:
                        continue
                    self.log(f"{ticker} largest daily range")

                    print(f"{ticker} check, close {d.close.iloc[-1]}, low {d.low.iloc[-1]}, high {d.high.iloc[-1]}")

                    if direction == 1:
                        px = self.floor2(d.high.iloc[-1] + 0.1)
                        stop_px = self.floor2(d.close.iloc[-1] - 1)
                    else:
                        px = self.floor2(d.low.iloc[-1] - 0.1)
                        stop_px = self.floor2(d.close.iloc[-1] + 1)
                    top.append({'ticker': ticker, 'stop': stop_px, 'entry': px, 'direction': direction})
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
        top_sorted = top[:free_slots]
        free_slots -= len(top_sorted)

        for item in top_sorted:
            alloc = 0
            entry = item['entry']
            alloc = round(alloc_slot / entry, 2)
            if alloc >= 1:
                if item['direction'] == -1:
                    alloc = -alloc
                value = self.floor2(entry * alloc)
                self.log(f"{item['ticker']:5s} px {entry} * {alloc} = {value}")
                new_portfolio['tickers'][item['ticker']] = {
                    'qty': alloc,
                    'entry': entry,
                    'close': entry,
                    'stop': item['stop'],
                    'type': 'stop'
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
                'entry': close if self.remains not in self.portfolio['tickers'] else self.portfolio['tickers'][self.remains]['entry'],
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
                qty = info['qty']
                d = self.data[ticker]
                px_diff = (info['close'] - info['entry']) * (1 if qty > 0 else -1)
                if px_diff > 2:
                    # take profit
                    self.log(f"close {ticker}: px_diff={px_diff:.2f}")
                    result.add(ticker)
                else:
                    # stop loss
                    stop_px = info['stop']
                    low = d.low.iloc[-1]
                    high = d.high.iloc[-1]
                    if (qty > 0 and stop_px > low) or (qty < 0 and stop_px < high):  # stop order triggered
                        self.log(f"close {ticker}: stopped qty {qty} low {low}, high {high}, stop {stop_px}")
                        result.add(ticker)
        return result
