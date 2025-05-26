# main.py

from datetime import datetime, timedelta
import json
import sys
import time
from loguru import logger  # pip install loguru

from broker import RStockTrader
from alloc import AlphaStrategy, DynamicTreasures, ETFAvalanches, MeanReversion, RisingAssets

def write_tickers(tickers, fn):
    with open(fn, "w") as f:
        for t in tickers:
            f.write(f"{t}\n")

def compute_equity(p):
    equity = p['cash']
    for key in ['ra', 'dt', 'ea', 'mr']:
        if key in p:
            for ticker, info in p[key]['tickers'].items():
                equity += info['close'] * info['qty']
    p['equity'] = equity

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

def alpha_alloc(params, cash):
    config = {}
    with open(params[1]) as f:
        config = json.load(f)
        #print(config)

    today = params[2]

    d = datetime.strptime(today, '%Y-%m-%d')
    logger.info(f"Alpha System start: {today}, weekday={d.weekday()}")

    if d.weekday() >= 5:
        print(f"{today} is a weekend, exiting")
        logger.error(f"{today} is a weekend, exiting")
        next_working_day(today)
        exit(1)

    #today = datetime.now().strftime('%Y-%m-%d')

    portfolio = None

    if len(params) == 4 and params[3] == 'sync':
        # get portfolio from broker
        broker = RStockTrader(config['auth'])
        sync = {
            "cash": broker.getcash(),
            "equity": broker.getvalue(),
            "unsure": {},
            'ra': {
                'tickers': {},
                'cash': 0,
                'equity': 0
            },
            'dt': {
                'tickers': {},
                'cash': 0,
                'equity': 0
            },
            'ea': {
                'tickers': {},
                'cash': 0,
                'equity': 0
            },
            'mr': {
                'tickers': {},
                'cash': 0,
                'equity': 0
            }
        }
        keys = {}  # ticker: [key]
        for key in ['ra', 'dt', 'ea', 'mr']:
            for t in AlphaStrategy.load_tickers(f"cfg/{key}.txt"):
                try:
                    keys[t].append(key)
                except KeyError:
                    keys[t] = [key]
        for ticker, p in broker.positions.items():
            pos = ticker.find('.')
            if pos >= 0:
                ticker = ticker[0:pos]
            k = keys[ticker]
            if len(k) == 1:
                sync[k[0]]['tickers'][ticker] = p
            elif len(k) == 0:
                raise NotImplementedError
            else:
                p['keys'] = k
                sync['unsure'][ticker] = p

        with open(f"work/portfolio/{config['subdir']}/sync_{today}.json", 'w') as f:
            json.dump(sync, f, indent=4, sort_keys=True)
        return

    else:
        try:
            with open(f"work/portfolio/{config['subdir']}/{today}.json") as f:
                portfolio = json.load(f)
                #print(self.portfolio)
        except FileNotFoundError:
            logger.debug("Starting with empty portfolio")
            cash30 = cash * 0.3
            cash20 = cash * 0.2
            portfolio = {
                'date': today,
                'cash': cash,
                'equity': cash,
                'ra': {
                    'tickers': {},
                    'cash': cash30,
                    'equity': cash30
                },
                'dt': {
                    'tickers': {},
                    'cash': cash20,
                    'equity': cash20
                },
                'ea': {
                    'tickers': {},
                    'cash': cash20,
                    'equity': cash20
                },
                'mr': {
                    'tickers': {},
                    'cash': cash30,
                    'equity': cash30
                }
            }
            #compute_equity(portfolio)
            save_portfolio(portfolio, f"work/portfolio/{config['subdir']}/{today}.json")

    new_portfolio = {"transitions": {}, "cash": 0}

    STRAT = [RisingAssets, DynamicTreasures, ETFAvalanches, MeanReversion]
    STRAT = [MeanReversion]

    for strategy_cls in STRAT:
        s = strategy_cls(logger, portfolio.copy(), today)
        new_portfolio[s.key], new_portfolio["transitions"][s.key] = s.allocate()

    #logger.info('new_portfolio: ' + json.dumps(new_portfolio, indent=4, sort_keys=True))

    compute_equity(new_portfolio)
    new_portfolio['cash'] = int((portfolio['equity'] - new_portfolio['equity']) * 100) / 100

    next_date_str = next_working_day(today)
    new_portfolio['date'] = next_date_str
    #save_portfolio(new_portfolio, f'work/portfolio/{config['subdir']}/next_{next_date_str}.json')
    save_portfolio(new_portfolio, f'work/portfolio/{config['subdir']}/{next_date_str}.json')

if __name__ == '__main__':
    logger.remove()
    #logger.add(sys.stderr,
    #    format = '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>')
    #    #filter = lambda record: record['extra'] is {})
    tm = time.localtime()
    logger.add('log/alpha_%04d%02d%02d.log' % (tm.tm_year, tm.tm_mon, tm.tm_mday),
            format = '{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}')

    logger.debug("\n")
    if len(sys.argv) < 3:
        logger.error("Usage: alpha/main.py <config> <YYYY-MM-DD> [sync]")
        exit(1)

    alpha_alloc(sys.argv, 10000)
