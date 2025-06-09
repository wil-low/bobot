# main.py

import argparse
from datetime import datetime, timedelta
import json
import os
import sys
import time
import importlib
from loguru import logger  # pip install loguru

from broker import RStockTrader

def write_tickers(tickers, fn):
    with open(fn, "w") as f:
        for t in tickers:
            f.write(f"{t}\n")

def floor2(val):
    return int(val * 100) / 100

def compute_totals(p, keys):
    equity = 0
    cash = 0
    for key in keys:
        if key in p:
            equity += p[key]['equity']
            cash += p[key]['cash']
    p['equity'] = floor2(equity)
    p['cash'] = floor2(cash)

def save_portfolio(p, fn):
    with open(fn, 'w') as f:
        json.dump(p, f, indent=4, sort_keys=True)

def next_working_day(today):
    next_date_str = None
    current = datetime.strptime(today, '%Y-%m-%d')
    while True:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0 = Monday, 6 = Sunday → skip Saturday (5), Sunday (6)
            next_date_str = current.strftime('%Y-%m-%d')
            print(f"Next working day is {next_date_str}")
            logger.info(f"Next working day is {next_date_str}")
            break
    return next_date_str

def alpha_alloc(config, today, sync):
    d = datetime.strptime(today, '%Y-%m-%d')
    logger.info(f"Alpha System start: {today}, weekday={d.weekday()}")

    if d.weekday() >= 5:
        print(f"{today} is a weekend, exiting")
        logger.error(f"{today} is a weekend, exiting")
        next_working_day(today)
        exit(1)

    work_dir = f"work/portfolio/{config['subdir']}"
    os.makedirs(work_dir, exist_ok=True)
    portfolio = None

    keys = [item['key'] for item in config['strategy']]

    if sync:
        # we assume tickers are correctly assigned to keys
        with open(f"{work_dir}/{today}.json") as f:
            portfolio = json.load(f)
            #print(self.portfolio)

        logger.info(f"Getting portfolio from broker {config['broker']}")
        # get portfolio from broker
        broker = RStockTrader(config['auth'])
        print(broker.positions)
        sync = {
            "cash": broker.getcash(),
            "equity": broker.getvalue(),
            "leverage": config['leverage']
        }
        for item in config['strategy']:
            sync[item['key']] = {
                'tickers': {},
                'cash': 0,
                'equity': 0
            }

        # scan all keys and update tickers
        for key in keys:
            sync[key]['cash'] = portfolio[key]['cash']
            sync[key]['equity'] = portfolio[key]['equity']
            for ticker, info in portfolio[key]['tickers'].items():
                p = broker.positions.get(ticker, None)
                prefix = "%2s - %-6s" % (key, ticker)
                if p is None and info['type'] == 'limit':
                    # limit day order was not filled
                    sync[key]['cash'] += floor2(info['qty'] * info['close'])
                    logger.info(f"{prefix}: REMOVE limit order")
                    continue
                sync[key]['tickers'][ticker] = info
                if sync[key]['tickers'][ticker]['close'] != p['close']:
                    sync[key]['tickers'][ticker]['close'] = p['close']
                    logger.info(f"{prefix}: update CLOSE price")
                if key == 'mr':
                    #logger.info(f"{prefix}: check {ticker}")
                    if sync[key]['tickers'][ticker]['entry'] != p['entry']:
                        sync[key]['tickers'][ticker]['entry'] = p['entry']
                        logger.info(f"{prefix}: update ENTRY price")

        #compute_totals(sync, keys)
        fn = f"{work_dir}/sync_{today}.json"
        with open(fn, 'w') as f:
            json.dump(sync, f, indent=4, sort_keys=True)

        logger.info(f"Portfolio written to {fn}")
        return

    else:
        try:
            with open(f"{work_dir}/{today}.json") as f:
                portfolio = json.load(f)
                #print(self.portfolio)
        except FileNotFoundError:
            cash = config['initial_cash']
            logger.debug(f"Starting with empty portfolio: {cash}")
            portfolio = {
                'date': today,
                'cash': cash,
                'equity': cash,
                'leverage': config['leverage']
            }
            for item in config['strategy']:
                item_cash = floor2(cash * item['percent'] / 100)
                portfolio[item['key']] = {
                    'tickers': {},
                    'cash': item_cash,
                    'equity': item_cash
                }
            compute_totals(portfolio, keys)
            save_portfolio(portfolio, f"{work_dir}/{today}.json")

    new_portfolio = {
        "transitions": {},
        "cash": 0,
        "leverage": config['leverage']
    }
 
    module = importlib.import_module("alloc")

    for item in config['strategy']:
        args = (logger, item['key'], portfolio.copy(), today)
        strategy_cls = getattr(module, item['class'])
        s = strategy_cls(*args)
        new_portfolio[s.key], trans = s.allocate()
        if trans:
            new_portfolio["transitions"][s.key] = trans

    if new_portfolio["transitions"]:
        new_portfolio["transitions"]['text'] = f"Execute transitions at open {today}"

    #logger.info('new_portfolio: ' + json.dumps(new_portfolio, indent=4, sort_keys=True))
    compute_totals(new_portfolio, keys)
    logger.info(f"NEW TOTALS: equity={new_portfolio['equity']}, cash={new_portfolio['cash']}")
    for key in keys:
        logger.info(f"    {key}: {floor2(new_portfolio[key]['equity'] / new_portfolio['equity'] * 100)}%")

    next_date_str = next_working_day(today)
    new_portfolio['date'] = next_date_str
    save_portfolio(new_portfolio, f"{work_dir}/{next_date_str}.json")


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", required=True, help='config file name')
    parser.add_argument("--date", "-d", required=True, help='date in format YYYY-MM-DD')
    parser.add_argument("--action", "-a", required=True, choices=['sync', 'next'], help="sync positions with broker or calculate next day")
    args = parser.parse_args()

    config = {}
    with open(args.config) as f:
        config = json.load(f)
        #print(config)

    today = args.date

    logger.remove()
    #logger.add(sys.stderr,
    #    format = '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>')
    #    #filter = lambda record: record['extra'] is {})
    tm = time.localtime()
    logger.add('log/%s/%04d%02d%02d.log' % (config['subdir'], tm.tm_year, tm.tm_mon, tm.tm_mday),
            format = '{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}')

    logger.debug("")
    logger.debug("")

    alpha_alloc(config, today, args.action == 'sync')
