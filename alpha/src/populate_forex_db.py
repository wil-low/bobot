import os
import sqlite3
import pandas as pd

DB_FILE = "alpha/work/forex.sqlite"

# Connect to SQLite
conn = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
cursor = conn.cursor()

# Create tables
cursor.executescript("""
CREATE TABLE IF NOT EXISTS "tickers" (
	"id"	INTEGER,
	"symbol"	TEXT NOT NULL UNIQUE,
	"disabled"	INTEGER NOT NULL DEFAULT 0,
	PRIMARY KEY("id" AUTOINCREMENT)
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
    trans_count INTEGER,
    FOREIGN KEY (ticker_id) REFERENCES tickers(id),
    UNIQUE(ticker_id, date)
);

CREATE INDEX idx_prices_covering
ON prices(ticker_id, date, close, volume);

CREATE INDEX idx_prices_date_ticker ON prices(date, ticker_id);
""")
conn.commit()

PAIRS = [
    'EURUSD',
    'USDJPY',
    'EURGBP',
    'AUDNZD',
    'USDCAD',
    'EURCHF',
    'GBPJPY',
    'GBPUSD',
    'AUDUSD',
    'USDCHF',
    'NZDUSD'
]

# Iterate over CSV files
for ticker in PAIRS:
    print(f"Processing {ticker}...")

    # Insert ticker into database
    cursor.execute("INSERT OR IGNORE INTO tickers (symbol) VALUES (?)", (ticker,))
    conn.commit()

print("All data imported successfully.")
conn.close()
