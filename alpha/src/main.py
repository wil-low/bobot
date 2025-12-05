# main.py

import argparse
from datetime import datetime, timedelta
import json
import os
import sys
import time
import glob
import importlib
import sqlite3
from strategy.base import AllocStrategy
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
    balance = 0
    margin = 0
    free_margin = 0
    upnl = 0
    p['summary'] = {}
    for key in keys:
        if key in p:
            s = p[key]['summary']
            equity += s['equity']
            balance += s['balance']
            margin += s['margin']
            free_margin += s['free_margin']
            upnl += s['upnl']
    s = p['summary']
    s['equity'] = floor2(equity)
    s['balance'] = floor2(balance)
    s['margin'] = floor2(margin)
    s['free_margin'] = floor2(free_margin)
    s['upnl'] = floor2(upnl)

def save_portfolio(p, fn):
    logger.info(f"Saving portfolio to {fn}")
    with open(fn, 'w') as f:
        json.dump(p, f, indent=4, sort_keys=True)

def print_summary(p, keys):
    # load ticker descriptions from DB
    conn = sqlite3.connect(AllocStrategy.DB_FILE)

    query = f"""
    SELECT t.symbol, t.type, t.name FROM tickers t
    WHERE t.disabled = 0
    ORDER BY t.symbol
    """
    cursor = conn.cursor()
    cursor.execute(query)
    rows = cursor.fetchall()
    names = {}
    for row in rows:
        names[row[0]] = (row[1], row[2])

    logger.info("Portfolio summary:")
    s = p['summary']
    summary_qty = {}
    summary_value = {}
    for key in keys:
        if key in p:
            for t, data in p[key]['tickers'].items():
                summary_qty[t] = summary_qty.get(t, 0) + data['qty'];
                summary_value[t] = summary_value.get(t, 0) + data['qty'] * data['close'];
    for t in sorted(summary_qty.keys()):
        logger.info(f"  {'-' if summary_qty[t] < 0 else ' '} {t:6s}= {abs(summary_qty[t]):6.2f}  {(abs(summary_value[t]) / s['equity'] * 100):6.2f}%   {names[t][0]:4s}  {names[t][1]}")
    logger.info('')
    logger.info(f"Totals: balance {s['balance']}, equity {s['equity']}, margin {s['margin']} ({floor2(s['equity'] / s['margin'] * 100)}%), free_margin {s['free_margin']}, upnl {s['upnl']}")
    for key in keys:
        logger.info(f"    {key}: {floor2(p[key]['summary']['equity'] / p['summary']['equity'] * 100)}%")

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

def alpha_alloc(config, today, action, excluded_symbols):
    work_dir = f"work/portfolio/{config['subdir']}"
    if today is None:
        # find latest portfolio json
        path = sorted(glob.glob(f"{work_dir}/[0-9]*.json"))[-1]
        print(path)
        filename = os.path.basename(path)
        today = os.path.splitext(filename)[0]
    elif today == 'today':
        today = datetime.now().strftime('%Y-%m-%d')
    d = datetime.strptime(today, '%Y-%m-%d')
    print(f"Alpha Formula System start: {today}, weekday={d.weekday()}")
    logger.info(f"Alpha Formula System start: {today}, weekday={d.weekday()}")

    latest_date = today

    if action == 'sync':
        # don't skip weekends, always use the latest portfolio from the past
        path = sorted(glob.glob(f"{work_dir}/[0-9]*.json"), reverse=True)
        for fn in path:
            print(fn)
            filename = os.path.basename(fn)
            fn_date = os.path.splitext(filename)[0]
            if fn_date <= today:
                latest_date = fn_date
                break
    elif d.weekday() >= 5:
        print(f"{today} is a weekend")
        logger.warning(f"{today} is a weekend")
        today = next_working_day(today)
        alpha_alloc(config, today, action, excluded_symbols)
        return

    os.makedirs(work_dir, exist_ok=True)
    portfolio = None

    keys = [item['key'] for item in config['strategy']]

    AllocStrategy.leverage = config['leverage']

    if action == 'sync':
        # we assume tickers are correctly assigned to keys
        with open(f"{work_dir}/{latest_date}.json") as f:
            portfolio = json.load(f)
            #print(self.portfolio)

        logger.info(f"Getting portfolio for date {latest_date} from broker {config['broker']}")
        # get portfolio from broker
        broker = RStockTrader(config['auth'])
        print(broker.positions)
        action = {
            "date": today,
            "summary": {
                #"balance": broker.getcash(),
                #"equity": broker.getvalue()
            }
        }
        for item in config['strategy']:
            action[item['key']] = {
                'tickers': {},
                'summary': {}
            }

        # scan all keys and update tickers
        for key in keys:
            s = action[key]['summary']
            for ticker, info in portfolio[key]['tickers'].items():
                p = broker.positions.get(ticker, None)
                prefix = "%2s - %-6s" % (key, ticker)
                if p is None:
                    if info['type'] == 'limit' or info['type'] == 'stop':
                        # limit day order was not filled
                        #s['cash'] += floor2(info['qty'] * info['close'])
                        logger.info(f"{prefix}: REMOVE limit order")
                        continue
                else:
                    action[key]['tickers'][ticker] = info
                    if ticker != 'JPST':
                        action[key]['tickers'][ticker]['qty'] = p['qty']
                    if action[key]['tickers'][ticker]['close'] != p['close']:
                        action[key]['tickers'][ticker]['close'] = p['close']
                        logger.info(f"{prefix}: update CLOSE, qty {action[key]['tickers'][ticker]['qty']}")
                    if action[key]['tickers'][ticker].get('entry', None) != p['entry']:
                        action[key]['tickers'][ticker]['entry'] = p['entry']
                        logger.info(f"{prefix}: update ENTRY")
                    action[key]['tickers'][ticker]['entry_time'] = p['entry_time']
            s['margin'] = 0
            s['upnl'] = 0
            for ticker, info in action[key]['tickers'].items():
                s['margin'] += abs(info['qty']) * info['entry']
                s['upnl'] += (info['close'] - info['entry']) * info['qty']
            s['margin'] = floor2(s['margin'])
            s['upnl'] = floor2(s['upnl'])

        save_portfolio(action, f"{work_dir}/sync.json")
        # rebalance by adjusting balances
        total_equity = broker.getvalue()
        for item in config['strategy']:
            s = action[item['key']]['summary']
            s['equity'] = floor2(total_equity * item['percent'] / 100)
            s['balance'] = floor2(s['equity'] - s['upnl'])
            s['free_margin'] = floor2(s['equity'] - s['margin'])
        action['text'] = f"Synched at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        compute_totals(action, keys)
        fn = f"{work_dir}/{today}_sync.json"
        with open(fn, 'w') as f:
            json.dump(action, f, indent=4, sort_keys=True)
        print_summary(action, keys)
        logger.info(f"Portfolio written to {fn}")
        return

    else:
        try:
            if action == 'next':
                logger.info(f"Reading portfolio from {work_dir}/{today}.json")
                with open(f"{work_dir}/{today}.json") as f:
                    portfolio = json.load(f)
                    #print(portfolio)
            else:
                raise FileNotFoundError('start')
        except FileNotFoundError:
            balance = config['initial_balance']
            logger.debug(f"Starting with empty portfolio: {balance}")
            portfolio = {
                'date': today,
                'summary': {
                    'balance': balance,
                    'equity': balance,
                    'margin': 0,
                    'free_margin': balance,
                    'upnl': 0
                }
            }
            for item in config['strategy']:
                item_balance = floor2(balance * item['percent'] / 100)
                portfolio[item['key']] = {
                    'tickers': {},
                    'summary': {
                        'balance': item_balance,
                        'equity': item_balance,
                        'margin': 0,
                        'free_margin': balance,
                        'upnl': 0
                    }
                }
            compute_totals(portfolio, keys)
            save_portfolio(portfolio, f"{work_dir}/{today}.json")

    new_portfolio = {
        "transitions": {}
    }
 
    for item in config['strategy']:
        args = (logger, item['key'], portfolio.copy(), today)
        module = importlib.import_module(f"strategy.{item['module']}")
        strategy_cls = getattr(module, item['class'])
        s = strategy_cls(*args)
        new_portfolio[s.key], trans = s.allocate(excluded_symbols)
        if trans:
            new_portfolio["transitions"][s.key] = trans

    if new_portfolio["transitions"]:
        new_portfolio["transitions"]['text'] = f"Execute transitions at open {today}"
        print(new_portfolio["transitions"])
    else:
        print(f"{today}: no transitions")

    if config.get('compute_totals', True):
        compute_totals(new_portfolio, keys)
        print_summary(new_portfolio, keys)

    next_date_str = next_working_day(today)
    new_portfolio['date'] = next_date_str
    save_portfolio(new_portfolio, f"{work_dir}/{next_date_str}.json")

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", required=True, help='config file name')
    parser.add_argument("--date", "-d", help="date in format YYYY-MM-DD, or 'today'")
    parser.add_argument("--action", "-a", required=True, choices=['sync', 'start', 'next'], help="sync positions with broker, start empty or calculate next day")
    parser.add_argument("--exclude", "-x", required=False, help="temporarily exclude symbols (comma-separated) - for MeanReversion only")
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

    excluded_symbols = [] if args.exclude is None else args.exclude.split(',')

    #if args.action == 'sync':
    #    today = 'today'
    alpha_alloc(config, today, args.action, excluded_symbols)
