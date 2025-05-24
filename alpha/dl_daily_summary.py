import json
import os
import sqlite3
import time
import requests
from datetime import datetime, timedelta, timezone

def dl_daily_summary(conn, ids, token, start_date):
    url = f"https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{start_date}?adjusted=true&include_otc=false&apiKey={token}"
    print(f"Downloading daily summary from {url}")

    response = requests.get(url)
    if response.status_code != 200:
        print(f"Error downloading {start_date}: {response.text}")
        exit(1)

    js_data = json.loads(response.content)

    if js_data['resultsCount'] > 0:
        cursor = conn.cursor()
        count = 0
        # Insert price data
        for row in js_data['results']:
            id = ids.get(row['T'], None)
            if id:
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
        print(f"Added {count} rows for {start_date}")
    else:
        print(f"No rows for {start_date}")

    time.sleep(13)  # 5 API Calls / Minute

if __name__ == '__main__':
    DB_FILE = "alpha/work/stock.sqlite"

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

    start_date = datetime.now()
    end_date = start_date
    
    #start_date = datetime.strptime('2023-12-20', '%Y-%m-%d')
    #end_date = datetime.strptime('2023-01-01', '%Y-%m-%d')

    current = start_date
    while current >= end_date:
        date_str = current.strftime('%Y-%m-%d')
        if current.weekday() < 5:  # 0 = Monday, 6 = Sunday → skip Saturday (5), Sunday (6)
            print(date_str)
            dl_daily_summary(conn, ids, token, date_str)
        else:
            print(f"Skip weekend {date_str}")
        current -= timedelta(days=1)
        #break

    print("All data imported successfully.")
    conn.close()

