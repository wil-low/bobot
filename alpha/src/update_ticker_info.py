import json
import os
import sqlite3
import sys
import time
import requests

def update_ticker_info(conn, ticker, token):
    url = f"https://api.massive.com/v3/reference/tickers/{ticker}"
    print(f"Downloading ticker info from {url}")

    response = requests.get(f"{url}?apiKey={token}")
    if response.status_code != 200:
        print(f"Error downloading: {response.text}")
        js_data = json.loads(response.content)
        if js_data['status'] == 'NOT_FOUND':
            cursor = conn.cursor()
            cursor.execute("UPDATE tickers SET disabled = 4 WHERE symbol = ?", (ticker,))
            conn.commit()
        else:
            exit(1)
        return

    js_data = json.loads(response.content)
    count = 0
    if js_data['status'] == 'OK':
        r = js_data['results']
        print(r)
        if not r['active']:
            raise LogicError(f"{ticker} is not active")
        cursor = conn.cursor()
        cursor.execute("UPDATE tickers SET sic_code = ?, sic_description = ?, description = ? WHERE symbol = ?",
            (r.get('sic_code', None), r.get('sic_description', None), r.get('description', 'No description'), ticker))
        conn.commit()


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
    cursor.execute("SELECT id, symbol, type, description FROM tickers where disabled <> 4")
    ids = {symbol: (ticker_id, type, description) for ticker_id, symbol, type, description in cursor.fetchall()}
    print(f"{len(ids)} tickers loaded")

    for ticker in ids:
        print(f"{ticker} ({ids[ticker][1]}) -> {ids[ticker][2]}")
        if ids[ticker][2] is None and ids[ticker][1] not in ['ETF', 'ETV', 'ETN']:
            update_ticker_info(conn, ticker, token)
            time.sleep(13)  # 5 API Calls / Minute
    conn.close()
