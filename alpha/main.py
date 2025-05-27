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

def floor2(val):
    return int(val * 100) / 100

def compute_totals(p):
    equity = 0
    cash = 0
    for key in ['ra', 'dt', 'ea', 'mr']:
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

def alpha_alloc(config, today):
    d = datetime.strptime(today, '%Y-%m-%d')
    logger.info(f"Alpha System start: {today}, weekday={d.weekday()}")

    if d.weekday() >= 5:
        print(f"{today} is a weekend, exiting")
        logger.error(f"{today} is a weekend, exiting")
        next_working_day(today)
        exit(1)

    portfolio = None

    if config['sync']:
        logger.info(f"Getting portfolio from broker {config['broker']}")
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
            k = keys[ticker].copy()
            if p['side'] == 'sell':
                sync['ea']['tickers'][ticker] = p
            else:
                if 'ea' in k:
                    k.remove('ea')
            if len(k) == 1:
                sync[k[0]]['tickers'][ticker] = p
            elif len(k) == 0:
                raise NotImplementedError
            else:
                p['keys'] = k
                sync['unsure'][ticker] = p

        fn = f"work/portfolio/{config['subdir']}/sync_{today}.json"
        with open(fn, 'w') as f:
            json.dump(sync, f, indent=4, sort_keys=True)

        logger.info(f"Portfolio written to {fn}")
        return

    else:
        try:
            with open(f"work/portfolio/{config['subdir']}/{today}.json") as f:
                portfolio = json.load(f)
                #print(self.portfolio)
        except FileNotFoundError:
            logger.debug("Starting with empty portfolio")
            cash = config['initial_cash']
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
            compute_totals(portfolio)
            save_portfolio(portfolio, f"work/portfolio/{config['subdir']}/{today}.json")

    new_portfolio = {"transitions": {}, "cash": 0}

    STRAT = [RisingAssets, DynamicTreasures, ETFAvalanches, MeanReversion]
 
    for strategy_cls in STRAT:
        s = strategy_cls(logger, portfolio.copy(), today)
        new_portfolio[s.key], new_portfolio["transitions"][s.key] = s.allocate()

    #logger.info('new_portfolio: ' + json.dumps(new_portfolio, indent=4, sort_keys=True))

    compute_totals(new_portfolio)
    logger.info(f"NEW TOTALS: equity={new_portfolio['equity']}, cash={new_portfolio['cash']}")

    next_date_str = next_working_day(today)
    new_portfolio['date'] = next_date_str
    save_portfolio(new_portfolio, f'work/portfolio/{config['subdir']}/{next_date_str}.json')

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: alpha/main.py <config> <YYYY-MM-DD>")
        exit(1)

    config = {}
    with open(sys.argv[1]) as f:
        config = json.load(f)
        #print(config)

    today = sys.argv[2]

    logger.remove()
    #logger.add(sys.stderr,
    #    format = '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>')
    #    #filter = lambda record: record['extra'] is {})
    tm = time.localtime()
    logger.add('log/%s/alpha_%04d%02d%02d.log' % (config['subdir'], tm.tm_year, tm.tm_mon, tm.tm_mday),
            format = '{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}')

    logger.debug("")
    logger.debug("")

    alpha_alloc(config, today)
