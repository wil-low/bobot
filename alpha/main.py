# main.py

from datetime import datetime, timedelta
import json
import sys
import time
from loguru import logger  # pip install loguru
from alloc import DynamicTreasures, ETFAvalanches, MeanReversion, RisingAssets

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

def alpha_alloc(today, cash):
    #today = datetime.now().strftime('%Y-%m-%d')

    portfolio = None

    try:
        with open(f'work/portfolio/{today}.json') as f:
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
        compute_equity(portfolio)
        save_portfolio(portfolio, f'work/portfolio/{today}.json')

    logger.info(f"alpha_alloc: {today}, equity {portfolio['equity']}, cash {portfolio['cash']}")

    new_portfolio = {"transitions": {}, "cash": 0}

    STRAT = [RisingAssets, DynamicTreasures, ETFAvalanches, MeanReversion]
    STRAT = [ETFAvalanches]

    for strategy_cls in STRAT:
        s = strategy_cls(logger, portfolio.copy(), today)
        new_portfolio[s.key], new_portfolio["transitions"][s.key] = s.allocate()

    #logger.info('new_portfolio: ' + json.dumps(new_portfolio, indent=4, sort_keys=True))

    compute_equity(new_portfolio)
    new_portfolio['cash'] = int((portfolio['equity'] - new_portfolio['equity']) * 100) / 100

    next_date_str = None
    current = datetime.strptime(today, '%Y-%m-%d')
    while True:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0 = Monday, 6 = Sunday → skip Saturday (5), Sunday (6)
            next_date_str = current.strftime('%Y-%m-%d')
            print(f"Next working day is {next_date_str}")
            logger.info(f"Next working day is {next_date_str}")
            break
    
    new_portfolio['date'] = next_date_str
    save_portfolio(new_portfolio, f'work/portfolio/next_{next_date_str}.json')

if __name__ == '__main__':
    logger.remove()
    #logger.add(sys.stderr,
    #    format = '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>')
    #    #filter = lambda record: record['extra'] is {})
    tm = time.localtime()
    logger.add('log/alpha_%04d%02d%02d.log' % (tm.tm_year, tm.tm_mon, tm.tm_mday),
            format = '{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}')

    if len(sys.argv) < 2:
        logger.error("Usage: alpha/main.py <YYYY-MM-DD>")
        exit(1)
        
    alpha_alloc(sys.argv[1], 10000)
