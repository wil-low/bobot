import os
import sqlite3
import pandas as pd

# Path to directory containing CSV files
DATA_DIR = "alpha/work/2025-05-24/csv"
DB_FILE = "alpha/work/stock.sqlite"

# Connect to SQLite
conn = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
cursor = conn.cursor()

# Create tables
cursor.executescript("""
CREATE TABLE IF NOT EXISTS tickers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT UNIQUE NOT NULL,
    roboforex_sfx TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker_id INTEGER NOT NULL,
    date DATE NOT NULL,
    close REAL,
    high REAL,
    low REAL,
    open REAL,
    volume INTEGER,
    adjClose REAL,
    adjHigh REAL,
    adjLow REAL,
    adjOpen REAL,
    adjVolume INTEGER,
    divCash REAL,
    splitFactor REAL,
    FOREIGN KEY (ticker_id) REFERENCES tickers(id),
    UNIQUE(ticker_id, date)
);

CREATE INDEX idx_prices_covering
ON prices(ticker_id, date, close, volume);

CREATE INDEX idx_prices_date_ticker ON prices(date, ticker_id);
""")
conn.commit()

# Iterate over CSV files
for file in os.listdir(DATA_DIR):
    if not file.endswith(".csv"):
        continue

    ticker = file.replace(".csv", "")
    filepath = os.path.join(DATA_DIR, file)
    print(f"Processing {ticker}...")

    # Insert ticker into database
    cursor.execute("INSERT OR IGNORE INTO tickers (symbol) VALUES (?)", (ticker,))
    conn.commit()

    # Get ticker_id
    cursor.execute("SELECT id FROM tickers WHERE symbol = ?", (ticker,))
    ticker_id = cursor.fetchone()[0]

    # Read CSV
    df = pd.read_csv(filepath, parse_dates=["date"])
    df["ticker_id"] = ticker_id

    # Insert price data
    for _, row in df.iterrows():
        cursor.execute("""
            INSERT OR REPLACE INTO prices (
                ticker_id, date, close, high, low, open, volume,
                adjClose, adjHigh, adjLow, adjOpen, adjVolume, divCash, splitFactor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["ticker_id"], row["date"].strftime("%Y-%m-%d"), row["close"], row["high"], row["low"],
            row["open"], row["volume"], row["adjClose"], row["adjHigh"],
            row["adjLow"], row["adjOpen"], row["adjVolume"], row["divCash"], row["splitFactor"]
        ))

    conn.commit()

print("All data imported successfully.")
conn.close()
