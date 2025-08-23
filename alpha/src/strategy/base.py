# alloc.py

import copy
from datetime import datetime
import json
import os
import sqlite3
import numpy as np
import pandas as pd

class AllocStrategy:
    DB_FILE = "work/stock.sqlite"
    ALLOC_PERCENT = 99.5

    def __init__(self, logger, key, portfolio, today, limit=253):
        self.key = key
        self.logger = logger
        self.portfolio = portfolio[key]
        self.leverage = portfolio['leverage']
        self.today = today
        self.rebalance = False

        self.log('')
        self.log(f"========= init =========")

        self.tickers = self.get_tickers()

        conn = sqlite3.connect(AllocStrategy.DB_FILE)
        self.data = {}
        for t in self.tickers:
            try:
                query = f"""
                SELECT *
                FROM (
                    SELECT date, adjClose as close, adjLow as low, adjHigh as high, adjOpen as open
                    FROM prices
                    JOIN tickers ON prices.ticker_id = tickers.id
                    WHERE tickers.symbol = ? AND date < ?
                    ORDER BY date DESC
                    LIMIT ?
                )
                ORDER BY date ASC;
                """
                df = pd.read_sql_query(query, conn, params=(t, today, limit), parse_dates=['date'])
                df.set_index('date', inplace=True)

                if len(df) < limit:
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
                #self.log(self.data[ticker].close.iloc[-10:])
                entry = info['close']
                qty = info['qty']
                #open = self.data[ticker].open.iloc[-1]
                low = self.data[ticker].low.iloc[-1]
                high = self.data[ticker].high.iloc[-1]
                #close = self.data[ticker].close.iloc[-1]
                #self.log(f"{ticker}: check expire: entry {entry}, open {open}, low {low}, high {high}, close {close}")
                if not ((qty > 0 and entry > low) or (qty < 0 and entry < high)):  # not filled
                    value = self.floor2(abs(entry * qty))
                    self.portfolio['cash'] += value
                    del self.portfolio['tickers'][ticker]
                    self.log(f"{ticker}: day order expired")
                else:
                    info['type'] = 'market'
        self.portfolio['cash'] = self.floor2(self.portfolio['cash'])
        # update prices by previous day close
        self.log(f"update prices:")
        equity = self.portfolio['cash']
        for ticker, info in self.portfolio['tickers'].items():
            close = self.data[ticker].close.iloc[-1]
            info['close'] = close
            value = self.floor2(abs(close * info['qty'] / self.leverage))
            equity += value
            self.log(f"   {ticker}: {close} * {info['qty']} = {value}")
        equity = self.floor2(equity)
        self.compute_cash(self.portfolio, equity)
        self.allocatable = self.floor2(self.portfolio['equity'] * self.ALLOC_PERCENT / 100 * self.leverage)  # reserve for fees
        self.log(f"equity={self.portfolio['equity']}, cash={self.portfolio['cash']}, allocatable={self.allocatable}")

    @staticmethod
    def load_tickers(fn):
        with open(fn, "r") as f:
            return [line.strip() for line in f if line.strip() and line[0] != '#']
        return None

    @staticmethod
    def compute_sma(series: pd.Series, period: int = 200) -> pd.Series:
        """
        Compute the Simple Moving Average (SMA) of a given pandas Series.

        Parameters:
            series (pd.Series): Input time series data (e.g., closing prices).
            period (int): The window period for the SMA (default is 200).

        Returns:
            pd.Series: SMA series with NaN for the first (period - 1) entries.
        """
        return series.rolling(window=period).mean()

    @staticmethod
    def compute_rsi(series: pd.Series, period=2) -> pd.Series:
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

    @staticmethod
    def compute_crsi(close: pd.Series, rsi_period=3, updown_len=2, roc_len=100) -> pd.Series:
        # Compute UpDown streaks: +n for consecutive ups, -n for downs, 0 for unchanged
        def compute_updown_streak(series: pd.Series) -> pd.Series:
            streak = [0] * len(series)
            for i in range(1, len(series)):
                if series.iloc[i] > series.iloc[i - 1]:
                    streak[i] = streak[i - 1] + 1 if streak[i - 1] > 0 else 1
                elif series.iloc[i] < series.iloc[i - 1]:
                    streak[i] = streak[i - 1] - 1 if streak[i - 1] < 0 else -1
                else:
                    streak[i] = 0
            return pd.Series(streak, index=series.index)

        # PercentRank over `window` periods
        def percent_rank(series, window):
            return series.rolling(window).apply(
                lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x.dropna()) == window else np.nan,
                raw=False
            )

        # Calculate RSI of close prices
        rsi = AllocStrategy.compute_rsi(close, rsi_period)

        # Calculate UpDown RSI (on streaks)
        updown_streak = compute_updown_streak(close)
        updown_rsi = AllocStrategy.compute_rsi(updown_streak, updown_len)

        # Calculate PercentRank of 1-day ROC
        roc = close.pct_change(periods=1) * 100
        roc_prank = percent_rank(roc, roc_len) * 100

        # Final Connors RSI
        crsi = (rsi + updown_rsi + roc_prank) / 3.0
        return crsi

    @staticmethod
    def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14, use_ema: bool = False) -> pd.Series:
        """
        Calculate the Average True Range (ATR) using only pandas.Series inputs.
        
        Parameters:
            high (pd.Series): High prices
            low (pd.Series): Low prices
            close (pd.Series): Close prices
            period (int): ATR period, usually 14
            use_ema (bool): Use EMA instead of SMA for averaging TR
            
        Returns:
            pd.Series: ATR values
        """
        prev_close = close.shift(1)

        tr1 = (high - low).abs()
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        if use_ema:
            atr = true_range.ewm(span=period, adjust=False).mean()
        else:
            atr = true_range.rolling(window=period).mean()

        return atr

    def floor2(self, val):
        return int(val * 100) / 100

    def print_p(self, portfolio):
        return json.dumps(portfolio, sort_keys=True)
    
    def get_tickers(self):
        return AllocStrategy.load_tickers(f"cfg/{self.key}.txt")

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
                if ticker in new_tickers and new_tickers[ticker]['type'] == 'limit':
                    text += f", using DAY LIMIT order at {new_tickers[ticker]['close']}"
                if self.key == 'mr' and old_qty == 0 and 'stop' in new_tickers[ticker]:
                    text += f", stop {new_tickers[ticker]['stop']}"
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
                if ticker in new_tickers and new_tickers[ticker]['type'] == 'limit':
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

    def error(self, txt):
        if self.logger:
            self.logger.debug('%s: %s' % (self.key, txt))
        print('%s: %s' % (self.key, txt))

    def compute_cash(self, portfolio, prev_equity):
        portfolio['equity'] = prev_equity
        cash = prev_equity
        #print(f"compute_eq: cash {cash}")
        for ticker, info in portfolio['tickers'].items():
            close = info['close']  #self.data[ticker].close.iloc[-1]
            #info['close'] = close
            value = self.floor2(abs(close * info['qty'] / self.leverage))
            cash -= value
            #print(f"compute_eq: {ticker}, {close}, {info['qty']}, {value}")
        #print(f"compute_eq: cash={cash}\n")
        portfolio['cash'] = self.floor2(cash)
        return cash

    def allocate(self, excluded_symbols):
        raise NotImplementedError
    
    def to_be_closed(self):
        return set()  # tickers for positions to be closed
