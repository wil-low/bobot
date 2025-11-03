import json
import os
import time
import requests
from datetime import date, datetime, timedelta, timezone

def tiingo_req(ticker, start_date, end_date, token, fn):
    url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start_date}&format=csv&token={token}"
    print(f"Downloading {ticker} from {url}")
    
    response = requests.get(url)
    if response.status_code != 200 or len(response.content) < 1000:
        print(f"Error downloading {ticker}: {response.text}")
        if os.path.exists(fn):
            os.remove(fn)
        exit(1)
    
    with open(fn, "wb") as f:
        f.write(response.content)

def polygon_daily_req(ticker, start_date, fn):
    url = f"https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/{start_date}?adjusted=true&include_otc=false&apiKey={token}"
    print(f"Downloading daily summary from {url}")
    
    response = requests.get(url)
    if response.status_code != 200 or len(response.content) < 1000:
        print(f"Error downloading {ticker}: {response.text}")
        if os.path.exists(fn):
            os.remove(fn)
        exit(1)
    
    with open(fn, "wb") as f:
        f.write(response.content)

def polygon_req(ticker, start_date, end_date, token, fn):
    url = f"https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}?adjusted=true&sort=asc&apiKey={token}"
    print(f"Downloading {ticker} from {url}")
    
    response = requests.get(url)
    if response.status_code != 200 or len(response.content) < 1000:
        print(f"Error downloading {ticker}: {response.text}")
        if os.path.exists(fn):
            os.remove(fn)
        exit(1)
    js_data = json.loads(response.content)
    print(f"{ticker}: got {js_data['resultsCount']} rows")
    if js_data['resultsCount'] < 21 * 12:
        print(f"Error downloading {ticker}: not enough rows")
        if os.path.exists(fn):
            os.remove(fn)
        exit(1)
    with open(fn, "w") as f:
        f.write("date,close,high,low,open,volume,adjClose,adjHigh,adjLow,adjOpen,adjVolume,divCash,splitFactor\n")
        for j in js_data['results']:
            date = datetime.fromtimestamp(j["t"] / 1000, timezone.utc).strftime('%Y-%m-%d')
            f.write(f"{date},{j['c']},{j['h']},{j['l']},{j['o']},{j['v']},{j['c']},{j['h']},{j['l']},{j['o']},{j['v']},0,1\n")
    time.sleep(13)  # 5 API Calls / Minute

def dl_datasets():
    all_tickers = set()
    for fn in ['ra', 'dt', 'ea', 'mr']:
        with open(f"alpha/cfg/{fn}.txt", "r") as f:
            all_tickers.update([line.strip() for line in f if line.strip()])

    tickers = sorted(list(all_tickers))
    print(tickers)
    print(len(tickers))
    #exit()

    # === Token and date setup ===
    token = os.environ.get("TOKEN")
    if not token:
        raise EnvironmentError("TOKEN environment variable is not set.")

    today = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=396)).strftime("%Y-%m-%d")  # ~13 months

    output_dir = f"alpha/work/{today}/csv"
    os.makedirs(output_dir, exist_ok=True)

    print(f"Start date: {start_date}")

    # === Download loop ===
    for ticker in tickers:
        fn = os.path.join(output_dir, f"{ticker}.csv")
        
        if os.path.exists(fn):
            print(f"{fn} exists")
            continue
        
        #tiingo_req(ticker, start_date, today, token, fn)
        polygon_req(ticker, start_date, today, token, fn)
        #exit()


if __name__ == '__main__':
    dl_datasets()
