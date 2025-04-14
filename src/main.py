# main.py

import json
import sys
import time
import backtrader as bt
from loguru import logger  # pip install loguru

from broker import DerivBroker
from datafeed import DerivLiveData
from strategy import AntyStrategy

def run_bot():
    config = {}
    with open(sys.argv[1]) as f:
        config = json.load(f)
        print(config)

    logger.remove()
    #logger.add(sys.stderr,
    #    format = '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <level>{message}</level>')
    #    #filter = lambda record: record['extra'] is {})
    logger.add(f'log/live_{config["strategy"]["name"]}.log',
            format = '{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}')
            #filter = lambda record, ticker=b['config["ticker"]']: record['extra'].get("ticker", '') == ticker)
    cerebro = bt.Cerebro()

    # Add live data feed
    for symbol in config['feed']['tickers']:
        data = DerivLiveData(logger=logger, app_id=config['auth']['account_id'], symbol=symbol, granularity=config['feed']['timeframe_sec'], history_size=config['feed']['history_size'])
        data.ticker = symbol
        cerebro.adddata(data)

    # Add broker (Deriv WebSocket trader)
    broker = DerivBroker(logger=logger, app_id=config['auth']['account_id'], api_token=config['auth']['api_key'], contract_expiration_min=config['trade']['expiration_min'])
    cerebro.setbroker(broker)

    while not broker.ready():
        time.sleep(0.5)

    # Add strategy
    cerebro.addstrategy(AntyStrategy, stake=config['trade']['stake'], logger=logger)

    print("🔁 Starting live Deriv bot...")
    cerebro.run()

if __name__ == '__main__':
    run_bot()
