import json
import os
import sqlite3
import sys
import time
import requests
from datetime import datetime, timedelta, timezone

def dl_daily_summary(conn, ids, token, start_date):
    url = f"https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/{start_date}?adjusted=true&include_otc=false"
    print(f"Downloading daily summary from {url}")

    response = requests.get(f"{url}&apiKey={token}")
    if response.status_code != 200:
        print(f"Error downloading {start_date}: {response.text}")
        exit(1)

    js_data = json.loads(response.content)

    count = 0
    if js_data['resultsCount'] > 0:
        cursor = conn.cursor()
        # Insert price data
        for row in js_data['results']:
            ticker = row['T']
            id = ids.get(ticker, None)
            if id is None:
                continue
                # Insert ticker into database
                cursor.execute("INSERT OR IGNORE INTO tickers (symbol) VALUES (?)", (ticker,))
                conn.commit()

                # Get ticker_id
                cursor.execute("SELECT id FROM tickers WHERE symbol = ?", (ticker,))
                id = cursor.fetchone()[0]
                ids[ticker] = id
                print(f"New ticker {id}: {ticker}")

            date = datetime.fromtimestamp(row["t"] / 1000, timezone.utc).strftime('%Y-%m-%d')
            cursor.execute("""
                INSERT OR REPLACE INTO prices (
                    ticker_id, date, close, high, low, open, volume,
                    adjClose, adjHigh, adjLow, adjOpen, adjVolume, divCash, splitFactor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                id, date, row["c"], row["h"], row["l"],
                row["o"], row["v"], row["c"], row["h"],
                row["l"], row["o"], row["v"], 0, 1
            ))
            count += 1
        conn.commit()
        print(f"Added/replaced {count} rows for {start_date}")
    else:
        print(f"No rows for {start_date}")

    return count

def load_ticker_info():
    url = f"https://api.massive.com/v3/reference/tickers?market=stocks&active=true&order=asc&limit=1000&sort=ticker"
    while True:
        print(f"Downloading ticker info from {url}")

        response = requests.get(f"{url}&apiKey={token}")
        if response.status_code != 200:
            print(f"Error downloading: {response.text}")
            exit(1)

        js_data = json.loads(response.content)

        count = 0
        if js_data['count'] > 0:
            cursor = conn.cursor()
            # Insert price data
            for row in js_data['results']:
                ticker = row['ticker']
                id = ids.get(ticker, None)
                if id:
                    cursor.execute("UPDATE tickers SET name = ?, type = ? WHERE symbol = ?", (row['name'], row['type'], ticker))
        conn.commit()
        if 'next_url' in js_data:
            url = js_data['next_url']
            time.sleep(13)  # 5 API Calls / Minute
        else:
            break


if __name__ == '__main__':
    DB_FILE = "work/stock.sqlite"

    # === Token and date setup ===
    token = os.environ.get("TOKEN")
    if not token:
        raise EnvironmentError("TOKEN environment variable is not set.")

    # Connect to SQLite
    conn = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    cursor = conn.cursor()

    # Get ticker_id's
    cursor.execute("SELECT id, symbol FROM tickers")
    ids = {symbol: ticker_id for ticker_id, symbol in cursor.fetchall()}
    print(f"{len(ids)} tickers loaded")

    #load_ticker_info()
    #exit()

    if len(sys.argv) > 2:
        start_date = datetime.strptime(sys.argv[1], '%Y-%m-%d')
        end_date = datetime.strptime(sys.argv[2], '%Y-%m-%d')

        current = start_date
        while current >= end_date:
            date_str = current.strftime('%Y-%m-%d')
            if current.weekday() < 5:  # 0 = Monday, 6 = Sunday → skip Saturday (5), Sunday (6)
                print(f"Download for {date_str}")
                dl_daily_summary(conn, ids, token, date_str)
                time.sleep(13)  # 5 API Calls / Minute
            else:
                print(f"Skip weekend {date_str}")
            current -= timedelta(days=1)
            #break
    else:
        # download last working day before today
        current = datetime.now()
        while True:
            current -= timedelta(days=1)
            date_str = current.strftime('%Y-%m-%d')
            if current.weekday() < 5:  # 0 = Monday, 6 = Sunday → skip Saturday (5), Sunday (6)
                print(f"Download for {date_str}")
                if dl_daily_summary(conn, ids, token, date_str) > 0:
                    break
                time.sleep(13)  # 5 API Calls / Minute
            else:
                print(f"Skip weekend {date_str}")

    conn.close()
