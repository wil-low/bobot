# tiingo_ohlc.py

import csv
from datetime import datetime, timedelta, timezone
import os
import sys
import time

import requests

def ohlc2csv(token):
    symbol = sys.argv[1]
    start_time = sys.argv[2]
    end_time = sys.argv[3]

    year = start_time[:4]

    print(f"{symbol}, start from {start_time} to {end_time}")

    try:
        with open(f"datasets/tiingo/{symbol}_M1{year}.csv", "r", newline="") as csvfile:
            reader = csv.reader(csvfile, delimiter=';')
            formatted = None
            for item in reader:
                formatted = item[0]
            print(formatted)

        start_time = datetime.strptime(formatted, "%Y%m%d %H%M%S")
        print(f"last file time: {start_time}")
        start_time += timedelta(seconds=60)
        start_time = start_time.strftime('%Y-%m-%dT%H:%M:%S')
        print(f"new file start_time={start_time}")
    except FileNotFoundError:
        pass

    while start_time < end_time:
        url = f"https://api.tiingo.com/tiingo/crypto/prices?tickers={symbol.lower()}&startDate={start_time}&endDate={end_time}&resampleFreq=1min&token={token}"
        print(url)
        response = requests.get(url)
        data = response.json()
        if 'detail' in data:
            print(f"symbol {symbol} error: {data}")
            exit()
        candles = data[0]["priceData"]
        print(repr(candles[-1]))
        start_time = datetime.strptime(candles[-1]['date'], "%Y-%m-%dT%H:%M:%S+00:00")
        print(f"last time: {start_time}")
        start_time += timedelta(seconds=60)
        start_time = start_time.strftime('%Y-%m-%dT%H:%M:%S')
        print(f"new start_time={start_time}")
        
        with open(f"datasets/tiingo/{symbol}_M1{year}.csv", "a", newline="") as csvfile:
            writer = csv.writer(csvfile, delimiter=';')
            
            for candle in candles:
                ts = candle['date']
                open_ = candle['open']
                high = candle['high']
                low = candle['low']
                close = candle['close']
                volume = candle['volume']

                # Convert timestamp to "YYYYMMDD HHMMSS"
                date_part, time_part = ts.split('T')
                time_part = time_part.split('+')[0]  # remove timezone
                formatted = date_part.replace('-', '') + ' ' + time_part.replace(':', '')

                writer.writerow([formatted, open_, high, low, close, volume])
        time.sleep(1)



if __name__ == '__main__':
    token = os.getenv('API_TOKEN')
    ohlc2csv(token)
