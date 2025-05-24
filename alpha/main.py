# main.py

from datetime import datetime
import sys
import time
from loguru import logger  # pip install loguru
from alloc import DynamicTreasures, ETFAvalanches, MeanReversion, RisingAssets

def write_tickers(tickers, fn):
    with open(fn, "w") as f:
        for t in tickers:
            f.write(f"{t}\n")

def alpha_alloc(today, initial_value):
    #today = datetime.now().strftime('%Y-%m-%d')

    logger.info(f"alpha_alloc: {today}")

    strategy0 = RisingAssets(logger, initial_value * 0.3, today)
    strategy0.allocate()
    #strategy0.save_portfolio()

    strategy1 = DynamicTreasures(logger, initial_value * 0.2, today)
    strategy1.allocate()
    #strategy1.save_portfolio()

    strategy2 = ETFAvalanches(logger, initial_value * 0.2, today)
    strategy2.allocate()
    #strategy2.save_portfolio()

    strategy3 = MeanReversion(logger, initial_value * 0.3, today)
    strategy3.allocate()
    #strategy3.save_portfolio()


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
