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

    def __init__(self, logger, key, portfolio, today, limit=253):
        self.key = key
        self.logger = logger
        self.portfolio = portfolio[key]
        self.leverage = portfolio['leverage']
        self.today = today

        self.log(f"========= init =========")

        self.tickers = self.get_tickers()

        conn = sqlite3.connect(AllocStrategy.DB_FILE)
        self.data = {}
        for t in self.tickers:
            try:
                query = f"""
                SELECT *
                FROM (
                    SELECT date, close, low, high, open
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
        self.portfolio['cash'] = self.floor2(self.portfolio['cash'])
        # update prices by previous day close
        self.log(f"update prices:")
        equity = self.portfolio['cash']
        for ticker, info in self.portfolio['tickers'].items():
            close = self.data[ticker].close.iloc[-1]
            info['close'] = close
            value = self.floor2(abs(close * info['qty'] / self.leverage))
            equity += value
            self.log(f"   {ticker}, {close}, {info['qty']}, {value}")
        equity = self.floor2(equity)
        self.compute_cash(self.portfolio, equity)
        self.allocatable = self.floor2(self.portfolio['equity'] * 0.98 * self.leverage)  # reserve for fees
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

    def allocate(self):
        raise NotImplementedError
    
    def to_be_closed(self):
        return set()  # tickers for positions to be closed


class RisingAssets(AllocStrategy):
    # Rebalances monthly
    def __init__(self, logger, key, portfolio, today):
        super().__init__(logger, key, portfolio, today)
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


class DynamicTreasures(AllocStrategy):
    # Rebalances weekly
    def __init__(self, logger, key, portfolio, today):
        super().__init__(logger, key, portfolio, today)
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


class ETFAvalanches(AllocStrategy):
    # Rebalances daily
    SLOT_COUNT = 5

    def __init__(self, logger, key, portfolio, today):
        super().__init__(logger, key, portfolio, today)
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
                        rsi = AllocStrategy.compute_rsi(d.close).iloc[-10:]
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
                rsi = AllocStrategy.compute_rsi(d.close).iloc[-1]
                if rsi < 15:
                    result.add(ticker)
        return result


class MeanReversion(AllocStrategy):
    # Rebalances weekly, checks stops daily
    SLOT_COUNT = 10
    STOP_SIZE = 5  # percents

    def __init__(self, logger, key, portfolio, today):
        self.long_trend_ticker = 'SPY'
        self.remains = 'SHY'
        super().__init__(logger, key, portfolio, today)
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
                                    rsi = AllocStrategy.compute_rsi(weekly_series).iloc[-1]
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
                    'stop': self.floor2(close * (100 - self.STOP_SIZE) / 100),
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
                'entry': close,
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
                if self.weekday == 0:  # Monday (end of week in fact)
                    weekly_series = d.close.resample('W').last()
                    #print(weekly_series)
                    rsi = AllocStrategy.compute_rsi(weekly_series).iloc[-1]
                    #self.log(f"{ticker}: weekly rsi={rsi}")
                    if rsi > 80:
                        result.add(ticker)
                stop_px = info['entry'] * (100 - self.STOP_SIZE) / 100  # the current price is more than STOP_SIZE% below the entry price
                low = d.low.iloc[-1]
                high = d.high.iloc[-1]
                if low < stop_px:  # stop order triggered
                    result.add(ticker)
        return result

    def get_tickers(self):
        # load from DB instead of file
        conn = sqlite3.connect(AllocStrategy.DB_FILE)

        query = f"""
        SELECT ticker_id, t.symbol
            FROM (
                SELECT ticker_id, AVG(close * volume) AS avg_dollar_volume
                FROM prices
                WHERE date >= DATE(?, 'start of month', '-200 days')
                GROUP BY ticker_id
                ORDER BY avg_dollar_volume DESC
            )  
            JOIN tickers t ON ticker_id = t.id
            WHERE t.type in ('CS', 'ADRC') AND t.disabled = 0
            LIMIT 500
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

    def allocate(self):
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
        top_sorted = sorted(top, key=lambda x: x['crsi'], reverse=False)[:free_slots]
        free_slots -= len(top_sorted)

        for item in top_sorted:
            alloc = 0
            entry = item['entry']
            alloc = round(alloc_slot / entry, 2)
            if alloc >= 1:
                value = self.floor2(entry * alloc)
                self.log(f"{item['ticker']}: px {entry}, {alloc}, val {value}, crsi {item['crsi']}")
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
                crsi = AllocStrategy.compute_crsi(d.close).iloc[-1]
                self.log(f"{ticker}: crsi={crsi}")
                if crsi > self.params['crsi_exit']:
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
        tickers.append('SPY')  # remains
        return tickers


class TPS(AllocStrategy):
    # Rebalances daily
    SLOT_COUNT = 5

    def __init__(self, logger, key, portfolio, today):
        super().__init__(logger, key, portfolio, today, 202)
        self.params = {
            'long_entry': 25,
            'long_exit': 70,
            'short_entry': 75,
            'short_exit': 30
        }

    def allocate(self):
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
        self.log(f"alloc_slot = {alloc_slot} per lot")

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
            self.log(f"{ticker}: rsi={rsi}")
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

    def allocate(self):
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
        self.log(f"alloc_slot = {alloc_slot} per lot")

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
